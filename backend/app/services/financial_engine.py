from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
import re
from typing import Dict, Any, List, Optional, Tuple

SP_TZ = ZoneInfo("America/Sao_Paulo")


def decimal_to_cents(value: float | str | Decimal | int) -> int:
    """Converte valor monetário (ex: 100.50 ou -89.90) para centavos inteiros com precisão Decimal."""
    if isinstance(value, int) and not isinstance(value, bool):
        # Na Pluggy, valores inteiros de API (ex: -100) representam R$ -100,00
        d = Decimal(str(value))
    else:
        d = Decimal(str(value))
    cents = (d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def cents_to_brl(cents: int) -> str:
    """Formata centavos inteiros no padrão R$ 1.234,56."""
    sign = "-" if cents < 0 else ""
    abs_cents = abs(int(cents))
    reais = abs_cents // 100
    centavos = abs_cents % 100
    reais_str = f"{reais:,}".replace(",", ".")
    return f"{sign}R$ {reais_str},{centavos:02d}"


def cents_to_float(cents: int) -> float:
    """Apenas para serialização JSON secundária quando necessário."""
    return round(int(cents) / 100.0, 2)


def parse_to_sp_timezone(iso_str: Optional[str]) -> Tuple[str, datetime]:
    """
    Converte uma data ISO (UTC ou com offset) para America/Sao_Paulo.
    Importante: A Pluggy frequentemente envia datas meia-noite como '2026-10-10T03:00:00.000Z',
    que em America/Sao_Paulo (-03:00) corresponde a '2026-10-10 00:00:00'.
    """
    if not iso_str:
        now_sp = datetime.now(SP_TZ).replace(tzinfo=None)
        return now_sp.strftime("%Y-%m-%d"), now_sp

    clean = iso_str.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", clean):
        dt_naive = datetime.strptime(clean, "%Y-%m-%d")
        return clean, dt_naive

    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt_sp = dt
        else:
            dt_sp = dt.astimezone(SP_TZ).replace(tzinfo=None)
        return dt_sp.strftime("%Y-%m-%d"), dt_sp
    except Exception:
        now_sp = datetime.now(SP_TZ).replace(tzinfo=None)
        return now_sp.strftime("%Y-%m-%d"), now_sp


def today_sp_str(ref: Optional[datetime] = None) -> str:
    if ref:
        if ref.tzinfo is not None:
            return ref.astimezone(SP_TZ).strftime("%Y-%m-%d")
        return ref.strftime("%Y-%m-%d")
    return datetime.now(SP_TZ).strftime("%Y-%m-%d")


def normalize_description(desc: str) -> str:
    """Remove múltiplos espaços, prefixos de adquirentes e padroniza em maiúsculas."""
    if not desc:
        return "COMPRA SEM DESCRICAO"
    cleaned = re.sub(r"\s+", " ", desc.strip()).upper()
    return cleaned


BILL_PAYMENT_PATTERNS = [
    "PAGAMENTO FATURA",
    "PAGTO FATURA",
    "PAGAMENTO DE FATURA",
    "FATURA CARTAO",
    "DEBITO AUTOMATICO FATURA",
    "PGTO FATURA",
]

SELF_TRANSFER_PATTERNS = [
    "TRANSFERENCIA ENTRE CONTAS PROPRIAS",
    "TRANSF MESMA TITULARIDADE",
    "RESGATE INVESTIMENTO",
    "APLICACAO CDB",
]


def classify_transaction_nature(
    account_type: str,
    raw_amount: float | str | Decimal,
    raw_type: Optional[str],
    description: str,
    pluggy_category: Optional[str] = None,
    pluggy_category_id: Optional[str] = None,
    operation_type: Optional[str] = None,
) -> Tuple[str, int]:
    """
    Classifica a natureza financeira da transação e retorna (tx_type, amount_cents).
    Regras estritas:
    - Pagamento de fatura ('Credit card payment' / '05100000' ou descrição de pagamento de fatura) -> BILL_PAYMENT
      (NUNCA deve ser somado como despesa de consumo se as compras do cartão já são contabilizadas).
    - Transferência entre contas próprias -> SELF_TRANSFER
    - Estorno / Reembolso no cartão -> REFUND (valor negativo em amount_cents para abater do gasto da categoria!)
    - Compra / Despesa de consumo -> EXPENSE (valor positivo em amount_cents)
    - Salário / Receita em conta corrente -> INCOME
    """
    desc_up = normalize_description(description)
    cat_up = (pluggy_category or "").upper()
    cat_id = (pluggy_category_id or "").strip()
    raw_cents = decimal_to_cents(raw_amount)

    # 1. Detecta Pagamento de Fatura de Cartão
    if (
        cat_id == "05100000"
        or "CREDIT CARD PAYMENT" in cat_up
        or any(pat in desc_up for pat in BILL_PAYMENT_PATTERNS)
    ):
        return "BILL_PAYMENT", abs(raw_cents)

    # 2. Detecta Transferência entre contas próprias / investimentos
    if (
        "SAME PERSON TRANSFER" in cat_up
        or any(pat in desc_up for pat in SELF_TRANSFER_PATTERNS)
    ):
        return "SELF_TRANSFER", abs(raw_cents)

    # 3. Detecta Estorno / Cancelamento explícito na descrição
    if any(k in desc_up for k in ["ESTORNO", "REEMBOLSO", "REFUND", "CANCELAMENTO COMPRA", "CREDITO ESTORNO"]):
        return "REFUND", -abs(raw_cents)

    # 4. Tratamento específico por tipo de conta (CREDIT vs BANK)
    acc_up = (account_type or "CREDIT").upper()
    if acc_up == "CREDIT":
        # Na API v2 da Pluggy para cartão de crédito:
        # Compras vêm com amount negativo (ex: -89.90 para Smart Fit) ou DEBIT.
        # Se vier um valor positivo que não é pagamento de fatura, mas tem indicador de crédito/estorno:
        if raw_cents > 0 and (raw_type == "CREDIT" and ("ESTORNO" in desc_up or "DEVOLUCAO" in desc_up)):
            return "REFUND", -abs(raw_cents)
        # Compras normais no cartão (mesmo que raw_cents seja -8990 ou +8990) viram EXPENSE com valor positivo
        return "EXPENSE", abs(raw_cents)
    else:
        # Conta Corrente (BANK)
        if raw_cents > 0 or (raw_type or "").upper() == "CREDIT":
            if "SALARY" in cat_up or cat_id.startswith("01"):
                return "INCOME", abs(raw_cents)
            return "INCOME", abs(raw_cents)
        return "EXPENSE", abs(raw_cents)


def extract_installment_metadata(raw_tx: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """
    Extrai número da parcela e total de parcelas a partir de creditCardMetadata da Pluggy
    ou de padrões como 'PARC 02/10' ou '2/6' na descrição.
    Não confunde o valor total da compra com a parcela da fatura atual.
    """
    cc_meta = raw_tx.get("creditCardMetadata")
    if isinstance(cc_meta, dict):
        inst_num = cc_meta.get("installmentNumber")
        total_inst = cc_meta.get("totalInstallments")
        if inst_num and total_inst:
            return int(inst_num), int(total_inst)

    desc = raw_tx.get("description") or ""
    match = re.search(r"(?:PARC(?:ELA)?\s*)?(\d{1,2})/(\d{1,2})\b", desc.upper())
    if match:
        n1, n2 = int(match.group(1)), int(match.group(2))
        if 1 <= n1 <= n2 <= 48:
            return n1, n2
    return None, None


def calculate_budget_metrics(
    limit_cents: int,
    transactions: List[Dict[str, Any]],
    include_pending: bool = False,
    days_elapsed: int = 1,
    total_days_in_period: int = 30,
) -> Dict[str, Any]:
    """
    Calcula com precisão de centavos o estado de um orçamento:
    - Despesas confirmadas (POSTED): EXPENSE soma, REFUND subtrai.
    - Despesas pendentes (PENDING): calculadas separadamente e somadas ao consumo principal apenas se include_pending=True.
    - Transações CANCELLED, BILL_PAYMENT, SELF_TRANSFER e INCOME são ignoradas.
    - Trata limite igual a zero, períodos vazios, estornos e excesso de limite.
    """
    confirmed_cents = 0
    pending_cents = 0
    tx_count = 0

    for tx in transactions:
        status = (tx.get("status") or "POSTED").upper()
        tx_type = (tx.get("tx_type") or "EXPENSE").upper()
        amt = int(tx.get("amount_cents", 0))

        if status == "CANCELLED":
            continue
        if tx_type not in ("EXPENSE", "REFUND"):
            continue

        if status == "PENDING":
            pending_cents += amt
            tx_count += 1
        elif status == "POSTED":
            confirmed_cents += amt
            tx_count += 1

    # Garante que estornos maiores que gastos não deixem o gasto negativo na visualização se desejar,
    # mas preservamos o cálculo algébrico exato:
    accounted_cents = confirmed_cents + (pending_cents if include_pending else 0)
    remaining_cents = limit_cents - accounted_cents
    exceeded_cents = max(0, accounted_cents - limit_cents)

    if limit_cents > 0:
        pct_used = round((accounted_cents / limit_cents) * 100.0, 2)
    else:
        pct_used = 100.0 if accounted_cents > 0 else 0.0

    # Projeção linear até o fim do período quando houver pelo menos 3 dias corridos e gasto > 0
    projected_cents = accounted_cents
    if days_elapsed >= 3 and total_days_in_period > days_elapsed and accounted_cents > 0:
        daily_avg = accounted_cents / float(days_elapsed)
        projected_cents = int(round(daily_avg * total_days_in_period))

    if limit_cents <= 0:
        state = "NO_LIMIT"
    elif accounted_cents > limit_cents:
        state = "EXCEEDED"
    elif pct_used >= 80.0:
        state = "WARNING"
    else:
        state = "HEALTHY"

    return {
        "limit_cents": limit_cents,
        "confirmed_spent_cents": confirmed_cents,
        "pending_spent_cents": pending_cents,
        "accounted_spent_cents": accounted_cents,
        "remaining_cents": remaining_cents,
        "exceeded_cents": exceeded_cents,
        "percentage_used": pct_used,
        "projected_spent_cents": projected_cents,
        "transactions_count": tx_count,
        "include_pending": include_pending,
        "state": state,
    }


def is_duplicate_pending_to_posted(
    existing_txs: List[Dict[str, Any]],
    candidate_merchant_or_desc: str,
    candidate_amount_cents: int,
    candidate_local_date: str,
    candidate_status: str,
) -> Optional[int]:
    """
    Evita somar simultaneamente uma compra pendente e sua versão posteriormente confirmada
    caso o provedor atribua um novo external_id na confirmação.
    Retorna o ID interno da transação PENDING correspondente para que seja promovida a POSTED.
    """
    if candidate_status.upper() != "POSTED":
        return None

    cand_norm = normalize_description(candidate_merchant_or_desc)
    try:
        cand_dt = datetime.strptime(candidate_local_date, "%Y-%m-%d").date()
    except Exception:
        return None

    for ex in existing_txs:
        if (ex.get("status") or "").upper() != "PENDING":
            continue
        if int(ex.get("amount_cents", 0)) != int(candidate_amount_cents):
            continue
        ex_norm = normalize_description(ex.get("normalized_description") or ex.get("original_description") or "")
        if ex_norm != cand_norm:
            continue
        try:
            ex_dt = datetime.strptime(ex.get("local_date", ""), "%Y-%m-%d").date()
            if abs((cand_dt - ex_dt).days) <= 3:
                return ex.get("id")
        except Exception:
            continue
    return None
