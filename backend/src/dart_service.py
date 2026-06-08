import html
import contextlib
import io
import json
import logging
import re
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
import OpenDartReader

from .config import EVENT_INDEX, EVENT_LOOKBACK_DAYS as CONFIG_EVENT_LOOKBACK_DAYS, REGULAR_INDEX, REGULAR_LOOKBACK_DAYS, cleaned_dir, raw_dir

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter


logger = logging.getLogger(__name__)

EVENT_CHUNK_SIZE = 2500
EVENT_CHUNK_OVERLAP = 200
EXTRACTION_MODEL = "gpt-4o-mini"

_EXTRACTION_PROMPT = """
다음은 DART 수시공시 원문입니다. 이 공시에서 아래 정보를 추출하세요.

1. 대상법인: 이 공시의 자금이 어떤 법인의 주식/증권 취득에 사용되는지. 법인명을 모두 나열.
2. 각 대상법인별 금액: 해당 법인에 배정된 금액.
3. 발행 대상자: 사채 발행 또는 증자의 대상자(인수자) 이름과 금액.
4. 지급방법: 대용납입, 현금, 기타.

정보가 없으면 "정보 없음"이라고 답하세요.
반드시 원문에 기재된 내용만 추출하고, 추론하지 마세요.
간결한 한국어 1~3문장으로 답하세요.

공시 원문 (앞부분 3000자):
{text}
""".strip()

EVENT_KEYWORDS = [
    "부도발생",
    "영업정지",
    "회생절차",
    "해산사유",
    "유상증자",
    "무상증자",
    "유무상증자",
    "감자",
    "관리절차개시",
    "소송",
    "해외상장결정",
    "해외상장폐지결정",
    "해외상장",
    "해외상장폐지",
    "전환사채발행",
    "신주인수권부사채발행",
    "교환사채발행",
    "관리절차중단",
    "조건부자본증권발행",
    "자산양수도",
    "타법인증권양도",
    "유형자산양도",
    "유형자산양수",
    "타법인증권양수",
    "영업양도",
    "영업양수",
    "자기주식취득신탁계약해지",
    "자기주식취득신탁계약체결",
    "자기주식처분",
    "자기주식취득",
    "주식교환",
    "회사분할합병",
    "회사분할",
    "회사합병",
    "사채권양수",
    "사채권양도결정",
]

EVENT_TYPE_BY_KEYWORD = {
    "전환사채발행": "convertible_bond_issuance",
    "신주인수권부사채발행": "bond_with_warrant_issuance",
    "교환사채발행": "exchangeable_bond_issuance",
    "조건부자본증권발행": "coco_bond_issuance",
    "유상증자": "paid_in_capital_increase",
    "무상증자": "bonus_issue",
    "유무상증자": "paid_and_bonus_issue",
    "감자": "capital_reduction",
    "타법인증권양수": "equity_acquisition",
    "타법인증권양도": "equity_disposal",
    "유형자산양수": "tangible_asset_acquisition",
    "유형자산양도": "tangible_asset_disposal",
    "영업양수": "business_acquisition",
    "영업양도": "business_disposal",
    "소송": "lawsuit",
    "영업정지": "business_suspension",
    "회생절차": "rehabilitation",
    "회사합병": "merger",
    "회사분할": "spin_off",
    "회사분할합병": "split_merger",
    "주식교환": "share_exchange",
    "자기주식취득": "treasury_stock_acquisition",
    "자기주식처분": "treasury_stock_disposal",
    "자기주식취득신탁계약체결": "treasury_stock_trust_contract",
    "자기주식취득신탁계약해지": "treasury_stock_trust_termination",
    "사채권양수": "bond_acquisition",
    "사채권양도결정": "bond_disposal",
}


def _parse_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9.-]", "", text)
    if not text:
        return None
    try:
        number = int(float(text))
        return -number if negative else number
    except ValueError:
        return None


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _first_value(row: Dict[str, Any], columns: Iterable[str]) -> str:
    for column in columns:
        value = _safe_str(row.get(column))
        if value and value != "-":
            return value
    return ""


def _first_number(row: Dict[str, Any], columns: Iterable[str]) -> Optional[int]:
    for column in columns:
        parsed = _parse_number(row.get(column))
        if parsed is not None:
            return parsed
    return None


def _funding_items(row: Dict[str, Any]) -> List[tuple[str, str]]:
    labels = [
        ("시설자금", "fdpp_fclt"),
        ("영업양수자금", "fdpp_bsninh"),
        ("운영자금", "fdpp_op"),
        ("채무상환자금", "fdpp_dtrp"),
        ("타법인증권 취득자금", "fdpp_ocsa"),
        ("기타자금", "fdpp_etc"),
    ]
    items = []
    for label, column in labels:
        value = _safe_str(row.get(column))
        if value and value != "-":
            items.append((label, value))
    return items


def _funding_purpose(row: Dict[str, Any]) -> str:
    return ", ".join(f"{label}: {value}" for label, value in _funding_items(row))


def _funding_amount(row: Dict[str, Any]) -> Optional[int]:
    total = 0
    found = False
    for _, value in _funding_items(row):
        parsed = _parse_number(value)
        if parsed is not None:
            total += parsed
            found = True
    return total if found else None


def _clean_event_text(raw_document: str) -> str:
    text = html.unescape(raw_document or "")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(re.compile(r"^(p|div|br|h1|h2|h3|h4|h5|h6|li|tr)$", re.I)):
        if tag.name.lower() == "br":
            tag.replace_with("\n")
        else:
            tag.insert_before("\n")
            tag.insert_after("\n")
    text = soup.get_text(" ")
    text = re.sub(r"&#x?[0-9a-fA-F]+;", " ", text)
    text = re.sub(r"\t+", " ", text)
    text = re.sub(r"[ \u00a0]{2,}", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _event_summary(event: Dict[str, Any]) -> str:
    fields = [
        ("기업코드", event.get("company_code")),
        ("회사명", event.get("company_name")),
        ("이벤트", event.get("event_label")),
        ("보고서명", event.get("report_name")),
        ("접수번호", event.get("receipt_no")),
        ("접수일자", event.get("receipt_date")),
        ("결정일", event.get("decision_date")),
        ("금액", event.get("amount")),
        ("대상회사", event.get("target_company")),
        ("목적", event.get("purpose")),
        ("전환가액", event.get("conversion_price")),
        ("전환가능주식수", event.get("conversion_shares")),
        ("취득주식수", event.get("acquisition_shares")),
        ("취득후 지분율", event.get("acquisition_ratio")),
        ("지급방법", event.get("payment_method")),
    ]
    lines = ["[정형 수시공시 이벤트 요약]"]
    for label, value in fields:
        if value not in (None, ""):
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _normalize_event(row: Dict[str, Any], keyword: str, company_code: str) -> Dict[str, Any]:
    event_type = EVENT_TYPE_BY_KEYWORD.get(keyword, re.sub(r"\W+", "_", keyword).strip("_"))
    receipt_no = _first_value(row, ["rcept_no"])
    receipt_date = _first_value(row, ["rcept_dt", "rcept_de"])
    decision_date = _first_value(row, ["bddd", "rs_sm_atn", "sbd", "pymd", "inh_prd"])
    amount = _first_number(row, ["bd_fta", "inhdtl_inhprc", "trfdtl_trfprc"])
    if amount is None:
        amount = _funding_amount(row)
    if amount is None:
        amount = _first_number(row, ["dl_prc", "ast_inh_prc", "ast_trf_prc"])
    target_company = _first_value(
        row,
        [
            "iscmp_cmpnm",
            "dlptn_cmpnm",
            "trf_cmpnm",
            "inh_cmpnm",
            "mgptncmp_cmpnm",
            "cmpnm",
        ],
    )
    purpose = _first_value(
        row,
        [
            "inh_pp",
            "trf_pp",
            "aq_pp",
        ],
    )
    if not purpose:
        purpose = _funding_purpose(row)
    payment_method = _first_value(row, ["dl_pym", "bdis_mthn", "ic_mthn", "bd_mtd", "pymd"])

    return {
        "company_code": company_code,
        "company_name": _first_value(row, ["corp_name"]),
        "event_type": event_type,
        "event_label": keyword,
        "report_name": keyword,
        "receipt_no": receipt_no,
        "receipt_date": receipt_date,
        "decision_date": decision_date,
        "amount": amount,
        "target_company": target_company,
        "purpose": purpose,
        "conversion_price": _first_number(row, ["cv_prc"]),
        "conversion_shares": _first_number(row, ["cvisstk_cnt"]),
        "acquisition_shares": _first_number(row, ["inhdtl_stkcnt", "atinh_owstkcnt"]),
        "acquisition_ratio": _first_value(row, ["atinh_eqrt", "inhdtl_ecpt_vs", "cvisstk_tisstk_vs"]),
        "payment_method": payment_method,
        "raw_json": json.dumps(row, ensure_ascii=False, default=str),
    }


def _load_major_report_meta(
    dart: OpenDartReader,
    company_code: str,
    start: str,
    end: str,
) -> Dict[str, Dict[str, str]]:
    try:
        reports = dart.list(company_code, start=start, end=end, kind="B", final=True)
    except Exception as exc:
        logger.warning("[%s] 주요사항보고 목록 조회 실패: %s", company_code, exc)
        return {}
    if reports is None or getattr(reports, "empty", True):
        return {}

    meta: Dict[str, Dict[str, str]] = {}
    for _, series in reports.iterrows():
        row = series.to_dict()
        receipt_no = _safe_str(row.get("rcept_no"))
        if not receipt_no:
            continue
        meta[receipt_no] = {
            "report_name": _safe_str(row.get("report_nm")),
            "receipt_date": _safe_str(row.get("rcept_dt")),
            "company_name": _safe_str(row.get("corp_name") or row.get("flr_nm")),
        }
    return meta


def _chunk_event_text(text: str) -> List[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=EVENT_CHUNK_SIZE,
        chunk_overlap=EVENT_CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text) if text else []


def _make_event_documents(event: Dict[str, Any], raw_text: str = "") -> List[Document]:
    summary = _event_summary(event)
    event_text = raw_text.strip() if raw_text else ""
    full_text = summary + ("\n\n[수시공시 원문]\n" + event_text if event_text else "")
    chunks = _chunk_event_text(full_text) or [summary]
    documents = []
    chunk_total = len(chunks)
    for index, chunk in enumerate(chunks, start=1):
        documents.append(
            Document(
                page_content=chunk,
                metadata={
                    "company_code": event.get("company_code", ""),
                    "company_name": event.get("company_name", ""),
                    "source_type": "DART",
                    "data_type": "event_text",
                    "event_type": event.get("event_type", ""),
                    "event_label": event.get("event_label", ""),
                    "report_name": event.get("report_name", ""),
                    "receipt_no": event.get("receipt_no", ""),
                    "receipt_date": event.get("receipt_date", ""),
                    "decision_date": event.get("decision_date", ""),
                    "section": "수시공시 이벤트",
                    "chunk_index": index,
                    "chunk_total": chunk_total,
                    "risk_type": "",
                },
            )
        )
    return documents


_EXTRACTION_TRIGGER_KEYWORDS = ["타법인", "취득", "대용납입", "양수", "양도", "합병", "분할"]


def _should_extract_detail(event: Dict[str, Any], raw_text: str) -> bool:
    """Determine if LLM extraction is worthwhile for this event."""
    purpose = _safe_str(event.get("purpose"))
    event_type = _safe_str(event.get("event_type"))
    if any(kw in purpose for kw in _EXTRACTION_TRIGGER_KEYWORDS):
        return True
    if event_type in {
        "convertible_bond_issuance",
        "bond_with_warrant_issuance",
        "exchangeable_bond_issuance",
        "equity_acquisition",
        "equity_disposal",
        "merger",
        "split_merger",
    }:
        return True
    return False


def _extract_relevant_sections(raw_text: str, max_chars: int = 5000) -> str:
    """Extract the most relevant sections from event text for LLM processing."""
    if len(raw_text) <= max_chars:
        return raw_text

    # Key section markers that contain target company info
    section_markers = [
        "특정인에 대한 대상자별",
        "사채발행내역",
        "양수도 계약",
        "대용납입",
        "납입자산",
        "증권발행회사",
        "자금의 사용목적",
        "대상회사",
    ]

    parts = [raw_text[:2000]]  # Always include beginning
    remaining = max_chars - 2000

    for marker in section_markers:
        idx = raw_text.find(marker, 2000)  # Search after the first 2000 chars
        if idx >= 0 and remaining > 0:
            start = max(2000, idx - 200)
            end = min(len(raw_text), idx + 800)
            section = raw_text[start:end]
            if len(section) <= remaining:
                parts.append(f"\n...\n{section}")
                remaining -= len(section)

    return "".join(parts)


def _extract_target_detail(raw_text: str) -> str:
    """Use gpt-4o-mini to extract target company details from event raw text."""
    if not raw_text or len(raw_text) < 50:
        return ""
    try:
        import os
        if not os.getenv("OPENAI_API_KEY"):
            return ""
        llm = ChatOpenAI(model=EXTRACTION_MODEL, temperature=0, max_tokens=300)
        relevant_text = _extract_relevant_sections(raw_text)
        prompt_text = _EXTRACTION_PROMPT.format(text=relevant_text)
        response = llm.invoke(prompt_text)
        detail = getattr(response, "content", str(response)).strip()
        if detail and "정보 없음" not in detail:
            return detail
    except Exception as exc:
        logger.warning("LLM target_detail 추출 실패: %s", exc)
    return ""


MAX_LOOKBACK_YEARS = 7
REGULAR_REPORT_PATTERNS = {
    "annual": "사업보고서",
    "semiannual": "반기보고서",
    "quarterly": "분기보고서",
}
DISCLOSURE_REPORT_PATTERNS = [
    ("single_sales_supply_contract", "단일판매/공급계약", r"단일판매[ㆍ·.]?공급계약|공급계약체결"),
    ("largest_shareholder_change", "최대주주변경", r"최대주주\s*변경|최대주주변경"),
    ("sanctions", "벌금/제재", r"벌금|제재|과징금|행정처분"),
    ("embezzlement_breach_of_trust", "횡령/배임", r"횡령|배임"),
    ("delisting", "상장폐지", r"상장폐지"),
    ("trading_suspension", "거래정지", r"거래정지|매매거래정지"),
]


@dataclass
class CollectedFiling:
    stock_code: str
    receipt_no: str
    report_name: str
    receipt_date: str
    corp_name: str
    corp_code: str
    index_type: str
    raw_path: Path
    report_kind: str = ""
    cleaned_path: Path | None = None
    row: Any = None

    def filing_record(self) -> Dict[str, Any]:
        return {
            "receipt_no": self.receipt_no,
            "stock_code": self.stock_code,
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "report_name": self.report_name,
            "receipt_date": self.receipt_date,
            "filing_type": "regular" if self.index_type == REGULAR_INDEX else "event",
            "filing_detail_type": self.report_kind,
            "index_type": self.index_type,
            "raw_path": str(self.raw_path),
            "cleaned_path": str(self.cleaned_path or ""),
            "metadata": {"report_kind": self.report_kind},
        }


def normalize_stock_code(value: Any) -> str:
    code = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"유효하지 않은 6자리 종목코드입니다: {value!r}")
    return code


def save_cleaned_text(stock_code: str, receipt_no: str, text: str) -> Path:
    path = cleaned_dir(stock_code) / f"{receipt_no}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def classify_regular_report(report_name: str) -> str:
    text = str(report_name or "")
    for report_kind, pattern in REGULAR_REPORT_PATTERNS.items():
        if pattern in text:
            return report_kind
    return ""


def _validate_report_list(reports: pd.DataFrame, stock_code: str) -> None:
    if reports is None or getattr(reports, "empty", True):
        raise ValueError(f"정기공시 목록이 없습니다: {stock_code}")
    required_columns = {"report_nm", "rcept_dt", "rcept_no"}
    missing = required_columns - set(reports.columns)
    if missing:
        raise ValueError(f"DART 공시 목록 컬럼 누락: {sorted(missing)}")


def _find_latest_annual_report(dart: OpenDartReader, stock_code: str) -> pd.Series:
    today = datetime.today()
    start = f"{today.year - MAX_LOOKBACK_YEARS}-01-01"
    end = today.strftime("%Y-%m-%d")
    reports = dart.list(stock_code, start=start, end=end, kind="A", final=False)
    _validate_report_list(reports, stock_code)
    annual_reports = reports[reports["report_nm"].astype(str).str.contains("사업보고서", na=False)].copy()
    if annual_reports.empty:
        raise ValueError(f"최근 사업보고서를 찾지 못했습니다: {stock_code}")
    return annual_reports.sort_values("rcept_dt", ascending=False).iloc[0]


def _find_recent_regular_reports(
    dart: OpenDartReader,
    stock_code: str,
    lookback_days: int = REGULAR_LOOKBACK_DAYS,
) -> pd.DataFrame:
    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    reports = dart.list(
        stock_code,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        kind="A",
        final=False,
    )
    _validate_report_list(reports, stock_code)
    reports = reports.copy()
    reports["report_kind"] = reports["report_nm"].map(classify_regular_report)
    reports = reports[reports["report_kind"].astype(bool)].copy()
    if reports.empty:
        raise ValueError(f"최근 {lookback_days}일 정기보고서를 찾지 못했습니다: {stock_code}")
    reports = reports.drop_duplicates(subset=["rcept_no"], keep="first")
    return reports.sort_values("rcept_dt", ascending=True)


def _collect_regular_filing_from_row(
    dart: OpenDartReader,
    stock_code: str,
    row: Any,
    sleep_seconds: float,
) -> tuple[CollectedFiling, str]:
    receipt_no = str(row.get("rcept_no", ""))
    if not receipt_no:
        raise ValueError("정기보고서 접수번호가 비어 있습니다.")
    time.sleep(sleep_seconds)
    raw_document = dart.document(receipt_no)
    if not raw_document:
        raise ValueError(f"정기보고서 원문 다운로드 실패: {receipt_no}")

    path = raw_dir(stock_code) / f"{receipt_no}.xml"
    path.write_text(raw_document, encoding="utf-8")
    filing = CollectedFiling(
        stock_code=stock_code,
        receipt_no=receipt_no,
        report_name=str(row.get("report_nm", "")),
        receipt_date=str(row.get("rcept_dt", "")),
        corp_name=str(row.get("corp_name", row.get("flr_nm", ""))),
        corp_code=str(row.get("corp_code", "")),
        index_type=REGULAR_INDEX,
        raw_path=path,
        report_kind=str(row.get("report_kind") or classify_regular_report(str(row.get("report_nm", "")))),
        row=row,
    )
    return filing, raw_document


def collect_latest_annual_filing(dart: OpenDartReader, stock_code: str, sleep_seconds: float = 0.3) -> tuple[CollectedFiling, str]:
    latest = _find_latest_annual_report(dart, stock_code)
    latest = latest.copy()
    latest["report_kind"] = "annual"
    return _collect_regular_filing_from_row(dart, stock_code, latest, sleep_seconds)


def collect_recent_regular_filings(
    dart: OpenDartReader,
    stock_code: str,
    lookback_days: int = REGULAR_LOOKBACK_DAYS,
    sleep_seconds: float = 0.3,
) -> Dict[str, Any]:
    reports = _find_recent_regular_reports(dart, stock_code, lookback_days=lookback_days)
    collected: List[tuple[CollectedFiling, str]] = []
    failed_list: List[Dict[str, str]] = []

    for _, series in reports.iterrows():
        row = series.copy()
        try:
            collected.append(_collect_regular_filing_from_row(dart, stock_code, row, sleep_seconds))
        except Exception as exc:
            receipt_no = str(row.get("rcept_no", ""))
            report_name = str(row.get("report_nm", ""))
            logger.warning("[%s] 정기보고서 수집 실패(%s): %s", stock_code, receipt_no, exc)
            failed_list.append({"receipt_no": receipt_no, "report_name": report_name, "reason": str(exc)})

    if not collected:
        raise ValueError(f"저장 가능한 최근 정기보고서가 없습니다: {stock_code}")
    return {"filings": collected, "failed_list": failed_list}


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
    records = []
    for document in _make_event_documents(event, raw_text):
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
    lookback_days: int = CONFIG_EVENT_LOOKBACK_DAYS,
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

    return {"events": events, "filings": filings, "chunks": chunks, "failed_list": failed_list}
