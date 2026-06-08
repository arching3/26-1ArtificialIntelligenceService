from __future__ import annotations

from typing import Any

import requests


def api_url(backend_url: str, path: str) -> str:
    base = backend_url.rstrip("/")
    return f"{base}{path}"


def request_json(
    method: str,
    path: str,
    *,
    backend_url: str,
    timeout: int,
    **kwargs: Any,
) -> tuple[bool, Any, str]:
    try:
        response = requests.request(
            method,
            api_url(backend_url, path),
            timeout=timeout,
            **kwargs,
        )
    except requests.RequestException as exc:
        return False, None, f"연결 실패: {exc}"

    if not response.ok:
        return False, None, f"HTTP {response.status_code}: {response.text[:240]}"

    if not response.content:
        return True, {}, ""

    try:
        return True, response.json(), ""
    except ValueError:
        return False, None, "응답이 JSON 형식이 아닙니다."


def fetch_companies(backend_url: str, query: str = "", timeout: int = 8) -> tuple[bool, Any, str]:
    payload = {"query": query.strip()} if query.strip() else {}
    return request_json(
        "GET",
        "/api/companies/search",
        backend_url=backend_url,
        timeout=timeout,
        params=payload,
    )


def normalize_company_results(data: Any) -> list[str]:
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = (
            data.get("companies")
            or data.get("list")
            or data.get("results")
            or data.get("data")
            or data.get("items")
            or []
        )
    else:
        raw_items = []

    results: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            results.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("company") or item.get("company_name")
            if name:
                results.append(str(name))

    return list(dict.fromkeys(results))
