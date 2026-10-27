import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import httpx
from sqlmodel import Session, select

from app.models import (
    User,
    BankConnection,
    Category,
    Budget,
    BudgetAlert,
    Transaction,
    ReportPreference,
    NotificationPreference,
    ReportRun,
    NotificationDelivery,
)
from app.services.financial_engine import (
    cents_to_brl,
    today_sp_str,
    calculate_budget_metrics,
)


def evaluate_and_record_budget_alerts(
    session: Session,
    user_id: int = 1,
    ref_month: Optional[str] = None,
) -> List[BudgetAlert]:
    """
    Verifica todos os orçamentos ativos do usuário no mês de referência (ex: '2026-10').
    Quando um orçamento atinge um dos limiares configurados (50%, 75%, 90%, 100%):
    - Grava o evento em BudgetAlert com idempotência por (budget_id, period_Reference, threshold_pct).
    - Evita disparos repetidos para o mesmo limiar no mesmo período.
    """
    month_prefix = ref_month or today_sp_str()[:7]
    budgets = session.exec(
        select(Budget).where(Budget.user_id == user_id, Budget.is_active == True)
    ).all()
    categories = {
        c.id: c for c in session.exec(select(Category).where(Category.user_id == user_id)).all()
    }
    month_txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.local_date.startswith(month_prefix),
        )
    ).all()

    triggered_alerts: List[BudgetAlert] = []

    for b in budgets:
        cat_txs = [
            {"status": t.status, "tx_type": t.tx_type, "amount_cents": t.amount_cents}
            for t in month_txs
            if t.category_id == b.category_id
        ]
        metrics = calculate_budget_metrics(
            limit_cents=b.limit_cents,
            transactions=cat_txs,
            include_pending=b.include_pending,
        )
        pct = metrics["percentage_used"]
        spent_cents = metrics["accounted_spent_cents"]

        thresholds = []
        for raw_t in (b.alert_thresholds or "50,75,90,100").split(","):
            raw_t = raw_t.strip()
            if raw_t.isdigit():
                thresholds.append(int(raw_t))

        cat_name = categories.get(b.category_id).name if b.category_id in categories else b.name

        for th in sorted(thresholds):
            if pct >= th:
                existing = session.exec(
                    select(BudgetAlert).where(
                        BudgetAlert.user_id == user_id,
                        BudgetAlert.budget_id == b.id,
                        BudgetAlert.period_Reference == month_prefix,
                        BudgetAlert.threshold_pct == th,
                    )
                ).first()
                if not existing:
                    msg = (
                        f"O orçamento de {cat_name} atingiu {pct:.0f}% "
                        f"({cents_to_brl(spent_cents)} de {cents_to_brl(b.limit_cents)})."
                    )
                    alert = BudgetAlert(
                        user_id=user_id,
                        budget_id=b.id,
                        period_Reference=month_prefix,
                        threshold_pct=th,
                        spent_cents_at_trigger=spent_cents,
                        limit_cents_at_trigger=b.limit_cents,
                        message=msg,
                        notified=True,
                    )
                    session.add(alert)
                    session.commit()
                    session.refresh(alert)
                    triggered_alerts.append(alert)

    return triggered_alerts


def get_sync_freshness_info(session: Session, user_id: int = 1) -> Tuple[Optional[str], Optional[str]]:
    """
    Retorna (last_sync_formatted, sync_warning).
    Se não houver conexão ou se a última sincronização falhou / tem mais de 24h, explicita o aviso.
    """
    conns = session.exec(select(BankConnection).where(BankConnection.user_id == user_id)).all()
    if not conns:
        return None, "Nenhuma instituição bancária conectada. Os dados exibidos referem-se apenas aos lançamentos locais."

    latest_sync = max((c.last_sync_at for c in conns if c.last_sync_at), default=None)
    failed_conns = [c for c in conns if c.status in ("LOGIN_ERROR", "OUTDATED", "CONSENT_EXPIRED") or c.error_message]

    last_sync_str = latest_sync.strftime("%d/%m/%Y às %H:%M") if latest_sync else None
    warning = None
    if failed_conns:
        c0 = failed_conns[0]
        warning = f"Atenção: A conexão com {c0.connector_name} apresenta status '{c0.status}'. Os dados podem estar desatualizados."
    elif latest_sync and (datetime.now() - latest_sync).total_seconds() > 86400:
        warning = f"Atenção: Última sincronização bancária realizada em {last_sync_str} (há mais de 24h)."

    return last_sync_str, warning


def build_daily_report(
    session: Session,
    user_id: int = 1,
    ref_date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gera o Relatório Financeiro Diário (Markdown, HTML e Texto Telegram) com base nos dados reais persistidos.
    Diferencia gastos confirmados e pendentes, exibe orçamentos e alertas e informa a última sincronização.
    """
    target_date = ref_date_str or today_sp_str()
    month_prefix = target_date[:7]
    dt_obj = datetime.strptime(target_date, "%Y-%m-%d")
    date_br = dt_obj.strftime("%d/%m/%Y")

    categories = {
        c.id: c for c in session.exec(select(Category).where(Category.user_id == user_id)).all()
    }
    budgets = session.exec(
        select(Budget).where(Budget.user_id == user_id, Budget.is_active == True)
    ).all()

    day_txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.local_date == target_date,
        )
    ).all()

    month_txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.local_date.startswith(month_prefix),
        )
    ).all()

    confirmed_day_cents = sum(
        t.amount_cents for t in day_txs if t.status == "POSTED" and t.tx_type in ("EXPENSE", "REFUND")
    )
    pending_day_cents = sum(
        t.amount_cents for t in day_txs if t.status == "PENDING" and t.tx_type in ("EXPENSE", "REFUND")
    )

    by_cat_day: Dict[str, int] = {}
    for t in day_txs:
        if t.status in ("POSTED", "PENDING") and t.tx_type in ("EXPENSE", "REFUND"):
            cname = categories[t.category_id].name if t.category_id in categories else "Não Categorizado"
            by_cat_day[cname] = by_cat_day.get(cname, 0) + t.amount_cents

    last_sync_str, sync_warning = get_sync_freshness_info(session, user_id)
    app_url = os.getenv("APP_PUBLIC_URL", "http://localhost:5173")

    md_lines = [
        f"## Resumo financeiro diário",
        f"**Data:** {date_br}",
        f"**Última sincronização:** {last_sync_str or 'Ainda não sincronizado'}",
        "",
    ]
    if sync_warning:
        md_lines.extend([f"> ⚠️ **{sync_warning}**", ""])

    md_lines.extend([
        f"- **Gastos confirmados no dia:** {cents_to_brl(confirmed_day_cents)}",
        f"- **Gastos pendentes identificados:** {cents_to_brl(pending_day_cents)}",
        "",
    ])

    if by_cat_day:
        md_lines.append("### Categorias com maior gasto no dia:")
        for cname, val in sorted(by_cat_day.items(), key=lambda x: x[1], reverse=True):
            md_lines.append(f"- **{cname}:** {cents_to_brl(val)}")
    else:
        md_lines.append(
            "*Nenhuma transação registrada para esta data até o momento da última sincronização.*"
        )

    md_lines.extend(["", "### Orçamentos Mensais"])
    attention_notes: List[str] = []

    for b in budgets:
        cat_name = categories[b.category_id].name if b.category_id in categories else b.name
        cat_txs = [
            {"status": t.status, "tx_type": t.tx_type, "amount_cents": t.amount_cents}
            for t in month_txs
            if t.category_id == b.category_id
        ]
        m = calculate_budget_metrics(b.limit_cents, cat_txs, include_pending=b.include_pending)
        spent_str = cents_to_brl(m["accounted_spent_cents"])
        limit_str = cents_to_brl(b.limit_cents)
        rem_cents = m["remaining_cents"]
        if rem_cents >= 0:
            rem_str = f"Restam {cents_to_brl(rem_cents)}."
        else:
            rem_str = f"Excedido em {cents_to_brl(abs(rem_cents))}."
        md_lines.append(f"- **{cat_name}:** {spent_str} de {limit_str} utilizados ({m['percentage_used']:.0f}%). {rem_str}")

        if m["percentage_used"] >= 50.0:
            attention_notes.append(f"O orçamento de **{cat_name}** atingiu **{m['percentage_used']:.0f}%**.")

    if attention_notes:
        md_lines.extend(["", "### Atenção"])
        for note in attention_notes:
            md_lines.append(f"- {note}")

    md_lines.extend(["", f"🔗 [Abrir Painel Financeiro]({app_url})"])
    markdown_text = "\n".join(md_lines)

    # HTML Executivo para E-mail
    html_text = f"""
    <div style="font-family: Inter, -apple-system, BlinkMacSystemFont, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; color: #0f172a;">
      <h2 style="margin-top: 0; color: #0f172a;">Resumo financeiro diário — {date_br}</h2>
      <p style="font-size: 13px; color: #64748b;">Última sincronização: <strong>{last_sync_str or 'Ainda não sincronizado'}</strong></p>
      {f'<div style="padding: 12px; background: #fef3c7; border-left: 4px solid #d97706; color: #92400e; font-size: 13px; margin-bottom: 16px;">{sync_warning}</div>' if sync_warning else ''}
      <div style="display: flex; gap: 16px; margin-bottom: 20px;">
        <div style="flex: 1; padding: 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;">
          <div style="font-size: 12px; color: #64748b;">Gastos confirmados no dia</div>
          <div style="font-size: 20px; font-weight: 700; color: #0f172a;">{cents_to_brl(confirmed_day_cents)}</div>
        </div>
        <div style="flex: 1; padding: 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;">
          <div style="font-size: 12px; color: #64748b;">Gastos pendentes</div>
          <div style="font-size: 20px; font-weight: 700; color: #d97706;">{cents_to_brl(pending_day_cents)}</div>
        </div>
      </div>
      <p style="font-size: 14px; line-height: 1.6; white-space: pre-line;">{markdown_text}</p>
      <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b;">
        Acesse o aplicativo em <a href="{app_url}" style="color: #0f766e; font-weight: 600;">{app_url}</a>
      </div>
    </div>
    """

    return {
        "report_type": "DAILY",
        "period_key": f"DAILY:{target_date}",
        "period_start": target_date,
        "period_end": target_date,
        "confirmed_spent_cents": confirmed_day_cents,
        "pending_spent_cents": pending_day_cents,
        "content_markdown": markdown_text,
        "content_html": html_text.strip(),
        "sync_warning": sync_warning,
    }


def build_weekly_report(
    session: Session,
    user_id: int = 1,
    ref_date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gera o Relatório Semanal com comparação explícita com a semana anterior (janela de 7 dias equivalentes),
    evolução diária, orçamentos próximos/acima do limite e nota de suficiência de histórico.
    """
    end_str = ref_date_str or today_sp_str()
    end_dt = datetime.strptime(end_str, "%Y-%m-%d").date()
    start_dt = end_dt - timedelta(days=6)
    prev_end_dt = start_dt - timedelta(days=1)
    prev_start_dt = prev_end_dt - timedelta(days=6)

    start_str = start_dt.strftime("%Y-%m-%d")
    prev_start_str = prev_start_dt.strftime("%Y-%m-%d")
    prev_end_str = prev_end_dt.strftime("%Y-%m-%d")
    month_prefix = end_str[:7]

    categories = {
        c.id: c for c in session.exec(select(Category).where(Category.user_id == user_id)).all()
    }
    budgets = session.exec(
        select(Budget).where(Budget.user_id == user_id, Budget.is_active == True)
    ).all()

    all_txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.local_date >= prev_start_str,
            Transaction.local_date <= end_str,
        )
    ).all()

    curr_week_txs = [t for t in all_txs if start_str <= t.local_date <= end_str]
    prev_week_txs = [t for t in all_txs if prev_start_str <= t.local_date <= prev_end_str]

    confirmed_curr = sum(
        t.amount_cents for t in curr_week_txs if t.status == "POSTED" and t.tx_type in ("EXPENSE", "REFUND")
    )
    pending_curr = sum(
        t.amount_cents for t in curr_week_txs if t.status == "PENDING" and t.tx_type in ("EXPENSE", "REFUND")
    )
    confirmed_prev = sum(
        t.amount_cents for t in prev_week_txs if t.status == "POSTED" and t.tx_type in ("EXPENSE", "REFUND")
    )

    last_sync_str, sync_warning = get_sync_freshness_info(session, user_id)

    # Comparação com a semana anterior
    distinct_days_prev = len({t.local_date for t in prev_week_txs if t.tx_type in ("EXPENSE", "REFUND")})
    if distinct_days_prev < 2:
        comparison_str = (
            f"Histórico insuficiente na semana anterior ({prev_start_dt.strftime('%d/%m')} a {prev_end_dt.strftime('%d/%m')}: "
            f"{cents_to_brl(confirmed_prev)}) para estabelecer uma tendência estatística confiável."
        )
    else:
        diff_cents = confirmed_curr - confirmed_prev
        pct_diff = ((diff_cents / confirmed_prev) * 100.0) if confirmed_prev > 0 else 0.0
        direction = "acima" if diff_cents > 0 else "abaixo"
        comparison_str = (
            f"{cents_to_brl(abs(diff_cents))} ({abs(pct_diff):.1f}%) {direction} da semana anterior "
            f"({prev_start_dt.strftime('%d/%m')} a {prev_end_dt.strftime('%d/%m')}: {cents_to_brl(confirmed_prev)})."
        )

    by_cat_week: Dict[str, int] = {}
    for t in curr_week_txs:
        if t.status in ("POSTED", "PENDING") and t.tx_type in ("EXPENSE", "REFUND"):
            cname = categories[t.category_id].name if t.category_id in categories else "Não Categorizado"
            by_cat_week[cname] = by_cat_week.get(cname, 0) + t.amount_cents

    md_lines = [
        f"## Relatório financeiro semanal ({start_dt.strftime('%d/%m/%Y')} a {end_dt.strftime('%d/%m/%Y')})",
        f"**Última sincronização:** {last_sync_str or 'Ainda não sincronizado'}",
        "",
        f"- **Total de gastos confirmados na semana:** {cents_to_brl(confirmed_curr)}",
        f"- **Total de gastos pendentes:** {cents_to_brl(pending_curr)}",
        f"- **Comparação com a semana anterior:** {comparison_str}",
        "",
        "### Categorias com maiores despesas na semana",
    ]
    if by_cat_week:
        for cname, val in sorted(by_cat_week.items(), key=lambda x: x[1], reverse=True):
            md_lines.append(f"- **{cname}:** {cents_to_brl(val)}")
    else:
        md_lines.append("- *Nenhuma despesa registrada no período.*")

    md_lines.extend(["", "### Evolução diária dos gastos"])
    for i in range(7):
        d_cur = start_dt + timedelta(days=i)
        d_iso = d_cur.strftime("%Y-%m-%d")
        d_sum = sum(
            t.amount_cents
            for t in curr_week_txs
            if t.local_date == d_iso and t.status in ("POSTED", "PENDING") and t.tx_type in ("EXPENSE", "REFUND")
        )
        md_lines.append(f"- **{d_cur.strftime('%d/%m')}:** {cents_to_brl(d_sum)}")

    month_txs = session.exec(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.local_date.startswith(month_prefix),
        )
    ).all()

    md_lines.extend(["", "### Situação dos Orçamentos no Mês"])
    for b in budgets:
        cat_name = categories[b.category_id].name if b.category_id in categories else b.name
        cat_txs = [
            {"status": t.status, "tx_type": t.tx_type, "amount_cents": t.amount_cents}
            for t in month_txs
            if t.category_id == b.category_id
        ]
        m = calculate_budget_metrics(b.limit_cents, cat_txs, include_pending=b.include_pending, days_elapsed=end_dt.day)
        status_tag = "🚨 EXCEDIDO" if m["state"] == "EXCEEDED" else ("⚠️ ATENÇÃO" if m["state"] == "WARNING" else "✅ DENTRO DA META")
        md_lines.append(
            f"- **{cat_name}** [{status_tag}]: {cents_to_brl(m['accounted_spent_cents'])} / {cents_to_brl(b.limit_cents)} "
            f"({m['percentage_used']:.0f}%) — Saldo disponível: {cents_to_brl(m['remaining_cents'])}"
        )

    markdown_text = "\n".join(md_lines)
    html_text = f"<div style='font-family: sans-serif; white-space: pre-line;'>{markdown_text}</div>"

    return {
        "report_type": "WEEKLY",
        "period_key": f"WEEKLY:{start_str}_{end_str}",
        "period_start": start_str,
        "period_end": end_str,
        "confirmed_spent_cents": confirmed_curr,
        "pending_spent_cents": pending_curr,
        "content_markdown": markdown_text,
        "content_html": html_text,
        "sync_warning": sync_warning,
    }


async def deliver_report_or_alert(
    session: Session,
    user_id: int,
    event_type: str,
    subject: str,
    markdown_body: str,
    html_body: str,
    report_run_id: Optional[int] = None,
    budget_alert_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Entrega o relatório ou alerta pelos canais habilitados (Prioridade 1: E-mail via Resend ou SMTP;
    Canais adicionais: Telegram e Discord Webhook).
    Nunca afirma que um e-mail ou mensagem foi enviado se as credenciais não estiverem configuradas;
    registra o estado transparente SIMULATED_NO_CREDENTIALS ou SENT/FAILED em NotificationDelivery.
    """
    prefs = session.exec(select(NotificationPreference).where(NotificationPreference.user_id == user_id)).first()
    if not prefs:
        prefs = NotificationPreference(user_id=user_id)
        session.add(prefs)
        session.commit()
        session.refresh(prefs)

    results: List[Dict[str, Any]] = []

    # 1. Canal E-mail (MVP Prioritário)
    if prefs.email_enabled:
        resend_key = (os.getenv("RESEND_API_KEY") or "").strip()
        smtp_host = (prefs.smtp_host or os.getenv("SMTP_HOST") or "").strip()
        smtp_user = (prefs.smtp_user or os.getenv("SMTP_USER") or "").strip()
        smtp_pass = (os.getenv("SMTP_PASSWORD") or "").strip()

        delivery = NotificationDelivery(
            user_id=user_id,
            report_run_id=report_run_id,
            budget_alert_id=budget_alert_id,
            event_type=event_type,
            channel="EMAIL",
            recipient=prefs.email_address,
            subject=subject,
            body_preview=markdown_body[:1000],
            status="PENDING",
            attempts=1,
        )

        if resend_key:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {resend_key}"},
                        json={
                            "from": os.getenv("EMAIL_FROM", "onboarding@resend.dev"),
                            "to": [prefs.email_address],
                            "subject": subject,
                            "html": html_body,
                        },
                    )
                    if resp.status_code in (200, 201):
                        delivery.status = "SENT"
                        delivery.sent_at = datetime.now()
                    else:
                        delivery.status = "FAILED"
                        delivery.error_message = f"Resend HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                delivery.status = "FAILED"
                delivery.error_message = str(exc)[:300]
        elif smtp_host and smtp_user and smtp_pass:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = smtp_user
                msg["To"] = prefs.email_address
                msg.attach(MIMEText(markdown_body, "plain", "utf-8"))
                msg.attach(MIMEText(html_body, "html", "utf-8"))
                with smtplib.SMTP(smtp_host, prefs.smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, [prefs.email_address], msg.as_string())
                delivery.status = "SENT"
                delivery.sent_at = datetime.now()
            except Exception as exc:
                delivery.status = "FAILED"
                delivery.error_message = str(exc)[:300]
        else:
            delivery.status = "SIMULATED_NO_CREDENTIALS"
            delivery.error_message = (
                "Envio de e-mail em modo de pré-visualização local: configure RESEND_API_KEY ou SMTP_HOST/SMTP_PASSWORD no .env para entrega real."
            )

        session.add(delivery)
        session.commit()
        results.append({
            "channel": "EMAIL",
            "recipient": prefs.email_address,
            "status": delivery.status,
            "error_message": delivery.error_message,
        })

    # 2. Canal Telegram Bot (se configurado/habilitado)
    tg_token = (prefs.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    tg_chat = (prefs.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if prefs.telegram_enabled or (tg_token and tg_chat):
        delivery_tg = NotificationDelivery(
            user_id=user_id,
            report_run_id=report_run_id,
            budget_alert_id=budget_alert_id,
            event_type=event_type,
            channel="TELEGRAM",
            recipient=tg_chat or "nao-configurado",
            subject=subject,
            body_preview=markdown_body[:1000],
            status="PENDING",
            attempts=1,
        )
        if tg_token and tg_chat:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id": tg_chat, "text": markdown_body},
                    )
                    if resp.status_code == 200 and resp.json().get("ok"):
                        delivery_tg.status = "SENT"
                        delivery_tg.sent_at = datetime.now()
                    else:
                        delivery_tg.status = "FAILED"
                        delivery_tg.error_message = resp.text[:250]
            except Exception as exc:
                delivery_tg.status = "FAILED"
                delivery_tg.error_message = str(exc)[:250]
        else:
            delivery_tg.status = "SIMULATED_NO_CREDENTIALS"
            delivery_tg.error_message = "Bot Token ou Chat ID do Telegram não configurados."

        session.add(delivery_tg)
        session.commit()
        results.append({
            "channel": "TELEGRAM",
            "recipient": tg_chat,
            "status": delivery_tg.status,
            "error_message": delivery_tg.error_message,
        })

    # 3. Canal Discord Webhook (se habilitado)
    discord_url = (prefs.discord_webhook_url or os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
    if prefs.discord_enabled and discord_url:
        delivery_dc = NotificationDelivery(
            user_id=user_id,
            report_run_id=report_run_id,
            budget_alert_id=budget_alert_id,
            event_type=event_type,
            channel="DISCORD",
            recipient="Discord Webhook",
            subject=subject,
            body_preview=markdown_body[:1000],
            status="PENDING",
            attempts=1,
        )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(discord_url, json={"content": markdown_body[:1950]})
                if resp.status_code in (200, 204):
                    delivery_dc.status = "SENT"
                    delivery_dc.sent_at = datetime.now()
                else:
                    delivery_dc.status = "FAILED"
                    delivery_dc.error_message = f"Discord HTTP {resp.status_code}"
        except Exception as exc:
            delivery_dc.status = "FAILED"
            delivery_dc.error_message = str(exc)[:250]

        session.add(delivery_dc)
        session.commit()
        results.append({
            "channel": "DISCORD",
            "status": delivery_dc.status,
            "error_message": delivery_dc.error_message,
        })

    return results
