from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stock_service import fetch_realtime_stock, fetch_stock_history


def main() -> int:
    stock_code = sys.argv[1] if len(sys.argv) > 1 else "005930"
    history = fetch_stock_history(stock_code, "최근 1주")
    realtime = fetch_realtime_stock(stock_code)

    print("history")
    print(_preview_result(history))
    print()
    print("realtime")
    print(_preview_result(realtime))

    _assert_stock_result("history", history)
    _assert_stock_result("realtime", realtime)
    return 0


def _preview_result(result: dict[str, Any]) -> str:
    preview = dict(result)
    rows = preview.get("stocks") or []
    preview["stock_count"] = len(rows)
    preview["stocks"] = rows[:3]
    return json.dumps(preview, ensure_ascii=False, indent=2, default=str)


def _assert_stock_result(label: str, result: dict[str, Any]) -> None:
    if result.get("status") != "ok":
        raise AssertionError(f"{label} status is not ok: {result}")
    rows = result.get("stocks")
    if not isinstance(rows, list) or not rows:
        raise AssertionError(f"{label} has no stock rows: {result}")
    first = rows[0]
    if not isinstance(first, list) or len(first) < 2:
        raise AssertionError(f"{label} row shape is invalid: {first!r}")
    if not isinstance(first[0], str):
        raise AssertionError(f"{label} timestamp is not a string: {first!r}")
    if not isinstance(first[1], (int, float)):
        raise AssertionError(f"{label} price is not numeric: {first!r}")


if __name__ == "__main__":
    raise SystemExit(main())
