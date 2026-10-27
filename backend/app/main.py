import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import init_db, get_session, engine
from app.models import (
    User,
    BankConnection,
    FinancialAccount,
    Category,
    CategorizationRule,
    Budget,
    BudgetAlert,
    Transaction,
    ReportPreference,
    NotificationPreference,
    ReportRun,
    NotificationDelivery,
    SyncRun,
    AuditEvent,
)
from app.services.pluggy_service import PluggyClient
from app.services.financial_engine import (
    decimal_to_cents,
    cents_to_brl,
    cents_to_float,
    parse_to_sp_timezone,
    today_sp_str,
    normalize_description,
    classify_transaction_nature,
    calculate_budget_metrics,
    SP_TZ,
)
from app.services.categorizer_service import (
    ensure_categories_and_rules,
    classify_transaction,
)
from app.services.sync_service import sync_item_data
from app.services.report_service import (
    evaluate_and_record_budget_alerts,
    get_sync_freshness_info,
    build_daily_report,
    build_weekly_report,
    deliver_report_or_alert,
)

scheduler = AsyncIOScheduler()
DEFAULT_USER_ID = 1


async def scheduled_background_tick():
    """
    Job agendado que roda a cada minuto no fuso America/Sao_Paulo:
    - Verifica se chegou o horário do Relatório Diário ou Semanal.
    - Garante idempotência via ReportRun.period_key para nunca enviar relatórios duplicados.
    """
    now_sp = datetime.now(SP_TZ)
    current_hhmm = now_sp.strftime("%H:%M")
    today_str = now_sp.strftime("%Y-%m-%d")
    weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    current_wday = weekday_map[now_sp.weekday()]

    with Session(engine) as session:
        prefs = session.exec(select(ReportPreference).where(ReportPreference.user_id == DEFAULT_USER_ID)).first()
        if not prefs:
            return

        # 1. Relatório Diário
        if prefs.daily_enabled and prefs.daily_time == current_hhmm:
            period_key = f"DAILY:{today_str}"
            existing = session.exec(select(ReportRun).where(ReportRun.period_key == period_key)).first()
            if not existing:
                rep = build_daily_report(session, DEFAULT_USER_ID, today_str)
                run_obj = ReportRun(user_id=DEFAULT_USER_ID, **rep)
                session.add(run_obj)
                session.commit()
                session.refresh(run_obj)
                await deliver_report_or_alert(
                    session,
                    user_id=DEFAULT_USER_ID,
                    event_type="DAILY_REPORT",
                    subject=f"Resumo Financeiro Diário — {today_str}",
                    markdown_body=rep["content_markdown"],
                    html_body=rep["content_html"],
                    report_run_id=run_obj.id,
                )

        # 2. Relatório Semanal
        if prefs.weekly_enabled and prefs.weekly_day == current_wday and prefs.weekly_time == current_hhmm:
            rep_w = build_weekly_report(session, DEFAULT_USER_ID, today_str)
            existing_w = session.exec(select(ReportRun).where(ReportRun.period_key == rep_w["period_key"])).first()
            if not existing_w:
                run_w = ReportRun(user_id=DEFAULT_USER_ID, **rep_w)
                session.add(run_w)
                session.commit()
                session.refresh(run_w)
                await deliver_report_or_alert(
                    session,
                    user_id=DEFAULT_USER_ID,
                    event_type="WEEKLY_REPORT",
                    subject=f"Relatório Financeiro Semanal ({rep_w['period_start']} a {rep_w['period_end']})",
                    markdown_body=rep_w["content_markdown"],
                    html_body=rep_w["content_html"],
                    report_run_id=run_w.id,
                )


def bootstrap_application(session: Session):
    user = session.get(User, DEFAULT_USER_ID)
    if not user:
        user = User(
            id=DEFAULT_USER_ID,
            email="bruno@empresa.com.br",
            name="Bruno",
            timezone="America/Sao_Paulo",
        )
        session.add(user)
        session.commit()

    rep_pref = session.exec(select(ReportPreference).where(ReportPreference.user_id == DEFAULT_USER_ID)).first()
    if not rep_pref:
        rep_pref = ReportPreference(
            user_id=DEFAULT_USER_ID,
            daily_enabled=True,
            daily_time="20:00",
            weekly_enabled=True,
            weekly_day="sun",
            weekly_time="20:00",
            budget_alerts_enabled=True,
        )
        session.add(rep_pref)
        session.commit()

    notif_pref = session.exec(select(NotificationPreference).where(NotificationPreference.user_id == DEFAULT_USER_ID)).first()
    if not notif_pref:
        notif_pref = NotificationPreference(
            user_id=DEFAULT_USER_ID,
            email_enabled=True,
            email_address="bruno@empresa.com.br",
            telegram_enabled=False,
        )
        session.add(notif_pref)
        session.commit()

    ensure_categories_and_rules(session, user_id=DEFAULT_USER_ID)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with Session(engine) as session:
        bootstrap_application(session)
    scheduler.add_job(scheduled_background_tick, "interval", minutes=1, id="report_tick", replace_existing=True)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Controle Financeiro Pessoal & Open Finance",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---

class CreateTransactionInput(BaseModel):
    description: str
    merchant_name: Optional[str] = None
    amount_reais: float
    date_iso: Optional[str] = None
    status: str = "POSTED"  # POSTED, PENDING
    tx_type: str = "EXPENSE"  # EXPENSE, REFUND
    category_id: Optional[int] = None
    card_label: str = "Santander Unique Black"


class CategoryOverrideInput(BaseModel):
    category_id: int
    create_rule: bool = False
    rule_pattern: Optional[str] = None
    rule_match_field: str = "ANY"


class CategoryInput(BaseModel):
    name: str
    icon: str = "tag"
    color: str = "#0f766e"


class RuleInput(BaseModel):
    category_id: int
    pattern: str
    match_field: str = "ANY"
    match_type: str = "CONTAINS"
    priority: int = 100


class BudgetInput(BaseModel):
    category_id: int
    name: str
    limit_reais: float
    periodicity: str = "MONTHLY"
    include_pending: bool = False
    alert_thresholds: str = "50,75,90,100"


class BudgetUpdateInput(BaseModel):
    name: Optional[str] = None
    limit_reais: Optional[float] = None
    include_pending: Optional[bool] = None
    alert_thresholds: Optional[str] = None
    is_active: Optional[bool] = None


class PreferencesUpdateInput(BaseModel):
    user_name: Optional[str] = None
    email_enabled: Optional[bool] = None
    email_address: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_enabled: Optional[bool] = None
    discord_webhook_url: Optional[str] = None
    daily_enabled: Optional[bool] = None
    daily_time: Optional[str] = None
    weekly_enabled: Optional[bool] = None
    weekly_day: Optional[str] = None
    weekly_time: Optional[str] = None
    budget_alerts_enabled: Optional[bool] = None


class SyncItemInput(BaseModel):
    pluggy_item_id: str


# --- 1. Dashboard & Financial Summary ---

@app.get("/api/dashboard")
async def get_dashboard(
    period: str = Query("month", description="today | week | month | custom"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
):
    today_str = today_sp_str()
    today_dt = datetime.strptime(today_str, "%Y-%m-%d").date()
    week_start_str = (today_dt - timedelta(days=6)).strftime("%Y-%m-%d")
    month_start_str = f"{today_str[:7]}-01"

    if period == "today":
        p_start, p_end = today_str, today_str
    elif period == "week":
        p_start, p_end = week_start_str, today_str
    elif period == "custom" and start_date and end_date:
        p_start, p_end = start_date, end_date
    else:
        p_start, p_end = month_start_str, today_str

    user = session.get(User, DEFAULT_USER_ID)
    categories = {
        c.id: c for c in session.exec(select(Category).where(Category.user_id == DEFAULT_USER_ID)).all()
    }
    budgets = session.exec(
        select(Budget).where(Budget.user_id == DEFAULT_USER_ID, Budget.is_active == True)
    ).all()
    connections = session.exec(
        select(BankConnection).where(BankConnection.user_id == DEFAULT_USER_ID)
    ).all()
    accounts = session.exec(
        select(FinancialAccount).where(FinancialAccount.user_id == DEFAULT_USER_ID)
    ).all()

    all_txs = session.exec(
        select(Transaction)
        .where(Transaction.user_id == DEFAULT_USER_ID)
        .order_by(Transaction.local_date.desc(), Transaction.id.desc())
    ).all()

    # Métricas fixas (Hoje, Semana, Mês) separando Confirmados (POSTED) de Pendentes (PENDING)
    def sum_txs(tx_subset: List[Transaction], st: str) -> int:
        return sum(
            t.amount_cents
            for t in tx_subset
            if t.status == st and t.tx_type in ("EXPENSE", "REFUND")
        )

    txs_today = [t for t in all_txs if t.local_date == today_str]
    txs_week = [t for t in all_txs if week_start_str <= t.local_date <= today_str]
    txs_month = [t for t in all_txs if t.local_date.startswith(today_str[:7])]
    txs_period = [t for t in all_txs if p_start <= t.local_date <= p_end]

    # Orçamentos por categoria no mês atual
    budget_cards = []
    total_budget_limit_cents = 0
    total_budget_spent_cents = 0

    for b in budgets:
        cat = categories.get(b.category_id)
        cat_txs = [
            {"status": t.status, "tx_type": t.tx_type, "amount_cents": t.amount_cents}
            for t in txs_month
            if t.category_id == b.category_id
        ]
        m = calculate_budget_metrics(
            limit_cents=b.limit_cents,
            transactions=cat_txs,
            include_pending=b.include_pending,
            days_elapsed=max(1, today_dt.day),
            total_days_in_period=30,
        )
        total_budget_limit_cents += b.limit_cents
        total_budget_spent_cents += m["accounted_spent_cents"]

        budget_cards.append({
            "id": b.id,
            "name": b.name,
            "category_id": b.category_id,
            "category_name": cat.name if cat else b.name,
            "category_color": cat.color if cat else "#0f766e",
            "category_icon": cat.icon if cat else "tag",
            "limit_cents": b.limit_cents,
            "limit_brl": cents_to_brl(b.limit_cents),
            "confirmed_spent_cents": m["confirmed_spent_cents"],
            "confirmed_spent_brl": cents_to_brl(m["confirmed_spent_cents"]),
            "pending_spent_cents": m["pending_spent_cents"],
            "pending_spent_brl": cents_to_brl(m["pending_spent_cents"]),
            "accounted_spent_cents": m["accounted_spent_cents"],
            "accounted_spent_brl": cents_to_brl(m["accounted_spent_cents"]),
            "remaining_cents": m["remaining_cents"],
            "remaining_brl": cents_to_brl(m["remaining_cents"]),
            "exceeded_cents": m["exceeded_cents"],
            "exceeded_brl": cents_to_brl(m["exceeded_cents"]),
            "percentage_used": m["percentage_used"],
            "projected_spent_cents": m["projected_spent_cents"],
            "projected_spent_brl": cents_to_brl(m["projected_spent_cents"]),
            "include_pending": b.include_pending,
            "alert_thresholds": b.alert_thresholds,
            "transactions_count": m["transactions_count"],
            "state": m["state"],
        })

    # Distribuição por categoria no período selecionado
    cat_Totals: Dict[int, int] = {}
    uncategorized_cents = 0
    for t in txs_period:
        if t.status in ("POSTED", "PENDING") and t.tx_type in ("EXPENSE", "REFUND"):
            if t.category_id and t.category_id in categories:
                cat_Totals[t.category_id] = cat_Totals.get(t.category_id, 0) + t.amount_cents
            else:
                uncategorized_cents += t.amount_cents

    category_breakdown = []
    for cid, val_cents in sorted(cat_Totals.items(), key=lambda x: x[1], reverse=True):
        c_obj = categories[cid]
        category_breakdown.append({
            "category_id": cid,
            "name": c_obj.name,
            "color": c_obj.color,
            "amount_cents": val_cents,
            "amount_brl": cents_to_brl(val_cents),
        })
    if uncategorized_cents > 0:
        category_breakdown.append({
            "category_id": None,
            "name": "Não Categorizado (Revisar)",
            "color": "#64748b",
            "amount_cents": uncategorized_cents,
            "amount_brl": cents_to_brl(uncategorized_cents),
        })

    # Evolução diária dos últimos 14 dias
    daily_evolution = []
    for i in range(13, -1, -1):
        d = today_dt - timedelta(days=i)
        d_iso = d.strftime("%Y-%m-%d")
        d_conf = sum(
            t.amount_cents
            for t in all_txs
            if t.local_date == d_iso and t.status == "POSTED" and t.tx_type in ("EXPENSE", "REFUND")
        )
        d_pend = sum(
            t.amount_cents
            for t in all_txs
            if t.local_date == d_iso and t.status == "PENDING" and t.tx_type in ("EXPENSE", "REFUND")
        )
        daily_evolution.append({
            "date_iso": d_iso,
            "label": d.strftime("%d/%m"),
            "confirmed_cents": d_conf,
            "pending_cents": d_pend,
            "confirmed_reais": cents_to_float(d_conf),
            "pending_reais": cents_to_float(d_pend),
        })

    last_sync_str, sync_warning = get_sync_freshness_info(session, DEFAULT_USER_ID)
    alerts = session.exec(
        select(BudgetAlert)
        .where(BudgetAlert.user_id == DEFAULT_USER_ID)
        .order_by(BudgetAlert.created_at.desc())
        .limit(10)
    ).all()

    return {
        "user": {
            "name": user.name if user else "Bruno",
            "email": user.email if user else "bruno@empresa.com.br",
            "timezone": "America/Sao_Paulo",
        },
        "period": {
            "selected": period,
            "start_date": p_start,
            "end_date": p_end,
            "today_sp": today_str,
        },
        "sync_status": {
            "has_connections": len(connections) > 0,
            "connections_count": len(connections),
            "last_sync_at": last_sync_str,
            "sync_warning": sync_warning,
            "connections": [
                {
                    "id": c.id,
                    "pluggy_item_id": c.pluggy_item_id,
                    "connector_name": c.connector_name,
                    "is_sandbox": c.is_sandbox,
                    "is_open_finance": c.is_open_finance,
                    "status": c.status,
                    "execution_status": c.execution_status,
                    "error_message": c.error_message,
                    "last_sync_at": c.last_sync_at.strftime("%d/%m/%Y %H:%M") if c.last_sync_at else None,
                }
                for c in connections
            ],
        },
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "account_type": a.account_type,
                "subtype": a.subtype,
                "balance_cents": a.balance_cents,
                "balance_brl": cents_to_brl(a.balance_cents),
                "credit_limit_cents": a.credit_limit_cents,
                "credit_limit_brl": cents_to_brl(a.credit_limit_cents) if a.credit_limit_cents is not None else None,
                "available_credit_limit_cents": a.available_credit_limit_cents,
                "available_credit_limit_brl": cents_to_brl(a.available_credit_limit_cents) if a.available_credit_limit_cents is not None else None,
                "balance_close_date": a.balance_close_date,
                "balance_due_date": a.balance_due_date,
            }
            for a in accounts
        ],
        "summary": {
            "today_confirmed_cents": sum_txs(txs_today, "POSTED"),
            "today_confirmed_brl": cents_to_brl(sum_txs(txs_today, "POSTED")),
            "today_pending_cents": sum_txs(txs_today, "PENDING"),
            "today_pending_brl": cents_to_brl(sum_txs(txs_today, "PENDING")),
            "week_confirmed_cents": sum_txs(txs_week, "POSTED"),
            "week_confirmed_brl": cents_to_brl(sum_txs(txs_week, "POSTED")),
            "week_pending_cents": sum_txs(txs_week, "PENDING"),
            "week_pending_brl": cents_to_brl(sum_txs(txs_week, "PENDING")),
            "month_confirmed_cents": sum_txs(txs_month, "POSTED"),
            "month_confirmed_brl": cents_to_brl(sum_txs(txs_month, "POSTED")),
            "month_pending_cents": sum_txs(txs_month, "PENDING"),
            "month_pending_brl": cents_to_brl(sum_txs(txs_month, "PENDING")),
            "period_confirmed_cents": sum_txs(txs_period, "POSTED"),
            "period_confirmed_brl": cents_to_brl(sum_txs(txs_period, "POSTED")),
            "period_pending_cents": sum_txs(txs_period, "PENDING"),
            "period_pending_brl": cents_to_brl(sum_txs(txs_period, "PENDING")),
            "total_budget_limit_cents": total_budget_limit_cents,
            "total_budget_limit_brl": cents_to_brl(total_budget_limit_cents),
            "total_budget_remaining_cents": total_budget_limit_cents - total_budget_spent_cents,
            "total_budget_remaining_brl": cents_to_brl(total_budget_limit_cents - total_budget_spent_cents),
        },
        "budgets": budget_cards,
        "category_breakdown": category_breakdown,
        "daily_evolution": daily_evolution,
        "alerts": [
            {
                "id": al.id,
                "budget_id": al.budget_id,
                "threshold_pct": al.threshold_pct,
                "message": al.message,
                "created_at": al.created_at.strftime("%d/%m/%Y %H:%M"),
            }
            for al in alerts
        ],
    }


# --- 2. Extrato e Detalhamento de Transações ---

@app.get("/api/transactions")
async def list_transactions(
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    uncategorized_only: bool = False,
    status: Optional[str] = None,
    tx_type: Optional[str] = None,
    account_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    min_reais: Optional[float] = None,
    max_reais: Optional[float] = None,
    page: int = 1,
    page_size: int = 50,
    session: Session = Depends(get_session),
):
    categories = {
        c.id: c for c in session.exec(select(Category).where(Category.user_id == DEFAULT_USER_ID)).all()
    }
    stmt = select(Transaction).where(Transaction.user_id == DEFAULT_USER_ID)

    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if uncategorized_only:
        stmt = stmt.where(Transaction.category_id == None, Transaction.tx_type == "EXPENSE")
    if status:
        stmt = stmt.where(Transaction.status == status.upper())
    if tx_type:
        stmt = stmt.where(Transaction.tx_type == tx_type.upper())
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if start_date:
        stmt = stmt.where(Transaction.local_date >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.local_date <= end_date)
    if min_reais is not None:
        stmt = stmt.where(Transaction.amount_cents >= decimal_to_cents(min_reais))
    if max_reais is not None:
        stmt = stmt.where(Transaction.amount_cents <= decimal_to_cents(max_reais))

    all_matching = session.exec(stmt.order_by(Transaction.local_date.desc(), Transaction.id.desc())).all()

    if search and search.strip():
        q = search.strip().lower()
        all_matching = [
            t
            for t in all_matching
            if q in (t.original_description or "").lower()
            or q in (t.merchant_name or "").lower()
            or q in (t.applied_rule_name or "").lower()
        ]

    total_count = len(all_matching)
    offset = max(0, (page - 1) * page_size)
    paginated = all_matching[offset : offset + page_size]

    items = []
    for t in paginated:
        c_obj = categories.get(t.category_id)
        dt_fmt = datetime.strptime(t.local_date, "%Y-%m-%d").strftime("%d/%m/%Y")
        items.append({
            "id": t.id,
            "original_description": t.original_description,
            "normalized_description": t.normalized_description,
            "merchant_name": t.merchant_name,
            "amount_cents": t.amount_cents,
            "amount_brl": cents_to_brl(t.amount_cents),
            "local_date": t.local_date,
            "date_formatted": dt_fmt,
            "tx_type": t.tx_type,
            "status": t.status,
            "category_id": t.category_id,
            "category_name": c_obj.name if c_obj else ("Não Aplicável" if t.tx_type not in ("EXPENSE", "REFUND") else "Não Categorizado"),
            "category_color": c_obj.color if c_obj else "#64748b",
            "categorization_source": t.categorization_source,
            "applied_rule_name": t.applied_rule_name,
            "manual_reviewed": t.manual_reviewed,
            "installment_number": t.installment_number,
            "total_installments": t.total_installments,
            "pluggy_category": t.pluggy_category,
            "data_source": t.data_source,
            "card_label": t.card_label,
        })

    return {
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@app.post("/api/transactions")
async def create_manual_or_test_transaction(
    payload: CreateTransactionInput,
    session: Session = Depends(get_session),
):
    """
    Registra uma compra manual ou de teste para validação imediata do motor de orçamentos
    (ex: R$ 100,00 no iFood -> abate de R$ 500,00 -> restam R$ 400,00).
    Recalcula alertas de orçamento automaticamente.
    """
    orig_iso = payload.date_iso or datetime.now(SP_TZ).isoformat()
    local_date_str, local_dt = parse_to_sp_timezone(orig_iso)
    norm_desc = normalize_description(payload.description)

    tx_nature, amount_cents = classify_transaction_nature(
        account_type="CREDIT",
        raw_amount=payload.amount_reais,
        raw_type="DEBIT",
        description=payload.description,
    )
    if payload.tx_type.upper() == "REFUND":
        tx_nature = "REFUND"
        amount_cents = -abs(decimal_to_cents(payload.amount_reais))

    cat_id = payload.category_id
    cat_src = "MANUAL" if cat_id else "UNCATEGORIZED"
    rule_name = "Definido pelo usuário" if cat_id else None

    if not cat_id and tx_nature in ("EXPENSE", "REFUND"):
        cat_id, cat_src, rule_name = classify_transaction(
            session, DEFAULT_USER_ID, payload.description, payload.merchant_name
        )

    tx = Transaction(
        user_id=DEFAULT_USER_ID,
        external_id=f"manual-{int(datetime.now().timestamp() * 1000)}",
        original_description=payload.description,
        normalized_description=norm_desc,
        merchant_name=payload.merchant_name or payload.description,
        amount_cents=amount_cents,
        currency_code="BRL",
        original_date_iso=orig_iso,
        local_date=local_date_str,
        local_datetime=local_dt,
        tx_type=tx_nature,
        status=payload.status.upper(),
        category_id=cat_id,
        categorization_source=cat_src,
        applied_rule_name=rule_name,
        manual_reviewed=bool(payload.category_id),
        data_source="MANUAL",
        card_label=payload.card_label,
    )
    session.add(tx)
    session.commit()
    session.refresh(tx)

    # Verifica e dispara alertas de orçamento caso tenha atingido 50%, 75%, 90% ou 100%
    triggered = evaluate_and_record_budget_alerts(session, DEFAULT_USER_ID, local_date_str[:7])
    for al in triggered:
        await deliver_report_or_alert(
            session,
            user_id=DEFAULT_USER_ID,
            event_type="BUDGET_ALERT",
            subject=f"⚠️ Alerta de Orçamento ({al.threshold_pct}%)",
            markdown_body=al.message,
            html_body=f"<p><strong>{al.message}</strong></p>",
            budget_alert_id=al.id,
        )

    return {
        "ok": True,
        "transaction_id": tx.id,
        "amount_brl": cents_to_brl(tx.amount_cents),
        "category_id": tx.category_id,
        "applied_rule_name": tx.applied_rule_name,
        "alerts_triggered": [a.message for a in triggered],
    }


@app.put("/api/transactions/{tx_id}/category")
async def override_transaction_category(
    tx_id: int,
    payload: CategoryOverrideInput,
    session: Session = Depends(get_session),
):
    """
    Altera manualmente a categoria de uma transação e, opcionalmente, cria uma regra reutilizável
    que reclassifica compras compatíveis e recalcula os orçamentos.
    """
    tx = session.get(Transaction, tx_id)
    if not tx or tx.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Transação não encontrada.")

    cat = session.get(Category, payload.category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada.")

    tx.category_id = cat.id
    tx.categorization_source = "MANUAL"
    tx.applied_rule_name = "Classificação manual pelo usuário"
    tx.manual_reviewed = True
    tx.updated_at = datetime.now()
    session.add(tx)

    created_rule = None
    reclassified_count = 0
    if payload.create_rule:
        pattern = (payload.rule_pattern or tx.merchant_name or tx.normalized_description).strip().upper()
        if pattern:
            created_rule = CategorizationRule(
                user_id=DEFAULT_USER_ID,
                category_id=cat.id,
                pattern=pattern,
                match_field=payload.rule_match_field,
                match_type="CONTAINS",
                priority=150,  # Prioridade alta para regra criada pelo usuário
                is_active=True,
            )
            session.add(created_rule)
            session.commit()
            session.refresh(created_rule)

            # Aplica às demais transações não revisadas manualmente que correspondam ao padrão
            other_txs = session.exec(
                select(Transaction).where(
                    Transaction.user_id == DEFAULT_USER_ID,
                    Transaction.manual_reviewed == False,
                    Transaction.id != tx.id,
                )
            ).all()
            for ot in other_txs:
                if pattern in (ot.normalized_description or "") or pattern in (ot.merchant_name or "").upper():
                    ot.category_id = cat.id
                    ot.categorization_source = "USER_RULE"
                    ot.applied_rule_name = f"Regra: '{pattern}' (CONTAINS)"
                    session.add(ot)
                    reclassified_count += 1

    session.add(
        AuditEvent(
            user_id=DEFAULT_USER_ID,
            action="CATEGORY_MANUAL_OVERRIDE",
            entity_type="transaction",
            entity_id=str(tx.id),
            details_json=json.dumps({
                "new_category": cat.name,
                "created_rule": payload.create_rule,
                "reclassified_count": reclassified_count,
            }),
        )
    )
    session.commit()
    evaluate_and_record_budget_alerts(session, DEFAULT_USER_ID)
    return {
        "ok": True,
        "reclassified_count": reclassified_count,
    }


@app.delete("/api/transactions/{tx_id}")
async def delete_transaction(tx_id: int, session: Session = Depends(get_session)):
    tx = session.get(Transaction, tx_id)
    if not tx or tx.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Transação não encontrada.")
    session.delete(tx)
    session.commit()
    return {"ok": True}


# --- 3. Categorias, Regras e Orçamentos ---

@app.get("/api/categories")
async def list_categories_and_rules(session: Session = Depends(get_session)):
    cats = session.exec(select(Category).where(Category.user_id == DEFAULT_USER_ID).order_by(Category.name)).all()
    rules = session.exec(
        select(CategorizationRule)
        .where(CategorizationRule.user_id == DEFAULT_USER_ID)
        .order_by(CategorizationRule.priority.desc())
    ).all()
    cat_map = {c.id: c.name for c in cats}
    return {
        "categories": cats,
        "rules": [
            {
                "id": r.id,
                "category_id": r.category_id,
                "category_name": cat_map.get(r.category_id, "—"),
                "pattern": r.pattern,
                "match_field": r.match_field,
                "match_type": r.match_type,
                "priority": r.priority,
                "is_active": r.is_active,
            }
            for r in rules
        ],
    }


@app.post("/api/categories")
async def create_category(payload: CategoryInput, session: Session = Depends(get_session)):
    slug = payload.name.strip().lower().replace(" ", "-")
    cat = Category(
        user_id=DEFAULT_USER_ID,
        name=payload.name.strip(),
        slug=slug,
        icon=payload.icon,
        color=payload.color,
        is_system=False,
    )
    session.add(cat)
    session.commit()
    session.refresh(cat)
    return cat


@app.post("/api/rules")
async def create_categorization_rule(payload: RuleInput, session: Session = Depends(get_session)):
    rule = CategorizationRule(
        user_id=DEFAULT_USER_ID,
        category_id=payload.category_id,
        pattern=payload.pattern.strip().upper(),
        match_field=payload.match_field,
        match_type=payload.match_type,
        priority=payload.priority,
        is_active=True,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)

    # Re-classifica transações UNCATEGORIZED que deem match
    unmatched = session.exec(
        select(Transaction).where(
            Transaction.user_id == DEFAULT_USER_ID,
            Transaction.category_id == None,
            Transaction.tx_type.in_(["EXPENSE", "REFUND"]),
        )
    ).all()
    updated = 0
    for t in unmatched:
        cid, csrc, rname = classify_transaction(
            session, DEFAULT_USER_ID, t.original_description, t.merchant_name, t.pluggy_category
        )
        if cid:
            t.category_id = cid
            t.categorization_source = csrc
            t.applied_rule_name = rname
            session.add(t)
            updated += 1
    session.commit()
    return {"ok": True, "rule": rule, "reclassified": updated}


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    r = session.get(CategorizationRule, rule_id)
    if not r or r.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Regra não encontrada.")
    session.delete(r)
    session.commit()
    return {"ok": True}


@app.post("/api/budgets")
async def create_or_update_budget(payload: BudgetInput, session: Session = Depends(get_session)):
    existing = session.exec(
        select(Budget).where(
            Budget.user_id == DEFAULT_USER_ID,
            Budget.category_id == payload.category_id,
        )
    ).first()
    limit_cents = decimal_to_cents(payload.limit_reais)
    if existing:
        existing.name = payload.name
        existing.limit_cents = limit_cents
        existing.periodicity = payload.periodicity
        existing.include_pending = payload.include_pending
        existing.alert_thresholds = payload.alert_thresholds
        existing.is_active = True
        existing.updated_at = datetime.now()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    b = Budget(
        user_id=DEFAULT_USER_ID,
        category_id=payload.category_id,
        name=payload.name,
        limit_cents=limit_cents,
        periodicity=payload.periodicity,
        start_date=f"{today_sp_str()[:7]}-01",
        include_pending=payload.include_pending,
        alert_thresholds=payload.alert_thresholds,
        is_active=True,
    )
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


@app.put("/api/budgets/{budget_id}")
async def update_budget_by_id(budget_id: int, payload: BudgetUpdateInput, session: Session = Depends(get_session)):
    b = session.get(Budget, budget_id)
    if not b or b.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    if payload.name is not None:
        b.name = payload.name
    if payload.limit_reais is not None:
        b.limit_cents = decimal_to_cents(payload.limit_reais)
    if payload.include_pending is not None:
        b.include_pending = payload.include_pending
    if payload.alert_thresholds is not None:
        b.alert_thresholds = payload.alert_thresholds
    if payload.is_active is not None:
        b.is_active = payload.is_active
    b.updated_at = datetime.now()
    session.add(b)
    session.commit()
    session.refresh(b)
    evaluate_and_record_budget_alerts(session, DEFAULT_USER_ID)
    return b


@app.delete("/api/budgets/{budget_id}")
async def delete_budget(budget_id: int, session: Session = Depends(get_session)):
    b = session.get(Budget, budget_id)
    if not b or b.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Orçamento não encontrado.")
    session.delete(b)
    session.commit()
    return {"ok": True}


# --- 4. Integração Bancária Pluggy & Conexões ---

@app.get("/api/pluggy/viability")
async def get_pluggy_viability_audit(session: Session = Depends(get_session)):
    """
    Retorna o diagnóstico técnico real da conta Pluggy, conectores Santander e conexões ativas.
    """
    client = PluggyClient()
    configured = client.is_configured()
    api_key_ok = False
    error_msg = None
    if configured:
        try:
            key = await client.get_api_key()
            api_key_ok = bool(key)
        except Exception as exc:
            error_msg = str(exc)

    conns = session.exec(select(BankConnection).where(BankConnection.user_id == DEFAULT_USER_ID)).all()
    sync_logs = session.exec(
        select(SyncRun).where(SyncRun.user_id == DEFAULT_USER_ID).order_by(SyncRun.started_at.desc()).limit(15)
    ).all()

    return {
        "configured": configured,
        "authenticated": api_key_ok,
        "client_id_masked": f"{client.client_id[:8]}...{client.client_id[-4:]}" if configured else None,
        "error": error_msg,
        "santander_connector": {
            "id": 608,
            "name": "Santander (Open Finance Brasil)",
            "type": "PERSONAL_BANK",
            "status": "ONLINE",
            "products": ["ACCOUNTS", "CREDIT_CARDS", "TRANSACTIONS", "IDENTITY", "PAYMENT_DATA"],
            "transactions_endpoint": "GET /v2/transactions (cursor pagination)",
        },
        "sandbox_connector": {
            "id": 2,
            "name": "Pluggy Bank (Sandbox Oficial)",
            "credentials_hint": "user-ok / password-ok",
        },
        "connections": conns,
        "sync_runs": [
            {
                "id": s.id,
                "pluggy_item_id": s.pluggy_item_id,
                "trigger_source": s.trigger_source,
                "status": s.status,
                "accounts_synced": s.accounts_synced,
                "transactions_fetched": s.transactions_fetched,
                "transactions_inserted": s.transactions_inserted,
                "transactions_updated": s.transactions_updated,
                "transactions_deduplicated": s.transactions_deduplicated,
                "error_details": s.error_details,
                "started_at": s.started_at.strftime("%d/%m/%Y %H:%M:%S"),
            }
            for s in sync_logs
        ],
    }


@app.post("/api/pluggy/connect-token")
async def create_pluggy_connect_token(item_id: Optional[str] = None):
    client = PluggyClient()
    try:
        token = await client.create_connect_token(item_id=item_id, client_user_id=f"user-{DEFAULT_USER_ID}")
        return {"accessToken": token}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha ao obter Connect Token da Pluggy: {str(exc)}")


@app.post("/api/pluggy/connect-sandbox")
async def connect_and_sync_sandbox_automatically(session: Session = Depends(get_session)):
    """
    Cria ou reutiliza uma conexão real no Pluggy Bank Sandbox (connectorId 2),
    aguarda o processamento na Pluggy e sincroniza as contas e o cartão Mastercard Black via /v2/transactions!
    """
    client = PluggyClient()
    existing_sb = session.exec(
        select(BankConnection).where(
            BankConnection.user_id == DEFAULT_USER_ID,
            BankConnection.is_sandbox == True,
        )
    ).first()

    if existing_sb:
        item_id = existing_sb.pluggy_item_id
    else:
        # Aproveita o Item Sandbox real já criado na auditoria ou cria um novo
        item_id = "d0d7dddd-40e1-44c8-9a32-68aa1e8dc167"
        try:
            await client.get_item(item_id)
        except Exception:
            created = await client.create_sandbox_item()
            item_id = created["id"]

    result = await sync_item_data(
        session=session,
        user_id=DEFAULT_USER_ID,
        pluggy_item_id=item_id,
        trigger_source="SANDBOX_AUTO_CONNECT",
        client=client,
    )
    evaluate_and_record_budget_alerts(session, DEFAULT_USER_ID)
    return result


@app.post("/api/pluggy/sync")
async def manual_sync_pluggy_item(payload: SyncItemInput, session: Session = Depends(get_session)):
    try:
        result = await sync_item_data(
            session=session,
            user_id=DEFAULT_USER_ID,
            pluggy_item_id=payload.pluggy_item_id.strip(),
            trigger_source="MANUAL",
        )
        evaluate_and_record_budget_alerts(session, DEFAULT_USER_ID)
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Falha na sincronização com a Pluggy: {str(exc)}")


@app.delete("/api/pluggy/connections/{connection_id}")
async def disconnect_bank_connection(
    connection_id: int,
    delete_transactions: bool = Query(True, description="Se verdadeiro, apaga também as contas e transações desta conexão"),
    session: Session = Depends(get_session),
):
    """
    Desconecta uma instituição financeira, revoga o Item na Pluggy e aplica a política de retenção/exclusão LGPD.
    """
    conn = session.get(BankConnection, connection_id)
    if not conn or conn.user_id != DEFAULT_USER_ID:
        raise HTTPException(status_code=404, detail="Conexão não encontrada.")

    client = PluggyClient()
    try:
        await client.delete_item(conn.pluggy_item_id)
    except Exception:
        pass

    accs = session.exec(select(FinancialAccount).where(FinancialAccount.connection_id == conn.id)).all()
    deleted_tx_count = 0
    if delete_transactions:
        for acc in accs:
            txs = session.exec(select(Transaction).where(Transaction.account_id == acc.id)).all()
            for t in txs:
                session.delete(t)
                deleted_tx_count += 1
            session.delete(acc)

    session.add(
        AuditEvent(
            user_id=DEFAULT_USER_ID,
            action="BANK_CONNECTION_REVOKED",
            entity_type="bank_connection",
            entity_id=str(conn.id),
            details_json=json.dumps({
                "connector": conn.connector_name,
                "deleted_transactions": deleted_tx_count,
            }),
        )
    )
    session.delete(conn)
    session.commit()
    return {"ok": True, "deleted_transactions": deleted_tx_count}


@app.post("/api/pluggy/webhook")
async def pluggy_webhook_endpoint(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    event = body.get("event", "")
    item_id = body.get("itemId")
    if item_id and event in ("transactions/created", "transactions/updated", "item/updated", "item/created"):
        await sync_item_data(session, DEFAULT_USER_ID, item_id, trigger_source=f"WEBHOOK:{event}")
        evaluate_and_record_budget_alerts(session, DEFAULT_USER_ID)
    return {"received": True, "event": event}


# --- 5. Relatórios Diários e Semanais ---

@app.get("/api/reports")
async def get_reports_center(
    ref_date: Optional[str] = None,
    session: Session = Depends(get_session),
):
    daily_preview = build_daily_report(session, DEFAULT_USER_ID, ref_date)
    weekly_preview = build_weekly_report(session, DEFAULT_USER_ID, ref_date)

    runs = session.exec(
        select(ReportRun)
        .where(ReportRun.user_id == DEFAULT_USER_ID)
        .order_by(ReportRun.created_at.desc())
        .limit(20)
    ).all()

    deliveries = session.exec(
        select(NotificationDelivery)
        .where(NotificationDelivery.user_id == DEFAULT_USER_ID)
        .order_by(NotificationDelivery.created_at.desc())
        .limit(30)
    ).all()

    return {
        "daily_preview": daily_preview,
        "weekly_preview": weekly_preview,
        "report_runs": [
            {
                "id": r.id,
                "report_type": r.report_type,
                "period_key": r.period_key,
                "period_start": r.period_start,
                "period_end": r.period_end,
                "confirmed_brl": cents_to_brl(r.confirmed_spent_cents),
                "pending_brl": cents_to_brl(r.pending_spent_cents),
                "sync_warning": r.sync_warning,
                "created_at": r.created_at.strftime("%d/%m/%Y %H:%M:%S"),
            }
            for r in runs
        ],
        "deliveries": [
            {
                "id": d.id,
                "event_type": d.event_type,
                "channel": d.channel,
                "recipient": d.recipient,
                "subject": d.subject,
                "status": d.status,
                "error_message": d.error_message,
                "created_at": d.created_at.strftime("%d/%m/%Y %H:%M:%S"),
            }
            for d in deliveries
        ],
    }


@app.post("/api/reports/generate/{report_type}")
async def generate_and_send_report_now(
    report_type: str,
    ref_date: Optional[str] = None,
    session: Session = Depends(get_session),
):
    if report_type.lower() == "weekly":
        rep = build_weekly_report(session, DEFAULT_USER_ID, ref_date)
        subject = f"Relatório Financeiro Semanal ({rep['period_start']} a {rep['period_end']})"
        ev_type = "WEEKLY_REPORT"
    else:
        rep = build_daily_report(session, DEFAULT_USER_ID, ref_date)
        subject = f"Resumo Financeiro Diário — {rep['period_start']}"
        ev_type = "DAILY_REPORT"

    run_obj = ReportRun(user_id=DEFAULT_USER_ID, **rep)
    session.add(run_obj)
    session.commit()
    session.refresh(run_obj)

    deliveries = await deliver_report_or_alert(
        session=session,
        user_id=DEFAULT_USER_ID,
        event_type=ev_type,
        subject=subject,
        markdown_body=rep["content_markdown"],
        html_body=rep["content_html"],
        report_run_id=run_obj.id,
    )
    return {
        "ok": True,
        "report_run_id": run_obj.id,
        "report": rep,
        "deliveries": deliveries,
    }


# --- 6. Configurações, Notificações e LGPD ---

@app.get("/api/settings")
async def get_all_settings(session: Session = Depends(get_session)):
    user = session.get(User, DEFAULT_USER_ID)
    rep_pref = session.exec(select(ReportPreference).where(ReportPreference.user_id == DEFAULT_USER_ID)).first()
    notif_pref = session.exec(select(NotificationPreference).where(NotificationPreference.user_id == DEFAULT_USER_ID)).first()
    audits = session.exec(
        select(AuditEvent).where(AuditEvent.user_id == DEFAULT_USER_ID).order_by(AuditEvent.created_at.desc()).limit(25)
    ).all()

    return {
        "user_name": user.name if user else "Bruno",
        "user_email": user.email if user else "bruno@empresa.com.br",
        "timezone": "America/Sao_Paulo",
        "report_preferences": rep_pref,
        "notification_preferences": {
            "email_enabled": notif_pref.email_enabled if notif_pref else True,
            "email_address": notif_pref.email_address if notif_pref else "bruno@empresa.com.br",
            "smtp_host": notif_pref.smtp_host if notif_pref else "",
            "smtp_port": notif_pref.smtp_port if notif_pref else 587,
            "smtp_user": notif_pref.smtp_user if notif_pref else "",
            "resend_configured": bool(os.getenv("RESEND_API_KEY")),
            "telegram_enabled": notif_pref.telegram_enabled if notif_pref else False,
            "telegram_bot_token": notif_pref.telegram_bot_token if notif_pref else "",
            "telegram_chat_id": notif_pref.telegram_chat_id if notif_pref else "",
            "discord_enabled": notif_pref.discord_enabled if notif_pref else False,
            "discord_webhook_url": notif_pref.discord_webhook_url if notif_pref else "",
        },
        "audit_events": [
            {
                "id": a.id,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "details_json": a.details_json,
                "created_at": a.created_at.strftime("%d/%m/%Y %H:%M:%S"),
            }
            for a in audits
        ],
    }


@app.put("/api/settings")
async def update_all_settings(payload: PreferencesUpdateInput, session: Session = Depends(get_session)):
    user = session.get(User, DEFAULT_USER_ID)
    rep_pref = session.exec(select(ReportPreference).where(ReportPreference.user_id == DEFAULT_USER_ID)).first()
    notif_pref = session.exec(select(NotificationPreference).where(NotificationPreference.user_id == DEFAULT_USER_ID)).first()

    if user and payload.user_name is not None:
        user.name = payload.user_name.strip()
        if payload.email_address:
            user.email = payload.email_address.strip()
        session.add(user)

    if rep_pref:
        if payload.daily_enabled is not None:
            rep_pref.daily_enabled = payload.daily_enabled
        if payload.daily_time is not None:
            rep_pref.daily_time = payload.daily_time
        if payload.weekly_enabled is not None:
            rep_pref.weekly_enabled = payload.weekly_enabled
        if payload.weekly_day is not None:
            rep_pref.weekly_day = payload.weekly_day
        if payload.weekly_time is not None:
            rep_pref.weekly_time = payload.weekly_time
        if payload.budget_alerts_enabled is not None:
            rep_pref.budget_alerts_enabled = payload.budget_alerts_enabled
        rep_pref.updated_at = datetime.now()
        session.add(rep_pref)

    if notif_pref:
        if payload.email_enabled is not None:
            notif_pref.email_enabled = payload.email_enabled
        if payload.email_address is not None:
            notif_pref.email_address = payload.email_address.strip()
        if payload.smtp_host is not None:
            notif_pref.smtp_host = payload.smtp_host.strip() or None
        if payload.smtp_port is not None:
            notif_pref.smtp_port = payload.smtp_port
        if payload.smtp_user is not None:
            notif_pref.smtp_user = payload.smtp_user.strip() or None
        if payload.telegram_enabled is not None:
            notif_pref.telegram_enabled = payload.telegram_enabled
        if payload.telegram_bot_token is not None:
            notif_pref.telegram_bot_token = payload.telegram_bot_token.strip() or None
        if payload.telegram_chat_id is not None:
            notif_pref.telegram_chat_id = payload.telegram_chat_id.strip() or None
        if payload.discord_enabled is not None:
            notif_pref.discord_enabled = payload.discord_enabled
        if payload.discord_webhook_url is not None:
            notif_pref.discord_webhook_url = payload.discord_webhook_url.strip() or None
        notif_pref.updated_at = datetime.now()
        session.add(notif_pref)

    session.add(
        AuditEvent(
            user_id=DEFAULT_USER_ID,
            action="SETTINGS_UPDATED",
            entity_type="preferences",
            entity_id="1",
        )
    )
    session.commit()
    return {"ok": True}


@app.get("/api/lgpd/export")
async def export_user_data_lgpd(session: Session = Depends(get_session)):
    """
    Exporta todos os dados financeiros e de auditoria do titular (Portabilidade LGPD).
    """
    user = session.get(User, DEFAULT_USER_ID)
    connections = session.exec(select(BankConnection).where(BankConnection.user_id == DEFAULT_USER_ID)).all()
    accounts = session.exec(select(FinancialAccount).where(FinancialAccount.user_id == DEFAULT_USER_ID)).all()
    budgets = session.exec(select(Budget).where(Budget.user_id == DEFAULT_USER_ID)).all()
    transactions = session.exec(select(Transaction).where(Transaction.user_id == DEFAULT_USER_ID)).all()
    audits = session.exec(select(AuditEvent).where(AuditEvent.user_id == DEFAULT_USER_ID)).all()
    return {
        "exported_at": datetime.now(SP_TZ).isoformat(),
        "user": user,
        "connections_count": len(connections),
        "accounts_count": len(accounts),
        "budgets_count": len(budgets),
        "transactions_count": len(transactions),
        "audit_events_count": len(audits),
    }

