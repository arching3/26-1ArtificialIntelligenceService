from typing import Any

from backend.src.query_analysis import (
    LLMQueryAnalyzer,
    QueryAnalysis,
    RuleBasedQueryAnalyzer,
)


class FakeStructuredOutputLLM:
    def __init__(
        self,
        response: QueryAnalysis | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.schemas: list[type[QueryAnalysis]] = []
        self.invocations: list[Any] = []

    def with_structured_output(
        self, schema: type[QueryAnalysis]
    ) -> "FakeStructuredOutputLLM":
        self.schemas.append(schema)
        return self

    def invoke(self, value: Any) -> QueryAnalysis:
        self.invocations.append(value)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def test_llm_analyzer_uses_structured_output_and_preserves_original_query() -> None:
    query = "삼성전자의 반도체 사업과 연구개발 리스크를 설명해줘"
    llm = FakeStructuredOutputLLM(
        QueryAnalysis(
            query="모델이 임의로 바꾼 질의",
            intents=["business_text", "risk_analysis"],
            intent="business_text",
            scope="segment",
            topics=["business", "research_and_development", "risk"],
            preferred_data_types=["business_text", "risk_text"],
        )
    )

    result = LLMQueryAnalyzer(llm=llm).analyze(query)

    assert llm.schemas == [QueryAnalysis]
    assert len(llm.invocations) == 1
    assert result.query == query
    assert result.intents == ["business_text", "risk_analysis"]
    assert result.scope == "segment"
    assert result.topics == ["business", "research_and_development", "risk"]


def assert_rule_fallback(error: Exception) -> None:
    query = "005930의 2024년 3분기 매출액"
    llm = FakeStructuredOutputLLM(error=error)

    result = LLMQueryAnalyzer(
        llm=llm,
        fallback=RuleBasedQueryAnalyzer(),
    ).analyze(query)

    assert result.query == query
    assert result.company_codes == ["005930"]
    assert result.business_years == [2024]
    assert result.report_codes == ["11014"]
    assert result.metrics == ["revenue"]
    assert result.intent == "financial_numeric"


def test_llm_analyzer_falls_back_when_structured_output_raises() -> None:
    assert_rule_fallback(RuntimeError("LLM failure"))


def test_llm_analyzer_falls_back_when_structured_output_times_out() -> None:
    assert_rule_fallback(TimeoutError())
