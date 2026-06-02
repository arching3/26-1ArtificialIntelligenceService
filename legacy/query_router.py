import re
from typing import Any, Dict, List, Optional

from company_resolver import find_company_codes_in_text


COMPANY_ALIASES = {
    "005930": ["005930", "삼성전자", "삼성"],
    "035420": ["035420", "네이버", "NAVER", "Naver"],
    "051910": ["051910", "LG화학", "엘지화학"],
    "351320": ["351320", "넥사다이내믹스", "넥사 다이내믹스", "넥사", "에스에이티이엔지"],
    "294870": ["294870", "HDC현대산업개발", "현대산업개발", "IPARK현대산업개발", "아이파크현대산업개발"],
    "000720": ["000720", "현대건설"],
}

METRIC_ALIASES = {
    "revenue": ["매출액", "매출", "영업수익", "수익"],
    "operating_profit": ["영업이익", "영업 이익"],
    "net_income": ["당기순이익", "순이익", "연결당기순이익"],
}

RISK_KEYWORDS = [
    "리스크",
    "위험",
    "소송",
    "제재",
    "우발부채",
    "유동성",
    "신용위험",
    "시장위험",
    "이자율",
    "외환",
    "PF",
    "안전",
    "영업정지",
]

BUSINESS_KEYWORDS = ["사업", "부문", "제품", "서비스", "생산", "전략", "연구개발", "수주"]
COMPARISON_KEYWORDS = ["비교", "중", "더 큰", "더 높은", "높은", "큰", "누가", "어디"]
EVENT_KEYWORDS = [
    "CB",
    "전환사채",
    "신주인수권부사채",
    "교환사채",
    "유상증자",
    "무상증자",
    "감자",
    "주식 취득",
    "주식취득",
    "타법인",
    "출자증권",
    "합병",
    "분할",
    "소송",
    "영업정지",
    "자기주식",
    "주요사항",
    "수시공시",
]
EVENT_TYPE_ALIASES = {
    "convertible_bond_issuance": ["CB", "전환사채"],
    "bond_with_warrant_issuance": ["신주인수권부사채", "BW"],
    "exchangeable_bond_issuance": ["교환사채", "EB"],
    "paid_in_capital_increase": ["유상증자"],
    "equity_acquisition": ["타법인", "출자증권", "주식 취득", "주식취득", "양수", "취득"],
    "lawsuit": ["소송"],
    "business_suspension": ["영업정지"],
    "merger": ["합병"],
    "spin_off": ["분할"],
    "treasury_stock_acquisition": ["자기주식"],
}


def extract_business_year(query: str) -> Optional[int]:
    matches = re.findall(r"(20\d{2})\s*년?", query)
    return int(matches[-1]) if matches else None


def extract_amounts(query: str) -> List[int]:
    """Extract monetary amounts from Korean text patterns like '45억', '85억원', '1,500,000,000원'."""
    amounts: List[int] = []
    # Pattern: N억 (e.g., 45억, 85억원)
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*억\s*(?:원)?", query):
        amounts.append(int(float(match.group(1)) * 100_000_000))
    # Pattern: N,NNN,NNN,NNN원 (e.g., 4,500,000,000원)
    for match in re.finditer(r"([\d,]+)\s*원", query):
        raw = match.group(1).replace(",", "")
        if len(raw) >= 8:  # Only large amounts (1억 이상)
            try:
                amounts.append(int(raw))
            except ValueError:
                pass
    return amounts


def extract_company_codes(query: str) -> List[str]:
    normalized = query or ""
    found: List[str] = []

    def add(code: str) -> None:
        if code not in found:
            found.append(code)

    try:
        for code in find_company_codes_in_text(normalized):
            add(code)
    except Exception:
        pass

    for code, aliases in COMPANY_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            add(code)

    explicit_codes = re.findall(r"\b\d{6}\b", normalized)
    for code in explicit_codes:
        add(code)

    return found


def extract_metric(query: str) -> Optional[str]:
    for metric, aliases in METRIC_ALIASES.items():
        if any(alias in query for alias in aliases):
            return metric
    if "이익률" in query:
        return "operating_profit"
    return None


def extract_event_type(query: str) -> Optional[str]:
    event_types = extract_event_types(query)
    return event_types[0] if len(event_types) == 1 else None


def extract_event_types(query: str) -> List[str]:
    found: List[str] = []
    for event_type, aliases in EVENT_TYPE_ALIASES.items():
        if any(alias in query for alias in aliases):
            found.append(event_type)
    return found


def route_query(query: str) -> Dict[str, Any]:
    text = query or ""
    company_codes = extract_company_codes(text)
    metric = extract_metric(text)
    event_type = extract_event_type(text)
    event_types = extract_event_types(text)
    business_year = extract_business_year(text)

    has_comparison = len(company_codes) >= 2 and any(keyword in text for keyword in COMPARISON_KEYWORDS)
    has_financial = metric is not None or "이익률" in text
    has_event = any(keyword in text for keyword in EVENT_KEYWORDS)
    has_risk = any(keyword in text for keyword in RISK_KEYWORDS)
    has_business = any(keyword in text for keyword in BUSINESS_KEYWORDS)

    if has_comparison and has_financial:
        intent = "comparison"
    elif has_financial:
        intent = "financial_numeric"
    elif has_event:
        intent = "event_disclosure"
    elif has_risk:
        intent = "risk_analysis"
    elif has_business:
        intent = "business_text"
    else:
        intent = "unknown"

    return {
        "intent": intent,
        "company_codes": company_codes,
        "business_year": business_year,
        "metric": metric,
        "event_type": event_type,
        "event_types": event_types,
        "amounts": extract_amounts(text),
    }
