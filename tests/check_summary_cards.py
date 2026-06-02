from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.api_server import _summary_for_company
from src.company_lookup import resolve_company
from src.config import EVENT_INDEX, REGULAR_INDEX, cleaned_dir, company_dir, index_dir, raw_dir
from src.finance_store import get_active_chunks, get_financials, init_db, list_filings
from src.pipeline import rebuild_company_indexes


FRONTEND_CARD_FIELDS = [
    ("overview", "사업 개요"),
    ("benefit", "수익 구조"),
    ("earnings", "실적 동향"),
    ("risk", "주요 리스크"),
    ("changing", "주요 변화"),
    ("status", "공모 상태"),
    ("anomaly", "특이사항"),
]

FALLBACK_MARKERS = [
    "아직 준비되지 않았습니다",
    "찾지 못했습니다",
    "저장되어 있지 않습니다",
    "적재 후 표시됩니다",
    "응답 없음",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate DART filing fetch outputs and frontend summary cards.")
    parser.add_argument("company", nargs="?", default="삼성전자", help="Company name or 6-digit stock code.")
    parser.add_argument("--rebuild", action="store_true", help="Run DART/OpenAI indexing before validation.")
    args = parser.parse_args()

    init_db()
    company = resolve_company(args.company)
    if not company:
        raise AssertionError(f"company not found: {args.company}")

    if args.rebuild:
        rebuild_company_indexes(company.stock_code)

    summary = _summary_for_company(company)
    report = {
        "company": company.to_dict(),
        "filing_outputs": _filing_outputs(company.stock_code),
        "summary_cards": _summary_preview(summary),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    _assert_filing_outputs(company.stock_code)
    _assert_summary_cards(summary)
    return 0


def _filing_outputs(stock_code: str) -> dict[str, Any]:
    regular_chunks = get_active_chunks(stock_code, REGULAR_INDEX)
    event_chunks = get_active_chunks(stock_code, EVENT_INDEX)
    regular_filings = list_filings(stock_code, index_type=REGULAR_INDEX, limit=100)
    event_filings = list_filings(stock_code, index_type=EVENT_INDEX, limit=100)
    return {
        "company_dir": str(company_dir(stock_code)),
        "raw_xml_count": len(list(raw_dir(stock_code).glob("*.xml"))),
        "cleaned_txt_count": len(list(cleaned_dir(stock_code).glob("*.txt"))),
        "regular_index_exists": (index_dir(stock_code, REGULAR_INDEX) / "index.faiss").exists(),
        "event_index_exists": (index_dir(stock_code, EVENT_INDEX) / "index.faiss").exists(),
        "regular_active_chunks": len(regular_chunks),
        "event_active_chunks": len(event_chunks),
        "regular_filings": len(regular_filings),
        "event_filings": len(event_filings),
        "financial_ready": bool(get_financials(stock_code)),
    }


def _summary_preview(summary: dict[str, str]) -> dict[str, Any]:
    return {
        key: {
            "label": label,
            "chars": len(str(summary.get(key, ""))),
            "text": str(summary.get(key, ""))[:180],
        }
        for key, label in FRONTEND_CARD_FIELDS
    }


def _assert_filing_outputs(stock_code: str) -> None:
    outputs = _filing_outputs(stock_code)
    if outputs["raw_xml_count"] <= 0:
        raise AssertionError(f"no raw DART XML files found: {outputs}")
    if outputs["cleaned_txt_count"] <= 0:
        raise AssertionError(f"no cleaned DART text files found: {outputs}")
    if not outputs["regular_index_exists"]:
        raise AssertionError(f"regular FAISS index is missing: {outputs}")
    if outputs["regular_active_chunks"] <= 0:
        raise AssertionError(f"no active regular chunks found: {outputs}")
    if outputs["regular_filings"] <= 0:
        raise AssertionError(f"no regular filing metadata found: {outputs}")
    if not outputs["financial_ready"]:
        raise AssertionError(f"financial summary data is missing: {outputs}")


def _assert_summary_cards(summary: dict[str, str]) -> None:
    missing = [key for key, _ in FRONTEND_CARD_FIELDS if key not in summary]
    if missing:
        raise AssertionError(f"summary is missing frontend card fields: {missing}")

    fallback_cards = []
    for key, label in FRONTEND_CARD_FIELDS:
        text = str(summary.get(key, "")).strip()
        if len(text) < 12:
            raise AssertionError(f"{label}({key}) is too short: {text!r}")
        if any(marker in text for marker in FALLBACK_MARKERS):
            fallback_cards.append(f"{label}({key})={text}")

    if fallback_cards:
        raise AssertionError("summary contains fallback cards:\n" + "\n".join(fallback_cards))


if __name__ == "__main__":
    raise SystemExit(main())
