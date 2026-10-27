import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlmodel import Session, select

from app.models import (
    BankConnection,
    FinancialAccount,
    Transaction,
    SyncRun,
    AuditEvent,
)
from app.services.pluggy_service import PluggyClient
from app.services.financial_engine import (
    decimal_to_cents,
    parse_to_sp_timezone,
    normalize_description,
    classify_transaction_nature,
    extract_installment_metadata,
    is_duplicate_pending_to_posted,
)
from app.services.categorizer_service import classify_transaction


async def sync_item_data(
    session: Session,
    user_id: int,
    pluggy_item_id: str,
    trigger_source: str = "MANUAL",
    client: Optional[PluggyClient] = None,
) -> Dict[str, Any]:
    """
    Sincroniza de ponta a ponta um Item da Pluggy:
    1. Evita sincronizações concorrentes desnecessárias para o mesmo Item.
    2. Atualiza status da conexão (UPDATED, LOGIN_ERROR, CONSENT_EXPIRED, OUTDATED).
    3. Sincroniza contas e cartões (incluindo limites e vencimento).
    4. Sincroniza transações via /v2/transactions com normalização SP, centavos inteiros e reconciliação idempotente.
    5. Registra SyncRun e AuditEvent.
    """
    pluggy = client or PluggyClient()

    # Verifica se já há sincronização RUNNING recente (últimos 2 minutos) para evitar concorrência
    running_sync = session.exec(
        select(SyncRun).where(
            SyncRun.pluggy_item_id == pluggy_item_id,
            SyncRun.status == "RUNNING",
        )
    ).first()
    if running_sync and (datetime.now() - running_sync.started_at).total_seconds() < 120:
        return {
            "ok": False,
            "already_running": True,
            "message": "Sincronização já está em andamento para esta instituição. Aguarde a conclusão.",
        }

    conn = session.exec(
        select(BankConnection).where(
            BankConnection.user_id == user_id,
            BankConnection.pluggy_item_id == pluggy_item_id,
        )
    ).first()

    sync_run = SyncRun(
        user_id=user_id,
        connection_id=conn.id if conn else None,
        pluggy_item_id=pluggy_item_id,
        trigger_source=trigger_source,
        status="RUNNING",
        started_at=datetime.now(),
    )
    session.add(sync_run)
    session.commit()
    session.refresh(sync_run)

    try:
        item_data = await pluggy.get_item(pluggy_item_id)
        connector = item_data.get("connector") or {}
        connector_id = int(connector.get("id") or 608)
        connector_name = connector.get("name") or "Instituição Conectada"
        is_sandbox = bool(connector.get("isSandbox", False))
        is_open_finance = bool(connector.get("isOpenFinance", True))
        item_status = item_data.get("status") or "UPDATED"
        exec_status = item_data.get("executionStatus") or "SUCCESS"
        err_obj = item_data.get("error")
        err_msg = err_obj.get("message") if isinstance(err_obj, dict) else None
        consent_exp_iso = item_data.get("consentExpiresAt")
        _, consent_exp_dt = parse_to_sp_timezone(consent_exp_iso) if consent_exp_iso else ("", None)

        if not conn:
            conn = BankConnection(
                user_id=user_id,
                pluggy_item_id=pluggy_item_id,
                connector_id=connector_id,
                connector_name=connector_name,
                is_sandbox=is_sandbox,
                is_open_finance=is_open_finance,
                status=item_status,
                execution_status=exec_status,
                error_message=err_msg,
                consent_expires_at=consent_exp_dt,
            )
            session.add(conn)
            session.commit()
            session.refresh(conn)
            sync_run.connection_id = conn.id
        else:
            conn.connector_id = connector_id
            conn.connector_name = connector_name
            conn.is_sandbox = is_sandbox
            conn.is_open_finance = is_open_finance
            conn.status = item_status
            conn.execution_status = exec_status
            conn.error_message = err_msg
            conn.consent_expires_at = consent_exp_dt
            conn.updated_at = datetime.now()
            session.add(conn)
            session.commit()

        accounts_raw = await pluggy.get_accounts(pluggy_item_id)
        accounts_synced = 0
        tx_fetched = 0
        tx_inserted = 0
        tx_updated = 0
        tx_dedup = 0

        data_source_label = "PLUGGY_SANDBOX" if is_sandbox else "PLUGGY_PRODUCTION"

        for acc_raw in accounts_raw:
            pluggy_acc_id = acc_raw.get("id")
            if not pluggy_acc_id:
                continue
            accounts_synced += 1

            acc_type = (acc_raw.get("type") or "CREDIT").upper()
            acc_subtype = acc_raw.get("subtype") or "CREDIT_CARD"
            acc_name = acc_raw.get("name") or connector_name
            bal_cents = decimal_to_cents(acc_raw.get("balance") or 0)
            credit_data = acc_raw.get("creditData") or {}
            limit_cents = (
                decimal_to_cents(credit_data["creditLimit"])
                if credit_data.get("creditLimit") is not None
                else None
            )
            avail_cents = (
                decimal_to_cents(credit_data["availableCreditLimit"])
                if credit_data.get("availableCreditLimit") is not None
                else None
            )
            close_date = (credit_data.get("balanceCloseDate") or "")[:10] or None
            due_date = (credit_data.get("balanceDueDate") or "")[:10] or None

            fin_acc = session.exec(
                select(FinancialAccount).where(FinancialAccount.pluggy_account_id == pluggy_acc_id)
            ).first()

            if not fin_acc:
                fin_acc = FinancialAccount(
                    user_id=user_id,
                    connection_id=conn.id,
                    pluggy_account_id=pluggy_acc_id,
                    name=acc_name,
                    account_type=acc_type,
                    subtype=acc_subtype,
                    currency_code=acc_raw.get("currencyCode") or "BRL",
                    balance_cents=bal_cents,
                    credit_limit_cents=limit_cents,
                    available_credit_limit_cents=avail_cents,
                    balance_close_date=close_date,
                    balance_due_date=due_date,
                )
                session.add(fin_acc)
                session.commit()
                session.refresh(fin_acc)
            else:
                fin_acc.name = acc_name
                fin_acc.balance_cents = bal_cents
                fin_acc.credit_limit_cents = limit_cents
                fin_acc.available_credit_limit_cents = avail_cents
                fin_acc.balance_close_date = close_date
                fin_acc.balance_due_date = due_date
                fin_acc.updated_at = datetime.now()
                session.add(fin_acc)
                session.commit()

            # Busca transações via API v2
            raw_txs = await pluggy.get_transactions_v2(pluggy_acc_id)
            tx_fetched += len(raw_txs)

            # Carrega transações pendentes existentes desta conta para reconciliação PENDING -> POSTED
            existing_account_txs = session.exec(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.account_id == fin_acc.id,
                )
            ).all()
            existing_dicts = [
                {
                    "id": t.id,
                    "status": t.status,
                    "amount_cents": t.amount_cents,
                    "normalized_description": t.normalized_description,
                    "original_description": t.original_description,
                    "local_date": t.local_date,
                }
                for t in existing_account_txs
            ]

            for rtx in raw_txs:
                ext_id = rtx.get("id")
                if not ext_id:
                    continue

                orig_desc = rtx.get("description") or rtx.get("descriptionRaw") or "Transação"
                norm_desc = normalize_description(orig_desc)
                merchant_obj = rtx.get("merchant") if isinstance(rtx.get("merchant"), dict) else {}
                merchant_name = (
                    merchant_obj.get("name")
                    or merchant_obj.get("businessName")
                    or None
                )
                merchant_cnpj = merchant_obj.get("cnpj") or None
                pluggy_cat = rtx.get("category")
                pluggy_cat_id = rtx.get("categoryId")
                tx_status = (rtx.get("status") or "POSTED").upper()
                orig_date_iso = rtx.get("date") or datetime.now().isoformat()
                local_date_str, local_dt = parse_to_sp_timezone(orig_date_iso)

                tx_nature, amount_cents = classify_transaction_nature(
                    account_type=acc_type,
                    raw_amount=rtx.get("amount") or 0,
                    raw_type=rtx.get("type"),
                    description=orig_desc,
                    pluggy_category=pluggy_cat,
                    pluggy_category_id=pluggy_cat_id,
                    operation_type=rtx.get("operationType"),
                )

                inst_num, total_inst = extract_installment_metadata(rtx)

                # 1. Verifica se já existe pelo external_id
                existing_tx = session.exec(
                    select(Transaction).where(Transaction.external_id == ext_id)
                ).first()

                if existing_tx:
                    # Atualização idempotente: preserva categoria se revisada manualmente pelo usuário!
                    changed = False
                    if existing_tx.status != tx_status:
                        existing_tx.status = tx_status
                        changed = True
                    if existing_tx.amount_cents != amount_cents:
                        existing_tx.amount_cents = amount_cents
                        changed = True
                    if existing_tx.local_date != local_date_str:
                        existing_tx.local_date = local_date_str
                        existing_tx.local_datetime = local_dt
                        changed = True
                    if not existing_tx.manual_reviewed and existing_tx.category_id is None and tx_nature in ("EXPENSE", "REFUND"):
                        cat_id, cat_src, rule_name = classify_transaction(
                            session, user_id, orig_desc, merchant_name, pluggy_cat
                        )
                        if cat_id:
                            existing_tx.category_id = cat_id
                            existing_tx.categorization_source = cat_src
                            existing_tx.applied_rule_name = rule_name
                            changed = True

                    if changed:
                        existing_tx.updated_at = datetime.now()
                        session.add(existing_tx)
                        tx_updated += 1
                    else:
                        tx_dedup += 1
                    continue

                # 2. Reconciliação PENDING -> POSTED com ID externo diferente
                pending_match_id = is_duplicate_pending_to_posted(
                    existing_dicts,
                    orig_desc,
                    amount_cents,
                    local_date_str,
                    tx_status,
                )
                if pending_match_id:
                    pending_tx = session.get(Transaction, pending_match_id)
                    if pending_tx:
                        pending_tx.external_id = ext_id
                        pending_tx.status = "POSTED"
                        pending_tx.original_date_iso = orig_date_iso
                        pending_tx.local_date = local_date_str
                        pending_tx.local_datetime = local_dt
                        pending_tx.updated_at = datetime.now()
                        session.add(pending_tx)
                        tx_updated += 1
                        continue

                # 3. Nova transação: categoriza se for despesa/estorno
                cat_id, cat_src, rule_name = (None, "NOT_APPLICABLE", None)
                if tx_nature in ("EXPENSE", "REFUND"):
                    cat_id, cat_src, rule_name = classify_transaction(
                        session, user_id, orig_desc, merchant_name, pluggy_cat
                    )

                new_tx = Transaction(
                    user_id=user_id,
                    account_id=fin_acc.id,
                    external_id=ext_id,
                    original_description=orig_desc,
                    normalized_description=norm_desc,
                    merchant_name=merchant_name,
                    merchant_cnpj=merchant_cnpj,
                    amount_cents=amount_cents,
                    currency_code=rtx.get("currencyCode") or "BRL",
                    original_date_iso=orig_date_iso,
                    local_date=local_date_str,
                    local_datetime=local_dt,
                    tx_type=tx_nature,
                    status=tx_status,
                    category_id=cat_id,
                    categorization_source=cat_src,
                    applied_rule_name=rule_name,
                    manual_reviewed=False,
                    installment_number=inst_num,
                    total_installments=total_inst,
                    pluggy_category=pluggy_cat,
                    pluggy_category_id=pluggy_cat_id,
                    data_source=data_source_label,
                    card_label=f"{connector_name} • {acc_name}",
                )
                session.add(new_tx)
                tx_inserted += 1

        conn.last_sync_at = datetime.now()
        session.add(conn)

        sync_run.status = "SUCCESS"
        sync_run.accounts_synced = accounts_synced
        sync_run.transactions_fetched = tx_fetched
        sync_run.transactions_inserted = tx_inserted
        sync_run.transactions_updated = tx_updated
        sync_run.transactions_deduplicated = tx_dedup
        sync_run.finished_at = datetime.now()
        session.add(sync_run)

        audit = AuditEvent(
            user_id=user_id,
            action="PLUGGY_SYNC_SUCCESS",
            entity_type="bank_connection",
            entity_id=str(conn.id),
            details_json=json.dumps({
                "pluggy_item_id": pluggy_item_id,
                "connector": connector_name,
                "is_sandbox": is_sandbox,
                "inserted": tx_inserted,
                "updated": tx_updated,
                "deduplicated": tx_dedup,
            }),
        )
        session.add(audit)
        session.commit()

        return {
            "ok": True,
            "connection_id": conn.id,
            "pluggy_item_id": pluggy_item_id,
            "connector_name": connector_name,
            "is_sandbox": is_sandbox,
            "status": conn.status,
            "accounts_synced": accounts_synced,
            "transactions_fetched": tx_fetched,
            "transactions_inserted": tx_inserted,
            "transactions_updated": tx_updated,
            "transactions_deduplicated": tx_dedup,
        }

    except Exception as exc:
        sync_run.status = "FAILED"
        sync_run.error_details = str(exc)[:500]
        sync_run.finished_at = datetime.now()
        session.add(sync_run)
        if conn:
            conn.error_message = str(exc)[:300]
            session.add(conn)
        session.commit()
        raise
