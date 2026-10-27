import os
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from app.main import app, bootstrap_application
from app.database import get_session


@pytest.fixture(name="client")
def client_fixture():
    """
    Cria um banco SQLite em memória isolado para o teste E2E completo da API,
    garantindo que os fluxos de ponta a ponta rodem de forma determinística.
    """
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        bootstrap_application(session)

    def get_test_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = get_test_session
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_e2e_full_journey_budgets_categorization_pluggy_and_reports(client: TestClient):
    # 1. Acessar Dashboard inicial e Categorias
    dash_res = client.get("/api/dashboard?period=month")
    assert dash_res.status_code == 200
    dash = dash_res.json()
    assert dash["user"]["name"] == "Bruno"
    assert len(dash["budgets"]) >= 5

    # Localizar orçamento de Delivery / Apps (iFood) de R$ 500,00
    ifood_budget = next(b for b in dash["budgets"] if "Delivery" in b["category_name"] or "iFood" in b["name"])
    assert ifood_budget["limit_cents"] == 50000
    assert ifood_budget["confirmed_spent_cents"] == 0
    assert ifood_budget["remaining_cents"] == 50000

    # 2. Registrar compra de R$ 100,00 no iFood e verificar cálculo automático (R$ 400,00 restantes / 20%)
    tx1_res = client.post(
        "/api/transactions",
        json={
            "description": "IFD*IFOOD COM AGENCIA DE RESTAURANTES",
            "amount_reais": 100.00,
            "status": "POSTED",
            "tx_type": "EXPENSE",
            "card_label": "Santander Unique Black",
        },
    )
    assert tx1_res.status_code == 200
    assert tx1_res.json()["ok"] is True

    dash_after_100 = client.get("/api/dashboard?period=month").json()
    b_100 = next(b for b in dash_after_100["budgets"] if b["id"] == ifood_budget["id"])
    assert b_100["confirmed_spent_cents"] == 10000
    assert b_100["remaining_cents"] == 40000
    assert b_100["percentage_used"] == 20.0

    # 3. Registrar segunda compra de R$ 50,00 no iFood -> gasto R$ 150,00 / saldo R$ 350,00 (30%)
    tx2_res = client.post(
        "/api/transactions",
        json={
            "description": "IFOOD *BURGER KING",
            "amount_reais": 50.00,
            "status": "POSTED",
            "tx_type": "EXPENSE",
            "card_label": "Santander Unique Black",
        },
    )
    assert tx2_res.status_code == 200

    dash_after_150 = client.get("/api/dashboard?period=month").json()
    b_150 = next(b for b in dash_after_150["budgets"] if b["id"] == ifood_budget["id"])
    assert b_150["confirmed_spent_cents"] == 15000
    assert b_150["remaining_cents"] == 35000
    assert b_150["percentage_used"] == 30.0

    # 4. Testar transação não categorizada + Reclassificação Manual com criação de regra retroativa
    u1 = client.post(
        "/api/transactions",
        json={
            "description": "PADARIA ARTESANAL SAO PAULO 01",
            "amount_reais": 42.50,
            "status": "POSTED",
            "tx_type": "EXPENSE",
        },
    ).json()
    u2 = client.post(
        "/api/transactions",
        json={
            "description": "PADARIA ARTESANAL SAO PAULO 02",
            "amount_reais": 18.00,
            "status": "POSTED",
            "tx_type": "EXPENSE",
        },
    ).json()
    assert u1["category_id"] is None
    assert u2["category_id"] is None

    # Buscar categoria "Alimentação e Restaurantes"
    cats = client.get("/api/categories").json()["categories"]
    rest_cat = next(c for c in cats if "Restaurantes" in c["name"])

    reclass_res = client.put(
        f"/api/transactions/{u1['transaction_id']}/category",
        json={
            "category_id": rest_cat["id"],
            "create_rule": True,
            "rule_pattern": "PADARIA ARTESANAL",
            "rule_match_field": "ANY",
        },
    )
    assert reclass_res.status_code == 200
    assert reclass_res.json()["reclassified_count"] >= 1

    # Verificar no extrato se ambas agora pertencem à categoria Alimentação e Restaurantes
    tx_list = client.get("/api/transactions?search=PADARIA").json()
    assert tx_list["total"] == 2
    for item in tx_list["items"]:
        assert item["category_id"] == rest_cat["id"]

    # 5. Sincronizar Pluggy Sandbox real e testar idempotência na segunda execução
    sb_res = client.post("/api/pluggy/connect-sandbox")
    assert sb_res.status_code == 200
    sb_data = sb_res.json()
    assert sb_data["accounts_synced"] >= 2
    assert sb_data["transactions_inserted"] > 0

    # Segunda sincronização do mesmo Item deve deduplicar 100% sem duplicar lançamentos
    sb_res_2 = client.post("/api/pluggy/sync", json={"pluggy_item_id": sb_data["pluggy_item_id"]})
    assert sb_res_2.status_code == 200
    sb_data_2 = sb_res_2.json()
    assert sb_data_2["transactions_inserted"] == 0
    assert sb_data_2["transactions_deduplicated"] >= sb_data["transactions_inserted"]

    # 6. Gerar Relatório Diário e Relatório Semanal e validar histórico de entregas
    rep_daily = client.post("/api/reports/generate/daily")
    assert rep_daily.status_code == 200
    assert rep_daily.json()["ok"] is True
    assert "resumo financeiro diário" in rep_daily.json()["report"]["content_markdown"].lower()
    assert "restam r$ 350,00" in rep_daily.json()["report"]["content_markdown"].lower()

    rep_weekly = client.post("/api/reports/generate/weekly")
    assert rep_weekly.status_code == 200
    assert rep_weekly.json()["ok"] is True
    assert "relatório financeiro semanal" in rep_weekly.json()["report"]["content_markdown"].lower()

    rep_center = client.get("/api/reports").json()
    assert len(rep_center["report_runs"]) >= 2
    assert len(rep_center["deliveries"]) >= 2

    # 7. Validar Configurações e Exportação LGPD
    set_res = client.put(
        "/api/settings",
        json={
            "user_name": "Bruno (Diretoria)",
            "email_address": "bruno@empresa.com.br",
            "daily_time": "20:00",
        },
    )
    assert set_res.status_code == 200

    lgpd_res = client.get("/api/lgpd/export")
    assert lgpd_res.status_code == 200
    assert lgpd_res.json()["transactions_count"] > 10
