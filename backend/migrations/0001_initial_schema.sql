-- Migration 0001: Initial Relational Schema for Personal Finance & Open Finance Copilot
-- Precision: All monetary values stored in integer cents (BIGINT/INTEGER).
-- Timezone: America/Sao_Paulo normalized dates.

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT 'Bruno',
    password_hash TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bank_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    pluggy_item_id TEXT NOT NULL UNIQUE,
    connector_id INTEGER NOT NULL DEFAULT 608,
    connector_name TEXT NOT NULL DEFAULT 'Santander',
    is_sandbox BOOLEAN NOT NULL DEFAULT 0,
    is_open_finance BOOLEAN NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'UPDATED',
    execution_status TEXT,
    error_message TEXT,
    consent_expires_at TIMESTAMP,
    last_sync_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS financial_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    connection_id INTEGER REFERENCES bank_connections(id),
    pluggy_account_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL DEFAULT 'CREDIT',
    subtype TEXT DEFAULT 'CREDIT_CARD',
    currency_code TEXT NOT NULL DEFAULT 'BRL',
    balance_cents INTEGER NOT NULL DEFAULT 0,
    credit_limit_cents INTEGER,
    available_credit_limit_cents INTEGER,
    balance_close_date TEXT,
    balance_due_date TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT 'tag',
    color TEXT NOT NULL DEFAULT '#0f766e',
    is_system BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS categorization_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    pattern TEXT NOT NULL,
    match_field TEXT NOT NULL DEFAULT 'ANY',
    match_type TEXT NOT NULL DEFAULT 'CONTAINS',
    priority INTEGER NOT NULL DEFAULT 100,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    name TEXT NOT NULL,
    limit_cents INTEGER NOT NULL DEFAULT 50000,
    periodicity TEXT NOT NULL DEFAULT 'MONTHLY',
    start_date TEXT NOT NULL,
    end_date TEXT,
    include_pending BOOLEAN NOT NULL DEFAULT 0,
    alert_thresholds TEXT NOT NULL DEFAULT '50,75,90,100',
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budget_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    budget_id INTEGER NOT NULL REFERENCES budgets(id),
    period_Reference TEXT NOT NULL,
    threshold_pct INTEGER NOT NULL,
    spent_cents_at_trigger INTEGER NOT NULL,
    limit_cents_at_trigger INTEGER NOT NULL,
    message TEXT NOT NULL,
    notified BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    account_id INTEGER REFERENCES financial_accounts(id),
    external_id TEXT NOT NULL UNIQUE,
    original_description TEXT NOT NULL,
    normalized_description TEXT NOT NULL,
    merchant_name TEXT,
    merchant_cnpj TEXT,
    amount_cents INTEGER NOT NULL,
    currency_code TEXT NOT NULL DEFAULT 'BRL',
    original_date_iso TEXT NOT NULL,
    local_date TEXT NOT NULL,
    local_datetime TIMESTAMP NOT NULL,
    tx_type TEXT NOT NULL DEFAULT 'EXPENSE',
    status TEXT NOT NULL DEFAULT 'POSTED',
    category_id INTEGER REFERENCES categories(id),
    categorization_source TEXT NOT NULL DEFAULT 'UNCATEGORIZED',
    applied_rule_name TEXT,
    manual_reviewed BOOLEAN NOT NULL DEFAULT 0,
    installment_number INTEGER,
    total_installments INTEGER,
    pluggy_category TEXT,
    pluggy_category_id TEXT,
    data_source TEXT NOT NULL DEFAULT 'PLUGGY_SANDBOX',
    card_label TEXT NOT NULL DEFAULT 'Cartão de Crédito',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS report_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    daily_enabled BOOLEAN NOT NULL DEFAULT 1,
    daily_time TEXT NOT NULL DEFAULT '20:00',
    weekly_enabled BOOLEAN NOT NULL DEFAULT 1,
    weekly_day TEXT NOT NULL DEFAULT 'sun',
    weekly_time TEXT NOT NULL DEFAULT '20:00',
    budget_alerts_enabled BOOLEAN NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    email_enabled BOOLEAN NOT NULL DEFAULT 1,
    email_address TEXT NOT NULL DEFAULT 'bruno@empresa.com.br',
    smtp_host TEXT,
    smtp_port INTEGER NOT NULL DEFAULT 587,
    smtp_user TEXT,
    resend_api_key_configured BOOLEAN NOT NULL DEFAULT 0,
    telegram_enabled BOOLEAN NOT NULL DEFAULT 0,
    telegram_bot_token TEXT,
    telegram_chat_id TEXT,
    discord_enabled BOOLEAN NOT NULL DEFAULT 0,
    discord_webhook_url TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    report_type TEXT NOT NULL,
    period_key TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    confirmed_spent_cents INTEGER NOT NULL DEFAULT 0,
    pending_spent_cents INTEGER NOT NULL DEFAULT 0,
    content_markdown TEXT NOT NULL,
    content_html TEXT NOT NULL,
    sync_warning TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    report_run_id INTEGER REFERENCES report_runs(id),
    budget_alert_id INTEGER REFERENCES budget_alerts(id),
    event_type TEXT NOT NULL,
    channel TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_preview TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 1,
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    connection_id INTEGER REFERENCES bank_connections(id),
    pluggy_item_id TEXT NOT NULL,
    trigger_source TEXT NOT NULL DEFAULT 'MANUAL',
    status TEXT NOT NULL DEFAULT 'RUNNING',
    accounts_synced INTEGER NOT NULL DEFAULT 0,
    transactions_fetched INTEGER NOT NULL DEFAULT 0,
    transactions_inserted INTEGER NOT NULL DEFAULT 0,
    transactions_updated INTEGER NOT NULL DEFAULT 0,
    transactions_deduplicated INTEGER NOT NULL DEFAULT 0,
    error_details TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL DEFAULT 1,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details_json TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
