import re
from typing import Any, Dict, List, Optional

METRIC_ALIASES = {
    "revenue": ["매출액", "매출", "영업수익", "수익"],
    "operating_profit": ["영업이익", "영업 이익"],
    "net_income": ["당기순이익", "순이익", "연결당기순이익"],
}

RISK_KEYWORDS = ["리스크", "위험", "소송", "제재", "우발부채", "유동성", "신용위험", "시장위험", "이자율", "외환", "PF", "안전", "영업정지"]
BUSINESS_KEYWORDS = ["사업", "부문", "제품", "서비스", "생산", "전략", "연구개발", "수주"]
COMPARISON_KEYWORDS = ["비교", "중", "더 큰", "더 높은", "높은", "큰", "누가", "어디"]
EVENT_KEYWORDS = ["CB", "전환사채", "신주인수권부사채", "교환사채", "유상증자", "무상증자", "감자", "주식 취득", "주식취득", "타법인", "출자증권", "합병", "분할", "소송", "영업정지", "자기주식", "주요사항", "수시공시", "공급계약", "최대주주", "벌금", "제재", "횡령", "배임", "상장폐지", "거래정지"]
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
    "single_sales_supply_contract": ["공급계약", "단일판매"],
    "largest_shareholder_change": ["최대주주", "최대주주변경"],
    "sanctions": ["벌금", "제재", "과징금", "행정처분"],
    "embezzlement_breach_of_trust": ["횡령", "배임"],
    "delisting": ["상장폐지"],
    "trading_suspension": ["거래정지", "매매거래정지"],
}


def extract_business_year(query: str) -> Optional[int]:
    matches = re.findall(r"(20\d{2})\s*년?", query or "")
    return int(matches[-1]) if matches else None


def extract_amounts(query: str) -> List[int]:
    amounts: List[int] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*억\s*(?:원)?", query or ""):
        amounts.append(int(float(match.group(1)) * 100_000_000))
    for match in re.finditer(r"([\d,]+)\s*원", query or ""):
        raw = match.group(1).replace(",", "")
        if len(raw) >= 8:
            try:
                amounts.append(int(raw))
            except ValueError:
                pass
    return amounts


def extract_stock_codes(query: str) -> List[str]:
    found: List[str] = []
    for code in re.findall(r"\b\d{6}\b", query or ""):
        if code not in found:
            found.append(code)
    return found


def extract_metric(query: str) -> Optional[str]:
    for metric, aliases in METRIC_ALIASES.items():
        if any(alias in (query or "") for alias in aliases):
            return metric
    if "이익률" in (query or ""):
        return "operating_profit"
    return None


def extract_event_types(query: str) -> List[str]:
    found: List[str] = []
    for event_type, aliases in EVENT_TYPE_ALIASES.items():
        if any(alias in (query or "") for alias in aliases):
            found.append(event_type)
    return found


def route_query(query: str) -> Dict[str, Any]:
    text = query or ""
    stock_codes = extract_stock_codes(text)
    metric = extract_metric(text)
    event_types = extract_event_types(text)
    has_comparison = len(stock_codes) >= 2 and any(keyword in text for keyword in COMPARISON_KEYWORDS)
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
        "company_codes": stock_codes,
        "stock_codes": stock_codes,
        "business_year": extract_business_year(text),
        "metric": metric,
        "event_types": event_types,
        "amounts": extract_amounts(text),
    }
