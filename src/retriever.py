from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Optional

from langchain_core.documents import Document

from .query_router import route_query
from .config import EVENT_INDEX, REGULAR_INDEX
from .finance_store import get_active_chunks, get_chunks_by_ids
from .index_manager import search_chunk_ids


logger = logging.getLogger(__name__)


def index_types_for_query(query_info: Dict) -> List[str]:
    intent = query_info.get("intent")
    if intent == "event_disclosure":
        return [EVENT_INDEX]
    if intent in {"business_text", "risk_analysis", "financial_numeric", "comparison"}:
        return [REGULAR_INDEX]
    return [REGULAR_INDEX, EVENT_INDEX]


def _chunk_to_document(chunk: Dict) -> Document:
    metadata = dict(chunk.get("metadata") or {})
    metadata.update(
        {
            "chunk_id": chunk["id"],
            "stock_code": chunk["stock_code"],
            "receipt_no": chunk.get("receipt_no") or metadata.get("receipt_no", ""),
            "index_type": chunk["index_type"],
            "data_type": chunk["data_type"],
            "section": chunk.get("section") or metadata.get("section", ""),
            "report_kind": chunk.get("report_kind") or metadata.get("report_kind", ""),
            "report_code": chunk.get("report_code") or metadata.get("report_code", ""),
            "event_type": chunk.get("event_type") or metadata.get("event_type", ""),
        }
    )
    return Document(page_content=chunk["content"], metadata=metadata)


def _desired_report_code(query: str) -> str:
    text = query or ""
    if "1분기" in text or re.search(r"\b1Q\b", text, flags=re.IGNORECASE):
        return "11013"
    if "3분기" in text or re.search(r"\b3Q\b", text, flags=re.IGNORECASE):
        return "11014"
    if "반기" in text or "상반기" in text or "2분기" in text:
        return "11012"
    if "사업보고서" in text or "연간" in text or "온기" in text:
        return "11011"
    return ""


def _as_int(value: object) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _sort_documents_for_query(documents: List[Document], query: str, query_info: Dict, k: int) -> List[Document]:
    intent = query_info.get("intent")
    desired_report_code = _desired_report_code(query)
    desired_year = query_info.get("business_year")
    desired_event_types = set(query_info.get("event_types") or [])

    def financial_key(document: Document) -> tuple[int, int, int]:
        metadata = document.metadata
        is_structured = metadata.get("data_type") == "structured_financials"
        report_code = metadata.get("report_code") or ""
        business_year = _as_int(metadata.get("business_year"))
        return (
            0 if is_structured else 1,
            0 if desired_report_code and report_code == desired_report_code else 1,
            0 if desired_year and business_year == desired_year else 1,
        )

    def event_key(document: Document) -> tuple[int, int]:
        event_type = document.metadata.get("event_type") or ""
        return (
            0 if desired_event_types and event_type in desired_event_types else 1,
            0 if document.metadata.get("data_type") == "event_text" else 1,
        )

    if intent in {"financial_numeric", "comparison"}:
        return sorted(documents, key=financial_key)[:k]
    if intent == "event_disclosure" and desired_event_types:
        return sorted(documents, key=event_key)[:k]
    if intent == "risk_analysis":
        risk_documents = [document for document in documents if document.metadata.get("data_type") == "risk_text"]
        other_documents = [document for document in documents if document.metadata.get("data_type") != "risk_text"]
        return (risk_documents + other_documents)[:k]
    return documents[:k]


def retrieve_context_documents(
    query: str,
    stock_codes: Optional[Iterable[str]] = None,
    k: int = 8,
) -> Dict[str, object]:
    query_info = route_query(query)
    routed_codes = query_info.get("company_codes") or []
    codes = list(routed_codes or stock_codes or [])
    if not codes:
        logger.info("retrieve_skipped_no_stock_codes intent=%s", query_info.get("intent"))
        return {"query_info": query_info, "documents": [], "missing_indexes": []}

    index_types = index_types_for_query(query_info)
    intent = query_info.get("intent")
    search_k = k * 4 if intent in {"risk_analysis", "financial_numeric", "comparison", "event_disclosure"} else k
    chunk_ids: List[int] = []
    missing_indexes = []
    logger.info("retrieve_start intent=%s stock_codes=%s index_types=%s k=%s search_k=%s", intent, codes, index_types, k, search_k)
    for stock_code in codes:
        for index_type in index_types:
            if not get_active_chunks(stock_code, index_type):
                missing_indexes.append(f"No active chunks: {stock_code}/{index_type}")
                logger.warning("retrieve_missing_active_chunks stock_code=%s index_type=%s", stock_code, index_type)
                continue
            try:
                for chunk_id in search_chunk_ids(stock_code, index_type, query, k=search_k):
                    if chunk_id not in chunk_ids:
                        chunk_ids.append(chunk_id)
            except FileNotFoundError as exc:
                missing_indexes.append(str(exc))
                logger.warning("retrieve_missing_index stock_code=%s index_type=%s error=%s", stock_code, index_type, exc)
            except Exception:
                logger.exception("retrieve_search_failed stock_code=%s index_type=%s", stock_code, index_type)
                raise

    chunks = get_chunks_by_ids(chunk_ids)
    documents = [_chunk_to_document(chunk) for chunk in chunks]
    documents = _sort_documents_for_query(documents, query, query_info, k)
    logger.info("retrieve_complete intent=%s chunk_ids=%s document_count=%s missing_indexes=%s", intent, len(chunk_ids), len(documents), missing_indexes)
    return {
        "query_info": query_info,
        "documents": documents,
        "missing_indexes": missing_indexes,
    }


def retrieve_context_text(query: str, stock_codes: Optional[Iterable[str]] = None, k: int = 8) -> Dict[str, object]:
    result = retrieve_context_documents(query, stock_codes=stock_codes, k=k)
    documents = result["documents"]
    context = "\n\n".join(document.page_content for document in documents)
    return {**result, "context": context}
