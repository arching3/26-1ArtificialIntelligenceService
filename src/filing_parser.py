from __future__ import annotations

import html
import logging
import re
import warnings
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional

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
