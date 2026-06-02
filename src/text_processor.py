import re
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from .data_processor import (
    _chunk_text,
    _clean_text,
    _extract_business_section,
    _pick_financial_value,
    make_business_chunk_text,
    make_structured_financial_text,
)
from .config import REGULAR_INDEX

RISK_PATTERNS = {
    "legal": ["소송", "제재", "영업정지", "법률분쟁", "분쟁"],
    "financial": ["우발부채", "차입금", "손상차손", "채무불이행", "채무상환"],
    "business": ["사업위험", "공급망위험", "경쟁심화", "영업환경악화"],
    "market": ["시장위험", "환율위험", "외환위험", "이자율위험", "가격위험"],
    "safety": ["안전사고", "중대재해", "품질사고"],
    "reputation": ["평판위험", "브랜드훼손", "신뢰하락"],
    "liquidity": ["유동성위험", "유동성부족"],
    "credit": ["신용위험", "신용등급하락"],
}

HIGH_SIGNAL_RISK_KEYWORDS = [
    "소송",
    "제재",
    "영업정지",
    "우발부채",
    "채무불이행",
    "손상차손",
    "유동성위험",
    "신용위험",
    "시장위험",
    "환율위험",
    "이자율위험",
    "안전사고",
]
MEDIUM_SIGNAL_RISK_KEYWORDS = [
    "법률분쟁",
    "분쟁",
    "차입금",
    "채무상환",
    "공급망위험",
    "경쟁심화",
    "영업환경악화",
    "외환위험",
    "가격위험",
    "중대재해",
    "품질사고",
    "평판위험",
    "브랜드훼손",
    "신뢰하락",
    "유동성부족",
    "신용등급하락",
]

REPORT_CODE_BY_KIND = {
    "annual": "11011",
    "semiannual": "11012",
}
REPORT_CODE_FIRST_QUARTER = "11013"
REPORT_CODE_THIRD_QUARTER = "11014"
FINANCIAL_ALIASES = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "operating_profit": ["영업이익", "영업이익(손실)"],
    "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "연결당기순이익"],
}


def _detect_risk_type(text: str) -> str:
    for risk_type, keywords in RISK_PATTERNS.items():
        compact = "".join(str(text or "").split())
        if any(keyword in compact for keyword in keywords):
            return risk_type
    return "general"


def _is_risk_related(text: str) -> bool:
    compact = "".join(str(text or "").split())
    if any(keyword in compact for keyword in HIGH_SIGNAL_RISK_KEYWORDS):
        return True
    medium_hits = {keyword for keyword in MEDIUM_SIGNAL_RISK_KEYWORDS if keyword in compact}
    return len(medium_hits) >= 2



def clean_document(raw_document: str) -> str:
    return _clean_text(raw_document)


def extract_business_section(clean_text: str) -> str:
    return _extract_business_section(clean_text)


def chunk_business_text(business_text: str) -> List[str]:
    return _chunk_text(business_text)


def _extract_report_year_month(report_name: str) -> tuple[Optional[int], Optional[int]]:
    match = re.search(r"\((20\d{2})\.(\d{2})\)", str(report_name or ""))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _report_code_for_row(report_row) -> str:
    report_name = str(report_row.get("report_nm", ""))
    report_kind = str(report_row.get("report_kind") or "")
    _, report_month = _extract_report_year_month(report_name)
    if report_kind == "quarterly":
        if report_month == 3:
            return REPORT_CODE_FIRST_QUARTER
        if report_month == 9:
            return REPORT_CODE_THIRD_QUARTER
        raise ValueError(f"지원하지 않는 분기보고서 월입니다: {report_name}")
    report_code = REPORT_CODE_BY_KIND.get(report_kind)
    if not report_code:
        raise ValueError(f"지원하지 않는 정기보고서 종류입니다: {report_kind or report_name}")
    return report_code


def _business_year_for_row(report_row) -> int:
    report_name = str(report_row.get("report_nm", ""))
    report_year, _ = _extract_report_year_month(report_name)
    if report_year:
        return report_year
    receipt_date = re.sub(r"\D", "", str(report_row.get("rcept_dt", "")))
    if len(receipt_date) >= 4:
        return int(receipt_date[:4])
    raise ValueError(f"사업연도를 추출할 수 없습니다: {report_name}")


def extract_financial_data(dart, stock_code: str, report_row) -> Dict[str, Any]:
    business_year = _business_year_for_row(report_row)
    report_code = _report_code_for_row(report_row)
    report_kind = str(report_row.get("report_kind") or "")
    _, period_month = _extract_report_year_month(str(report_row.get("report_nm", "")))
    fin_df = dart.finstate(stock_code, str(business_year), reprt_code=report_code)
    if fin_df is None or getattr(fin_df, "empty", True):
        raise ValueError(f"재무제표가 비어 있습니다: year={business_year}, reprt_code={report_code}")

    financial_data = {
        "business_year": business_year,
        "report_code": report_code,
        "report_kind": report_kind,
        "period_month": period_month,
        "revenue": _pick_financial_value(fin_df, FINANCIAL_ALIASES["revenue"]),
        "operating_profit": _pick_financial_value(fin_df, FINANCIAL_ALIASES["operating_profit"]),
        "net_income": _pick_financial_value(fin_df, FINANCIAL_ALIASES["net_income"]),
        "currency": "KRW",
    }
    if all(financial_data[key] is None for key in ("revenue", "operating_profit", "net_income")):
        raise ValueError(f"주요 재무값을 파싱하지 못했습니다: year={business_year}, reprt_code={report_code}")
    return financial_data


def _make_structured_financial_chunk_text(structured_data: Dict[str, Any]) -> str:
    return "\n".join(
        [
            make_structured_financial_text(structured_data),
            f"보고서종류: {structured_data.get('report_kind') or '정보 없음'}",
            f"보고서코드: {structured_data.get('report_code') or '정보 없음'}",
            f"대상월: {structured_data.get('period_month') or '정보 없음'}",
        ]
    )


def build_regular_chunk_records(
    structured_data: Dict[str, Any],
    business_chunks: List[str],
    include_structured: bool = True,
) -> List[Dict[str, Any]]:
    stock_code = structured_data.get("company_code") or structured_data.get("stock_code") or ""
    receipt_no = structured_data.get("receipt_no") or ""
    base_metadata = {
        "stock_code": stock_code,
        "company_code": stock_code,
        "company_name": structured_data.get("company_name", ""),
        "report_name": structured_data.get("report_name", ""),
        "receipt_no": receipt_no,
        "receipt_date": structured_data.get("receipt_date", ""),
        "report_kind": structured_data.get("report_kind", ""),
        "report_code": structured_data.get("report_code", ""),
        "business_year": structured_data.get("business_year", ""),
        "period_month": structured_data.get("period_month", ""),
        "source_type": "DART",
        "risk_type": "",
    }

    records: List[Dict[str, Any]] = []
    if include_structured:
        structured_metadata = {
            **base_metadata,
            "index_type": REGULAR_INDEX,
            "data_type": "structured_financials",
            "section": "정형 재무 요약",
            "chunk_index": 0,
            "chunk_total": 1,
        }
        records.append(
            {
                "receipt_no": receipt_no,
                "data_type": "structured_financials",
                "section": "정형 재무 요약",
                "chunk_index": 0,
                "chunk_total": 1,
                "content": _make_structured_financial_chunk_text(structured_data),
                "metadata": structured_metadata,
            }
        )

    chunk_total = len(business_chunks)
    for index, chunk in enumerate(business_chunks, start=1):
        business_metadata = {
            **base_metadata,
            "index_type": REGULAR_INDEX,
            "data_type": "business_text",
            "section": "II. 사업의 내용",
            "chunk_index": index,
            "chunk_total": chunk_total,
        }
        business_content = make_business_chunk_text(
            chunk=chunk,
            structured_data=structured_data,
            chunk_index=index,
            chunk_total=chunk_total,
        )
        records.append(
            {
                "receipt_no": receipt_no,
                "data_type": "business_text",
                "section": "II. 사업의 내용",
                "chunk_index": index,
                "chunk_total": chunk_total,
                "content": business_content,
                "metadata": business_metadata,
            }
        )

        if _is_risk_related(chunk):
            risk_metadata = {
                **business_metadata,
                "data_type": "risk_text",
                "section": "II. 사업의 내용 - 위험 관련 문단",
                "risk_type": _detect_risk_type(chunk),
            }
            records.append(
                {
                    "receipt_no": receipt_no,
                    "data_type": "risk_text",
                    "section": "II. 사업의 내용 - 위험 관련 문단",
                    "chunk_index": index,
                    "chunk_total": chunk_total,
                    "content": business_content.replace("[비정형 사업 내용]", "[비정형 리스크 내용]", 1),
                    "metadata": risk_metadata,
                }
            )
    return records


def documents_from_chunk_records(records: List[Dict[str, Any]]) -> List[Document]:
    return [Document(page_content=record["content"], metadata=record.get("metadata") or {}) for record in records]
