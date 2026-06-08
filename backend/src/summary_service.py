from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .company_lookup import Company
from .config import EVENT_INDEX, LLM_MODEL, REGULAR_INDEX, index_dir
from .finance_store import (
    get_active_chunks,
    get_company_summary,
    get_financials,
    get_latest_chunks,
    list_filings,
    upsert_company_summary,
)


logger = logging.getLogger(__name__)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

SUMMARY_KEYS = ("overview", "benefit", "earnings", "risk", "changing", "status", "anomaly")
SUMMARY_PROMPT_VERSION = "summary_prompt.v5"
_REVENUE_MODEL_KEYWORDS = (
    "매출",
    "수익",
    "판매",
    "제공",
    "서비스",
    "제품",
    "플랫폼",
    "광고",
    "구독",
    "수수료",
    "용역",
    "라이선스",
    "고객",
    "시장",
    "사업부문",
    "사업부",
    "제조",
    "공급",
    "계약",
)
_OVERVIEW_KEYWORDS = (
    "사업",
    "영위",
    "주요",
    "회사",
    "부문",
    "제품",
    "서비스",
    "플랫폼",
    "제조",
    "개발",
    "판매",
    "시장",
    "고객",
    "산업",
)
_FINANCIAL_PERFORMANCE_KEYWORDS = (
    "매출액",
    "영업이익",
    "당기순이익",
    "순이익",
    "손익",
    "이익률",
    "영업손실",
    "실적",
    "재무",
)
SUMMARY_PROMPT = """
당신은 DART 공시 기반 투자 정보 요약기입니다.
아래 evidence만 사용해 프론트엔드 카드용 한국어 요약을 작성하세요. 단순히 "보고서가 저장됐다", "인덱스가 준비됐다"처럼 시스템 상태만 말하지 말고, 투자자가 카드에서 바로 이해할 수 있는 내용으로 요약합니다.

규칙:
- 반드시 JSON object만 반환합니다.
- key는 overview, benefit, earnings, risk, changing, status, anomaly 7개만 사용합니다.
- status key는 시스템/인덱스 준비 상태가 아니라 "공모 상태" 카드입니다. IPO, 유상증자, 무상증자, 전환사채, 신주인수권부사채, 회사채, 증권 발행, 자금조달, 상장/상장폐지, 모집/매출 관련 공시 상태를 요약합니다.
- 각 값은 한국어 2~4문장 문자열입니다.
- evidence에 없는 숫자, 전망, 목표가, 매수/매도 의견을 만들지 않습니다.
- 재무 숫자는 financial_data에 있는 값만 사용합니다.
- fallback_summary 문장을 그대로 베끼지 않습니다. fallback은 참고용 초안일 뿐입니다.
- 문서 수집/인덱스 준비 상태는 frontend 카드 내용에 쓰지 않습니다.
- overview는 "무슨 회사인지"를 설명합니다. 주요 사업영역, 제품/서비스 범위, 고객/시장, 산업 내 역할을 요약하고, 매출액/영업이익/당기순이익 같은 실적 숫자는 쓰지 않습니다.
- benefit은 "어떻게 돈을 버는지"를 설명합니다. 사업부문별 수익원, 판매/제공 방식, 고객군, 수수료/광고/구독/제조/용역/라이선스 등 매출 발생 방식을 요약하고, earnings와 같은 재무 실적 설명을 반복하지 않습니다.
- earnings는 반드시 financial_data의 매출액, 영업이익, 당기순이익을 사용해 실적의 규모와 수익성 방향을 설명합니다. 단, 비교 기간 데이터가 없으면 증감 추세를 단정하지 않습니다.
- status는 "공모 상태"입니다. 자금조달/증권발행/상장 관련 event_filings 또는 event_chunks가 있으면 최근 공시명, 결정일, 금액, 목적을 중심으로 요약합니다. 관련 evidence가 없으면 "현재 수집된 최근 공시에서는 공모 또는 증권 발행 관련 주요 상태가 확인되지 않습니다"라고 명확히 씁니다.
- overview, benefit, earnings 세 카드는 서로 다른 문장과 관점을 가져야 합니다. 같은 내용을 문장만 바꿔 반복하지 않습니다.
- risk, changing, anomaly는 evidence가 부족하면 부족하다고 말하되, 어떤 종류의 추가 공시 확인이 필요한지 짧게 덧붙입니다.

evidence:
{evidence}
""".strip()


class SummaryService:
    def get_or_build(self, company: Company, *, force_refresh: bool = False, use_llm: bool = True) -> dict[str, str]:
        source_hash = self._source_hash(company.stock_code)
        cached = get_company_summary(company.stock_code)
        if not force_refresh and cached and cached.get("source_hash") == source_hash and cached.get("status") == "ready":
            logger.info("summary_cache_hit stock_code=%s generated_by=%s", company.stock_code, cached.get("generated_by"))
            return _normalize_summary(cached.get("summary"))

        if cached:
            logger.info("summary_cache_stale stock_code=%s", company.stock_code)
        else:
            logger.info("summary_cache_miss stock_code=%s", company.stock_code)
        return self.refresh(company, source_hash=source_hash, use_llm=use_llm)

    def refresh(self, company: Company, *, source_hash: str | None = None, use_llm: bool = True) -> dict[str, str]:
        source_hash = source_hash or self._source_hash(company.stock_code)
        logger.info("summary_build_start stock_code=%s use_llm=%s", company.stock_code, use_llm)
        fallback = self._fallback_summary(company)
        generated_by = "fallback"
        status = "ready"
        error = ""
        summary = fallback

        if use_llm and os.getenv("OPENAI_API_KEY"):
            try:
                llm_summary = self._llm_summary(company, fallback)
                summary = {key: llm_summary.get(key) or fallback[key] for key in SUMMARY_KEYS}
                generated_by = "llm"
                logger.info("summary_llm_success stock_code=%s", company.stock_code)
            except Exception as exc:
                error = str(exc)
                logger.warning("summary_llm_failed stock_code=%s error=%s", company.stock_code, exc)
                logger.info("summary_fallback_used stock_code=%s", company.stock_code)
        else:
            logger.info("summary_fallback_used stock_code=%s reason=llm_disabled_or_missing_key", company.stock_code)

        upsert_company_summary(
            stock_code=company.stock_code,
            corp_name=company.corp_name,
            source_hash=source_hash,
            summary=summary,
            generated_by=generated_by,
            status=status,
            error=error,
        )
        logger.info("summary_store_complete stock_code=%s generated_by=%s status=%s", company.stock_code, generated_by, status)
        return summary

    def _llm_summary(self, company: Company, fallback: dict[str, str]) -> dict[str, str]:
        evidence = json.dumps(self._evidence_package(company, fallback), ensure_ascii=False, default=str)
        prompt = ChatPromptTemplate.from_messages([("system", SUMMARY_PROMPT)])
        llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
        response = llm.invoke(prompt.format_messages(evidence=evidence))
        content = str(getattr(response, "content", response)).strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.removeprefix("json").strip()
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("LLM summary response is not a JSON object")
        return _normalize_summary(parsed)

    def _evidence_package(self, company: Company, fallback: dict[str, str]) -> dict[str, Any]:
        return {
            "company": {"stock_code": company.stock_code, "corp_name": company.corp_name},
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "financial_data": get_financials(company.stock_code) or {},
            "index_readiness_for_internal_use_only": self._index_status(company.stock_code),
            "fallback_summary": fallback,
            "business_chunks": _chunk_previews(get_latest_chunks(company.stock_code, index_type=REGULAR_INDEX, data_type="business_text", limit=3)),
            "risk_chunks": _chunk_previews(get_latest_chunks(company.stock_code, index_type=REGULAR_INDEX, data_type="risk_text", limit=2)),
            "event_chunks": _chunk_previews(get_latest_chunks(company.stock_code, index_type=EVENT_INDEX, data_type="event_text", limit=3)),
            "event_filings": list_filings(company.stock_code, index_type=EVENT_INDEX, limit=5),
        }

    def _fallback_summary(self, company: Company) -> dict[str, str]:
        financial = get_financials(company.stock_code)
        business_chunks = get_latest_chunks(company.stock_code, index_type=REGULAR_INDEX, data_type="business_text", limit=3)
        risk_chunks = get_latest_chunks(company.stock_code, index_type=REGULAR_INDEX, data_type="risk_text", limit=2)
        event_chunks = get_latest_chunks(company.stock_code, index_type=EVENT_INDEX, data_type="event_text", limit=3)

        return {
            "overview": _overview_line(company, business_chunks),
            "benefit": _benefit_line(business_chunks),
            "earnings": _earnings_line(financial),
            "risk": _summarize_chunks(risk_chunks, fallback="공시 인덱스에서 별도 리스크 문단을 찾지 못했습니다."),
            "changing": _summarize_chunks(event_chunks, fallback="최근 이벤트 공시 인덱스가 아직 준비되지 않았거나 해당 이벤트가 없습니다."),
            "status": _offering_status_line(company.stock_code),
            "anomaly": _event_anomaly_line(company.stock_code),
        }

    def _source_hash(self, stock_code: str) -> str:
        regular_chunks = get_active_chunks(stock_code, REGULAR_INDEX)
        event_chunks = get_active_chunks(stock_code, EVENT_INDEX)
        financial = get_financials(stock_code) or {}
        event_filings = list_filings(stock_code, index_type=EVENT_INDEX, limit=20)
        payload = {
            "summary_prompt_version": SUMMARY_PROMPT_VERSION,
            "regular_chunks": _source_chunk_refs(regular_chunks),
            "event_chunks": _source_chunk_refs(event_chunks),
            "financial": {key: financial.get(key) for key in ("receipt_no", "receipt_date", "updated_at")},
            "event_filings": [
                {key: row.get(key) for key in ("receipt_no", "receipt_date", "updated_at")}
                for row in event_filings
            ],
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _index_status(self, stock_code: str) -> dict[str, Any]:
        regular_file = (index_dir(stock_code, REGULAR_INDEX) / "index.faiss").exists()
        event_file = (index_dir(stock_code, EVENT_INDEX) / "index.faiss").exists()
        regular_chunks = len(get_active_chunks(stock_code, REGULAR_INDEX))
        event_chunks = len(get_active_chunks(stock_code, EVENT_INDEX))
        return {
            "regular_ready": regular_file and regular_chunks > 0,
            "event_ready": event_file and event_chunks > 0,
            "regular_active_chunks": regular_chunks,
            "event_active_chunks": event_chunks,
        }


def _normalize_summary(value: Any) -> dict[str, str]:
    data = value if isinstance(value, dict) else {}
    return {key: str(data.get(key) or "").strip() for key in SUMMARY_KEYS}


def _chunk_previews(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "chunk_id": chunk.get("id"),
            "receipt_no": chunk.get("receipt_no"),
            "section": chunk.get("section"),
            "data_type": chunk.get("data_type"),
            "content": str(chunk.get("content") or "")[:1600],
        }
        for chunk in chunks
    ]


def _source_chunk_refs(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": chunk.get("id"),
            "receipt_no": chunk.get("receipt_no"),
            "updated_at": chunk.get("updated_at"),
        }
        for chunk in chunks
    ]


def _summarize_chunks(chunks: list[dict[str, Any]], fallback: str) -> str:
    if not chunks:
        return fallback
    text = " ".join((chunk.get("content") or "").replace("\n", " ") for chunk in chunks)
    return text[:420] + ("..." if len(text) > 420 else "")


def _financial_line(financial: dict[str, Any] | None) -> str:
    if not financial:
        return "정형 재무 데이터가 아직 준비되지 않았습니다."
    report_name = financial.get("report_name") or f"{financial.get('business_year')}년 보고서"
    period_month = financial.get("period_month")
    period_text = f"{period_month}개월 누적" if period_month else "보고서 기준"
    return (
        f"{report_name} {period_text} 기준 매출액은 {_format_krw(financial.get('revenue'))}, "
        f"영업이익은 {_format_krw(financial.get('operating_profit'))}, "
        f"당기순이익은 {_format_krw(financial.get('net_income'))}입니다. "
        "현재 저장된 정형 재무 데이터 기준의 수익 구조이며, 사업부문별 매출 비중은 원문 표 확인이 필요합니다."
    )


def _overview_line(company: Company, chunks: list[dict[str, Any]]) -> str:
    selected = _select_sentences(
        chunks,
        positive_keywords=_OVERVIEW_KEYWORDS,
        negative_keywords=_FINANCIAL_PERFORMANCE_KEYWORDS,
        limit=3,
    )
    if selected:
        text = " ".join(selected)
        return text[:520] + ("..." if len(text) > 520 else "")
    return f"{company.corp_name}의 주요 사업, 제품, 서비스 범위를 설명할 공시 근거가 아직 준비되지 않았습니다."


def _benefit_line(chunks: list[dict[str, Any]]) -> str:
    selected = _select_revenue_model_sentences(chunks)
    if selected:
        text = " ".join(selected)
        return text[:520] + ("..." if len(text) > 520 else "")
    return (
        "사업부문별 제품이나 서비스 설명은 현재 요약 근거에서 충분히 확인되지 않았습니다. "
        "구체적인 수익원은 사업의 내용 원문 표와 부문 설명을 추가 확인해야 합니다."
    )


def _select_revenue_model_sentences(chunks: list[dict[str, Any]], limit: int = 3) -> list[str]:
    return _select_sentences(
        chunks,
        positive_keywords=_REVENUE_MODEL_KEYWORDS,
        negative_keywords=_FINANCIAL_PERFORMANCE_KEYWORDS,
        limit=limit,
    )


def _select_sentences(
    chunks: list[dict[str, Any]],
    *,
    positive_keywords: tuple[str, ...],
    negative_keywords: tuple[str, ...] = (),
    limit: int = 3,
) -> list[str]:
    text = " ".join((chunk.get("content") or "").replace("\n", " ") for chunk in chunks)
    if not text.strip():
        return []
    sentences = _split_sentences(text)
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        compact = "".join(sentence.split())
        score = sum(2 for keyword in positive_keywords if keyword in compact)
        score -= sum(2 for keyword in negative_keywords if keyword in compact)
        if score > 0:
            scored.append((score, -index, sentence))
    scored.sort(reverse=True)
    return [sentence for _, _, sentence in scored[:limit]]


def _split_sentences(text: str) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+", cleaned)
        if sentence.strip()
    ]


def _earnings_line(financial: dict[str, Any] | None) -> str:
    if not financial:
        return "실적 동향은 정형 재무 데이터 적재 후 표시됩니다."
    report_name = financial.get("report_name") or f"{financial.get('business_year')}년 보고서"
    revenue = _as_number(financial.get("revenue"))
    operating_profit = _as_number(financial.get("operating_profit"))
    net_income = _as_number(financial.get("net_income"))
    margin_text = ""
    if revenue and operating_profit is not None:
        margin_text = f" 영업이익률은 약 {operating_profit / revenue * 100:.1f}%로 계산됩니다."
    return (
        f"{report_name} 기준 매출액은 {_format_krw(revenue)}, 영업이익은 {_format_krw(operating_profit)}, "
        f"당기순이익은 {_format_krw(net_income)}입니다.{margin_text} "
        "비교 기간 데이터가 함께 저장되어 있지 않다면 증감 추세보다는 현재 보고서의 실적 규모와 수익성 수준으로 해석해야 합니다."
    )


def _offering_status_line(stock_code: str) -> str:
    filings = list_filings(stock_code, index_type=EVENT_INDEX, limit=10)
    offering_filings = [
        row for row in filings
        if _is_offering_related(row.get("report_name") or row.get("filing_detail_type") or "")
    ]
    if not offering_filings:
        return "현재 수집된 최근 공시에서는 공모, 증권 발행, 상장 관련 주요 상태가 확인되지 않습니다."

    names = ", ".join(row.get("report_name") or row.get("filing_detail_type") or row.get("receipt_no") for row in offering_filings[:3])
    latest = offering_filings[0]
    return (
        f"최근 공모/자금조달 관련 공시로 {names} 등이 확인됩니다. "
        f"가장 최근 항목은 {latest.get('receipt_date') or '접수일 정보 없음'} 접수된 "
        f"{latest.get('report_name') or latest.get('filing_detail_type') or latest.get('receipt_no')}입니다."
    )


def _is_offering_related(text: Any) -> bool:
    compact = "".join(str(text or "").split())
    keywords = (
        "공모",
        "모집",
        "매출",
        "유상증자",
        "무상증자",
        "증권발행",
        "전환사채",
        "신주인수권부사채",
        "교환사채",
        "회사채",
        "상장",
        "상장폐지",
        "투자설명서",
        "증권신고서",
    )
    return any(keyword in compact for keyword in keywords)


def _event_anomaly_line(stock_code: str) -> str:
    filings = list_filings(stock_code, index_type=EVENT_INDEX, limit=5)
    if not filings:
        return "최근 이벤트 공시 특이사항이 저장되어 있지 않습니다."
    names = ", ".join(row.get("report_name") or row.get("filing_detail_type") or row.get("receipt_no") for row in filings[:3])
    return f"최근 이벤트 공시로 {names} 등이 저장되어 있습니다."


def _format_krw(value: Any) -> str:
    if value in (None, ""):
        return "정보 없음"
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return str(value)


def _as_number(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
