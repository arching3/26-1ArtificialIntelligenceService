from __future__ import annotations

import logging
import time
from typing import Any

import requests


logger = logging.getLogger(__name__)


# frontend 브랜치 변경: Streamlit 화면에서 직접 하던 backend API 호출을 이 모듈로 분리했습니다.
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
    started_at = time.perf_counter()
    url = api_url(backend_url, path)
    logger.debug("frontend_api_request method=%s path=%s timeout=%s", method, path, timeout)
    try:
        response = requests.request(
            method,
            url,
            timeout=timeout,
            **kwargs,
        )
    except requests.RequestException as exc:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning("frontend_api_request_failed method=%s path=%s elapsed_ms=%.1f error=%s", method, path, elapsed_ms, exc)
        return False, None, f"연결 실패: {exc}"

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    if not response.ok:
        logger.warning(
            "frontend_api_bad_status method=%s path=%s status_code=%s elapsed_ms=%.1f body_chars=%s",
            method,
            path,
            response.status_code,
            elapsed_ms,
            len(response.text or ""),
        )
        return False, None, f"HTTP {response.status_code}: {response.text[:240]}"

    if not response.content:
        logger.info("frontend_api_response_empty method=%s path=%s status_code=%s elapsed_ms=%.1f", method, path, response.status_code, elapsed_ms)
        return True, {}, ""

    try:
        data = response.json()
    except ValueError:
        logger.warning("frontend_api_invalid_json method=%s path=%s status_code=%s elapsed_ms=%.1f", method, path, response.status_code, elapsed_ms)
        return False, None, "응답이 JSON 형식이 아닙니다."
    logger.debug("frontend_api_response_ok method=%s path=%s status_code=%s elapsed_ms=%.1f", method, path, response.status_code, elapsed_ms)
    return True, data, ""


def fetch_companies(backend_url: str, query: str = "", timeout: int = 8) -> tuple[bool, Any, str]:
    payload = {"query": query.strip()} if query.strip() else {}
    logger.info("frontend_companies_search query_chars=%s has_query=%s", len(query.strip()), bool(payload))
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

    normalized = list(dict.fromkeys(results))
    logger.debug("frontend_companies_normalized input_type=%s result_count=%s", type(data).__name__, len(normalized))
    return normalized
