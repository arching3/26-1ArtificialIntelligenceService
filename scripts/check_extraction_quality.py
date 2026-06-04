import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "storage" / "finance.db"
sys.path.insert(0, str(BASE_DIR))


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_json(value: str | None) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def _print_rows(title: str, rows: Iterable[Iterable[Any]]) -> None:
    print(f"\n[{title}]")
    for row in rows:
        print(" - " + " | ".join(str(item) for item in row))


def _columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _row_value(row: sqlite3.Row, column: str, metadata: Dict[str, Any], default: Any = "") -> Any:
    return row[column] if column in row.keys() and row[column] not in (None, "") else metadata.get(column, default)


def report_financials(conn: sqlite3.Connection, stock_code: str) -> None:
    cols = _columns(conn, "financials")
    extra_cols = []
    for column in ["report_kind", "report_code", "period_month"]:
        if column in cols:
            extra_cols.append(column)
    select_extra = ", " + ", ".join(extra_cols) if extra_cols else ""
    rows = conn.execute(
        f"""
        SELECT stock_code, business_year, revenue, operating_profit, net_income, report_name, receipt_no{select_extra}
        FROM financials
        WHERE stock_code = ?
        ORDER BY business_year, receipt_no
        """,
        (stock_code,),
    ).fetchall()
    _print_rows(
        f"{stock_code} financials",
        [
            (
                row["business_year"],
                row["report_name"],
                row["receipt_no"],
                row["report_kind"] if "report_kind" in row.keys() else "",
                row["report_code"] if "report_code" in row.keys() else "",
                row["period_month"] if "period_month" in row.keys() else "",
                row["revenue"],
                row["operating_profit"],
                row["net_income"],
            )
            for row in rows
        ],
    )


def report_regular_chunks(conn: sqlite3.Connection, stock_code: str) -> None:
    rows = conn.execute(
        """
        SELECT receipt_no, data_type, report_kind, report_code, metadata_json, LENGTH(content) AS content_length
        FROM chunks
        WHERE stock_code = ? AND index_type = 'regular' AND active = 1
        ORDER BY receipt_no, id
        """,
        (stock_code,),
    ).fetchall()
    by_receipt: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        metadata = _load_json(row["metadata_json"])
        receipt_no = row["receipt_no"]
        item = by_receipt.setdefault(
            receipt_no,
            {
                "report_name": metadata.get("report_name", ""),
                "report_kind": _row_value(row, "report_kind", metadata),
                "report_code": _row_value(row, "report_code", metadata),
                "types": {},
                "content_length": 0,
            },
        )
        data_type = row["data_type"]
        item["types"][data_type] = item["types"].get(data_type, 0) + 1
        item["content_length"] += row["content_length"] or 0

    _print_rows(
        f"{stock_code} regular chunks by filing",
        [
            (
                receipt_no,
                item["report_name"],
                item["report_kind"],
                item["report_code"],
                item["types"],
                item["content_length"],
            )
            for receipt_no, item in by_receipt.items()
        ],
    )
    missing_structured = [
        (receipt_no, item["report_name"], item["report_kind"])
        for receipt_no, item in by_receipt.items()
        if not item["types"].get("structured_financials")
    ]
    _print_rows(f"{stock_code} missing structured financial chunks", missing_structured or [("none",)])


def report_event_chunks(conn: sqlite3.Connection, stock_code: str) -> None:
    rows = conn.execute(
        """
        SELECT event_type, event_label, report_name, receipt_no, receipt_date
        FROM event_disclosures
        WHERE stock_code = ?
        ORDER BY receipt_date, receipt_no, event_type
        """,
        (stock_code,),
    ).fetchall()
    by_type: Dict[str, int] = {}
    for row in rows:
        by_type[row["event_type"]] = by_type.get(row["event_type"], 0) + 1
    _print_rows(f"{stock_code} event disclosure counts", sorted(by_type.items()))

    chunk_rows = conn.execute(
        """
        SELECT event_type, metadata_json
        FROM chunks
        WHERE stock_code = ? AND index_type = 'event' AND active = 1
        """,
        (stock_code,),
    ).fetchall()
    chunk_by_type: Dict[str, int] = {}
    for row in chunk_rows:
        metadata = _load_json(row["metadata_json"])
        event_type = _row_value(row, "event_type", metadata, "unknown")
        chunk_by_type[event_type] = chunk_by_type.get(event_type, 0) + 1
    _print_rows(f"{stock_code} event chunk counts", sorted(chunk_by_type.items()))


def report_integrity(conn: sqlite3.Connection) -> None:
    _print_rows(
        "chunk active status",
        [tuple(row) for row in conn.execute("SELECT active, COUNT(*) FROM chunks GROUP BY active ORDER BY active")],
    )
    _print_rows(
        "inactive chunks by stock/index",
        [
            tuple(row)
            for row in conn.execute(
                """
                SELECT stock_code, index_type, COUNT(*)
                FROM chunks
                WHERE active = 0
                GROUP BY stock_code, index_type
                ORDER BY stock_code, index_type
                """
            )
        ]
        or [("none",)],
    )
    _print_rows(
        "active chunks without faiss mapping",
        [
            tuple(row)
            for row in conn.execute(
                """
                SELECT c.stock_code, c.index_type, COUNT(*)
                FROM chunks c
                LEFT JOIN faiss_mappings f ON f.chunk_id = c.id
                WHERE c.active = 1 AND f.chunk_id IS NULL
                GROUP BY c.stock_code, c.index_type
                ORDER BY c.stock_code, c.index_type
                """
            )
        ]
        or [("none",)],
    )
    _print_rows(
        "faiss mappings pointing to inactive chunks",
        [
            tuple(row)
            for row in conn.execute(
                """
                SELECT f.stock_code, f.index_type, COUNT(*)
                FROM faiss_mappings f
                JOIN chunks c ON c.id = f.chunk_id
                WHERE c.active = 0
                GROUP BY f.stock_code, f.index_type
                ORDER BY f.stock_code, f.index_type
                """
            )
        ]
        or [("none",)],
    )


def report_retriever_samples(regular_stock: str, event_stock: str) -> None:
    from src.retriever import retrieve_context_text

    samples = [
        ("삼성전자 2026년 1분기 매출액은?", [regular_stock]),
        ("삼성전자 2025년 반기 매출액은?", [regular_stock]),
        ("넥사다이내믹스 최근 공급계약 공시는?", [event_stock]),
        ("넥사다이내믹스 최근 전환사채 발행 공시는?", [event_stock]),
        ("삼성전자 위험 요인은?", [regular_stock]),
    ]
    print("\n[retriever samples]")
    for query, codes in samples:
        result = retrieve_context_text(query, codes)
        summary = [
            (
                doc.metadata.get("data_type"),
                doc.metadata.get("report_code"),
                doc.metadata.get("event_type"),
                doc.metadata.get("risk_type"),
                doc.metadata.get("report_name"),
            )
            for doc in result["documents"][:5]
        ]
        print(f" - {query}: {summary}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only v2 extraction quality report")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to storage/finance.db")
    parser.add_argument("--regular-stock", default="005930")
    parser.add_argument("--event-stock", default="351320")
    parser.add_argument("--samples", action="store_true", help="Run retriever sample checks")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    with _connect(db_path) as conn:
        report_integrity(conn)
        report_financials(conn, args.regular_stock)
        report_regular_chunks(conn, args.regular_stock)
        report_event_chunks(conn, args.event_stock)
    if args.samples:
        report_retriever_samples(args.regular_stock, args.event_stock)


if __name__ == "__main__":
    main()
