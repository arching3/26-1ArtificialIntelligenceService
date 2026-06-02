from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from src.api_server import app
from src.config import EVENT_INDEX, REGULAR_INDEX
from src.finance_store import get_active_chunks, init_db


def main() -> int:
    company = sys.argv[1] if len(sys.argv) > 1 else "현대자동차"
    client = TestClient(app)
    init_db()

    before = _index_snapshot(company)

    # This mirrors streamlit_app.py:
    # add_company() -> sync_watchlist() -> select_company()
    # select_company() -> fetch_summary() + fetch_initial_stocks()
    responses = {
        "set_watchlist": _post(client, "/api/companies/list", {"companies": [company]}),
        "summary": _post(client, f"/api/companies/{company}/summary", {"name": company, "period": "최근 1년"}),
        "stocks": _post(client, "/api/companies/stocks", {"company": company, "period": "최근 1년"}),
        "index_status": _get(client, f"/api/companies/{company}/index-status"),
    }

    after = _index_snapshot(company)
    report = {
        "company": company,
        "before": before,
        "after": after,
        "responses": responses,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    if before["regular_chunks"] == 0 and after["regular_chunks"] == 0:
        raise AssertionError(
            "frontend add-company flow did not trigger DART filing fetch/indexing "
            "for a company with no existing DB/index data"
        )
    return 0


def _post(client: TestClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    return _response_info(response)


def _get(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    return _response_info(response)


def _response_info(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {
        "status_code": response.status_code,
        "body": _compact_body(body),
    }


def _compact_body(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    compact = dict(body)
    if isinstance(compact.get("stocks"), list):
        compact["stocks_count"] = len(compact["stocks"])
        compact["stocks"] = compact["stocks"][:2]
    for key, value in list(compact.items()):
        if isinstance(value, str) and len(value) > 220:
            compact[key] = value[:220] + "..."
    return compact


def _index_snapshot(company: str) -> dict[str, Any]:
    client = TestClient(app)
    status_response = client.get(f"/api/companies/{company}/index-status")
    status = status_response.json() if status_response.status_code == 200 else {}
    stock_code = status.get("stock_code") or ""
    return {
        "status_code": status_response.status_code,
        "stock_code": stock_code,
        "index_status": status.get("status"),
        "regular_chunks": len(get_active_chunks(stock_code, REGULAR_INDEX)) if stock_code else 0,
        "event_chunks": len(get_active_chunks(stock_code, EVENT_INDEX)) if stock_code else 0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
