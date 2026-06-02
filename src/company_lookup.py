from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .finance_store import find_companies_by_name, list_companies


FALLBACK_COMPANIES = {
    "005930": {"corp_name": "삼성전자", "corp_code": "00126380", "aliases": ["삼성전자", "삼전"]},
    "035420": {"corp_name": "NAVER", "corp_code": "00266961", "aliases": ["네이버", "NAVER", "Naver"]},
    "051910": {"corp_name": "LG화학", "corp_code": "00356370", "aliases": ["LG화학", "엘지화학"]},
    "351320": {"corp_name": "넥사다이내믹스", "corp_code": "", "aliases": ["넥사다이내믹스", "넥사 다이내믹스", "에스에이티이엔지"]},
    "005380": {"corp_name": "현대자동차", "corp_code": "00164742", "aliases": ["현대자동차", "현대차"]},
}


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
    return _dedupe([*_db_candidates(query), *_fallback_candidates(query)])


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
