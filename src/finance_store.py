import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .config import DB_PATH, ensure_storage_dirs

METRIC_COLUMNS = {
    "revenue": "revenue",
    "operating_profit": "operating_profit",
    "net_income": "net_income",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    ensure_storage_dirs()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _as_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def init_db(db_path: Path | str = DB_PATH) -> None:
    ensure_storage_dirs()
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS companies (
                stock_code TEXT PRIMARY KEY,
                corp_code TEXT,
                corp_name TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS filings (
                receipt_no TEXT PRIMARY KEY,
                stock_code TEXT NOT NULL,
                corp_code TEXT,
                corp_name TEXT,
                report_name TEXT,
                receipt_date TEXT,
                filing_type TEXT,
                filing_detail_type TEXT,
                index_type TEXT NOT NULL,
                raw_path TEXT,
                cleaned_path TEXT,
                metadata_json TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_filings_stock_index
            ON filings(stock_code, index_type, receipt_date);

            CREATE TABLE IF NOT EXISTS financials (
                stock_code TEXT NOT NULL,
                corp_name TEXT,
                business_year INTEGER,
                revenue INTEGER,
                operating_profit INTEGER,
                net_income INTEGER,
                currency TEXT DEFAULT 'KRW',
                report_name TEXT,
                report_kind TEXT,
                report_code TEXT,
                period_month INTEGER,
                receipt_no TEXT,
                receipt_date TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (stock_code, business_year, receipt_no)
            );

            CREATE INDEX IF NOT EXISTS idx_financials_stock_year
            ON financials(stock_code, business_year);

            CREATE TABLE IF NOT EXISTS event_disclosures (
                stock_code TEXT NOT NULL,
                corp_name TEXT,
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
            );

            CREATE INDEX IF NOT EXISTS idx_events_stock_date
            ON event_disclosures(stock_code, receipt_date, decision_date);

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_code TEXT NOT NULL,
                receipt_no TEXT,
                index_type TEXT NOT NULL,
                data_type TEXT NOT NULL,
                section TEXT,
                chunk_index INTEGER,
                chunk_total INTEGER,
                content TEXT NOT NULL,
                report_kind TEXT,
                report_code TEXT,
                event_type TEXT,
                metadata_json TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_stock_index_active
            ON chunks(stock_code, index_type, active);

            CREATE INDEX IF NOT EXISTS idx_chunks_receipt
            ON chunks(receipt_no);

            CREATE TABLE IF NOT EXISTS faiss_mappings (
                stock_code TEXT NOT NULL,
                index_type TEXT NOT NULL,
                vector_id INTEGER NOT NULL,
                chunk_id INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (stock_code, index_type, vector_id)
            );

            CREATE INDEX IF NOT EXISTS idx_faiss_mappings_chunk
            ON faiss_mappings(chunk_id);
            """
        )
        _ensure_column(conn, "financials", "report_kind", "TEXT")
        _ensure_column(conn, "financials", "report_code", "TEXT")
        _ensure_column(conn, "financials", "period_month", "INTEGER")
        _ensure_column(conn, "chunks", "report_kind", "TEXT")
        _ensure_column(conn, "chunks", "report_code", "TEXT")
        _ensure_column(conn, "chunks", "event_type", "TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_report_code "
            "ON chunks(stock_code, index_type, report_code, active)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_event_type "
            "ON chunks(stock_code, index_type, event_type, active)"
        )


def upsert_company(stock_code: str, corp_name: str = "", corp_code: str = "") -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO companies(stock_code, corp_code, corp_name, updated_at)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(stock_code) DO UPDATE SET
                corp_code=COALESCE(NULLIF(excluded.corp_code, ''), companies.corp_code),
                corp_name=COALESCE(NULLIF(excluded.corp_name, ''), companies.corp_name),
                updated_at=excluded.updated_at
            """,
            (stock_code, corp_code, corp_name, _now()),
        )


def list_companies() -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT stock_code, corp_code, corp_name, updated_at
            FROM companies
            ORDER BY corp_name, stock_code
            """
        ).fetchall()
    return [dict(row) for row in rows]


def find_companies_by_name(query: str) -> List[Dict[str, Any]]:
    init_db()
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return list_companies()

    compact_query = "".join(normalized_query.split())
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT stock_code, corp_code, corp_name, updated_at
            FROM companies
            WHERE stock_code = ?
               OR corp_name = ?
               OR REPLACE(corp_name, ' ', '') = ?
               OR corp_name LIKE ?
            ORDER BY
                CASE
                    WHEN stock_code = ? THEN 0
                    WHEN corp_name = ? THEN 1
                    WHEN REPLACE(corp_name, ' ', '') = ? THEN 2
                    ELSE 3
                END,
                LENGTH(corp_name),
                corp_name
            LIMIT 20
            """,
            (
                normalized_query.zfill(6) if normalized_query.isdigit() else normalized_query,
                normalized_query,
                compact_query,
                f"%{normalized_query}%",
                normalized_query.zfill(6) if normalized_query.isdigit() else normalized_query,
                normalized_query,
                compact_query,
            ),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_filing(filing: Dict[str, Any]) -> None:
    init_db()
    receipt_no = str(filing.get("receipt_no") or "").strip()
    stock_code = str(filing.get("stock_code") or "").strip()
    index_type = str(filing.get("index_type") or "").strip()
    if not receipt_no or not stock_code or not index_type:
        raise ValueError("filing requires receipt_no, stock_code, and index_type")

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO filings(
                receipt_no, stock_code, corp_code, corp_name, report_name,
                receipt_date, filing_type, filing_detail_type, index_type,
                raw_path, cleaned_path, metadata_json, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receipt_no) DO UPDATE SET
                stock_code=excluded.stock_code,
                corp_code=excluded.corp_code,
                corp_name=excluded.corp_name,
                report_name=excluded.report_name,
                receipt_date=excluded.receipt_date,
                filing_type=excluded.filing_type,
                filing_detail_type=excluded.filing_detail_type,
                index_type=excluded.index_type,
                raw_path=excluded.raw_path,
                cleaned_path=excluded.cleaned_path,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                receipt_no,
                stock_code,
                filing.get("corp_code") or "",
                filing.get("corp_name") or "",
                filing.get("report_name") or "",
                filing.get("receipt_date") or "",
                filing.get("filing_type") or "",
                filing.get("filing_detail_type") or "",
                index_type,
                filing.get("raw_path") or "",
                filing.get("cleaned_path") or "",
                _json_dumps(filing.get("metadata")),
                _now(),
            ),
        )


def upsert_financials(structured_data: Dict[str, Any]) -> None:
    init_db()
    stock_code = str(structured_data.get("company_code") or structured_data.get("stock_code") or "").strip()
    if not stock_code:
        raise ValueError("structured_data requires stock_code/company_code")
    corp_name = str(structured_data.get("company_name") or structured_data.get("corp_name") or "")
    upsert_company(stock_code, corp_name=corp_name)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO financials(
                stock_code, corp_name, business_year, revenue, operating_profit,
                net_income, currency, report_name, report_kind, report_code,
                period_month, receipt_no, receipt_date, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stock_code, business_year, receipt_no) DO UPDATE SET
                corp_name=excluded.corp_name,
                revenue=excluded.revenue,
                operating_profit=excluded.operating_profit,
                net_income=excluded.net_income,
                currency=excluded.currency,
                report_name=excluded.report_name,
                report_kind=excluded.report_kind,
                report_code=excluded.report_code,
                period_month=excluded.period_month,
                receipt_date=excluded.receipt_date,
                updated_at=excluded.updated_at
            """,
            (
                stock_code,
                corp_name,
                _as_int_or_none(structured_data.get("business_year")),
                _as_int_or_none(structured_data.get("revenue")),
                _as_int_or_none(structured_data.get("operating_profit")),
                _as_int_or_none(structured_data.get("net_income")),
                structured_data.get("currency") or "KRW",
                structured_data.get("report_name"),
                structured_data.get("report_kind"),
                structured_data.get("report_code"),
                _as_int_or_none(structured_data.get("period_month")),
                structured_data.get("receipt_no") or "",
                structured_data.get("receipt_date"),
                _now(),
            ),
        )


def delete_financials_for_receipts(stock_code: str, receipt_nos: Iterable[str]) -> None:
    init_db()
    receipts = [str(receipt_no or "").strip() for receipt_no in receipt_nos if str(receipt_no or "").strip()]
    if not receipts:
        return
    placeholders = ",".join("?" for _ in receipts)
    with _connect() as conn:
        conn.execute(
            f"DELETE FROM financials WHERE stock_code = ? AND receipt_no IN ({placeholders})",
            (stock_code, *receipts),
        )


def upsert_event_disclosure(event_data: Dict[str, Any]) -> None:
    init_db()
    stock_code = str(event_data.get("company_code") or event_data.get("stock_code") or "").strip()
    receipt_no = str(event_data.get("receipt_no") or "").strip()
    event_type = str(event_data.get("event_type") or "").strip()
    if not stock_code or not receipt_no or not event_type:
        raise ValueError("event_data requires stock_code/company_code, receipt_no, and event_type")
    raw_json = event_data.get("raw_json")
    if raw_json is not None and not isinstance(raw_json, str):
        raw_json = _json_dumps(raw_json)
    corp_name = event_data.get("company_name") or event_data.get("corp_name") or ""
    upsert_company(stock_code, corp_name=corp_name)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO event_disclosures(
                stock_code, corp_name, event_type, event_label, report_name,
                receipt_no, receipt_date, decision_date, amount, target_company,
                purpose, conversion_price, conversion_shares, acquisition_shares,
                acquisition_ratio, payment_method, target_detail, raw_json, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receipt_no, event_type) DO UPDATE SET
                stock_code=excluded.stock_code,
                corp_name=excluded.corp_name,
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
                stock_code,
                corp_name,
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


def deactivate_chunks(stock_code: str, index_type: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE chunks SET active = 0, updated_at = ? WHERE stock_code = ? AND index_type = ? AND active = 1",
            (_now(), stock_code, index_type),
        )
        conn.execute(
            "DELETE FROM faiss_mappings WHERE stock_code = ? AND index_type = ?",
            (stock_code, index_type),
        )


def prune_inactive_chunks(stock_code: str, index_type: str) -> int:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM chunks WHERE stock_code = ? AND index_type = ? AND active = 0",
            (stock_code, index_type),
        )
        return int(cur.rowcount or 0)


def insert_chunk(chunk: Dict[str, Any]) -> int:
    init_db()
    metadata = dict(chunk.get("metadata") or {})
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO chunks(
                stock_code, receipt_no, index_type, data_type, section,
                chunk_index, chunk_total, content, metadata_json,
                report_kind, report_code, event_type, active, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                chunk["stock_code"],
                chunk.get("receipt_no") or "",
                chunk["index_type"],
                chunk["data_type"],
                chunk.get("section") or "",
                chunk.get("chunk_index"),
                chunk.get("chunk_total"),
                chunk["content"],
                _json_dumps(metadata),
                metadata.get("report_kind") or "",
                metadata.get("report_code") or "",
                metadata.get("event_type") or "",
                _now(),
                _now(),
            ),
        )
        return int(cur.lastrowid)


def insert_chunks(stock_code: str, index_type: str, chunks: Iterable[Dict[str, Any]]) -> List[int]:
    deactivate_chunks(stock_code, index_type)
    ids = []
    for chunk in chunks:
        item = dict(chunk)
        item["stock_code"] = stock_code
        item["index_type"] = index_type
        ids.append(insert_chunk(item))
    return ids


def get_active_chunks(stock_code: str, index_type: str) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM chunks
            WHERE stock_code = ? AND index_type = ? AND active = 1
            ORDER BY id
            """,
            (stock_code, index_type),
        ).fetchall()
    return [_inflate_chunk(row) for row in rows]


def get_chunks_by_ids(chunk_ids: Iterable[int]) -> List[Dict[str, Any]]:
    ids = [int(chunk_id) for chunk_id in chunk_ids]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _connect() as conn:
        rows = conn.execute(f"SELECT * FROM chunks WHERE id IN ({placeholders})", ids).fetchall()
    by_id = {int(row["id"]): _inflate_chunk(row) for row in rows}
    return [by_id[chunk_id] for chunk_id in ids if chunk_id in by_id]


def get_latest_chunks(stock_code: str, index_type: Optional[str] = None, data_type: Optional[str] = None, limit: int = 8) -> List[Dict[str, Any]]:
    init_db()
    params: List[Any] = [stock_code]
    where = "WHERE stock_code = ? AND active = 1"
    if index_type:
        where += " AND index_type = ?"
        params.append(index_type)
    if data_type:
        where += " AND data_type = ?"
        params.append(data_type)
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM chunks
            {where}
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_inflate_chunk(row) for row in rows]


def replace_faiss_mappings(stock_code: str, index_type: str, vector_to_chunk: Iterable[tuple[int, int]]) -> None:
    init_db()
    now = _now()
    with _connect() as conn:
        conn.execute("DELETE FROM faiss_mappings WHERE stock_code = ? AND index_type = ?", (stock_code, index_type))
        conn.executemany(
            """
            INSERT INTO faiss_mappings(stock_code, index_type, vector_id, chunk_id, updated_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            [(stock_code, index_type, int(vector_id), int(chunk_id), now) for vector_id, chunk_id in vector_to_chunk],
        )


def get_financials(stock_code: str, business_year: Optional[int] = None) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        if business_year is not None:
            row = conn.execute(
                """
                SELECT * FROM financials
                WHERE stock_code = ? AND business_year = ?
                ORDER BY receipt_date DESC, updated_at DESC
                LIMIT 1
                """,
                (stock_code, int(business_year)),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM financials
                WHERE stock_code = ?
                ORDER BY business_year DESC, receipt_date DESC, updated_at DESC
                LIMIT 1
                """,
                (stock_code,),
            ).fetchone()
    return dict(row) if row else None


def compare_metric(stock_codes: Iterable[str], metric: str, business_year: Optional[int] = None) -> List[Dict[str, Any]]:
    column = METRIC_COLUMNS.get(metric)
    if not column:
        raise ValueError(f"Unsupported metric: {metric}")
    rows = [row for code in stock_codes if (row := get_financials(code, business_year=business_year))]
    return sorted(rows, key=lambda item: item.get(column) if item.get(column) is not None else float("-inf"), reverse=True)


def get_recent_events(stock_code: str, event_type: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    init_db()
    params: List[Any] = [stock_code]
    where = "WHERE stock_code = ?"
    if event_type:
        where += " AND event_type = ?"
        params.append(event_type)
    params.append(limit)
    with _connect() as conn:
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


def list_filings(stock_code: str, index_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    params: List[Any] = [stock_code]
    where = "WHERE stock_code = ?"
    if index_type:
        where += " AND index_type = ?"
        params.append(index_type)
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM filings
            {where}
            ORDER BY receipt_date DESC, updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_filing(receipt_no: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM filings WHERE receipt_no = ?", (receipt_no,)).fetchone()
    return dict(row) if row else None


def _inflate_chunk(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    try:
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
    except json.JSONDecodeError:
        item["metadata"] = {}
    return item
