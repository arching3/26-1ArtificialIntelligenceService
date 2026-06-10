from typing import Any

from backend.src.query_analysis import (
    HybridQueryAnalyzer,
    LLMQueryAnalyzer,
    QueryAnalysis,
    RuleBasedQueryAnalyzer,
)


class FakeStructuredOutputLLM:
    def __init__(self, response: QueryAnalysis) -> None:
        self.response = response
        self.schema: type[QueryAnalysis] | None = None

    def with_structured_output(
        self, schema: type[QueryAnalysis]
    ) -> "FakeStructuredOutputLLM":
        self.schema = schema
        return self

    def invoke(self, value: Any) -> QueryAnalysis:
        return self.response


def make_hybrid(llm_result: QueryAnalysis) -> HybridQueryAnalyzer:
    return HybridQueryAnalyzer(
        rules_analyzer=RuleBasedQueryAnalyzer(),
        llm_analyzer=LLMQueryAnalyzer(llm=FakeStructuredOutputLLM(llm_result)),
    )


def test_hybrid_keeps_rule_determined_values_over_conflicting_llm_values() -> None:
    query = "005930의 2024년 3분기 지역별 매출액"
    analyzer = make_hybrid(
        QueryAnalysis(
            query=query,
            intents=["business_text"],
            intent="business_text",
            company_codes=["000270"],
            stock_codes=["000270"],
            business_years=[2023],
            business_year=2023,
            report_codes=["11011"],
            report_code="11011",
            metrics=["net_income"],
            metric="net_income",
            scope="product",
            topics=["product"],
        )
    )

    result = analyzer.analyze(query)

    assert result.company_codes == ["005930"]
    assert result.stock_codes == ["005930"]
    assert result.business_years == [2024]
    assert result.business_year == 2024
    assert result.report_codes == ["11014"]
    assert result.report_code == "11014"
    assert result.metrics == ["revenue"]
    assert result.metric == "revenue"


def test_hybrid_merges_composite_intents_scopes_and_topics() -> None:
    query = "005930의 매출액과 사업 리스크를 알려줘"
    analyzer = make_hybrid(
        QueryAnalysis(
            query=query,
            intents=["comparison", "event_disclosure"],
            intent="comparison",
            scope="segment",
            topics=["research_and_development", "event"],
            preferred_data_types=["structured_financials", "event_text"],
        )
    )

    result = analyzer.analyze(query)

    assert result.scope == "segment"
    assert set(result.intents) == {
        "financial_numeric",
        "comparison",
        "event_disclosure",
        "risk_analysis",
        "business_text",
    }
    assert result.intent == "comparison"
    assert set(result.topics) == {
        "performance",
        "business",
        "risk",
        "research_and_development",
        "event",
    }
    assert result.preferred_data_types == [
        "risk_text",
        "table_text",
        "business_text",
        "event_text",
    ]


def test_hybrid_uses_union_of_rule_and_llm_event_types_without_duplicates() -> None:
    query = "005930의 전환사채와 유상증자 공시"
    analyzer = make_hybrid(
        QueryAnalysis(
            query=query,
            intents=["event_disclosure"],
            intent="event_disclosure",
            topics=["event"],
            event_types=[
                "lawsuit",
                "convertible_bond_issuance",
                "merger",
            ],
        )
    )

    result = analyzer.analyze(query)

    assert result.event_types == [
        "convertible_bond_issuance",
        "paid_in_capital_increase",
        "lawsuit",
        "merger",
    ]
