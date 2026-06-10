from backend.src.query_analysis import analyze_query


def test_analyzes_multiple_metrics_year_quarter_and_stock_code() -> None:
    analysis = analyze_query("005930의 2024년 3분기 매출액과 영업이익을 비교해줘")

    assert analysis.company_codes == ["005930"]
    assert analysis.business_years == [2024]
    assert analysis.report_codes == ["11014"]
    assert analysis.metrics == ["revenue", "operating_profit"]
    assert analysis.intents[:2] == ["financial_numeric", "comparison"]
    assert analysis.preferred_data_types[0] == "structured_financials"


def test_stock_code_lookup_is_not_confused_with_an_explicit_code() -> None:
    analysis = analyze_query("삼성전자 종목코드가 뭐야?")

    assert analysis.intents == ["stock_code_lookup"]
    assert analysis.company_codes == []
    assert analysis.requires_stock_code_lookup is True


def test_extracts_scope_topics_and_composite_intents() -> None:
    analysis = analyze_query("현대차의 지역별 사업 리스크와 유상증자 공시를 알려줘")

    assert analysis.scope == "region"
    assert {"business", "risk", "event"}.issubset(analysis.topics)
    assert analysis.event_types == ["paid_in_capital_increase"]
    assert {"business_text", "risk_analysis", "event_disclosure"}.issubset(analysis.intents)
    assert analysis.preferred_data_types == [
        "risk_text",
        "table_text",
        "business_text",
        "event_text",
    ]


def test_maps_each_reporting_period_to_dart_report_code() -> None:
    assert analyze_query("2025년 1분기 실적").report_code == "11013"
    assert analyze_query("2025년 반기 실적").report_code == "11012"
    assert analyze_query("2025년 3분기 실적").report_code == "11014"
    assert analyze_query("2025년 사업보고서 실적").report_code == "11011"


def test_extracts_stock_codes_followed_by_korean_particles() -> None:
    analysis = analyze_query("005930과 000270 중 2025년 매출액이 더 큰 회사는?")

    assert analysis.stock_codes == ["005930", "000270"]
    assert analysis.intent == "comparison"


def test_business_domain_terms_do_not_fall_back_to_unknown() -> None:
    assert analyze_query("기아의 주요 승용 차종").intent == "business_text"
    assert analyze_query("기아의 주요 원재료와 공급 방식").intent == "business_text"
    assert analyze_query("기아가 확보한 핵심특허 분야").intent == "business_text"
    assert analyze_query("Harman의 1분기 가동률").intent == "business_text"


def test_generic_filing_word_does_not_turn_segment_sales_into_event_query() -> None:
    analysis = analyze_query("2026년 1분기 부문별 매출액과 공시된 구성 비율")

    assert "event_disclosure" not in analysis.intents
    assert analysis.scope == "segment"
