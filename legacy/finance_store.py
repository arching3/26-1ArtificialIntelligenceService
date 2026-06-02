import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DB_PATH = "finance.db"
METRIC_COLUMNS = {
    "revenue": "revenue",
    "operating_profit": "operating_profit",
    "net_income": "net_income",
}


def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True) if Path(db_path).parent != Path(".") else None
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS companies (
                company_code TEXT PRIMARY KEY,
                company_name TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS financials (
                company_code TEXT NOT NULL,
                company_name TEXT,
                business_year INTEGER,
                revenue INTEGER,
                operating_profit INTEGER,
                net_income INTEGER,
                currency TEXT DEFAULT 'KRW',
                report_name TEXT,
                receipt_no TEXT,
                receipt_date TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (company_code, business_year, receipt_no)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_financials_company_year
            ON financials(company_code, business_year)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_disclosures (
                company_code TEXT NOT NULL,
                company_name TEXT,
                event_type TEXT NOT NULL,
                event_label TEXT,
                report_name TEXT,
                receipt_no TEXT NOT NULL,
                receipt_date TEXT,
                decision_date TEXT,
                amount INTEGER,
                target_company TEXT,
                purpose TEXT,
                conversion_price INTEGER,
                conversion_shares INTEGER,
                acquisition_shares INTEGER,
                acquisition_ratio TEXT,
                payment_method TEXT,
                target_detail TEXT,
                raw_json TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (receipt_no, event_type)
            )
            """
        )
        # Add target_detail column if not exists (migration for existing DBs)
        try:
            conn.execute("ALTER TABLE event_disclosures ADD COLUMN target_detail TEXT")
        except Exception:
            pass  # Column already exists
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_disclosures_company_date
            ON event_disclosures(company_code, receipt_date, decision_date)
            """
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def upsert_company(company_code: str, company_name: str = "", db_path: str = DB_PATH) -> None:
    init_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO companies(company_code, company_name, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(company_code) DO UPDATE SET
                company_name=excluded.company_name,
                updated_at=excluded.updated_at
            """,
            (company_code, company_name, _now()),
        )


def list_companies(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT company_code, company_name, updated_at
            FROM companies
            ORDER BY company_name, company_code
            """
        ).fetchall()
    return [dict(row) for row in rows]


def find_companies_by_name(query: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    init_db(db_path)
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return []

    compact_query = "".join(normalized_query.split())
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT company_code, company_name, updated_at
            FROM companies
            WHERE company_name = ?
               OR REPLACE(company_name, ' ', '') = ?
               OR company_name LIKE ?
            ORDER BY
                CASE
                    WHEN company_name = ? THEN 0
                    WHEN REPLACE(company_name, ' ', '') = ? THEN 1
                    ELSE 2
                END,
                LENGTH(company_name),
                company_name
            LIMIT 20
            """,
            (
                normalized_query,
                compact_query,
                f"%{normalized_query}%",
                normalized_query,
                compact_query,
            ),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_financials(structured_data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    init_db(db_path)
    company_code = str(structured_data.get("company_code") or "").strip()
    if not company_code:
        raise ValueError("structured_data.company_code is required")

    upsert_company(company_code, str(structured_data.get("company_name") or ""), db_path=db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO financials(
                company_code, company_name, business_year, revenue,
                operating_profit, net_income, currency, report_name,
                receipt_no, receipt_date, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_code, business_year, receipt_no) DO UPDATE SET
                company_name=excluded.company_name,
                revenue=excluded.revenue,
                operating_profit=excluded.operating_profit,
                net_income=excluded.net_income,
                currency=excluded.currency,
                report_name=excluded.report_name,
                receipt_date=excluded.receipt_date,
                updated_at=excluded.updated_at
            """,
            (
                company_code,
                structured_data.get("company_name"),
                _as_int_or_none(structured_data.get("business_year")),
                _as_int_or_none(structured_data.get("revenue")),
                _as_int_or_none(structured_data.get("operating_profit")),
                _as_int_or_none(structured_data.get("net_income")),
                structured_data.get("currency") or "KRW",
                structured_data.get("report_name"),
                structured_data.get("receipt_no") or "",
                structured_data.get("receipt_date"),
                _now(),
            ),
        )


def _row_to_dict(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    return dict(row) if row else None


def get_financials(
    company_code: str,
    business_year: Optional[int] = None,
    db_path: str = DB_PATH,
) -> Optional[Dict[str, Any]]:
    init_db(db_path)
    with _connect(db_path) as conn:
        if business_year is not None:
            row = conn.execute(
                """
                SELECT * FROM financials
                WHERE company_code = ? AND business_year = ?
                ORDER BY receipt_date DESC, updated_at DESC
                LIMIT 1
                """,
                (company_code, int(business_year)),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM financials
                WHERE company_code = ?
                ORDER BY business_year DESC, receipt_date DESC, updated_at DESC
                LIMIT 1
                """,
                (company_code,),
            ).fetchone()
    return _row_to_dict(row)


def compare_metric(
    company_codes: Iterable[str],
    metric: str,
    business_year: Optional[int] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    column = METRIC_COLUMNS.get(metric)
    if not column:
        raise ValueError(f"지원하지 않는 metric입니다: {metric}")

    rows = []
    for company_code in company_codes:
        row = get_financials(company_code, business_year=business_year, db_path=db_path)
        if row is not None:
            rows.append(row)

    return sorted(
        rows,
        key=lambda item: item.get(column) if item.get(column) is not None else float("-inf"),
        reverse=True,
    )


def upsert_event_disclosure(event_data: Dict[str, Any], db_path: str = DB_PATH) -> None:
    init_db(db_path)
    company_code = str(event_data.get("company_code") or "").strip()
    receipt_no = str(event_data.get("receipt_no") or "").strip()
    event_type = str(event_data.get("event_type") or "").strip()
    if not company_code or not receipt_no or not event_type:
        raise ValueError("event_data requires company_code, receipt_no, and event_type")

    raw_json = event_data.get("raw_json")
    if raw_json is not None and not isinstance(raw_json, str):
        raw_json = json.dumps(raw_json, ensure_ascii=False, default=str)

    upsert_company(company_code, str(event_data.get("company_name") or ""), db_path=db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO event_disclosures(
                company_code, company_name, event_type, event_label,
                report_name, receipt_no, receipt_date, decision_date, amount,
                target_company, purpose, conversion_price, conversion_shares,
                acquisition_shares, acquisition_ratio, payment_method, target_detail, raw_json,
                updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receipt_no, event_type) DO UPDATE SET
                company_code=excluded.company_code,
                company_name=excluded.company_name,
                event_label=excluded.event_label,
                report_name=excluded.report_name,
                receipt_date=excluded.receipt_date,
                decision_date=excluded.decision_date,
                amount=excluded.amount,
                target_company=excluded.target_company,
                purpose=excluded.purpose,
                conversion_price=excluded.conversion_price,
                conversion_shares=excluded.conversion_shares,
                acquisition_shares=excluded.acquisition_shares,
                acquisition_ratio=excluded.acquisition_ratio,
                payment_method=excluded.payment_method,
                target_detail=excluded.target_detail,
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                company_code,
                event_data.get("company_name"),
                event_type,
                event_data.get("event_label"),
                event_data.get("report_name"),
                receipt_no,
                event_data.get("receipt_date"),
                event_data.get("decision_date"),
                _as_int_or_none(event_data.get("amount")),
                event_data.get("target_company"),
                event_data.get("purpose"),
                _as_int_or_none(event_data.get("conversion_price")),
                _as_int_or_none(event_data.get("conversion_shares")),
                _as_int_or_none(event_data.get("acquisition_shares")),
                event_data.get("acquisition_ratio"),
                event_data.get("payment_method"),
                event_data.get("target_detail"),
                raw_json,
                _now(),
            ),
        )


def get_recent_events(
    company_code: str,
    event_type: Optional[str] = None,
    limit: int = 10,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    init_db(db_path)
    params: List[Any] = [company_code]
    where = "WHERE company_code = ?"
    if event_type:
        where += " AND event_type = ?"
        params.append(event_type)
    params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM event_disclosures
            {where}
            ORDER BY COALESCE(receipt_date, decision_date) DESC, updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]
