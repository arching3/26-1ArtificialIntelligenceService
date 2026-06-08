from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import EVENT_INDEX, LLM_MODEL, REGULAR_INDEX
from .finance_store import compare_metric, get_active_chunks, get_chunks_by_ids, get_financials, get_recent_events
from .index_manager import search_chunk_ids

logger = logging.getLogger(__name__)

METRIC_ALIASES = {
    "revenue": ["매출액", "매출", "영업수익", "수익"],
    "operating_profit": ["영업이익", "영업 이익"],
    "net_income": ["당기순이익", "순이익", "연결당기순이익"],
}

RISK_KEYWORDS = ["리스크", "위험", "소송", "제재", "우발부채", "유동성", "신용위험", "시장위험", "이자율", "외환", "PF", "안전", "영업정지"]
BUSINESS_KEYWORDS = ["사업", "부문", "제품", "서비스", "생산", "전략", "연구개발", "수주"]
COMPARISON_KEYWORDS = ["비교", "중", "더 큰", "더 높은", "높은", "큰", "누가", "어디"]
EVENT_KEYWORDS = [
    "CB", "전환사채", "신주인수권부사채", "교환사채",
    "유상증자", "무상증자", "감자",
    "주식 취득", "주식취득", "타법인", "출자증권",
    "합병", "분할", "소송", "영업정지", "자기주식",
    "주요사항", "수시공시", "공급계약", "최대주주",
    "벌금", "제재", "횡령", "배임", "상장폐지", "거래정지",
    "이벤트", "이벤트 공시", "최근 공시", "공시 내용", "공시사항", "주요 공시",
]
EVENT_TYPE_ALIASES = {
    "convertible_bond_issuance": ["CB", "전환사채"],
    "bond_with_warrant_issuance": ["신주인수권부사채", "BW"],
    "exchangeable_bond_issuance": ["교환사채", "EB"],
    "paid_in_capital_increase": ["유상증자"],
    "equity_acquisition": ["타법인", "출자증권", "주식 취득", "주식취득", "양수", "취득"],
    "lawsuit": ["소송"],
    "business_suspension": ["영업정지"],
    "merger": ["합병"],
    "spin_off": ["분할"],
    "treasury_stock_acquisition": ["자기주식 취득", "자기주식취득"],
    "treasury_stock_disposal": ["자기주식 처분", "자기주식처분"],
    "single_sales_supply_contract": ["공급계약", "단일판매"],
    "largest_shareholder_change": ["최대주주", "최대주주변경"],
    "sanctions": ["벌금", "제재", "과징금", "행정처분"],
    "embezzlement_breach_of_trust": ["횡령", "배임"],
    "delisting": ["상장폐지"],
    "trading_suspension": ["거래정지", "매매거래정지"],
}

UNSUPPORTED_KEYWORDS = ["사도", "매수", "팔아", "매도", "손절", "물타기", "목표가", "포트폴리오", "비중"]

SYSTEM_PROMPT = """
당신은 DART 공시 기반 기업 분석 보조 도구입니다.
반드시 제공된 Context 안에서만 답변하세요.
공시에 없는 내용은 지어내지 말고, 확인 가능한 범위를 명확히 말하세요.
주가 예측, 매수/매도 판단, 목표가 제시, 포트폴리오 비중 조언은 하지 마세요.
투자 행동 대신 공시 기반 사실, 리스크, 실적 변화 요인, 확인할 체크 포인트를 정리하세요.
숫자는 SQLite 정형 데이터가 있으면 그것을 우선 사용하세요.
답변 마지막에는 근거가 된 보고서명, 접수번호, 섹션을 간단히 붙이세요.

Context:
{context}
""".strip()


def extract_business_year(query: str) -> Optional[int]:
    matches = re.findall(r"(20\d{2})\s*년?", query or "")
    return int(matches[-1]) if matches else None


def extract_amounts(query: str) -> List[int]:
    amounts: List[int] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*억\s*(?:원)?", query or ""):
        amounts.append(int(float(match.group(1)) * 100_000_000))
    for match in re.finditer(r"([\d,]+)\s*원", query or ""):
        raw = match.group(1).replace(",", "")
        if len(raw) >= 8:
            try:
                amounts.append(int(raw))
            except ValueError:
                pass
    return amounts


def extract_stock_codes(query: str) -> List[str]:
    found: List[str] = []
    for code in re.findall(r"\b\d{6}\b", query or ""):
        if code not in found:
            found.append(code)
    return found


def extract_metric(query: str) -> Optional[str]:
    for metric, aliases in METRIC_ALIASES.items():
        if any(alias in (query or "") for alias in aliases):
            return metric
    if "이익률" in (query or ""):
        return "operating_profit"
    return None


def extract_event_types(query: str) -> List[str]:
    found: List[str] = []
    for event_type, aliases in EVENT_TYPE_ALIASES.items():
        if any(alias in (query or "") for alias in aliases):
            found.append(event_type)
    if "자기주식" in (query or "") and not any(event_type.startswith("treasury_stock") for event_type in found):
        found.extend(["treasury_stock_acquisition", "treasury_stock_disposal"])
    return found


def route_query(query: str) -> Dict[str, Any]:
    text = query or ""
    stock_codes = extract_stock_codes(text)
    metric = extract_metric(text)
    event_types = extract_event_types(text)
    has_comparison = len(stock_codes) >= 2 and any(keyword in text for keyword in COMPARISON_KEYWORDS)
    has_financial = metric is not None or "이익률" in text
    has_event = any(keyword in text for keyword in EVENT_KEYWORDS)
    has_risk = any(keyword in text for keyword in RISK_KEYWORDS)
    has_business = any(keyword in text for keyword in BUSINESS_KEYWORDS)

    if has_comparison and has_financial:
        intent = "comparison"
    elif has_financial:
        intent = "financial_numeric"
    elif has_event:
        intent = "event_disclosure"
    elif has_risk:
        intent = "risk_analysis"
    elif has_business:
        intent = "business_text"
    else:
        intent = "unknown"

    return {
        "intent": intent,
        "company_codes": stock_codes,
        "stock_codes": stock_codes,
        "business_year": extract_business_year(text),
        "metric": metric,
        "event_types": event_types,
        "amounts": extract_amounts(text),
    }


def index_types_for_query(query_info: Dict) -> List[str]:
    intent = query_info.get("intent")
    if intent == "event_disclosure":
        return [EVENT_INDEX]
    if intent in {"business_text", "risk_analysis", "financial_numeric", "comparison"}:
        return [REGULAR_INDEX]
    return [REGULAR_INDEX, EVENT_INDEX]


def retrieve_context_documents(
    query: str,
    stock_codes: Optional[Iterable[str]] = None,
    k: int = 8,
    query_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, object]:
    query_info = query_info or route_query(query)
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
    return {"query_info": query_info, "documents": documents, "missing_indexes": missing_indexes}


def retrieve_context_text(query: str, stock_codes: Optional[Iterable[str]] = None, k: int = 8) -> Dict[str, object]:
    result = retrieve_context_documents(query, stock_codes=stock_codes, k=k)
    documents = result["documents"]
    context = "\n\n".join(document.page_content for document in documents)
    return {**result, "context": context}


def answer_question(question: str, stock_codes: list[str]) -> dict[str, Any]:
    question = str(question or "").strip()
    if not question:
        logger.info("empty_question")
        return {"answer": "질문을 입력해 주세요.", "sources": [], "query_info": {}}

    if _is_unsupported(question):
        logger.info("unsupported_question question_chars=%s", len(question))
        return {
            "answer": (
                "주가 예측, 매수/매도 판단, 목표가 제시, 포트폴리오 조언은 제공하지 않습니다. "
                "대신 DART 공시에서 확인 가능한 사업, 실적, 리스크, 최근 변화의 체크 포인트를 정리할 수 있습니다."
            ),
            "sources": [],
            "query_info": {"intent": "unsupported"},
            "route": "unsupported",
        }

    query_info = route_query(question)
    routed_codes = query_info.get("stock_codes") or query_info.get("company_codes") or []
    codes = list(dict.fromkeys([*routed_codes, *stock_codes]))
    logger.info("answer_route intent=%s stock_codes=%s", query_info.get("intent"), codes)
    sql_context = _sql_context(query_info, codes)
    try:
        retrieved = retrieve_context_documents(question, stock_codes=codes, k=8, query_info=query_info)
    except Exception as exc:
        logger.exception("retrieve_context_failed intent=%s stock_codes=%s", query_info.get("intent"), codes)
        retrieved = {"documents": [], "missing_indexes": [str(exc)]}
    documents = retrieved.get("documents", [])
    context = _join_context(sql_context, documents)
    sources = [_document_source(document) for document in documents]

    if context == "검색된 Context가 없습니다.":
        logger.warning("no_context_found intent=%s stock_codes=%s missing_indexes=%s", query_info.get("intent"), codes, retrieved.get("missing_indexes", []))
        return {
            "answer": "주어진 공시 자료에서는 해당 내용을 찾을 수 없습니다.",
            "sources": sources,
            "query_info": query_info,
            "route": _route_name(query_info),
            "missing_indexes": retrieved.get("missing_indexes", []),
        }

    if os.getenv("OPENAI_API_KEY"):
        try:
            answer = _llm_answer(question, context)
        except Exception:
            logger.exception("llm_answer_failed intent=%s stock_codes=%s", query_info.get("intent"), codes)
            raise
    else:
        logger.warning("openai_api_key_missing_using_extractive_answer")
        answer = _extractive_answer(question, context, query_info)
    logger.info("answer_complete route=%s source_count=%s", _route_name(query_info), len(sources))
    return {
        "answer": answer,
        "sources": sources,
        "query_info": query_info,
        "route": _route_name(query_info),
        "missing_indexes": retrieved.get("missing_indexes", []),
    }


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

    def event_key(document: Document) -> tuple[int, int, str]:
        metadata = document.metadata
        event_type = metadata.get("event_type") or ""
        return (
            0 if desired_event_types and event_type in desired_event_types else 1,
            0 if metadata.get("data_type") == "event_text" else 1,
            str(metadata.get("receipt_date") or ""),
        )

    if intent in {"financial_numeric", "comparison"}:
        return sorted(documents, key=financial_key)[:k]
    if intent == "event_disclosure":
        return sorted(documents, key=event_key, reverse=not desired_event_types)[:k]
    if intent == "risk_analysis":
        risk_documents = [document for document in documents if document.metadata.get("data_type") == "risk_text"]
        other_documents = [document for document in documents if document.metadata.get("data_type") != "risk_text"]
        return (risk_documents + other_documents)[:k]
    return documents[:k]


def _is_unsupported(question: str) -> bool:
    return any(keyword in question for keyword in UNSUPPORTED_KEYWORDS)


def _route_name(query_info: dict[str, Any]) -> str:
    intent = query_info.get("intent")
    if intent in {"financial_numeric", "comparison"}:
        return "structured_api"
    if intent in {"business_text", "risk_analysis"}:
        return "raw_filing_rag"
    if intent == "event_disclosure":
        return "event_filing_rag"
    return "both"


def _sql_context(query_info: dict[str, Any], stock_codes: list[str]) -> str:
    intent = query_info.get("intent")
    metric = query_info.get("metric")
    business_year = query_info.get("business_year")
    lines = []

    if intent == "comparison" and metric and len(stock_codes) >= 2:
        rows = compare_metric(stock_codes, metric, business_year=business_year)
        for rank, row in enumerate(rows, start=1):
            lines.append(
                f"[SQLite 정형 재무 비교] {rank}. {row.get('corp_name') or row.get('stock_code')} "
                f"{metric}={_format_krw(row.get(metric))}, 사업연도={row.get('business_year')}, "
                f"보고서={row.get('report_name')}, 접수번호={row.get('receipt_no')}"
            )
    elif intent in {"financial_numeric", "comparison"}:
        for code in stock_codes:
            row = get_financials(code, business_year=business_year)
            if row:
                lines.append(
                    "[SQLite 정형 재무]\n"
                    f"종목코드: {row.get('stock_code')}\n"
                    f"회사명: {row.get('corp_name')}\n"
                    f"사업연도: {row.get('business_year')}\n"
                    f"매출액: {_format_krw(row.get('revenue'))}\n"
                    f"영업이익: {_format_krw(row.get('operating_profit'))}\n"
                    f"당기순이익: {_format_krw(row.get('net_income'))}\n"
                    f"보고서: {row.get('report_name')}\n"
                    f"접수번호: {row.get('receipt_no')}"
                )
    elif intent == "event_disclosure":
        event_types = query_info.get("event_types") or [None]
        for code in stock_codes:
            for event_type in event_types:
                for row in get_recent_events(code, event_type=event_type, limit=5):
                    lines.append(
                        "[SQLite 이벤트 공시]\n"
                        f"회사명: {row.get('corp_name')}\n"
                        f"이벤트: {row.get('event_label') or row.get('event_type')}\n"
                        f"보고서: {row.get('report_name')}\n"
                        f"접수번호: {row.get('receipt_no')}\n"
                        f"접수일: {row.get('receipt_date')}\n"
                        f"금액: {_format_krw(row.get('amount'))}\n"
                        f"대상회사: {row.get('target_company') or '정보 없음'}\n"
                        f"목적: {row.get('purpose') or '정보 없음'}"
                    )
    return "\n\n".join(lines)


def _join_context(sql_context: str, documents: list[Document]) -> str:
    parts = []
    if sql_context:
        parts.append(sql_context)
    if documents:
        parts.append("[FAISS 검색 공시 Context]\n" + "\n\n".join(document.page_content for document in documents))
    return "\n\n".join(parts) if parts else "검색된 Context가 없습니다."


def _llm_answer(question: str, context: str) -> str:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "{question}"),
        ]
    )
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
    response = llm.invoke(prompt.format_messages(context=context, question=question))
    return str(getattr(response, "content", response))


def _extractive_answer(question: str, context: str, query_info: dict[str, Any]) -> str:
    preview = context[:1200].strip()
    suffix = "\n\n이 답변은 현재 LLM API 키 없이 검색된 공시 context를 발췌한 결과입니다."
    if query_info.get("intent") == "financial_numeric":
        return f"공시/정형 데이터에서 확인된 내용입니다.\n\n{preview}{suffix}"
    if query_info.get("intent") == "event_disclosure":
        return f"최근 이벤트 공시에서 확인된 내용입니다.\n\n{preview}{suffix}"
    return f"DART 공시 context에서 확인된 내용입니다.\n\n{preview}{suffix}"


def _document_source(document: Document) -> dict[str, Any]:
    metadata = document.metadata or {}
    return {
        "chunk_id": metadata.get("chunk_id"),
        "stock_code": metadata.get("stock_code"),
        "report_name": metadata.get("report_name", ""),
        "rcept_no": metadata.get("receipt_no", ""),
        "receipt_no": metadata.get("receipt_no", ""),
        "section": metadata.get("section", ""),
        "index_type": metadata.get("index_type", ""),
        "data_type": metadata.get("data_type", ""),
    }


def _format_krw(value: Any) -> str:
    if value in (None, ""):
        return "정보 없음"
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return str(value)
