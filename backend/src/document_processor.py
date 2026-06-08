from __future__ import annotations

import html
import logging
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Union

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

CHILD_CHUNK_SIZE = 1400
CHILD_CHUNK_OVERLAP = 160
TABLE_TEXT_LIMIT = 6000
BUSINESS_SECTION_MIN_BLOCKS = 3
BUSINESS_SECTION_MIN_CHARS = 700

BUSINESS_START_RE = re.compile(
    r"^(?:(?:II|Ⅱ)\s*\.?|2\s*\.?|제\s*2\s*부\s*)\s*사업의\s*내용$",
    re.IGNORECASE,
)
BUSINESS_FALLBACK_RE = re.compile(r"^(?:\d+\s*[.)]?\s*)?(?:사업의\s*내용|사업의\s*개요)$")
FINANCIAL_START_RE = re.compile(
    r"^(?:(?:III|Ⅲ)\s*\.?|3\s*\.?|제\s*3\s*부\s*)\s*재무에\s*관한\s*사항$",
    re.IGNORECASE,
)
MAJOR_HEADING_RE = re.compile(r"^(?:(?:[IVXⅠⅡⅢⅣⅤ]+|\d+)\s*\.|제\s*\d+\s*부)")
SUB_HEADING_RE = re.compile(r"^(?:\d{1,2}\s*[.)]|[가-하]\s*[.)]|\(\d{1,2}\)|\([가-하]\))\s*")
HEADING_KEYWORDS = [
    "사업의 개요",
    "주요 제품",
    "주요 서비스",
    "원재료",
    "생산",
    "매출",
    "수주",
    "위험",
    "리스크",
    "연구개발",
    "설비",
    "투자",
]
RISK_SECTION_KEYWORDS = ["위험", "리스크", "우발", "소송", "제재", "분쟁"]
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
    "소송", "제재", "영업정지", "우발부채", "채무불이행", "손상차손",
    "유동성위험", "신용위험", "시장위험", "환율위험", "이자율위험", "안전사고",
]
MEDIUM_SIGNAL_RISK_KEYWORDS = [
    "법률분쟁", "분쟁", "차입금", "채무상환", "공급망위험", "경쟁심화",
    "영업환경악화", "외환위험", "가격위험", "중대재해", "품질사고",
    "평판위험", "브랜드훼손", "신뢰하락", "유동성부족", "신용등급하락",
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
FALLBACK_CHUNK_SIZE = 2500
FALLBACK_CHUNK_OVERLAP = 300


@dataclass
class ParsedBlock:
    block_type: str
    text: str
    markdown: str = ""
    level: int = 0
    order: int = 0
    row_count: int = 0
    col_count: int = 0


@dataclass
class ParsedSection:
    title: str
    path: List[str]
    blocks: List[ParsedBlock] = field(default_factory=list)
    start_order: int = 0
    end_order: int = 0


@dataclass
class ParsedFiling:
    blocks: List[ParsedBlock]
    clean_text: str


@dataclass
class BusinessChunk:
    content: str
    data_type: str = "business_text"
    section: str = "II. 사업의 내용"
    section_path: List[str] = field(default_factory=list)
    section_title: str = ""
    section_level: int = 0
    chunk_strategy: str = "xml_section"
    block_types: List[str] = field(default_factory=list)
    extra_metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_space(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text.replace("\xa0", " "))
    return text.strip()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _parse_positive_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(str(value or default).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _markdown_cell(value: str) -> str:
    return _normalize_space(value).replace("|", " / ")


def _table_to_block(table, order: int) -> Optional[ParsedBlock]:
    rows = table.find_all(re.compile(r"^tr$", re.I))
    if not rows:
        return None

    matrix: dict[tuple[int, int], str] = {}
    max_col = 0
    row_count = 0
    for row_idx, row in enumerate(rows):
        col_idx = 0
        cells = row.find_all(re.compile(r"^(th|td)$", re.I))
        if not cells:
            continue
        row_count += 1
        for cell in cells:
            while matrix.get((row_idx, col_idx)) is not None:
                col_idx += 1
            cell_text = _normalize_space(cell.get_text(" ", strip=True))
            colspan = _parse_positive_int(cell.get("colspan"))
            rowspan = _parse_positive_int(cell.get("rowspan"))
            for r_offset in range(rowspan):
                for c_offset in range(colspan):
                    matrix[(row_idx + r_offset, col_idx + c_offset)] = cell_text
            col_idx += colspan
        max_col = max(max_col, col_idx)

    if not matrix or max_col == 0:
        return None

    lines: List[str] = []
    plain_lines: List[str] = []
    header_written = False
    for row_idx in range(len(rows)):
        values = [matrix.get((row_idx, col_idx), "") for col_idx in range(max_col)]
        if not any(value.strip() for value in values):
            continue
        plain_lines.append(" ".join(value for value in values if value.strip()))
        lines.append("| " + " | ".join(_markdown_cell(value) for value in values) + " |")
        if not header_written:
            lines.append("|" + "|".join(["---"] * len(values)) + "|")
            header_written = True

    markdown = "\n".join(lines).strip()
    text = "\n".join(plain_lines).strip()
    if len(markdown) > TABLE_TEXT_LIMIT:
        markdown = text[:TABLE_TEXT_LIMIT].strip() + "\n[대형 표 일부 생략]"
    return ParsedBlock(
        block_type="table",
        text=text,
        markdown=markdown,
        order=order,
        row_count=row_count,
        col_count=max_col,
    )


def _looks_like_heading(text: str) -> bool:
    normalized = _normalize_space(text)
    if not normalized or len(normalized) > 90:
        return False
    if BUSINESS_START_RE.match(normalized) or BUSINESS_FALLBACK_RE.match(normalized):
        return True
    if FINANCIAL_START_RE.match(normalized):
        return True
    if MAJOR_HEADING_RE.match(normalized) or SUB_HEADING_RE.match(normalized):
        return True
    return any(keyword in normalized for keyword in HEADING_KEYWORDS)


def _heading_level(text: str) -> int:
    normalized = _normalize_space(text)
    if MAJOR_HEADING_RE.match(normalized):
        return 1
    if re.match(r"^\d{1,2}\s*[.)]", normalized):
        return 2
    if re.match(r"^[가-하]\s*[.)]", normalized):
        return 3
    if re.match(r"^\(\d{1,2}\)", normalized):
        return 4
    if re.match(r"^\([가-하]\)", normalized):
        return 5
    return 2


def parse_filing_document(raw_document: str) -> ParsedFiling:
    text = html.unescape(raw_document or "")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, "lxml")

    blocks: List[ParsedBlock] = []
    order = 0
    consumed_tables: set[int] = set()
    block_tags = re.compile(r"^(title|h1|h2|h3|h4|h5|h6|p|div|li|section|table)$", re.I)

    for tag in soup.find_all(block_tags):
        if tag.find_parent(re.compile(r"^table$", re.I)) and tag.name.lower() != "table":
            continue

        if tag.name.lower() == "table":
            table_id = id(tag)
            if table_id in consumed_tables:
                continue
            consumed_tables.add(table_id)
            block = _table_to_block(tag, order)
            if block:
                blocks.append(block)
                order += 1
            continue

        direct_text_parts = [
            text_node.strip()
            for text_node in tag.find_all(string=True, recursive=False)
            if text_node and text_node.strip()
        ]
        if not direct_text_parts and tag.find(block_tags):
            continue

        tag_text = _normalize_space(" ".join(direct_text_parts) or tag.get_text(" ", strip=True))
        if not tag_text:
            continue
        if len(tag_text) > 12000:
            continue

        block_type = "heading" if _looks_like_heading(tag_text) else "paragraph"
        blocks.append(
            ParsedBlock(
                block_type=block_type,
                text=tag_text,
                level=_heading_level(tag_text) if block_type == "heading" else 0,
                order=order,
            )
        )
        order += 1

    clean_text = "\n\n".join(
        block.markdown if block.block_type == "table" and block.markdown else block.text
        for block in blocks
        if block.text or block.markdown
    ).strip()
    logger.info("DART 원문 구조 파싱 완료: blocks=%s tables=%s", len(blocks), sum(1 for block in blocks if block.block_type == "table"))
    return ParsedFiling(blocks=blocks, clean_text=clean_text)


def _is_business_start(text: str) -> bool:
    normalized = _normalize_space(text)
    return bool(BUSINESS_START_RE.match(normalized) or BUSINESS_FALLBACK_RE.match(normalized))


def _is_financial_start(text: str) -> bool:
    return bool(FINANCIAL_START_RE.match(_normalize_space(text)))


def extract_business_sections(parsed: ParsedFiling) -> List[ParsedSection]:
    blocks = parsed.blocks or []
    if not blocks:
        return []

    start_index = next((idx for idx, block in enumerate(blocks) if block.block_type == "heading" and _is_business_start(block.text)), None)
    if start_index is None:
        return []

    end_index = len(blocks)
    for idx in range(start_index + 1, len(blocks)):
        block = blocks[idx]
        if block.block_type == "heading" and _is_financial_start(block.text):
            end_index = idx
            break

    business_blocks = blocks[start_index:end_index]
    business_chars = sum(len(block.text or block.markdown) for block in business_blocks)
    if len(business_blocks) < BUSINESS_SECTION_MIN_BLOCKS or business_chars < BUSINESS_SECTION_MIN_CHARS:
        return []

    sections: List[ParsedSection] = []
    current: Optional[ParsedSection] = None
    heading_stack: List[tuple[int, str]] = []

    for block in business_blocks:
        if block.block_type == "heading":
            while heading_stack and heading_stack[-1][0] >= block.level:
                heading_stack.pop()
            heading_stack.append((block.level, block.text))
            if current and current.blocks:
                current.end_order = block.order - 1
                sections.append(current)
            current = ParsedSection(
                title=block.text,
                path=[title for _, title in heading_stack],
                blocks=[],
                start_order=block.order,
                end_order=block.order,
            )
            continue

        if current is None:
            current = ParsedSection(
                title="II. 사업의 내용",
                path=["II. 사업의 내용"],
                blocks=[],
                start_order=block.order,
                end_order=block.order,
            )
        current.blocks.append(block)
        current.end_order = block.order

    if current and current.blocks:
        sections.append(current)

    return [section for section in sections if section.blocks]


def _split_text(text: str, chunk_size: int = CHILD_CHUNK_SIZE, chunk_overlap: int = CHILD_CHUNK_OVERLAP) -> List[str]:
    if not text:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def _is_risk_section(section: ParsedSection) -> bool:
    compact_path = _compact(" ".join(section.path))
    return any(keyword in compact_path for keyword in RISK_SECTION_KEYWORDS)


def chunk_business_sections(sections: Iterable[ParsedSection]) -> List[BusinessChunk]:
    chunks: List[BusinessChunk] = []
    for section in sections:
        paragraph_parts: List[str] = []
        paragraph_block_types: set[str] = set()
        table_index = 0

        for block in section.blocks:
            if block.block_type == "table":
                if paragraph_parts:
                    section_text = "\n\n".join(paragraph_parts).strip()
                    for part in _split_text(section_text):
                        chunks.append(
                            BusinessChunk(
                                content=part,
                                data_type="risk_text" if _is_risk_section(section) else "business_text",
                                section=section.title,
                                section_path=section.path,
                                section_title=section.title,
                                section_level=len(section.path),
                                block_types=sorted(paragraph_block_types or {"paragraph"}),
                                extra_metadata={"source_block_start": section.start_order, "source_block_end": section.end_order},
                            )
                        )
                    paragraph_parts = []
                    paragraph_block_types = set()

                table_index += 1
                table_text = block.markdown or block.text
                if table_text:
                    chunks.append(
                        BusinessChunk(
                            content=table_text,
                            data_type="table_text",
                            section=section.title,
                            section_path=section.path,
                            section_title=section.title,
                            section_level=len(section.path),
                            block_types=["table"],
                            extra_metadata={
                                "table_index": table_index,
                                "row_count": block.row_count,
                                "col_count": block.col_count,
                                "source_block_start": block.order,
                                "source_block_end": block.order,
                            },
                        )
                    )
                continue

            if block.text:
                paragraph_parts.append(block.text)
                paragraph_block_types.add(block.block_type or "paragraph")

        if paragraph_parts:
            section_text = "\n\n".join(paragraph_parts).strip()
            for part in _split_text(section_text):
                chunks.append(
                    BusinessChunk(
                        content=part,
                        data_type="risk_text" if _is_risk_section(section) else "business_text",
                        section=section.title,
                        section_path=section.path,
                        section_title=section.title,
                        section_level=len(section.path),
                        block_types=sorted(paragraph_block_types or {"paragraph"}),
                        extra_metadata={"source_block_start": section.start_order, "source_block_end": section.end_order},
                    )
                )

    return [chunk for chunk in chunks if chunk.content.strip()]


def clean_document(raw_document: str) -> str:
    try:
        return parse_filing_document(raw_document).clean_text
    except Exception:
        text = html.unescape(raw_document or "")
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
            soup = BeautifulSoup(text, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for tag in soup.find_all(re.compile(r"^(p|div|br|h1|h2|h3|h4|h5|h6|li|title)$", re.I)):
            if tag.name.lower() == "br":
                tag.replace_with("\n")
            else:
                tag.insert_before("\n\n")
                tag.insert_after("\n\n")
        text = soup.get_text(" ")
        text = re.sub(r"\t+", " ", text)
        text = re.sub(r"[ \u00a0]{2,}", " ", text)
        text = re.sub(r"\S+\.(?:jpg|jpeg|png|gif|bmp|svg)", "", text, flags=re.I)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def extract_business_section(clean_text: str) -> str:
    lines = clean_text.splitlines()
    start = next((idx for idx, line in enumerate(lines) if _is_business_start(line)), None)
    if start is None:
        start = next((idx for idx, line in enumerate(lines) if BUSINESS_FALLBACK_RE.match(_normalize_space(line))), None)
    if start is None:
        return ""
    end = next((idx for idx in range(start + 1, len(lines)) if _is_financial_start(lines[idx])), len(lines))
    return "\n".join(lines[start:end]).strip()


def chunk_business_text(business_text: str) -> List[str]:
    return _split_text(business_text, chunk_size=FALLBACK_CHUNK_SIZE, chunk_overlap=FALLBACK_CHUNK_OVERLAP)


def _parse_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "nan", "NaN", "None"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.-]", "", text)
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        number = int(float(cleaned))
    except ValueError:
        return None
    return -abs(number) if negative else number


def _pick_financial_value(fin_df, aliases: Iterable[str]) -> Optional[int]:
    if fin_df is None or getattr(fin_df, "empty", True) or "account_nm" not in fin_df.columns:
        return None

    df = fin_df.copy()
    df["account_nm"] = df["account_nm"].astype(str).str.replace(r"\s+", "", regex=True)
    if "fs_div" in df.columns:
        cfs = df[df["fs_div"].astype(str).eq("CFS")]
        if not cfs.empty:
            df = cfs
    if "sj_div" in df.columns:
        preferred = df[df["sj_div"].astype(str).isin(["IS", "CIS"])]
        if not preferred.empty:
            df = preferred

    amount_columns = ["thstrm_amount", "thstrm_add_amount", "frmtrm_amount", "frmtrm_add_amount"]
    available_amount_columns = [column for column in amount_columns if column in df.columns]
    if not available_amount_columns:
        return None

    normalized_aliases = [re.sub(r"\s+", "", alias) for alias in aliases]
    for alias in normalized_aliases:
        exact = df[df["account_nm"].eq(alias)]
        contains = df[df["account_nm"].str.contains(re.escape(alias), na=False)]
        candidates = exact if not exact.empty else contains
        if candidates.empty:
            continue
        for _, row in candidates.iterrows():
            for column in available_amount_columns:
                parsed = _parse_number(row.get(column))
                if parsed is not None:
                    return parsed
    return None


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


def _format_krw(value: Optional[int]) -> str:
    if value is None:
        return "정보 없음"
    return f"{value:,}원"


def _safe_str(value: Any, fallback: str = "정보 없음") -> str:
    if value is None:
        return fallback
    return str(value)


def make_structured_financial_text(structured_data: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "[정형 재무 요약]",
            f"기업코드: {_safe_str(structured_data.get('company_code'))}",
            f"회사명: {_safe_str(structured_data.get('company_name'))}",
            f"보고서: {_safe_str(structured_data.get('report_name'))}",
            f"접수번호: {_safe_str(structured_data.get('receipt_no'))}",
            f"접수일자: {_safe_str(structured_data.get('receipt_date'))}",
            f"사업연도: {_safe_str(structured_data.get('business_year'))}",
            f"매출액: {_format_krw(structured_data.get('revenue'))}",
            f"영업이익: {_format_krw(structured_data.get('operating_profit'))}",
            f"당기순이익: {_format_krw(structured_data.get('net_income'))}",
            "위 숫자는 DART 사업보고서 재무제표 API에서 추출한 값입니다.",
        ]
    )


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


def _make_structured_financial_chunk_text(structured_data: Dict[str, Any]) -> str:
    return "\n".join(
        [
            make_structured_financial_text(structured_data),
            f"보고서종류: {structured_data.get('report_kind') or '정보 없음'}",
            f"보고서코드: {structured_data.get('report_code') or '정보 없음'}",
            f"대상월: {structured_data.get('period_month') or '정보 없음'}",
        ]
    )


def _make_regular_chunk_text(
    chunk: str,
    structured_data: Dict[str, Any],
    chunk_index: int,
    chunk_total: int,
    section: str,
    label: str,
) -> str:
    return "\n".join(
        [
            label,
            f"기업코드: {structured_data.get('company_code')}",
            f"회사명: {structured_data.get('company_name')}",
            f"보고서: {structured_data.get('report_name')}",
            f"접수번호: {structured_data.get('receipt_no')}",
            f"섹션: {section}",
            f"청크: {chunk_index}/{chunk_total}",
            "",
            chunk.strip(),
        ]
    )


def build_regular_chunk_records(
    structured_data: Dict[str, Any],
    business_chunks: List[Union[str, BusinessChunk]],
    include_structured: bool = True,
) -> List[Dict[str, Any]]:
    from .config import REGULAR_INDEX

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
    for index, chunk_item in enumerate(business_chunks, start=1):
        if isinstance(chunk_item, BusinessChunk):
            chunk = chunk_item.content
            data_type = chunk_item.data_type or "business_text"
            section = chunk_item.section or chunk_item.section_title or "II. 사업의 내용"
            section_path = chunk_item.section_path or [section]
            chunk_strategy = chunk_item.chunk_strategy or "xml_section"
            block_types = chunk_item.block_types or []
            extra_metadata = dict(chunk_item.extra_metadata or {})
        else:
            chunk = str(chunk_item or "")
            data_type = "business_text"
            section = "II. 사업의 내용"
            section_path = [section]
            chunk_strategy = "recursive_text"
            block_types = ["text"]
            extra_metadata = {}

        if not chunk.strip():
            continue

        label = "[비정형 사업 내용]"
        if data_type == "risk_text":
            label = "[비정형 리스크 내용]"
        elif data_type == "table_text":
            label = "[비정형 표 내용]"

        business_metadata = {
            **base_metadata,
            "index_type": REGULAR_INDEX,
            "data_type": data_type,
            "section": section,
            "section_path": section_path,
            "section_title": section_path[-1] if section_path else section,
            "section_level": len(section_path),
            "chunk_strategy": chunk_strategy,
            "block_types": block_types,
            "chunk_index": index,
            "chunk_total": chunk_total,
            **extra_metadata,
        }
        business_content = _make_regular_chunk_text(
            chunk=chunk,
            structured_data=structured_data,
            chunk_index=index,
            chunk_total=chunk_total,
            section=section,
            label=label,
        )
        records.append(
            {
                "receipt_no": receipt_no,
                "data_type": data_type,
                "section": section,
                "chunk_index": index,
                "chunk_total": chunk_total,
                "content": business_content,
                "metadata": business_metadata,
            }
        )

        if data_type == "business_text" and _is_risk_related(chunk):
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
