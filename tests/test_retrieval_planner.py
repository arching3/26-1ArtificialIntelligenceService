from backend.src.query_analysis import analyze_query
from backend.src.retrieval_planner import plan_retrieval


def test_financial_plan_uses_sql_and_regular_index() -> None:
    plan = plan_retrieval(analyze_query("005930의 2024년 매출액과 순이익"))

    assert plan.use_sql is True
    assert plan.index_types == ["regular"]
    assert plan.preferred_data_types == ["structured_financials"]
    assert plan.candidate_count == 32
    assert plan.final_count == 8


def test_event_plan_uses_event_index_and_event_text() -> None:
    plan = plan_retrieval(analyze_query("005930의 최근 전환사채 공시"))

    assert plan.use_sql is True
    assert plan.index_types == ["event"]
    assert plan.preferred_data_types == ["event_text"]


def test_composite_plan_searches_both_indexes_with_high_recall() -> None:
    analysis = analyze_query("005930의 사업 리스크와 최근 유상증자 공시를 비교해줘")
    plan = plan_retrieval(analysis, final_count=5)

    assert plan.index_types == ["regular", "event"]
    assert plan.candidate_count == 20
    assert plan.final_count == 5


def test_stock_code_lookup_does_not_search_company_indexes() -> None:
    plan = plan_retrieval(analyze_query("삼성전자 종목코드 알려줘"))

    assert plan.use_sql is False
    assert plan.index_types == []


def test_segment_financial_query_uses_filing_tables_instead_of_company_sql() -> None:
    plan = plan_retrieval(analyze_query("2026년 1분기 부문별 매출액과 구성 비율"))

    assert plan.use_financial_sql is False
    assert plan.index_types == ["regular"]
    assert plan.preferred_data_types == ["table_text", "business_text"]
