import pytest
from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    User,
    Category,
    CategorizationRule,
    Budget,
    Transaction,
)
from app.services.financial_engine import (
    decimal_to_cents,
    cents_to_brl,
    parse_to_sp_timezone,
    normalize_description,
    classify_transaction_nature,
    extract_installment_metadata,
    calculate_budget_metrics,
    is_duplicate_pending_to_posted,
)
from app.services.categorizer_service import (
    ensure_categories_and_rules,
    classify_transaction,
)
from app.services.report_service import (
    evaluate_and_record_budget_alerts,
    build_daily_report,
    build_weekly_report,
)


@pytest.fixture
def mem_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(id=1, email="bruno@teste.com", name="Bruno Teste")
        session.add(user)
        session.commit()
        ensure_categories_and_rules(session, user_id=1)
        yield session


def test_monetary_precision_and_formatting():
    """Garante precisão decimal sem erro de ponto flutuante binário (ex: 0.1 + 0.2)."""
    assert decimal_to_cents("100.00") == 10000
    assert decimal_to_cents(89.90) == 8990
    assert decimal_to_cents(-55.90) == -5590
    assert decimal_to_cents(500) == 50000
    assert cents_to_brl(50000) == "R$ 500,00"
    assert cents_to_brl(123456) == "R$ 1.234,56"
    assert cents_to_brl(-10000) == "-R$ 100,00"


def test_sp_timezone_conversion():
    """Garante conversão correta de datas UTC da Pluggy para America/Sao_Paulo (-03:00)."""
    # 2026-10-10T03:00:00.000Z em UTC equivale a 2026-10-10 00:00:00 em São Paulo
    d_str, dt = parse_to_sp_timezone("2026-10-10T03:00:00.000Z")
    assert d_str == "2026-10-10"
    assert dt.hour == 0

    # 2026-10-27T01:30:00.000Z em UTC equivale a 2026-10-26 22:30:00 em São Paulo (dia anterior!)
    d_str2, dt2 = parse_to_sp_timezone("2026-10-27T01:30:00.000Z")
    assert d_str2 == "2026-10-26"
    assert dt2.hour == 22


def test_ifood_budget_example_from_prompt():
    """
    Valida exatamente o exemplo do prompt:
    - Orçamento mensal Delivery (iFood): R$ 500,00 (50000 centavos)
    - Compra de R$ 100,00 -> Gasto R$ 100,00, Saldo disponível R$ 400,00, 20% consumido.
    - Nova compra de R$ 50,00 -> Gasto R$ 150,00, Saldo disponível R$ 350,00, 30% consumido.
    """
    txs = [
        {"status": "POSTED", "tx_type": "EXPENSE", "amount_cents": 10000},
    ]
    m1 = calculate_budget_metrics(limit_cents=50000, transactions=txs)
    assert m1["confirmed_spent_cents"] == 10000
    assert m1["remaining_cents"] == 40000
    assert m1["percentage_used"] == 20.0
    assert m1["state"] == "HEALTHY"

    txs.append({"status": "POSTED", "tx_type": "EXPENSE", "amount_cents": 5000})
    m2 = calculate_budget_metrics(limit_cents=50000, transactions=txs)
    assert m2["confirmed_spent_cents"] == 15000
    assert m2["remaining_cents"] == 35000
    assert m2["percentage_used"] == 30.0


def test_refunds_cancellations_and_pending_transactions():
    """
    Testa estornos (REFUND), cancelamentos (CANCELLED) e separação de compras pendentes (PENDING).
    """
    txs = [
        {"status": "POSTED", "tx_type": "EXPENSE", "amount_cents": 20000},     # +R$ 200,00 confirmado
        {"status": "POSTED", "tx_type": "REFUND", "amount_cents": -5000},      # -R$ 50,00 estorno
        {"status": "CANCELLED", "tx_type": "EXPENSE", "amount_cents": 99900},  # Cancelada -> ignorada
        {"status": "PENDING", "tx_type": "EXPENSE", "amount_cents": 4000},     # +R$ 40,00 pendente
    ]
    # Com include_pending=False: contabiliza apenas R$ 150,00 confirmados; pendente separado (R$ 40,00)
    m_excl = calculate_budget_metrics(limit_cents=50000, transactions=txs, include_pending=False)
    assert m_excl["confirmed_spent_cents"] == 15000
    assert m_excl["pending_spent_cents"] == 4000
    assert m_excl["accounted_spent_cents"] == 15000
    assert m_excl["remaining_cents"] == 35000

    # Com include_pending=True: incorpora pendentes no saldo disponível (R$ 190,00 consumidos)
    m_incl = calculate_budget_metrics(limit_cents=50000, transactions=txs, include_pending=True)
    assert m_incl["accounted_spent_cents"] == 19000
    assert m_incl["remaining_cents"] == 31000


def test_bill_payment_and_self_transfer_exclusion():
    """
    Garante que pagamento de fatura ('PAGAMENTO FATURA CARTAO VISA' / categoryId 05100000)
    e transferências próprias não sejam classificados como despesa de consumo (EXPENSE).
    """
    t_bill, cents_bill = classify_transaction_nature(
        account_type="BANK",
        raw_amount=-167.70,
        raw_type="DEBIT",
        description="PAGAMENTO FATURA CARTAO VISA",
        pluggy_category="Credit card payment",
        pluggy_category_id="05100000",
    )
    assert t_bill == "BILL_PAYMENT"
    assert cents_bill == 16770

    t_self, _ = classify_transaction_nature(
        account_type="BANK",
        raw_amount=-1000.00,
        raw_type="DEBIT",
        description="TRANSFERENCIA ENTRE CONTAS PROPRIAS",
        pluggy_category="Same person transfer",
    )
    assert t_self == "SELF_TRANSFER"

    # E garante que calculate_budget_metrics ignore ambos caso passem pela lista
    m = calculate_budget_metrics(
        limit_cents=50000,
        transactions=[
            {"status": "POSTED", "tx_type": "BILL_PAYMENT", "amount_cents": 16770},
            {"status": "POSTED", "tx_type": "SELF_TRANSFER", "amount_cents": 100000},
        ],
    )
    assert m["confirmed_spent_cents"] == 0
    assert m["remaining_cents"] == 50000


def test_installment_metadata_extraction():
    """Verifica extração de parcelas sem confundir valor da parcela com valor total."""
    inst_n, inst_tot = extract_installment_metadata({
        "description": "MERCADOLIVRE PARC 03/10",
        "creditCardMetadata": {"installmentNumber": 3, "totalInstallments": 10},
    })
    assert inst_n == 3
    assert inst_tot == 10

    inst_n2, inst_tot2 = extract_installment_metadata({"description": "AMAZON BR 2/6"})
    assert inst_n2 == 2
    assert inst_tot2 == 6


def test_pending_to_posted_deduplication():
    """Impede somar simultaneamente uma compra pendente e sua versão posteriormente confirmada."""
    existing = [
        {
            "id": 42,
            "status": "PENDING",
            "amount_cents": 10000,
            "normalized_description": "IFD*IFOOD COM AGENCIA",
            "original_description": "IFD*IFOOD COM AGENCIA",
            "local_date": "2026-10-25",
        }
    ]
    matched_id = is_duplicate_pending_to_posted(
        existing_txs=existing,
        candidate_merchant_or_desc="IFD*IFOOD COM AGENCIA",
        candidate_amount_cents=10000,
        candidate_local_date="2026-10-26",
        candidate_status="POSTED",
    )
    assert matched_id == 42


def test_categorization_priority_and_alerts(mem_session: Session):
    """Testa regras determinísticas de categorização (iFood -> Delivery, Uber -> Transporte) e disparo de alertas."""
    cat_id, src, rule_name = classify_transaction(
        mem_session, 1, "IFD*IFOOD COM AGENCIA", "iFood", "Food Delivery"
    )
    cat_obj = mem_session.get(Category, cat_id)
    assert cat_obj is not None
    assert cat_obj.slug == "delivery"
    assert src == "USER_RULE"

    # Insere uma compra de R$ 400,00 em Delivery (80% de R$ 500,00) -> deve disparar alertas de 50% e 75%
    tx = Transaction(
        user_id=1,
        external_id="tx-alert-test-1",
        original_description="IFD*IFOOD JANTAR",
        normalized_description="IFD*IFOOD JANTAR",
        amount_cents=40000,
        original_date_iso="2026-10-26T19:00:00-03:00",
        local_date="2026-10-26",
        local_datetime=parse_to_sp_timezone("2026-10-26T19:00:00-03:00")[1],
        tx_type="EXPENSE",
        status="POSTED",
        category_id=cat_id,
    )
    mem_session.add(tx)
    mem_session.commit()

    alerts1 = evaluate_and_record_budget_alerts(mem_session, user_id=1, ref_month="2026-10")
    assert len(alerts1) == 2
    assert [a.threshold_pct for a in alerts1] == [50, 75]

    # Rodar novamente no mesmo mês é idempotente (não duplica alertas)
    alerts2 = evaluate_and_record_budget_alerts(mem_session, user_id=1, ref_month="2026-10")
    assert len(alerts2) == 0

    # Verifica geração de relatório diário e semanal
    daily = build_daily_report(mem_session, user_id=1, ref_date_str="2026-10-26")
    assert "R$ 400,00" in daily["content_markdown"]
    assert "Restam R$ 100,00" in daily["content_markdown"]

    weekly = build_weekly_report(mem_session, user_id=1, ref_date_str="2026-10-26")
    assert "R$ 400,00" in weekly["content_markdown"]
