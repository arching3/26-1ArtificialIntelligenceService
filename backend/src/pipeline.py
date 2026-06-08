import logging
import os
from typing import Any, Dict, List

from dotenv import load_dotenv
import OpenDartReader

from .config import EVENT_INDEX, REGULAR_INDEX
from .dart_service import collect_event_filings, collect_recent_regular_filings, normalize_stock_code, save_cleaned_text
from .finance_store import (
    delete_financials_for_receipts,
    init_db,
    insert_chunks,
    prune_inactive_chunks,
    upsert_company,
    upsert_event_disclosure,
    upsert_filing,
    upsert_financials,
)
from .index_manager import rebuild_index
from .logging_config import configure_logging
from .company_lookup import Company, resolve_company
from .summary_service import SummaryService
from .document_processor import (
    build_regular_chunk_records,
    chunk_business_text,
    chunk_business_sections,
    clean_document,
    extract_business_section,
    extract_business_sections,
    extract_financial_data,
    parse_filing_document,
)

logging.getLogger("dotenv.main").setLevel(logging.ERROR)
envrst = load_dotenv()
configure_logging()
logger = logging.getLogger(__name__)
logger.info(f"OPEN_API_KEY load success T:{envrst}") 

def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        raise ValueError(f"{name} 환경변수가 설정되어 있지 않습니다.")
    return value


def _dart_client() -> OpenDartReader:
    return OpenDartReader(_required_env("DART_API_KEY"))


def rebuild_regular_index(stock_code: str, dart: OpenDartReader | None = None) -> Dict[str, Any]:
    stock_code = normalize_stock_code(stock_code)
    logger.info("[%s] regular index rebuild started", stock_code)
    dart = dart or _dart_client()
    result = collect_recent_regular_filings(dart, stock_code)
    filings = result["filings"]
    failed_list = list(result["failed_list"])
    chunk_records = []
    financial_records = []

    for filing, raw_document in filings:
        parsed_filing = None
        try:
            parsed_filing = parse_filing_document(raw_document)
        except Exception as exc:
            logger.warning("[%s] DART 원문 구조 파싱 실패(%s): %s", stock_code, filing.receipt_no, exc)

        clean_text = parsed_filing.clean_text if parsed_filing and parsed_filing.clean_text else clean_document(raw_document)
        cleaned_path = save_cleaned_text(stock_code, filing.receipt_no, clean_text)
        filing.cleaned_path = cleaned_path

        base_data = {
            "company_code": stock_code,
            "stock_code": stock_code,
            "company_name": filing.corp_name,
            "corp_name": filing.corp_name,
            "corp_code": filing.corp_code,
            "report_name": filing.report_name,
            "receipt_no": filing.receipt_no,
            "receipt_date": filing.receipt_date,
            "report_kind": filing.report_kind,
        }
        structured_data = dict(base_data)
        include_structured = False
        try:
            structured_data = extract_financial_data(dart, stock_code, filing.row)
            structured_data.update(base_data)
            financial_records.append(structured_data)
            include_structured = True
        except Exception as exc:
            logger.warning("[%s] 재무 정형 데이터 추출 실패(%s): %s", stock_code, filing.receipt_no, exc)
            failed_list.append(
                {
                    "receipt_no": filing.receipt_no,
                    "report_name": filing.report_name,
                    "stage": "financials",
                    "reason": str(exc),
                }
            )

        business_chunks = []
        if parsed_filing:
            business_sections = extract_business_sections(parsed_filing)
            business_chunks = chunk_business_sections(business_sections)
            if business_chunks:
                logger.info(
                    "[%s] XML section-aware chunks created receipt_no=%s sections=%s chunks=%s",
                    stock_code,
                    filing.receipt_no,
                    len(business_sections),
                    len(business_chunks),
                )

        if not business_chunks:
            logger.warning(
                "[%s] XML section-aware chunking unavailable; fallback to recursive text chunks receipt_no=%s",
                stock_code,
                filing.receipt_no,
            )
            business_text = extract_business_section(clean_text)
            business_chunks = chunk_business_text(business_text)

        chunk_records.extend(
            build_regular_chunk_records(
                structured_data,
                business_chunks,
                include_structured=include_structured,
            )
        )

    init_db()
    first_filing = filings[0][0]
    upsert_company(stock_code, corp_name=first_filing.corp_name, corp_code=first_filing.corp_code)
    for filing, _ in filings:
        upsert_filing(filing.filing_record())
    delete_financials_for_receipts(stock_code, [filing.receipt_no for filing, _ in filings])
    for structured_data in financial_records:
        upsert_financials(structured_data)
    chunk_ids = insert_chunks(stock_code, REGULAR_INDEX, chunk_records)
    index_result = rebuild_index(stock_code, REGULAR_INDEX)
    pruned_chunks = prune_inactive_chunks(stock_code, REGULAR_INDEX)
    logger.info(
        "[%s] regular index rebuild complete filings=%s chunks=%s pruned=%s failed=%s",
        stock_code,
        len(filings),
        len(chunk_ids),
        pruned_chunks,
        len(failed_list),
    )

    return {
        "stock_code": stock_code,
        "index_type": REGULAR_INDEX,
        "filing_count": len(filings),
        "regular_report_count": len(filings),
        "receipt_nos": [filing.receipt_no for filing, _ in filings],
        "chunk_count": len(chunk_ids),
        "pruned_inactive_chunks": pruned_chunks,
        "failed_list": failed_list,
        "index": index_result,
    }


def rebuild_event_index(stock_code: str, dart: OpenDartReader | None = None) -> Dict[str, Any]:
    stock_code = normalize_stock_code(stock_code)
    logger.info("[%s] event index rebuild started", stock_code)
    dart = dart or _dart_client()
    result = collect_event_filings(dart, stock_code)

    init_db()
    for filing in result["filings"]:
        upsert_filing(filing)
    for event in result["events"]:
        upsert_event_disclosure(event)
    chunk_ids = insert_chunks(stock_code, EVENT_INDEX, result["chunks"])

    index_result = None
    if chunk_ids:
        index_result = rebuild_index(stock_code, EVENT_INDEX)
        pruned_chunks = prune_inactive_chunks(stock_code, EVENT_INDEX)
    else:
        pruned_chunks = 0
    logger.info(
        "[%s] event index rebuild complete filings=%s events=%s chunks=%s pruned=%s failed=%s",
        stock_code,
        len(result["filings"]),
        len(result["events"]),
        len(chunk_ids),
        pruned_chunks,
        len(result["failed_list"]),
    )

    return {
        "stock_code": stock_code,
        "index_type": EVENT_INDEX,
        "filing_count": len(result["filings"]),
        "event_count": len(result["events"]),
        "chunk_count": len(chunk_ids),
        "pruned_inactive_chunks": pruned_chunks,
        "failed_list": result["failed_list"],
        "index": index_result,
    }


def rebuild_company_indexes(
    stock_code: str,
    include_regular: bool = True,
    include_event: bool = True,
) -> Dict[str, Any]:
    stock_code = normalize_stock_code(stock_code)
    logger.info(
        "[%s] company index rebuild started include_regular=%s include_event=%s",
        stock_code,
        include_regular,
        include_event,
    )
    _required_env("OPENAI_API_KEY")
    dart = _dart_client()
    results: Dict[str, Any] = {"stock_code": stock_code, "regular": None, "event": None}

    if include_regular:
        results["regular"] = rebuild_regular_index(stock_code, dart=dart)
    if include_event:
        results["event"] = rebuild_event_index(stock_code, dart=dart)
    _refresh_summary_after_rebuild(stock_code)
    logger.info("[%s] company index rebuild complete", stock_code)
    return results


def _refresh_summary_after_rebuild(stock_code: str) -> None:
    try:
        company = resolve_company(stock_code) or Company(stock_code=stock_code, corp_name=stock_code, source="direct")
        SummaryService().refresh(company, use_llm=True)
    except Exception as exc:
        logger.warning("[%s] summary refresh after index rebuild failed: %s", stock_code, exc)


def rebuild_batch(stock_codes: List[str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    failed = []
    for code in stock_codes:
        try:
            results[code] = rebuild_company_indexes(code)
        except Exception as exc:
            logger.exception("[%s] v2 rebuild failed", code)
            failed.append({"stock_code": code, "reason": str(exc)})
            results[code] = {"status": "failed", "reason": str(exc)}
    return {
        "results": results,
        "failed_list": failed,
        "summary": {
            "requested": len(stock_codes),
            "succeeded": len(stock_codes) - len(failed),
            "failed": len(failed),
        },
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Rebuild dart-inform-v2 company indexes")
    parser.add_argument("stock_codes", nargs="+", help="6-digit stock codes")
    parser.add_argument("--regular-only", action="store_true")
    parser.add_argument("--event-only", action="store_true")
    args = parser.parse_args()

    output = {}
    for code in args.stock_codes:
        output[code] = rebuild_company_indexes(
            code,
            include_regular=not args.event_only,
            include_event=not args.regular_only,
        )
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
