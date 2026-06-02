import contextlib
import io
import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import OpenDartReader

from .event_helpers import (
    EVENT_KEYWORDS,
    EVENT_TYPE_BY_KEYWORD,
    _clean_event_text,
    _extract_target_detail,
    _load_major_report_meta,
    _make_event_documents,
    _normalize_event,
    _should_extract_detail,
)
from .config import EVENT_INDEX, EVENT_LOOKBACK_DAYS, cleaned_dir, raw_dir
from .dart_collector import save_cleaned_text

logger = logging.getLogger(__name__)

DISCLOSURE_REPORT_PATTERNS = [
    ("single_sales_supply_contract", "단일판매/공급계약", r"단일판매[ㆍ·.]?공급계약|공급계약체결"),
    ("largest_shareholder_change", "최대주주변경", r"최대주주\s*변경|최대주주변경"),
    ("sanctions", "벌금/제재", r"벌금|제재|과징금|행정처분"),
    ("embezzlement_breach_of_trust", "횡령/배임", r"횡령|배임"),
    ("delisting", "상장폐지", r"상장폐지"),
    ("trading_suspension", "거래정지", r"거래정지|매매거래정지"),
]


def _event_filing_record(stock_code: str, event: Dict[str, Any], raw_path: str, cleaned_path: str) -> Dict[str, Any]:
    return {
        "receipt_no": event.get("receipt_no") or "",
        "stock_code": stock_code,
        "corp_code": event.get("corp_code") or "",
        "corp_name": event.get("company_name") or "",
        "report_name": event.get("report_name") or event.get("event_label") or "",
        "receipt_date": event.get("receipt_date") or "",
        "filing_type": "event",
        "filing_detail_type": event.get("event_type") or "",
        "index_type": EVENT_INDEX,
        "raw_path": raw_path,
        "cleaned_path": cleaned_path,
        "metadata": {"event_label": event.get("event_label"), "event_type": event.get("event_type")},
    }


def _event_chunk_records(stock_code: str, event: Dict[str, Any], raw_text: str) -> List[Dict[str, Any]]:
    documents = _make_event_documents(event, raw_text)
    records = []
    for document in documents:
        metadata = dict(document.metadata or {})
        records.append(
            {
                "receipt_no": metadata.get("receipt_no") or event.get("receipt_no") or "",
                "data_type": "event_text",
                "section": metadata.get("section") or "수시공시 이벤트",
                "chunk_index": metadata.get("chunk_index"),
                "chunk_total": metadata.get("chunk_total"),
                "content": document.page_content,
                "metadata": {**metadata, "index_type": EVENT_INDEX, "stock_code": stock_code},
            }
        )
    return records


def _safe_row_value(row: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() != "nan":
            return text
    return ""


def _normalize_disclosure_event(
    row: Dict[str, Any],
    stock_code: str,
    event_type: str,
    event_label: str,
) -> Dict[str, Any]:
    return {
        "company_code": stock_code,
        "company_name": _safe_row_value(row, "corp_name", "flr_nm"),
        "event_type": event_type,
        "event_label": event_label,
        "report_name": _safe_row_value(row, "report_nm"),
        "receipt_no": _safe_row_value(row, "rcept_no"),
        "receipt_date": _safe_row_value(row, "rcept_dt", "rcept_de"),
        "decision_date": "",
        "amount": None,
        "target_company": "",
        "purpose": "",
        "conversion_price": None,
        "conversion_shares": None,
        "acquisition_shares": None,
        "acquisition_ratio": "",
        "payment_method": "",
        "raw_json": json.dumps(row, ensure_ascii=False, default=str),
    }


def _find_disclosure_pattern(row: Dict[str, Any]) -> tuple[str, str] | None:
    report_name = _safe_row_value(row, "report_nm")
    for event_type, event_label, pattern in DISCLOSURE_REPORT_PATTERNS:
        if re.search(pattern, report_name):
            return event_type, event_label
    return None


def _download_event_document(
    dart: OpenDartReader,
    stock_code: str,
    event: Dict[str, Any],
) -> tuple[str, str, str]:
    receipt_no = event.get("receipt_no") or ""
    if not receipt_no:
        return "", "", ""
    raw_document = dart.document(receipt_no)
    raw_file = raw_dir(stock_code) / f"{receipt_no}.xml"
    raw_file.write_text(raw_document or "", encoding="utf-8")
    clean_text = _clean_event_text(raw_document)
    cleaned_path = str(save_cleaned_text(stock_code, receipt_no, clean_text))
    return raw_document or "", str(raw_file), cleaned_path


def collect_event_filings(
    dart: OpenDartReader,
    stock_code: str,
    lookback_days: int = EVENT_LOOKBACK_DAYS,
    event_keywords: Optional[List[str]] = None,
    sleep_seconds: float = 0.2,
) -> Dict[str, Any]:
    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    start = start_date.strftime("%Y-%m-%d")
    end = end_date.strftime("%Y-%m-%d")
    keywords = event_keywords or EVENT_KEYWORDS
    report_meta_by_receipt = _load_major_report_meta(dart, stock_code, start, end)
    seen_keys = set()
    events: List[Dict[str, Any]] = []
    filings: List[Dict[str, Any]] = []
    chunks: List[Dict[str, Any]] = []
    failed_list: List[Dict[str, str]] = []

    logger.info("[%s] 이벤트 공시 수집 시작: %s ~ %s", stock_code, start, end)
    for keyword in keywords:
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                df = dart.event(stock_code, keyword, start=start, end=end)
            if df is None or getattr(df, "empty", True):
                continue
            for _, series in df.iterrows():
                row = series.to_dict()
                event = _normalize_event(row, keyword, stock_code)
                report_meta = report_meta_by_receipt.get(event.get("receipt_no", ""), {})
                if report_meta:
                    event["report_name"] = report_meta.get("report_name") or event["report_name"]
                    event["receipt_date"] = report_meta.get("receipt_date") or event["receipt_date"]
                    event["company_name"] = report_meta.get("company_name") or event["company_name"]
                dedupe_key = (event.get("receipt_no"), event.get("event_type"))
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                receipt_no = event.get("receipt_no") or ""
                raw_document = ""
                clean_text = ""
                raw_path = ""
                cleaned_path = ""
                if receipt_no:
                    try:
                        raw_document, raw_path, cleaned_path = _download_event_document(dart, stock_code, event)
                        clean_text = _clean_event_text(raw_document)
                    except Exception as exc:
                        logger.warning("[%s] 이벤트 원문 다운로드 실패(%s): %s", stock_code, receipt_no, exc)

                if clean_text and _should_extract_detail(event, clean_text):
                    detail = _extract_target_detail(clean_text)
                    if detail:
                        event["target_detail"] = detail

                events.append(event)
                filings.append(_event_filing_record(stock_code, event, raw_path, cleaned_path))
                chunks.extend(_event_chunk_records(stock_code, event, clean_text))
                time.sleep(sleep_seconds)
        except Exception as exc:
            logger.warning("[%s] 이벤트 조회 실패(%s): %s", stock_code, keyword, exc)
            failed_list.append({"event_label": keyword, "reason": str(exc)})
        finally:
            time.sleep(sleep_seconds)

    try:
        reports = dart.list(stock_code, start=start, end=end, final=False)
        if reports is not None and not getattr(reports, "empty", True):
            for _, series in reports.iterrows():
                row = series.to_dict()
                match = _find_disclosure_pattern(row)
                if not match:
                    continue
                event_type, event_label = match
                event = _normalize_disclosure_event(row, stock_code, event_type, event_label)
                dedupe_key = (event.get("receipt_no"), event.get("event_type"))
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)

                receipt_no = event.get("receipt_no") or ""
                raw_document = ""
                clean_text = ""
                raw_path = ""
                cleaned_path = ""
                if receipt_no:
                    try:
                        raw_document, raw_path, cleaned_path = _download_event_document(dart, stock_code, event)
                        clean_text = _clean_event_text(raw_document)
                    except Exception as exc:
                        logger.warning("[%s] 공시명 기반 이벤트 원문 다운로드 실패(%s): %s", stock_code, receipt_no, exc)

                if clean_text and _should_extract_detail(event, clean_text):
                    detail = _extract_target_detail(clean_text)
                    if detail:
                        event["target_detail"] = detail

                events.append(event)
                filings.append(_event_filing_record(stock_code, event, raw_path, cleaned_path))
                chunks.extend(_event_chunk_records(stock_code, event, clean_text))
                time.sleep(sleep_seconds)
    except Exception as exc:
        logger.warning("[%s] 공시명 기반 이벤트 조회 실패: %s", stock_code, exc)
        failed_list.append({"event_label": "공시명 기반 이벤트", "reason": str(exc)})

    return {
        "events": events,
        "filings": filings,
        "chunks": chunks,
        "failed_list": failed_list,
    }
