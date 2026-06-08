from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from .config import CACHE_DIR, ensure_cache_dir
from .finance_store import find_companies_by_name, list_companies, upsert_company


FALLBACK_COMPANIES = {
    "005930": {"corp_name": "삼성전자", "corp_code": "00126380", "aliases": ["삼성전자", "삼전"]},
    "035420": {"corp_name": "NAVER", "corp_code": "00266961", "aliases": ["네이버", "NAVER", "Naver"]},
    "051910": {"corp_name": "LG화학", "corp_code": "00356370", "aliases": ["LG화학", "엘지화학"]},
    "351320": {"corp_name": "넥사다이내믹스", "corp_code": "", "aliases": ["넥사다이내믹스", "넥사 다이내믹스", "에스에이티이엔지"]},
    "005380": {"corp_name": "현대자동차", "corp_code": "00164742", "aliases": ["현대자동차", "현대차"]},
}

SEARCH_LIMIT = 20

logger = logging.getLogger(__name__)
_DART_CORP_CODES: Any | None = None


@dataclass(frozen=True)
class Company:
    stock_code: str
    corp_name: str
    corp_code: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        data = asdict(self)
        data["name"] = self.corp_name
        data["company_name"] = self.corp_name
        return data


def normalize_stock_code(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{1,6}", text):
        return text.zfill(6)
    return text


def is_stock_code(value: Any) -> bool:
    return bool(re.fullmatch(r"\d{6}", str(value or "").strip()))


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _fallback_candidates(query: str = "") -> list[Company]:
    normalized_query = _normalize_text(query)
    results = []
    for stock_code, info in FALLBACK_COMPANIES.items():
        aliases = [str(info["corp_name"]), *info.get("aliases", [])]
        normalized_aliases = [_normalize_text(alias) for alias in aliases]
        if not normalized_query or normalize_stock_code(query) == stock_code or any(normalized_query in alias for alias in normalized_aliases):
            results.append(
                Company(
                    stock_code=stock_code,
                    corp_name=str(info["corp_name"]),
                    corp_code=str(info.get("corp_code") or ""),
                    source="fallback",
                )
            )
    return results


def _db_candidates(query: str = "") -> list[Company]:
    rows = find_companies_by_name(query) if query else list_companies()
    return [
        Company(
            stock_code=str(row.get("stock_code") or "").zfill(6),
            corp_name=str(row.get("corp_name") or ""),
            corp_code=str(row.get("corp_code") or ""),
            source="sqlite",
        )
        for row in rows
        if is_stock_code(str(row.get("stock_code") or "").zfill(6))
    ]


def _dart_corp_codes() -> Any | None:
    global _DART_CORP_CODES
    if _DART_CORP_CODES is not None:
        return _DART_CORP_CODES

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("DART_API_KEY", "").strip()
    if not api_key or api_key.startswith("your_"):
        logger.warning("dart_company_search_unavailable reason=missing_dart_api_key")
        return None
    try:
        import pandas as pd
        from OpenDartReader import dart_list
    except ImportError as exc:
        logger.warning("dart_company_search_unavailable reason=dart_dependency_missing error=%s", exc)
        return None

    cache_path = _dart_corp_codes_cache_path()
    if cache_path.exists():
        try:
            _DART_CORP_CODES = pd.read_pickle(cache_path)
            logger.info("dart_company_cache_loaded path=%s", cache_path)
            return _DART_CORP_CODES
        except Exception as exc:
            logger.warning("dart_company_cache_read_failed path=%s error=%s", cache_path, exc)

    try:
        _DART_CORP_CODES = dart_list.corp_codes(api_key)
        _DART_CORP_CODES.to_pickle(cache_path)
        logger.info("dart_company_cache_created path=%s rows=%s", cache_path, len(_DART_CORP_CODES))
        _prune_old_dart_corp_code_caches(cache_path)
        return _DART_CORP_CODES
    except Exception as exc:
        logger.warning("dart_company_search_client_failed error=%s", exc)
        return None


def _dart_corp_codes_cache_path() -> Path:
    ensure_cache_dir()
    today = datetime.today().strftime("%Y%m%d")
    return CACHE_DIR / f"opendartreader_corp_codes_{today}.pkl"


def _prune_old_dart_corp_code_caches(current_path: Path) -> None:
    for path in CACHE_DIR.glob("opendartreader_corp_codes_*.pkl"):
        if path == current_path:
            continue
        try:
            path.unlink()
            logger.info("dart_company_cache_pruned path=%s", path)
        except OSError as exc:
            logger.warning("dart_company_cache_prune_failed path=%s error=%s", path, exc)


def _dart_candidates(query: str = "", limit: int = SEARCH_LIMIT) -> list[Company]:
    query = str(query or "").strip()
    if not query:
        return []

    corp_codes = _dart_corp_codes()
    if corp_codes is None:
        return []

    normalized_query = _normalize_text(query)
    normalized_stock_query = normalize_stock_code(query)
    rows: list[tuple[int, int, Company]] = []

    try:
        records = corp_codes.to_dict("records")
    except Exception as exc:
        logger.warning("dart_company_search_failed reason=invalid_corp_codes error=%s", exc)
        return []

    for record in records:
        stock_code = normalize_stock_code(_clean_text(record.get("stock_code")))
        corp_name = _clean_text(record.get("corp_name"))
        corp_code = _clean_text(record.get("corp_code"))
        if not is_stock_code(stock_code) or not corp_name:
            continue

        normalized_name = _normalize_text(corp_name)
        score = _dart_match_score(
            query=query,
            normalized_query=normalized_query,
            normalized_stock_query=normalized_stock_query,
            stock_code=stock_code,
            corp_code=corp_code,
            normalized_name=normalized_name,
        )
        if score is None:
            continue

        rows.append(
            (
                score,
                len(corp_name),
                Company(
                    stock_code=stock_code,
                    corp_name=corp_name,
                    corp_code=corp_code,
                    source="dart",
                ),
            )
        )

    rows.sort(key=lambda item: (item[0], item[1], item[2].corp_name, item[2].stock_code))
    companies = [company for _, _, company in rows[:limit]]
    for company in companies:
        try:
            upsert_company(company.stock_code, corp_name=company.corp_name, corp_code=company.corp_code)
        except Exception as exc:
            logger.warning("dart_company_cache_upsert_failed stock_code=%s error=%s", company.stock_code, exc)
    logger.info("dart_company_search_complete query=%r result_count=%s", query, len(companies))
    return companies


def _dart_match_score(
    *,
    query: str,
    normalized_query: str,
    normalized_stock_query: str,
    stock_code: str,
    corp_code: str,
    normalized_name: str,
) -> int | None:
    if normalized_stock_query == stock_code:
        return 0
    if query.isdigit() and query == corp_code:
        return 1
    if normalized_query == normalized_name:
        return 2
    if normalized_name.startswith(normalized_query):
        return 3
    if normalized_query and normalized_query in normalized_name:
        return 4
    return None


def _dedupe(companies: Iterable[Company]) -> list[Company]:
    seen = set()
    results = []
    for company in companies:
        if not is_stock_code(company.stock_code):
            continue
        if company.stock_code in seen:
            continue
        seen.add(company.stock_code)
        results.append(company)
    return results


def search_companies(query: str = "") -> list[Company]:
    query = str(query or "").strip()
    return _dedupe([*_fallback_candidates(query), *_db_candidates(query), *_dart_candidates(query)])[:SEARCH_LIMIT]


def resolve_company(value: str) -> Company | None:
    query = str(value or "").strip()
    if not query:
        return None
    stock_code = normalize_stock_code(query)
    if is_stock_code(stock_code):
        matches = search_companies(stock_code)
        return matches[0] if matches else Company(stock_code=stock_code, corp_name=stock_code, source="direct")
    matches = search_companies(query)
    return matches[0] if matches else None
