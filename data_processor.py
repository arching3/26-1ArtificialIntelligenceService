import html
import json
import logging
import os
import re
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from dotenv import load_dotenv
from opendartreader import OpenDartReader
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter


load_dotenv()

REPORT_CODE_ANNUAL = "11011"
DEFAULT_SLEEP_SECONDS = 0.4
MAX_LOOKBACK_YEARS = 7
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 300
LARGE_TABLE_MAX_COLS = 30
LARGE_TABLE_MAX_ROWS = 500
LARGE_TABLE_MAX_AREA = 20000
SUSPICIOUS_BUSINESS_TEXT_CHARS = 1_000_000
SUSPICIOUS_CHUNK_COUNT = 1000
SUSPICIOUS_PIPE_RATIO = 0.08
BUSINESS_SECTION_MIN_CHARS = 1000
BUSINESS_SECTION_START_PATTERN = (
    r"(?m)^[ \t\u00a0]*(?:(?:II|Ⅱ)[ \t\u00a0]*\.?|2[ \t\u00a0]*\.|"
    r"제[ \t\u00a0]*2[ \t\u00a0]*부)[ \t\u00a0]*사업의[ \t\u00a0]*내용[ \t\u00a0]*$"
)
FINANCIAL_SECTION_START_PATTERN = (
    r"(?m)^[ \t\u00a0]*(?:(?:III|Ⅲ)[ \t\u00a0]*\.?|3[ \t\u00a0]*\.|"
    r"제[ \t\u00a0]*3[ \t\u00a0]*부)[ \t\u00a0]*재무에[ \t\u00a0]*관한[ \t\u00a0]*사항[ \t\u00a0]*$"
)
BUSINESS_FALLBACK_START_PATTERN = (
    r"(?m)^[ \t\u00a0]*(?:(?:1|가)[ \t\u00a0]*[.)]?[ \t\u00a0]*)?"
    r"(?:사업의[ \t\u00a0]*내용|사업의[ \t\u00a0]*개요)[ \t\u00a0]*$"
)
FINANCIAL_FALLBACK_START_PATTERN = (
    r"(?m)^[ \t\u00a0]*(?:재무에[ \t\u00a0]*관한[ \t\u00a0]*사항)[ \t\u00a0]*$"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


class DartProcessingError(Exception):
    """Raised when one company cannot be processed but the batch should continue."""


@dataclass
class CompanyResult:
    company_code: str
    status: str
    structured_data: Dict[str, Any] = field(default_factory=dict)
    business_text: Optional[str] = None
    chunks: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def format_krw(value: Optional[int]) -> str:
    if value is None:
        return "정보 없음"
    return f"{value:,}원"


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        raise DartProcessingError(f"{name} 환경변수가 설정되어 있지 않습니다.")
    return value


def _normalize_company_code(company_code: Any) -> str:
    code = str(company_code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise DartProcessingError(f"유효하지 않은 기업/종목 코드입니다: {company_code!r}")
    return code


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type(
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
            TimeoutError,
            ConnectionError,
        )
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _retryable_call(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return func(*args, **kwargs)


def _safe_call(func: Callable[..., Any], *args: Any, default: Any = None, **kwargs: Any) -> Any:
    try:
        return _retryable_call(func, *args, **kwargs)
    except json.JSONDecodeError:
        logger.exception("JSON 파싱 오류: %s", getattr(func, "__name__", repr(func)))
        return default
    except (requests.exceptions.RequestException, TimeoutError, ConnectionError):
        logger.exception("네트워크/API 호출 오류: %s", getattr(func, "__name__", repr(func)))
        return default
    except ValueError as exc:
        logger.warning("API 값 오류: %s - %s", getattr(func, "__name__", repr(func)), exc)
        return default


def _find_latest_annual_report(dart: OpenDartReader, company_code: str) -> pd.Series:
    today = datetime.today()
    start = f"{today.year - MAX_LOOKBACK_YEARS}-01-01"
    end = today.strftime("%Y-%m-%d")
    logger.info("[%s] 정기공시 목록 조회: %s ~ %s", company_code, start, end)

    reports = _safe_call(
        dart.list,
        company_code,
        start=start,
        end=end,
        kind="A",
        final=False,
        default=None,
    )
    if reports is None or getattr(reports, "empty", True):
        raise DartProcessingError("정기공시 목록이 없거나 조회에 실패했습니다.")

    required_columns = {"report_nm", "rcept_dt", "rcept_no"}
    missing_columns = required_columns - set(reports.columns)
    if missing_columns:
        raise DartProcessingError(f"DART 공시 목록 컬럼 누락: {sorted(missing_columns)}")

    annual_reports = reports[reports["report_nm"].astype(str).str.contains("사업보고서", na=False)].copy()
    if annual_reports.empty:
        raise DartProcessingError("최근 사업보고서를 찾을 수 없습니다.")

    annual_reports = annual_reports.sort_values("rcept_dt", ascending=False)
    latest = annual_reports.iloc[0]
    logger.info("[%s] 최신 사업보고서 선택: %s / %s", company_code, latest["report_nm"], latest["rcept_no"])
    return latest


def _candidate_business_years(report: pd.Series) -> List[str]:
    years: List[int] = []

    report_name = str(report.get("report_nm", ""))
    years.extend(int(match) for match in re.findall(r"(20\d{2})", report_name))

    receipt_date = re.sub(r"\D", "", str(report.get("rcept_dt", "")))
    if len(receipt_date) >= 4:
        receipt_year = int(receipt_date[:4])
        years.extend([receipt_year - 1, receipt_year, receipt_year - 2])

    current_year = datetime.today().year
    years.extend(range(current_year - 1, current_year - MAX_LOOKBACK_YEARS - 1, -1))

    deduped: List[str] = []
    for year in years:
        if 1990 <= year <= current_year and str(year) not in deduped:
            deduped.append(str(year))
    return deduped


def _parse_number(value: Any) -> Optional[int]:
    if value is None or pd.isna(value):
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


def _pick_financial_value(fin_df: pd.DataFrame, aliases: Iterable[str]) -> Optional[int]:
    if fin_df is None or fin_df.empty or "account_nm" not in fin_df.columns:
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

    amount_columns = [
        "thstrm_amount",
        "thstrm_add_amount",
        "frmtrm_amount",
        "frmtrm_add_amount",
    ]
    available_amount_columns = [col for col in amount_columns if col in df.columns]
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


def _extract_financial_data(
    dart: OpenDartReader,
    company_code: str,
    candidate_years: Iterable[str],
) -> Dict[str, Any]:
    aliases = {
        "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
        "operating_profit": ["영업이익", "영업이익(손실)"],
        "net_income": ["당기순이익", "당기순이익(손실)", "분기순이익", "연결당기순이익"],
    }

    last_error = None
    for year in candidate_years:
        logger.info("[%s] 재무제표 조회: 사업연도=%s", company_code, year)
        try:
            fin_df = _safe_call(
                dart.finstate,
                company_code,
                year,
                reprt_code=REPORT_CODE_ANNUAL,
                default=None,
            )
            if fin_df is None or getattr(fin_df, "empty", True):
                logger.warning("[%s] %s년 재무제표가 비어 있습니다.", company_code, year)
                continue

            return {
                "business_year": int(year),
                "revenue": _pick_financial_value(fin_df, aliases["revenue"]),
                "operating_profit": _pick_financial_value(fin_df, aliases["operating_profit"]),
                "net_income": _pick_financial_value(fin_df, aliases["net_income"]),
                "currency": "KRW",
            }
        except Exception as exc:
            last_error = exc
            logger.warning("[%s] %s년 재무제표 파싱 실패: %s", company_code, year, exc)

    logger.warning("[%s] 사용 가능한 재무제표를 찾지 못했습니다.", company_code)
    if last_error:
        logger.debug("[%s] 마지막 재무제표 오류: %s", company_code, last_error)
    return {
        "business_year": None,
        "revenue": None,
        "operating_profit": None,
        "net_income": None,
        "currency": "KRW",
    }


def _clean_cell_text(cell) -> str:
    text = cell.get_text(" ", strip=True)
    text = re.sub(r"[\r\n\t]+", " ", text)
    return re.sub(r"[ \u00a0]{2,}", " ", text).strip()


def _markdown_cell(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.replace("|", " / ")


def _parse_positive_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(str(value or default).strip())
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _looks_like_annotation_table(matrix: Dict[tuple, str], row_count: int, max_col: int) -> bool:
    if max_col == 1:
        return True

    non_empty_rows = []
    for r in range(row_count):
        vals = [matrix.get((r, c), "").strip() for c in range(max_col)]
        combined = " ".join(v for v in vals if v)
        if combined:
            non_empty_rows.append(combined)

    if len(non_empty_rows) > 2:
        return False

    compact = " ".join(non_empty_rows)
    annotation_markers = [
        "단위",
        "※",
        "주)",
        "주:",
        "△",
        "부(-)",
        "기준",
        "상기",
        "해당사항",
    ]
    return any(marker in compact for marker in annotation_markers)


def _is_large_table(row_count: int, max_col: int, cell_count: int) -> bool:
    if row_count > LARGE_TABLE_MAX_ROWS:
        return True
    if max_col > LARGE_TABLE_MAX_COLS:
        return True
    if row_count * max_col > LARGE_TABLE_MAX_AREA:
        return True
    return False


def _flatten_table_rows(row_values: List[List[str]], max_rows: int = 2000) -> str:
    lines = []
    for values in row_values[:max_rows]:
        cleaned = [value for value in values if value]
        if cleaned:
            lines.append(" ".join(cleaned))

    remaining = len(row_values) - max_rows
    if remaining > 0:
        lines.append(f"[대형 표 일부 생략: {remaining}개 행]")

    return "\n".join(lines)


def _trim_empty_edges(values: List[str]) -> List[str]:
    start = 0
    end = len(values)
    while start < end and not values[start]:
        start += 1
    while end > start and not values[end - 1]:
        end -= 1
    return values[start:end]


def _clean_text(raw_document: str) -> str:
    text = html.unescape(raw_document or "")
    text = re.sub(r"&#x?[0-9A-Fa-f]+;?", " ", text)
    text = re.sub(r"\\x[0-9A-Fa-f]{2}", " ", text)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(text, "lxml")
        
    for table in soup.find_all(re.compile(r"^table$", re.I)):
        rows = table.find_all(re.compile(r"^tr$", re.I))
        if not rows:
            continue
            
        matrix = {}
        max_col = 0
        cell_count = 0
        row_values: List[List[str]] = []
        
        for row_idx, row in enumerate(rows):
            col_idx = 0
            cells = row.find_all(re.compile(r"^(th|td)$", re.I))
            plain_values: List[str] = []
            cell_count += len(cells)
            
            for cell in cells:
                while matrix.get((row_idx, col_idx)) is not None:
                    col_idx += 1
                    
                colspan = _parse_positive_int(cell.get("colspan"), default=1)
                rowspan = _parse_positive_int(cell.get("rowspan"), default=1)
                    
                cell_text = _clean_cell_text(cell)
                if cell_text:
                    plain_values.append(cell_text)
                
                for r in range(rowspan):
                    for c in range(colspan):
                        matrix[(row_idx + r, col_idx + c)] = cell_text
                        
                col_idx += colspan
            max_col = max(max_col, col_idx)
            row_values.append(plain_values)

        if max_col == 0:
            continue

        if _is_large_table(len(rows), max_col, cell_count):
            logger.info(
                "대형 표를 행 단위 텍스트로 변환합니다: rows=%s, cols=%s, cells=%s",
                len(rows),
                max_col,
                cell_count,
            )
            flattened = _flatten_table_rows(row_values)
            table.replace_with("\n" + flattened + "\n")
            continue

        # Note/unit annotation tables are clearer as plain text.
        if _looks_like_annotation_table(matrix, len(rows), max_col):
            plain_parts = []
            for r in range(len(rows)):
                vals = [matrix.get((r, c), "").strip() for c in range(max_col)]
                combined = " ".join(v for v in vals if v)
                if combined:
                    plain_parts.append(combined)
            table.replace_with("\n" + "\n".join(plain_parts) + "\n")
            continue

        markdown_table = []
        header_written = False
        for r in range(len(rows)):
            row_data = []
            all_empty = True
            for c in range(max_col):
                val = matrix.get((r, c), "")
                if val:
                    all_empty = False
                row_data.append(val)
            # Skip entirely empty rows
            if all_empty:
                continue
            row_data = _trim_empty_edges(row_data)
            if not row_data:
                continue
            markdown_table.append("| " + " | ".join(_markdown_cell(val) for val in row_data) + " |")
            
            if not header_written:
                markdown_table.append("|" + "|".join(["---"] * len(row_data)) + "|")
                header_written = True
                
        table.replace_with("\n\n" + "\n".join(markdown_table) + "\n\n")

    for tag in soup.find_all(re.compile(r"^(p|div|br|h1|h2|h3|h4|h5|h6|li|title)$", re.I)):
        if tag.name.lower() == 'br':
            tag.replace_with('\n')
        else:
            tag.insert_before('\n\n')
            tag.insert_after('\n\n')

    text = soup.get_text(" ")

    text = re.sub(r"\t+", " ", text)
    text = re.sub(r"[ \u00a0]{2,}", " ", text)
    # Remove image file references (e.g. 연구개발조직도.jpg)
    text = re.sub(r"\S+\.(?:jpg|jpeg|png|gif|bmp|svg)", "", text, flags=re.I)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _find_section_candidates(
    text: str,
    start_pattern: str,
    end_patterns: Iterable[str],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    start_matches = list(re.finditer(start_pattern, text, flags=re.IGNORECASE))

    for start_match in start_matches:
        end_index = len(text)
        tail = text[start_match.end() :]
        for pattern in end_patterns:
            end_match = re.search(pattern, tail, flags=re.IGNORECASE)
            if end_match:
                end_index = min(end_index, start_match.end() + end_match.start())

        section = text[start_match.start() : end_index].strip()
        if section:
            candidates.append(
                {
                    "section": section,
                    "start": start_match.start(),
                    "end": end_index,
                    "length": len(section),
                }
            )

    return candidates


def _score_business_section(section: str) -> int:
    normalized = re.sub(r"\s+", "", section)
    score = len(section)

    if len(section) < BUSINESS_SECTION_MIN_CHARS:
        score -= BUSINESS_SECTION_MIN_CHARS - len(section)

    for marker in [
        "1.사업의개요",
        "주요제품및서비스",
        "매출및수주상황",
        "위험관리",
        "연구개발",
        "기타참고사항",
    ]:
        if marker in normalized:
            score += 500

    return score


def _select_best_business_section(candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return ""

    best = max(candidates, key=lambda item: _score_business_section(item["section"]))
    if len(candidates) > 1:
        logger.info(
            "사업 내용 heading 후보 %s개 중 길이 %s자 후보를 선택했습니다.",
            len(candidates),
            best["length"],
        )
    if best["length"] < BUSINESS_SECTION_MIN_CHARS:
        logger.warning("선택된 사업 내용 섹션이 짧습니다: %s자", best["length"])

    return best["section"]


def _extract_business_section(clean_text: str) -> str:
    section = _select_best_business_section(
        _find_section_candidates(
            clean_text,
            BUSINESS_SECTION_START_PATTERN,
            [FINANCIAL_SECTION_START_PATTERN],
        )
    )
    if section:
        return section

    logger.warning("엄격한 'II. 사업의 내용' 섹션을 찾지 못해 보조 fallback을 사용합니다.")
    return _select_best_business_section(
        _find_section_candidates(
            clean_text,
            BUSINESS_FALLBACK_START_PATTERN,
            [
                FINANCIAL_SECTION_START_PATTERN,
                FINANCIAL_FALLBACK_START_PATTERN,
            ],
        )
    )


def _chunk_text(text: str) -> List[str]:
    if not text:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, 
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n\n", "\n\n", "\n", ". ", " ", ""]
    )
    raw_chunks = splitter.split_text(text)
    return _repair_orphan_table_headers(raw_chunks)


def audit_business_text_quality(business_text: str, chunks: List[str]) -> Dict[str, Any]:
    text = business_text or ""
    chunk_list = chunks or []
    table_rows = sum(
        1
        for line in text.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    )
    header_separators = sum(
        1
        for line in text.splitlines()
        if re.match(r"^\|[-|]+\|$", line.strip())
    )
    orphan_table_chunks = []
    for index, chunk in enumerate(chunk_list, start=1):
        lines = chunk.splitlines()
        has_table_rows = any(
            line.strip().startswith("|") and line.strip().endswith("|")
            for line in lines
        )
        has_header_separator = any(
            re.match(r"^\|[-|]+\|$", line.strip())
            for line in lines
        )
        if has_table_rows and not has_header_separator:
            orphan_table_chunks.append(index)

    return {
        "business_text_chars": len(text),
        "chunk_count": len(chunk_list),
        "contains_financial_heading": bool(
            re.search(FINANCIAL_SECTION_START_PATTERN, text, flags=re.IGNORECASE)
        ),
        "contains_html_tag": bool(re.search(r"</?[a-zA-Z][^>]*>", text)),
        "contains_image_reference": bool(
            re.search(r"\S+\.(?:jpg|jpeg|png|gif|bmp|svg)", text, flags=re.IGNORECASE)
        ),
        "contains_triple_newline": "\n\n\n" in text,
        "table_rows": table_rows,
        "table_header_separators": header_separators,
        "orphan_table_chunk_count": len(orphan_table_chunks),
        "orphan_table_chunks": orphan_table_chunks[:20],
        "pipe_ratio": round(text.count("|") / max(len(text), 1), 6),
    }


def _log_business_text_quality(company_code: str, quality: Dict[str, Any]) -> None:
    logger.info("[%s] 비정형 품질 진단: %s", company_code, json.dumps(quality, ensure_ascii=False))

    warnings_to_log = []
    if quality["business_text_chars"] > SUSPICIOUS_BUSINESS_TEXT_CHARS:
        warnings_to_log.append(f"본문 길이 과다({quality['business_text_chars']}자)")
    if quality["chunk_count"] > SUSPICIOUS_CHUNK_COUNT:
        warnings_to_log.append(f"청크 수 과다({quality['chunk_count']}개)")
    if quality["pipe_ratio"] > SUSPICIOUS_PIPE_RATIO:
        warnings_to_log.append(f"파이프 문자 비율 과다({quality['pipe_ratio']})")
    if quality["contains_financial_heading"]:
        warnings_to_log.append("재무 섹션 heading 침범")
    if quality["contains_html_tag"]:
        warnings_to_log.append("HTML 태그 잔존")
    if quality["contains_image_reference"]:
        warnings_to_log.append("이미지 참조 잔존")
    if quality["orphan_table_chunk_count"]:
        warnings_to_log.append(f"고아 표 청크 {quality['orphan_table_chunk_count']}개")

    if warnings_to_log:
        logger.warning("[%s] 비정형 품질 경고: %s", company_code, ", ".join(warnings_to_log))


def _repair_orphan_table_headers(chunks: List[str]) -> List[str]:
    """If a chunk contains markdown table rows but no header separator (|---|),
    find the table's header from the preceding chunk and prepend it."""
    repaired = []
    for i, chunk in enumerate(chunks):
        lines = chunk.split("\n")
        has_table_rows = any(line.strip().startswith("|") and line.strip().endswith("|") for line in lines)
        has_header_sep = any(re.match(r"^\|[-|]+\|$", line.strip()) for line in lines)

        if has_table_rows and not has_header_sep and i > 0:
            # Extract the last table header from the previous chunk
            prev_lines = chunks[i - 1].split("\n")
            header_line = None
            sep_line = None
            for j, pline in enumerate(prev_lines):
                if re.match(r"^\|[-|]+\|$", pline.strip()):
                    sep_line = pline
                    if j > 0:
                        header_line = prev_lines[j - 1]

            if header_line and sep_line:
                chunk = header_line + "\n" + sep_line + "\n" + chunk

        repaired.append(chunk)
    return repaired


def _safe_str(value: Any, fallback: str = "정보 없음") -> str:
    """Convert a value to string, replacing None with a human-readable fallback."""
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
            f"매출액: {format_krw(structured_data.get('revenue'))}",
            f"영업이익: {format_krw(structured_data.get('operating_profit'))}",
            f"당기순이익: {format_krw(structured_data.get('net_income'))}",
            "위 숫자는 DART 사업보고서 재무제표 API에서 추출한 값입니다.",
        ]
    )


def make_business_chunk_text(
    chunk: str,
    structured_data: Dict[str, Any],
    chunk_index: int,
    chunk_total: int,
) -> str:
    return "\n".join(
        [
            "[비정형 사업 내용]",
            f"기업코드: {structured_data.get('company_code')}",
            f"회사명: {structured_data.get('company_name')}",
            f"보고서: {structured_data.get('report_name')}",
            f"접수번호: {structured_data.get('receipt_no')}",
            "섹션: II. 사업의 내용",
            f"청크: {chunk_index}/{chunk_total}",
            "",
            chunk.strip(),
        ]
    )


def process_company(dart: OpenDartReader, company_code: str, sleep_seconds: float = DEFAULT_SLEEP_SECONDS) -> CompanyResult:
    code = _normalize_company_code(company_code)
    logger.info("[%s] 처리 시작", code)

    latest_report = _find_latest_annual_report(dart, code)
    candidate_years = _candidate_business_years(latest_report)

    structured_data = _extract_financial_data(dart, code, candidate_years)
    structured_data.update(
        {
            "company_code": code,
            "company_name": str(latest_report.get("corp_name", latest_report.get("flr_nm", ""))),
            "report_name": str(latest_report.get("report_nm", "")),
            "receipt_no": str(latest_report.get("rcept_no", "")),
            "receipt_date": str(latest_report.get("rcept_dt", "")),
        }
    )

    time.sleep(sleep_seconds)
    raw_document = _safe_call(dart.document, latest_report["rcept_no"], default="")
    if not raw_document:
        raise DartProcessingError("사업보고서 원문 다운로드에 실패했습니다.")

    clean_text = _clean_text(raw_document)
    business_text = _extract_business_section(clean_text)
    chunks = _chunk_text(business_text)
    quality = audit_business_text_quality(business_text, chunks)
    _log_business_text_quality(code, quality)
    if not chunks:
        logger.warning("[%s] 사업 내용 chunk가 비어 있습니다.", code)

    logger.info("[%s] 처리 완료: chunks=%s", code, len(chunks))
    return CompanyResult(
        company_code=code,
        status="success",
        structured_data=structured_data,
        business_text=business_text,
        chunks=chunks,
        meta={
            "candidate_years": candidate_years,
            "chunk_size": CHUNK_SIZE,
            "chunk_overlap": CHUNK_OVERLAP,
            "business_text_quality": quality,
        },
    )


def process_batch_companies(
    company_list: Iterable[Any],
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> Dict[str, Any]:
    companies = list(company_list)
    dart = OpenDartReader(_get_required_env("DART_API_KEY"))
    results: Dict[str, Dict[str, Any]] = {}
    failed_list: List[Dict[str, str]] = []

    for raw_code in companies:
        code_for_log = str(raw_code)
        try:
            result = process_company(dart, raw_code, sleep_seconds=sleep_seconds)
            results[result.company_code] = asdict(result)
        except DartProcessingError as exc:
            logger.error("[%s] 기업 처리 실패: %s", code_for_log, exc)
            failed_list.append({"company_code": code_for_log, "reason": str(exc)})
            normalized = str(raw_code or "").strip()
            results[normalized or code_for_log] = asdict(
                CompanyResult(
                    company_code=normalized or code_for_log,
                    status="failed",
                    error=str(exc),
                )
            )
        except Exception as exc:
            logger.exception("[%s] 예상하지 못한 기업 처리 실패", code_for_log)
            failed_list.append({"company_code": code_for_log, "reason": str(exc)})
            normalized = str(raw_code or "").strip()
            results[normalized or code_for_log] = asdict(
                CompanyResult(
                    company_code=normalized or code_for_log,
                    status="failed",
                    error=str(exc),
                )
            )
        finally:
            time.sleep(sleep_seconds)

    return {
        "results": results,
        "failed_list": failed_list,
        "summary": {
            "requested": len(companies),
            "succeeded": sum(1 for item in results.values() if item["status"] == "success"),
            "failed": len(failed_list),
        },
    }


if __name__ == "__main__":
    dummy_companies = ["005930", "035420", "000000"]
    output = process_batch_companies(dummy_companies)

    print("\n=== Batch Summary ===")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print("\n=== Failed List ===")
    print(json.dumps(output["failed_list"], ensure_ascii=False, indent=2))

    for company_code, result in output["results"].items():
        print(f"\n--- {company_code} / {result['status']} ---")
        print(json.dumps(result["structured_data"], ensure_ascii=False, indent=2))
        print(f"chunks={len(result['chunks'])}")
