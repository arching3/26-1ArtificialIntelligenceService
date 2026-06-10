import sqlite3

import pytest

from backend.src import finance_store


@pytest.fixture
def financial_db(tmp_path, monkeypatch):
    db_path = tmp_path / "financials.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE financials (
                stock_code TEXT NOT NULL,
                corp_name TEXT,
                business_year INTEGER,
                revenue INTEGER,
                operating_profit INTEGER,
                net_income INTEGER,
                currency TEXT,
                report_name TEXT,
                report_kind TEXT,
                report_code TEXT,
                period_month INTEGER,
                receipt_no TEXT,
                receipt_date TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO financials(
                stock_code, corp_name, business_year, revenue, operating_profit,
                net_income, currency, report_name, report_kind, report_code,
                period_month, receipt_no, receipt_date, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, 'KRW', ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "000001",
                    "Alpha",
                    2025,
                    100,
                    10,
                    5,
                    "1분기보고서",
                    "quarter",
                    "11013",
                    3,
                    "a-q1",
                    "20250501",
                    "2025-05-01T00:00:00",
                ),
                (
                    "000001",
                    "Alpha",
                    2025,
                    300,
                    30,
                    15,
                    "반기보고서",
                    "half",
                    "11012",
                    6,
                    "a-h1",
                    "20250801",
                    "2025-08-01T00:00:00",
                ),
                (
                    "000001",
                    "Alpha",
                    2024,
                    900,
                    90,
                    45,
                    "사업보고서",
                    "annual",
                    "11011",
                    12,
                    "a-fy",
                    "20250301",
                    "2025-03-01T00:00:00",
                ),
                (
                    "000002",
                    "Beta",
                    2025,
                    200,
                    20,
                    10,
                    "1분기보고서",
                    "quarter",
                    "11013",
                    3,
                    "b-q1",
                    "20250502",
                    "2025-05-02T00:00:00",
                ),
                (
                    "000002",
                    "Beta",
                    2025,
                    50,
                    5,
                    2,
                    "반기보고서",
                    "half",
                    "11012",
                    6,
                    "b-h1",
                    "20250802",
                    "2025-08-02T00:00:00",
                ),
            ],
        )

    def connect():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(finance_store, "init_db", lambda: None)
    monkeypatch.setattr(finance_store, "_connect", connect)
    return db_path


def test_get_financials_selects_requested_reporting_period(financial_db):
    row = finance_store.get_financials(
        "000001",
        business_year=2025,
        report_code="11013",
        period_month=3,
    )

    assert row is not None
    assert row["receipt_no"] == "a-q1"
    assert row["revenue"] == 100


def test_get_financials_keeps_existing_calls_compatible(financial_db):
    latest = finance_store.get_financials("000001")
    latest_for_year = finance_store.get_financials("000001", 2025)

    assert latest is not None
    assert latest["receipt_no"] == "a-h1"
    assert latest_for_year is not None
    assert latest_for_year["receipt_no"] == "a-h1"


def test_compare_metric_uses_same_reporting_period(financial_db):
    rows = finance_store.compare_metric(
        ["000001", "000002"],
        "revenue",
        business_year=2025,
        report_code="11013",
        period_month=3,
    )

    assert [row["stock_code"] for row in rows] == ["000002", "000001"]
    assert [row["revenue"] for row in rows] == [200, 100]
