from __future__ import annotations

import logging
import os
from typing import Any

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import LLM_MODEL
from .finance_store import compare_metric, get_financials, get_recent_events
from .query_router import route_query
from .retriever import retrieve_context_documents


logger = logging.getLogger(__name__)

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
        retrieved = retrieve_context_documents(question, stock_codes=codes, k=8)
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
