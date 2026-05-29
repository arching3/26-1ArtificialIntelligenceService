import pickle
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, List, Optional

from finance_store import find_companies_by_name, list_companies


CORP_CODE_CACHE_DIR = Path("docs_cache")
CORP_CODE_CACHE_PATTERN = "opendartreader_corp_codes_*.pkl"
FALLBACK_COMPANY_ALIASES = {
    "005930": ["삼성전자"],
    "035420": ["네이버", "NAVER", "Naver"],
    "051910": ["LG화학", "엘지화학"],
    "351320": ["넥사다이내믹스", "넥사 다이내믹스", "에스에이티이엔지"],
    "294870": ["HDC현대산업개발", "현대산업개발", "IPARK현대산업개발", "아이파크현대산업개발"],
    "000720": ["현대건설"],
}


@dataclass(frozen=True)
class CompanyCandidate:
    stock_code: str
    corp_name: str
    corp_code: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ResolveResult:
    status: str
    query: str
    selected: Optional[CompanyCandidate] = None
    candidates: tuple[CompanyCandidate, ...] = ()
    message: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["selected"] = self.selected.to_dict() if self.selected else None
        data["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return data


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _is_stock_code(value: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", value.strip()))


def _first_existing_cache() -> Optional[Path]:
    if not CORP_CODE_CACHE_DIR.exists():
        return None
    matches = sorted(
        CORP_CODE_CACHE_DIR.glob(CORP_CODE_CACHE_PATTERN),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def _record_get(record: Any, names: Iterable[str]) -> str:
    for name in names:
        value = ""
        if isinstance(record, dict):
            value = record.get(name, "")
        else:
            try:
                value = getattr(record, name)
            except Exception:
                value = ""
            if value in (None, "") and hasattr(record, "__getitem__"):
                try:
                    value = record[name]
                except Exception:
                    value = ""
        value = str(value or "").strip()
        if value and value.lower() != "nan":
            return value
    return ""


def _candidate_from_record(record: Any, source: str) -> Optional[CompanyCandidate]:
    stock_code = _record_get(record, ["stock_code", "stockCode", "종목코드"]).zfill(6)
    if not _is_stock_code(stock_code):
        return None
    corp_name = _record_get(record, ["corp_name", "corpName", "corp_nm", "회사명", "company_name"])
    if not corp_name:
        return None
    corp_code = _record_get(record, ["corp_code", "corpCode", "고유번호"])
    return CompanyCandidate(
        stock_code=stock_code,
        corp_name=corp_name,
        corp_code=corp_code,
        source=source,
    )


def _iter_records(raw: Any) -> Iterable[Any]:
    if hasattr(raw, "to_dict"):
        try:
            return raw.to_dict("records")
        except Exception:
            pass
    if isinstance(raw, dict):
        if all(isinstance(value, list) for value in raw.values()):
            keys = list(raw.keys())
            length = min(len(raw[key]) for key in keys) if keys else 0
            return [{key: raw[key][index] for key in keys} for index in range(length)]
        return raw.values()
    if isinstance(raw, list):
        return raw
    return []


@lru_cache(maxsize=1)
def load_dart_company_candidates() -> tuple[CompanyCandidate, ...]:
    cache_path = _first_existing_cache()
    if cache_path is None:
        return ()

    try:
        with cache_path.open("rb") as file:
            raw = pickle.load(file)
    except Exception:
        return ()

    candidates = []
    seen = set()
    for record in _iter_records(raw):
        candidate = _candidate_from_record(record, source="dart_cache")
        if candidate is None:
            continue
        key = (candidate.stock_code, _normalize_text(candidate.corp_name))
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)
    return tuple(candidates)


def _db_candidates_by_name(query: str) -> List[CompanyCandidate]:
    rows = find_companies_by_name(query)
    normalized_query = _normalize_text(query)
    return [
        CompanyCandidate(
            stock_code=str(row.get("company_code") or "").zfill(6),
            corp_name=str(row.get("company_name") or ""),
            source="finance_db",
        )
        for row in rows
        if _is_stock_code(str(row.get("company_code") or "").zfill(6))
        and (len(normalized_query) >= 3 or _normalize_text(row.get("company_name")) == normalized_query)
    ]


def _dart_candidates_by_name(query: str) -> List[CompanyCandidate]:
    normalized_query = _normalize_text(query)
    if not normalized_query:
        return []

    exact = []
    partial = []
    for candidate in load_dart_company_candidates():
        normalized_name = _normalize_text(candidate.corp_name)
        if not normalized_name:
            continue
        if normalized_name == normalized_query:
            exact.append(candidate)
        elif len(normalized_query) >= 3 and normalized_query in normalized_name:
            partial.append(candidate)

    return exact or partial[:20]


def _fallback_candidates_by_name(query: str) -> List[CompanyCandidate]:
    normalized_query = _normalize_text(query)
    candidates = []
    for stock_code, aliases in FALLBACK_COMPANY_ALIASES.items():
        normalized_aliases = [_normalize_text(alias) for alias in aliases]
        if normalized_query in normalized_aliases:
            candidates.append(
                CompanyCandidate(
                    stock_code=stock_code,
                    corp_name=aliases[0],
                    source="fallback_alias",
                )
            )
    return candidates


def _dedupe_candidates(candidates: Iterable[CompanyCandidate]) -> tuple[CompanyCandidate, ...]:
    deduped = []
    seen = set()
    for candidate in candidates:
        if not _is_stock_code(candidate.stock_code):
            continue
        key = candidate.stock_code
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return tuple(deduped)


def resolve_company(value: str) -> ResolveResult:
    query = str(value or "").strip()
    if not query:
        return ResolveResult(status="not_found", query=query, message="기업명을 입력해 주세요.")

    if _is_stock_code(query):
        return ResolveResult(
            status="resolved",
            query=query,
            selected=CompanyCandidate(stock_code=query, corp_name="", source="direct_stock_code"),
        )

    db_candidates = _db_candidates_by_name(query)
    fallback_candidates = _fallback_candidates_by_name(query)
    dart_candidates = _dart_candidates_by_name(query)
    candidates = _dedupe_candidates(db_candidates + fallback_candidates + dart_candidates)

    if len(candidates) == 1:
        return ResolveResult(status="resolved", query=query, selected=candidates[0], candidates=candidates)
    if len(candidates) > 1:
        return ResolveResult(
            status="ambiguous",
            query=query,
            candidates=candidates,
            message="여러 기업이 검색되었습니다. 더 정확한 회사명 또는 6자리 종목코드를 입력해 주세요.",
        )
    return ResolveResult(status="not_found", query=query, message="기업을 찾을 수 없습니다.")


def resolve_company_inputs(values: Iterable[str]) -> List[ResolveResult]:
    return [resolve_company(value) for value in values]


def learned_company_candidates() -> tuple[CompanyCandidate, ...]:
    return tuple(
        CompanyCandidate(
            stock_code=str(row.get("company_code") or "").zfill(6),
            corp_name=str(row.get("company_name") or ""),
            source="finance_db",
        )
        for row in list_companies()
        if _is_stock_code(str(row.get("company_code") or "").zfill(6))
    )


def find_company_codes_in_text(text: str, include_dart_cache: bool = True) -> List[str]:
    normalized_text = _normalize_text(text)
    found: List[str] = []

    def add(code: str) -> None:
        if code and code not in found:
            found.append(code)

    for candidate in learned_company_candidates():
        normalized_name = _normalize_text(candidate.corp_name)
        if normalized_name and normalized_name in normalized_text:
            add(candidate.stock_code)

    if include_dart_cache:
        for candidate in load_dart_company_candidates():
            normalized_name = _normalize_text(candidate.corp_name)
            if len(normalized_name) >= 3 and normalized_name in normalized_text:
                add(candidate.stock_code)

    return found
