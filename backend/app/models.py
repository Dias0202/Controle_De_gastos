from typing import Optional
from sqlmodel import SQLModel, Field
from pydantic import NaiveDatetime
from datetime import datetime


class User(SQLModel, table=True):
    __tablename__ = "users"
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, default="bruno@empresa.com.br")
    name: str = Field(default="Bruno")
    password_hash: str = Field(default="")
    timezone: str = Field(default="America/Sao_Paulo")
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class BankConnection(SQLModel, table=True):
    __tablename__ = "bank_connections"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    pluggy_item_id: str = Field(index=True, unique=True)
    connector_id: int = Field(default=608)
    connector_name: str = Field(default="Santander")
    is_sandbox: bool = Field(default=False)
    is_open_finance: bool = Field(default=True)
    status: str = Field(default="UPDATED")  # UPDATED, UPDATING, LOGIN_ERROR, WAITING_USER_INPUT, OUTDATED, CONSENT_EXPIRED, DISCONNECTED
    execution_status: Optional[str] = Field(default="SUCCESS")
    error_message: Optional[str] = Field(default=None)
    consent_expires_at: Optional[NaiveDatetime] = Field(default=None)
    last_sync_at: Optional[NaiveDatetime] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class FinancialAccount(SQLModel, table=True):
    __tablename__ = "financial_accounts"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    connection_id: Optional[int] = Field(default=None, foreign_key="bank_connections.id", index=True)
    pluggy_account_id: str = Field(index=True, unique=True)
    name: str = Field(default="Santander Cartão de Crédito")
    account_type: str = Field(default="CREDIT")  # CREDIT, BANK
    subtype: Optional[str] = Field(default="CREDIT_CARD")
    currency_code: str = Field(default="BRL")
    balance_cents: int = Field(default=0)
    credit_limit_cents: Optional[int] = Field(default=None)
    available_credit_limit_cents: Optional[int] = Field(default=None)
    balance_close_date: Optional[str] = Field(default=None)  # YYYY-MM-DD
    balance_due_date: Optional[str] = Field(default=None)    # YYYY-MM-DD
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class Category(SQLModel, table=True):
    __tablename__ = "categories"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    name: str = Field(index=True)
    slug: str = Field(index=True)
    icon: str = Field(default="tag")
    color: str = Field(default="#0f766e")
    is_system: bool = Field(default=False)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)


class CategorizationRule(SQLModel, table=True):
    __tablename__ = "categorization_rules"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    category_id: int = Field(foreign_key="categories.id", index=True)
    pattern: str = Field(index=True)  # Ex: "IFOOD", "UBER"
    match_field: str = Field(default="ANY")  # MERCHANT, DESCRIPTION, ANY
    match_type: str = Field(default="CONTAINS")  # CONTAINS, EXACT, STARTS_WITH
    priority: int = Field(default=100)  # Maior número = maior prioridade
    is_active: bool = Field(default=True)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)


class Budget(SQLModel, table=True):
    __tablename__ = "budgets"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    category_id: int = Field(foreign_key="categories.id", index=True)
    name: str
    limit_cents: int = Field(default=50000)  # Ex: R$ 500,00 = 50000 centavos
    periodicity: str = Field(default="MONTHLY")  # MONTHLY, WEEKLY
    start_date: str = Field(default="2026-10-01")  # YYYY-MM-DD
    end_date: Optional[str] = Field(default=None)
    include_pending: bool = Field(default=False)  # Regra explícita: incluir ou separar pendentes no cálculo principal
    alert_thresholds: str = Field(default="50,75,90,100")  # Percentuais separados por vírgula
    is_active: bool = Field(default=True)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class BudgetAlert(SQLModel, table=True):
    __tablename__ = "budget_alerts"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    budget_id: int = Field(foreign_key="budgets.id", index=True)
    period_Reference: str = Field(index=True)  # Ex: "2026-10" para controle de idempotência
    threshold_pct: int  # 50, 75, 90, 100
    spent_cents_at_trigger: int
    limit_cents_at_trigger: int
    message: str
    notified: bool = Field(default=False)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    account_id: Optional[int] = Field(default=None, foreign_key="financial_accounts.id", index=True)
    external_id: str = Field(index=True, unique=True)
    original_description: str
    normalized_description: str
    merchant_name: Optional[str] = Field(default=None)
    merchant_cnpj: Optional[str] = Field(default=None)
    amount_cents: int  # Sempre em centavos inteiros. Positivo para despesa, negativo para estorno/crédito
    currency_code: str = Field(default="BRL")
    original_date_iso: str
    local_date: str = Field(index=True)  # YYYY-MM-DD em America/Sao_Paulo
    local_datetime: NaiveDatetime = Field(index=True)
    tx_type: str = Field(default="EXPENSE")  # EXPENSE, REFUND, BILL_PAYMENT, SELF_TRANSFER, INCOME
    status: str = Field(default="POSTED")    # POSTED (Confirmada), PENDING (Pendente), CANCELLED (Cancelada)
    category_id: Optional[int] = Field(default=None, foreign_key="categories.id", index=True)
    categorization_source: str = Field(default="UNCATEGORIZED")  # MANUAL, USER_RULE, KEYWORD_MATCH, PROVIDER_CATEGORY, UNCATEGORIZED
    applied_rule_name: Optional[str] = Field(default=None)
    manual_reviewed: bool = Field(default=False)
    installment_number: Optional[int] = Field(default=None)
    total_installments: Optional[int] = Field(default=None)
    pluggy_category: Optional[str] = Field(default=None)
    pluggy_category_id: Optional[str] = Field(default=None)
    data_source: str = Field(default="PLUGGY_SANDBOX")  # PLUGGY_PRODUCTION, PLUGGY_SANDBOX, MANUAL, DEMO_SEED
    card_label: str = Field(default="Cartão de Crédito")
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class ReportPreference(SQLModel, table=True):
    __tablename__ = "report_preferences"
    id: Optional[int] = Field(default=1, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    daily_enabled: bool = Field(default=True)
    daily_time: str = Field(default="20:00")  # America/Sao_Paulo
    weekly_enabled: bool = Field(default=True)
    weekly_day: str = Field(default="sun")
    weekly_time: str = Field(default="20:00")
    budget_alerts_enabled: bool = Field(default=True)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class NotificationPreference(SQLModel, table=True):
    __tablename__ = "notification_preferences"
    id: Optional[int] = Field(default=1, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    email_enabled: bool = Field(default=True)
    email_address: str = Field(default="bruno@empresa.com.br")
    smtp_host: Optional[str] = Field(default=None)
    smtp_port: int = Field(default=587)
    smtp_user: Optional[str] = Field(default=None)
    resend_api_key_configured: bool = Field(default=False)
    telegram_enabled: bool = Field(default=False)
    telegram_bot_token: Optional[str] = Field(default=None)
    telegram_chat_id: Optional[str] = Field(default=None)
    discord_enabled: bool = Field(default=False)
    discord_webhook_url: Optional[str] = Field(default=None)
    updated_at: NaiveDatetime = Field(default_factory=datetime.now)


class ReportRun(SQLModel, table=True):
    __tablename__ = "report_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    report_type: str = Field(index=True)  # DAILY, WEEKLY
    period_key: str = Field(index=True)   # Ex: "DAILY:2026-10-26" ou "WEEKLY:2026-W43" para idempotência
    period_start: str
    period_end: str
    confirmed_spent_cents: int = Field(default=0)
    pending_spent_cents: int = Field(default=0)
    content_markdown: str
    content_html: str
    sync_warning: Optional[str] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)


class NotificationDelivery(SQLModel, table=True):
    __tablename__ = "notification_deliveries"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    report_run_id: Optional[int] = Field(default=None, foreign_key="report_runs.id")
    budget_alert_id: Optional[int] = Field(default=None, foreign_key="budget_alerts.id")
    event_type: str  # DAILY_REPORT, WEEKLY_REPORT, BUDGET_ALERT, PURCHASE_ALERT
    channel: str     # EMAIL, TELEGRAM, DISCORD, IN_APP
    recipient: str
    subject: str
    body_preview: str
    status: str = Field(default="PENDING")  # SENT, SIMULATED_NO_CREDENTIALS, FAILED, PENDING
    attempts: int = Field(default=1)
    error_message: Optional[str] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
    sent_at: Optional[NaiveDatetime] = Field(default=None)


class SyncRun(SQLModel, table=True):
    __tablename__ = "sync_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, default=1)
    connection_id: Optional[int] = Field(default=None, foreign_key="bank_connections.id")
    pluggy_item_id: str
    trigger_source: str = Field(default="MANUAL")  # MANUAL, SCHEDULED, WEBHOOK, INITIAL_CONNECT
    status: str = Field(default="RUNNING")  # RUNNING, SUCCESS, FAILED
    accounts_synced: int = Field(default=0)
    transactions_fetched: int = Field(default=0)
    transactions_inserted: int = Field(default=0)
    transactions_updated: int = Field(default=0)
    transactions_deduplicated: int = Field(default=0)
    error_details: Optional[str] = Field(default=None)
    started_at: NaiveDatetime = Field(default_factory=datetime.now)
    finished_at: Optional[NaiveDatetime] = Field(default=None)


class AuditEvent(SQLModel, table=True):
    __tablename__ = "audit_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(default=1, index=True)
    action: str = Field(index=True)  # Ex: "CONNECTION_CREATED", "BUDGET_UPDATED", "CATEGORY_MANUAL_OVERRIDE"
    entity_type: str
    entity_id: Optional[str] = Field(default=None)
    details_json: Optional[str] = Field(default=None)
    created_at: NaiveDatetime = Field(default_factory=datetime.now)
