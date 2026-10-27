from typing import Optional, List, Tuple, Dict
from sqlmodel import Session, select
from app.models import Category, CategorizationRule, Budget, Transaction
from app.services.financial_engine import normalize_description


INITIAL_CATEGORIES = [
    {"name": "Delivery", "slug": "delivery", "icon": "utensils", "color": "#dc2626", "is_system": True},
    {"name": "Alimentação e Restaurantes", "slug": "alimentacao", "icon": "wine", "color": "#ea580c", "is_system": True},
    {"name": "Supermercado", "slug": "supermercado", "icon": "shopping-cart", "color": "#16a34a", "is_system": True},
    {"name": "Transporte", "slug": "transporte", "icon": "car", "color": "#d97706", "is_system": True},
    {"name": "Combustível", "slug": "combustivel", "icon": "fuel", "color": "#ca8a04", "is_system": True},
    {"name": "Moradia", "slug": "moradia", "icon": "home", "color": "#4f46e5", "is_system": True},
    {"name": "Saúde", "slug": "saude", "icon": "heart-pulse", "color": "#0891b2", "is_system": True},
    {"name": "Assinaturas", "slug": "assinaturas", "icon": "tv", "color": "#2563eb", "is_system": True},
    {"name": "Compras Pessoais", "slug": "compras", "icon": "shopping-bag", "color": "#db2777", "is_system": True},
    {"name": "Lazer", "slug": "lazer", "icon": "sparkles", "color": "#9333ea", "is_system": True},
    {"name": "Educação", "slug": "educacao", "icon": "book-open", "color": "#0d9488", "is_system": True},
    {"name": "Viagens", "slug": "viagens", "icon": "plane", "color": "#0284c7", "is_system": True},
    {"name": "Serviços", "slug": "servicos", "icon": "wrench", "color": "#475569", "is_system": True},
    {"name": "Outros", "slug": "outros", "icon": "folder", "color": "#64748b", "is_system": True},
]

INITIAL_RULES = [
    {"slug": "delivery", "pattern": "IFOOD", "match_field": "ANY", "match_type": "CONTAINS", "priority": 100},
    {"slug": "delivery", "pattern": "IFD*", "match_field": "DESCRIPTION", "match_type": "CONTAINS", "priority": 100},
    {"slug": "delivery", "pattern": "RAPPI", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "delivery", "pattern": "ZE DELIVERY", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "transporte", "pattern": "UBER", "match_field": "ANY", "match_type": "CONTAINS", "priority": 100},
    {"slug": "transporte", "pattern": "99APP", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "transporte", "pattern": "SEM PARAR", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "combustivel", "pattern": "POSTO", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "combustivel", "pattern": "IPIRANGA", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "combustivel", "pattern": "SHELL", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "assinaturas", "pattern": "NETFLIX", "match_field": "ANY", "match_type": "CONTAINS", "priority": 100},
    {"slug": "assinaturas", "pattern": "SPOTIFY", "match_field": "ANY", "match_type": "CONTAINS", "priority": 100},
    {"slug": "assinaturas", "pattern": "AMAZON PRIME", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "assinaturas", "pattern": "OPENAI", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "saude", "pattern": "SMART FIT", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "saude", "pattern": "DROGASIL", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "saude", "pattern": "DROGA RAIA", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "supermercado", "pattern": "PAO DE ACUCAR", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "supermercado", "pattern": "CARREFOUR", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "supermercado", "pattern": "ASSAI", "match_field": "ANY", "match_type": "CONTAINS", "priority": 95},
    {"slug": "alimentacao", "pattern": "OUTBACK", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "alimentacao", "pattern": "MADERO", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "alimentacao", "pattern": "RESTAURANTE", "match_field": "ANY", "match_type": "CONTAINS", "priority": 80},
    {"slug": "moradia", "pattern": "CONDOMINIO", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "moradia", "pattern": "ELETROBRAS", "match_field": "ANY", "match_type": "CONTAINS", "priority": 90},
    {"slug": "servicos", "pattern": "VIVO", "match_field": "ANY", "match_type": "CONTAINS", "priority": 85},
]

INITIAL_BUDGETS = [
    {"slug": "delivery", "name": "Orçamento Delivery (iFood)", "limit_cents": 50000, "alert_thresholds": "50,75,90,100"},
    {"slug": "transporte", "name": "Orçamento Transporte (Uber)", "limit_cents": 30000, "alert_thresholds": "50,75,90,100"},
    {"slug": "alimentacao", "name": "Orçamento Alimentação & Restaurantes", "limit_cents": 60000, "alert_thresholds": "50,75,90,100"},
    {"slug": "supermercado", "name": "Orçamento Supermercado", "limit_cents": 120000, "alert_thresholds": "50,75,90,100"},
    {"slug": "assinaturas", "name": "Orçamento Assinaturas & Streaming", "limit_cents": 20000, "alert_thresholds": "50,75,90,100"},
    {"slug": "saude", "name": "Orçamento Saúde & Academia", "limit_cents": 35000, "alert_thresholds": "50,75,90,100"},
]

PROVIDER_CATEGORY_MAP: Dict[str, str] = {
    "food delivery": "delivery",
    "delivery": "delivery",
    "eating out": "alimentacao",
    "restaurants": "alimentacao",
    "supermarkets": "supermercado",
    "groceries": "supermercado",
    "taxi and ride-sharing": "transporte",
    "public transportation": "transporte",
    "tolls and in vehicle payment": "transporte",
    "gas stations": "combustivel",
    "automotive": "combustivel",
    "housing": "moradia",
    "electricity": "moradia",
    "water": "moradia",
    "rent": "moradia",
    "gyms and fitness centers": "saude",
    "healthcare": "saude",
    "pharmacy": "saude",
    "video streaming": "assinaturas",
    "music streaming": "assinaturas",
    "digital services": "assinaturas",
    "telecommunications": "servicos",
    "services": "servicos",
    "shopping": "compras",
    "clothing": "compras",
    "electronics": "compras",
    "entertainment": "lazer",
    "education": "educacao",
    "travel": "viagens",
}


def ensure_categories_and_rules(session: Session, user_id: int = 1) -> None:
    existing_cats = session.exec(select(Category).where(Category.user_id == user_id)).all()
    slug_to_cat: Dict[str, Category] = {c.slug: c for c in existing_cats}

    if not existing_cats:
        for c_data in INITIAL_CATEGORIES:
            cat = Category(user_id=user_id, **c_data)
            session.add(cat)
        session.commit()
        existing_cats = session.exec(select(Category).where(Category.user_id == user_id)).all()
        slug_to_cat = {c.slug: c for c in existing_cats}

    existing_rules = session.exec(select(CategorizationRule).where(CategorizationRule.user_id == user_id)).all()
    if not existing_rules:
        for r_data in INITIAL_RULES:
            cat = slug_to_cat.get(r_data["slug"])
            if cat and cat.id:
                rule = CategorizationRule(
                    user_id=user_id,
                    category_id=cat.id,
                    pattern=r_data["pattern"],
                    match_field=r_data["match_field"],
                    match_type=r_data["match_type"],
                    priority=r_data["priority"],
                    is_active=True,
                )
                session.add(rule)
        session.commit()

    existing_budgets = session.exec(select(Budget).where(Budget.user_id == user_id)).all()
    if not existing_budgets:
        for b_data in INITIAL_BUDGETS:
            cat = slug_to_cat.get(b_data["slug"])
            if cat and cat.id:
                budget = Budget(
                    user_id=user_id,
                    category_id=cat.id,
                    name=b_data["name"],
                    limit_cents=b_data["limit_cents"],
                    periodicity="MONTHLY",
                    start_date="2026-10-01",
                    include_pending=False,
                    alert_thresholds=b_data["alert_thresholds"],
                    is_active=True,
                )
                session.add(budget)
        session.commit()


def evaluate_rule_match(
    rule: CategorizationRule,
    normalized_desc: str,
    merchant_name: Optional[str],
) -> bool:
    pat = rule.pattern.strip().upper().replace("*", "")
    if not pat:
        return False

    merch_up = (merchant_name or "").strip().upper()
    desc_up = (normalized_desc or "").strip().upper()

    if rule.match_field == "MERCHANT":
        target = merch_up
    elif rule.match_field == "DESCRIPTION":
        target = desc_up
    else:
        target = f"{merch_up} {desc_up}".strip()

    if rule.match_type == "EXACT":
        return target == pat or merch_up == pat or desc_up == pat
    elif rule.match_type == "STARTS_WITH":
        return target.startswith(pat) or merch_up.startswith(pat) or desc_up.startswith(pat)
    else:  # CONTAINS
        return pat in target


def classify_transaction(
    session: Session,
    user_id: int,
    original_description: str,
    merchant_name: Optional[str] = None,
    pluggy_category: Optional[str] = None,
) -> Tuple[Optional[int], str, Optional[str]]:
    """
    Classifica uma transação de forma determinística e transparente, retornando:
    (category_id, categorization_source, applied_rule_name)

    Ordem de prioridade:
    1. Regras personalizadas ativas do usuário (ordenadas por priority DESC, id ASC).
    2. Categoria enriquecida da instituição/provedor (Pluggy) quando mapeável com alta confiança.
    3. Caso não haja correspondência confiável -> (None, "UNCATEGORIZED", None) para revisão manual.
    """
    norm_desc = normalize_description(original_description)

    # 1. Regras do usuário ordenadas por prioridade explícita
    rules = session.exec(
        select(CategorizationRule)
        .where(CategorizationRule.user_id == user_id, CategorizationRule.is_active == True)
        .order_by(CategorizationRule.priority.desc(), CategorizationRule.id.asc())
    ).all()

    for rule in rules:
        if evaluate_rule_match(rule, norm_desc, merchant_name):
            return rule.category_id, "USER_RULE", f"Regra: '{rule.pattern}' ({rule.match_type})"

    # 2. Enriquecimento da instituição / provedor (Pluggy)
    if pluggy_category:
        cat_clean = pluggy_category.strip().lower()
        mapped_slug = PROVIDER_CATEGORY_MAP.get(cat_clean)
        if not mapped_slug:
            for k, v in PROVIDER_CATEGORY_MAP.items():
                if k in cat_clean:
                    mapped_slug = v
                    break
        if mapped_slug:
            cat_obj = session.exec(
                select(Category).where(Category.user_id == user_id, Category.slug == mapped_slug)
            ).first()
            if cat_obj and cat_obj.id:
                return cat_obj.id, "PROVIDER_CATEGORY", f"Pluggy: {pluggy_category}"

    # 3. Baixa confiança -> Não categorizado (aguardando revisão manual)
    return None, "UNCATEGORIZED", None
