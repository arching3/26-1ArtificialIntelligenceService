from __future__ import annotations

import logging
import re
from typing import Any, List, Literal, Optional, Protocol

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

Intent = Literal[
    "stock_code_lookup",
    "financial_numeric",
    "comparison",
    "event_disclosure",
    "risk_analysis",
    "business_text",
    "unknown",
]
Scope = Literal["company_total", "segment", "product", "region", "unknown"]
AnalyzerMode = Literal["rules", "llm", "hybrid"]

REPORT_CODE_ANNUAL = "11011"
REPORT_CODE_SEMIANNUAL = "11012"
REPORT_CODE_FIRST_QUARTER = "11013"
REPORT_CODE_THIRD_QUARTER = "11014"

METRIC_ALIASES = {
    "revenue": ("매출액", "매출", "영업수익", "수익"),
    "operating_profit": ("영업이익", "영업 이익"),
    "net_income": ("당기순이익", "순이익", "연결당기순이익"),
}

EVENT_TYPE_ALIASES = {
    "convertible_bond_issuance": ("전환사채", "CB"),
    "bond_with_warrant_issuance": ("신주인수권부사채", "BW"),
    "exchangeable_bond_issuance": ("교환사채", "EB"),
    "paid_in_capital_increase": ("유상증자",),
    "equity_acquisition": ("타법인", "출자증권", "주식 취득", "주식취득", "양수"),
    "lawsuit": ("소송",),
    "business_suspension": ("영업정지",),
    "merger": ("합병",),
    "spin_off": ("분할",),
    "treasury_stock_acquisition": ("자기주식 취득", "자기주식취득"),
    "treasury_stock_disposal": ("자기주식 처분", "자기주식처분"),
    "single_sales_supply_contract": ("공급계약", "단일판매"),
    "largest_shareholder_change": ("최대주주", "최대주주변경"),
    "sanctions": ("벌금", "제재", "과징금", "행정처분"),
    "embezzlement_breach_of_trust": ("횡령", "배임"),
    "delisting": ("상장폐지",),
    "trading_suspension": ("거래정지", "매매거래정지"),
}

TOPIC_ALIASES = {
    "stock_code": ("종목코드", "티커", "ticker"),
    "performance": ("실적", "재무", "손익", "매출", "이익"),
    "business": ("사업", "사업모델", "생산", "서비스", "전략"),
    "product": ("제품", "품목", "브랜드", "차종"),
    "raw_material": ("원재료", "원자재", "공급업체", "공급 방식"),
    "production": ("생산능력", "생산실적", "가동률", "생산공장", "공장"),
    "research_and_development": ("연구개발", "연구개발비", "R&D", "R & D"),
    "patent": ("특허", "지적재산권", "라이선스"),
    "contract": ("계약", "수주"),
    "sales_strategy": ("판매전략", "판매 전략"),
    "risk": ("리스크", "위험", "우발부채", "유동성", "신용위험", "시장위험"),
    "event": ("공시", "주요사항", "수시공시", "이벤트"),
}

RISK_KEYWORDS = (
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
    "안전",
    "영업정지",
)
BUSINESS_KEYWORDS = (
    "사업",
    "부문",
    "제품",
    "서비스",
    "생산",
    "전략",
    "연구개발",
    "수주",
    "차종",
    "원재료",
    "원자재",
    "공급업체",
    "특허",
    "지적재산권",
    "가동률",
    "생산능력",
    "생산실적",
    "공장",
    "계약",
)
EVENT_KEYWORDS = (
    "주요사항",
    "수시공시",
    "최근 공시",
    "이벤트 공시",
    "공시 내용",
    "공시사항",
    "주요 공시",
    "이벤트",
    *tuple(alias for aliases in EVENT_TYPE_ALIASES.values() for alias in aliases),
)
COMPARISON_KEYWORDS = ("비교", "대비", "차이", "더 큰", "더 높은", "가장", "순위", "중에서")


class QueryAnalysis(BaseModel):
    query: str
    intents: List[Intent] = Field(default_factory=list)
    intent: Intent = "unknown"
    company_codes: List[str] = Field(default_factory=list)
    stock_codes: List[str] = Field(default_factory=list)
    requires_stock_code_lookup: bool = False
    business_years: List[int] = Field(default_factory=list)
    business_year: Optional[int] = None
    report_codes: List[str] = Field(default_factory=list)
    report_code: Optional[str] = None
    metrics: List[str] = Field(default_factory=list)
    metric: Optional[str] = None
    scope: Scope = "unknown"
    topics: List[str] = Field(default_factory=list)
    event_types: List[str] = Field(default_factory=list)
    preferred_data_types: List[str] = Field(default_factory=list)


class QueryAnalyzer(Protocol):
    def analyze(self, query: str) -> QueryAnalysis:
        ...


class RuleBasedQueryAnalyzer:
    def analyze(self, query: str) -> QueryAnalysis:
        text = str(query or "").strip()
        company_codes = _extract_stock_codes(text)
        years = _extract_business_years(text)
        report_codes = _extract_report_codes(text)
        metrics = _extract_aliases(text, METRIC_ALIASES)
        event_types = _extract_event_types(text)
        topics = _extract_aliases(text, TOPIC_ALIASES)
        scope = _extract_scope(text)
        intents = _extract_intents(text, company_codes, metrics, event_types)
        preferred_data_types = _preferred_data_types(intents, scope)

        return QueryAnalysis(
            query=text,
            intents=intents,
            intent=_primary_intent(intents),
            company_codes=company_codes,
            stock_codes=company_codes,
            requires_stock_code_lookup="stock_code_lookup" in intents and not company_codes,
            business_years=years,
            business_year=years[-1] if years else None,
            report_codes=report_codes,
            report_code=report_codes[-1] if report_codes else None,
            metrics=metrics,
            metric=metrics[0] if metrics else None,
            scope=scope,
            topics=topics,
            event_types=event_types,
            preferred_data_types=preferred_data_types,
        )


LLM_ANALYSIS_PROMPT = """\
You analyze Korean financial and corporate-disclosure questions.
Return only fields defined by the structured output schema.

Classify all applicable intents, the requested scope, topics, and event types.
Extract company/stock codes only when an explicit six-digit code is present.
Use DART report codes 11013 (Q1), 11012 (half/Q2), 11014 (Q3), and
11011 (annual/Q4). Use canonical metric and event names represented by the
schema and examples in the field descriptions. Do not invent identifiers.

Query:
{query}
"""


class LLMQueryAnalyzer:
    """Structured-output analyzer with an unconditional rule-based fallback."""

    def __init__(
        self,
        model: Any = "gpt-4o-mini",
        timeout: Optional[float] = 30,
        *,
        llm: Any = None,
        fallback: Optional[QueryAnalyzer] = None,
    ) -> None:
        self.model = model
        self.timeout = timeout
        self.llm = llm
        self.fallback = fallback or RuleBasedQueryAnalyzer()

    def analyze(self, query: str) -> QueryAnalysis:
        text = str(query or "").strip()
        fallback_analysis = self.fallback.analyze(text)
        try:
            structured_llm = self._get_llm().with_structured_output(QueryAnalysis)
            result = structured_llm.invoke(LLM_ANALYSIS_PROMPT.format(query=text))
            analysis = (
                result
                if isinstance(result, QueryAnalysis)
                else QueryAnalysis.model_validate(result)
            )
            return _normalize_analysis(analysis, text)
        except Exception as exc:
            logger.warning("LLM query analysis failed; using rules fallback: %s", exc)
            return fallback_analysis

    def _get_llm(self) -> Any:
        if self.llm is not None:
            return self.llm
        if not isinstance(self.model, str):
            return self.model

        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
        }
        if self.timeout is not None:
            kwargs["timeout"] = self.timeout
        self.llm = ChatOpenAI(**kwargs)
        return self.llm


class HybridQueryAnalyzer:
    """Combine deterministic rule extraction with semantic LLM classification."""

    def __init__(
        self,
        model: Any = "gpt-4o-mini",
        timeout: Optional[float] = 30,
        *,
        llm: Any = None,
        rules_analyzer: Optional[QueryAnalyzer] = None,
        llm_analyzer: Optional[QueryAnalyzer] = None,
    ) -> None:
        self.rules_analyzer = rules_analyzer or RuleBasedQueryAnalyzer()
        self.llm_analyzer = llm_analyzer or LLMQueryAnalyzer(
            model=model,
            timeout=timeout,
            llm=llm,
            fallback=self.rules_analyzer,
        )

    def analyze(self, query: str) -> QueryAnalysis:
        rules = self.rules_analyzer.analyze(query)
        try:
            llm = self.llm_analyzer.analyze(query)
        except Exception as exc:
            logger.warning("Hybrid LLM query analysis failed; using rules: %s", exc)
            return rules
        return merge_analysis(rules, llm)


def merge_analysis(
    rules_analysis: QueryAnalysis,
    llm_analysis: QueryAnalysis,
) -> QueryAnalysis:
    """Merge analyses while retaining rules as the deterministic authority."""
    query = rules_analysis.query or llm_analysis.query
    intents = _merge_semantic_values(llm_analysis.intents, rules_analysis.intents)
    topics = _merge_semantic_values(llm_analysis.topics, rules_analysis.topics)
    event_types = _dedupe(rules_analysis.event_types + llm_analysis.event_types)
    scope = (
        llm_analysis.scope
        if llm_analysis.scope != "unknown"
        else rules_analysis.scope
    )

    if intents != ["unknown"]:
        intents = [intent for intent in intents if intent != "unknown"]
    if not intents:
        intents = ["unknown"]

    company_codes = list(rules_analysis.company_codes)
    years = list(rules_analysis.business_years)
    report_codes = list(rules_analysis.report_codes)
    metrics = list(rules_analysis.metrics)
    requires_lookup = "stock_code_lookup" in intents and not company_codes

    return QueryAnalysis(
        query=query,
        intents=intents,
        intent=_primary_intent(intents),
        company_codes=company_codes,
        stock_codes=company_codes,
        requires_stock_code_lookup=requires_lookup,
        business_years=years,
        business_year=years[-1] if years else None,
        report_codes=report_codes,
        report_code=report_codes[-1] if report_codes else None,
        metrics=metrics,
        metric=metrics[0] if metrics else None,
        scope=scope,
        topics=topics,
        event_types=event_types,
        preferred_data_types=_preferred_data_types(intents, scope),
    )


def create_query_analyzer(
    mode: AnalyzerMode = "rules",
    *,
    model: Any = "gpt-4o-mini",
    timeout: Optional[float] = 30,
    llm: Any = None,
) -> QueryAnalyzer:
    normalized_mode = str(mode or "rules").strip().lower()
    if normalized_mode in {"rules", "rule", "rule_based"}:
        return RuleBasedQueryAnalyzer()
    if normalized_mode == "llm":
        return LLMQueryAnalyzer(model=model, timeout=timeout, llm=llm)
    if normalized_mode == "hybrid":
        return HybridQueryAnalyzer(model=model, timeout=timeout, llm=llm)
    raise ValueError(f"Unsupported query analyzer mode: {mode}")


get_query_analyzer = create_query_analyzer


def analyze_query(
    query: str,
    analyzer: Optional[QueryAnalyzer] = None,
    *,
    mode: AnalyzerMode = "rules",
    model: Any = "gpt-4o-mini",
    timeout: Optional[float] = 30,
    llm: Any = None,
) -> QueryAnalysis:
    """Analyze a query with an injected analyzer or a selected analyzer mode."""
    selected = analyzer or create_query_analyzer(
        mode=mode,
        model=model,
        timeout=timeout,
        llm=llm,
    )
    return selected.analyze(query)


def _normalize_analysis(analysis: QueryAnalysis, query: str) -> QueryAnalysis:
    data = analysis.model_dump()
    data["query"] = query
    data["company_codes"] = _dedupe(analysis.company_codes)
    data["stock_codes"] = list(data["company_codes"])
    data["business_years"] = _dedupe_int(analysis.business_years)
    data["report_codes"] = _dedupe(analysis.report_codes)
    data["metrics"] = _dedupe(analysis.metrics)
    data["topics"] = _dedupe(analysis.topics)
    data["event_types"] = _dedupe(analysis.event_types)
    data["intents"] = _dedupe(analysis.intents) or ["unknown"]
    data["intent"] = _primary_intent(data["intents"])
    data["business_year"] = (
        data["business_years"][-1] if data["business_years"] else None
    )
    data["report_code"] = (
        data["report_codes"][-1] if data["report_codes"] else None
    )
    data["metric"] = data["metrics"][0] if data["metrics"] else None
    data["requires_stock_code_lookup"] = (
        "stock_code_lookup" in data["intents"] and not data["company_codes"]
    )
    data["preferred_data_types"] = _preferred_data_types(
        data["intents"],
        analysis.scope,
    )
    return QueryAnalysis.model_validate(data)


def _merge_semantic_values(llm_values: List[str], rule_values: List[str]) -> List[str]:
    return _dedupe(list(llm_values) + list(rule_values))


def _extract_stock_codes(text: str) -> List[str]:
    return _dedupe(re.findall(r"(?<!\d)\d{6}(?!\d)", text))


def _extract_business_years(text: str) -> List[int]:
    return _dedupe_int(int(value) for value in re.findall(r"(?<!\d)(20\d{2})\s*년?", text))


def _extract_report_codes(text: str) -> List[str]:
    matches = []
    patterns = (
        (REPORT_CODE_FIRST_QUARTER, r"1\s*분기|(?<![A-Z0-9])1Q(?![A-Z0-9])"),
        (REPORT_CODE_SEMIANNUAL, r"2\s*분기|반기|상반기|(?<![A-Z0-9])2Q(?![A-Z0-9])"),
        (REPORT_CODE_THIRD_QUARTER, r"3\s*분기|(?<![A-Z0-9])3Q(?![A-Z0-9])"),
        (REPORT_CODE_ANNUAL, r"4\s*분기|사업보고서|연간|연차|온기|(?<![A-Z0-9])4Q(?![A-Z0-9])"),
    )
    for report_code, pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            matches.append(report_code)
    return matches


def _extract_aliases(text: str, aliases_by_name: dict[str, tuple[str, ...]]) -> List[str]:
    lowered = text.lower()
    return [
        name
        for name, aliases in aliases_by_name.items()
        if any(alias.lower() in lowered for alias in aliases)
    ]


def _extract_event_types(text: str) -> List[str]:
    found = _extract_aliases(text, EVENT_TYPE_ALIASES)
    if "자기주식" in text and not any(item.startswith("treasury_stock") for item in found):
        found.extend(["treasury_stock_acquisition", "treasury_stock_disposal"])
    return found


def _extract_scope(text: str) -> Scope:
    if any(keyword in text for keyword in ("지역", "국내", "해외", "국가별", "지역별")):
        return "region"
    if any(keyword in text for keyword in ("제품", "품목", "브랜드", "제품별", "차종")):
        return "product"
    if any(keyword in text for keyword in ("부문", "사업부", "세그먼트", "부문별")):
        return "segment"
    if any(keyword in text for keyword in ("전체", "전사", "회사 전체", "기업 전체", "연결", "별도")):
        return "company_total"
    return "unknown"


def _extract_intents(
    text: str,
    company_codes: List[str],
    metrics: List[str],
    event_types: List[str],
) -> List[Intent]:
    intents: List[Intent] = []
    if any(keyword.lower() in text.lower() for keyword in TOPIC_ALIASES["stock_code"]):
        intents.append("stock_code_lookup")
    if metrics:
        intents.append("financial_numeric")
    if any(keyword in text for keyword in COMPARISON_KEYWORDS) or len(company_codes) >= 2:
        intents.append("comparison")
    if event_types or any(keyword.lower() in text.lower() for keyword in EVENT_KEYWORDS):
        intents.append("event_disclosure")
    if any(keyword in text for keyword in RISK_KEYWORDS):
        intents.append("risk_analysis")
    if any(keyword in text for keyword in BUSINESS_KEYWORDS):
        intents.append("business_text")
    return intents or ["unknown"]


def _preferred_data_types(intents: List[Intent], scope: Scope) -> List[str]:
    preferred: List[str] = []
    if ("financial_numeric" in intents or "comparison" in intents) and scope not in {
        "segment",
        "product",
        "region",
    }:
        preferred.append("structured_financials")
    if "risk_analysis" in intents:
        preferred.append("risk_text")
    if scope in {"segment", "product", "region"}:
        preferred.extend(["table_text", "business_text"])
    elif "business_text" in intents:
        preferred.extend(["business_text", "table_text"])
    if "event_disclosure" in intents:
        preferred.append("event_text")
    return _dedupe(preferred)


def _primary_intent(intents: List[Intent]) -> Intent:
    intent_set = set(intents)
    if "stock_code_lookup" in intent_set:
        return "stock_code_lookup"
    if {"financial_numeric", "comparison"}.issubset(intent_set):
        return "comparison"
    for intent in (
        "financial_numeric",
        "event_disclosure",
        "risk_analysis",
        "business_text",
        "comparison",
    ):
        if intent in intent_set:
            return intent
    return "unknown"


def _dedupe(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def _dedupe_int(values) -> List[int]:
    return list(dict.fromkeys(values))
