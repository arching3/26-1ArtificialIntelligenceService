from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - dependency availability is runtime-specific.
    yf = None


logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 20
_MARKET_SUFFIXES = (".KS", ".KQ")
_CACHE: dict[tuple[str, str, str, bool], tuple[float, dict[str, Any]]] = {}


@dataclass(frozen=True)
class StockPeriod:
    period: str
    interval: str


PERIOD_MAP = {
    "최근 1주": StockPeriod("7d", "30m"),
    "최근 1개월": StockPeriod("1mo", "1d"),
    "최근 3개월": StockPeriod("3mo", "1d"),
    "최근 6개월": StockPeriod("6mo", "1d"),
    "최근 1년": StockPeriod("1y", "1d"),
    "최근 3년": StockPeriod("3y", "1wk"),
    "전체": StockPeriod("max", "1mo"),
}
DEFAULT_PERIOD = StockPeriod("1mo", "1d")
REALTIME_PERIOD = StockPeriod("1d", "1m")


def fetch_stock_history(stock_code: str, requested_period: str | None = None) -> dict[str, Any]:
    stock_period = PERIOD_MAP.get(requested_period or "", DEFAULT_PERIOD)
    logger.info(
        "stock_history_request stock_code=%s period=%s interval=%s",
        stock_code,
        stock_period.period,
        stock_period.interval,
    )
    return _fetch_stock_rows(stock_code, stock_period, realtime=False)


def fetch_realtime_stock(stock_code: str) -> dict[str, Any]:
    logger.info("stock_realtime_request stock_code=%s", stock_code)
    return _fetch_stock_rows(stock_code, REALTIME_PERIOD, realtime=True)


def _fetch_stock_rows(stock_code: str, stock_period: StockPeriod, realtime: bool) -> dict[str, Any]:
    cache_key = (stock_code, stock_period.period, stock_period.interval, realtime)
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    if yf is None:
        return _store_cache(
            cache_key,
            _empty_response(stock_code, "", "yfinance is not installed"),
        )

    errors = []
    for symbol in _candidate_symbols(stock_code):
        try:
            frame = yf.Ticker(symbol).history(
                period=stock_period.period,
                interval=stock_period.interval,
                auto_adjust=False,
                prepost=False,
            )
        except Exception as exc:  # pragma: no cover - external provider failure.
            logger.warning("stock_provider_failed symbol=%s error=%s", symbol, exc)
            errors.append(f"{symbol}: {exc}")
            continue

        rows = _frame_to_rows(frame, realtime=realtime)
        if rows:
            result = {
                "stocks": rows,
                "symbol": symbol,
                "provider": "yfinance",
                "status": "ok",
            }
            logger.info("stock_response_ready stock_code=%s symbol=%s rows=%s", stock_code, symbol, len(rows))
            return _store_cache(cache_key, result)

        errors.append(f"{symbol}: no rows")

    message = "; ".join(errors) if errors else "no provider candidates"
    logger.warning("stock_response_empty stock_code=%s reason=%s", stock_code, message)
    return _store_cache(cache_key, _empty_response(stock_code, "", message))


def _candidate_symbols(stock_code: str) -> list[str]:
    code = str(stock_code or "").strip()
    if not code:
        return []
    if code.isdigit() and len(code) == 6:
        return [f"{code}{suffix}" for suffix in _MARKET_SUFFIXES]
    return [code]


def _frame_to_rows(frame: Any, realtime: bool) -> list[list[Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    if "Close" not in frame:
        return []

    close = frame["Close"].dropna()
    if close.empty:
        return []
    if realtime:
        close = close.tail(1)

    rows = []
    for index, price in close.items():
        timestamp = pd.Timestamp(index)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(None)
        rows.append([timestamp.isoformat(timespec="seconds"), float(price)])
    return rows


def _cached(cache_key: tuple[str, str, str, bool]) -> dict[str, Any] | None:
    cached = _CACHE.get(cache_key)
    if not cached:
        return None
    created_at, value = cached
    if time.time() - created_at <= _CACHE_TTL_SECONDS:
        return value
    _CACHE.pop(cache_key, None)
    return None


def _store_cache(cache_key: tuple[str, str, str, bool], value: dict[str, Any]) -> dict[str, Any]:
    _CACHE[cache_key] = (time.time(), value)
    return value


def _empty_response(stock_code: str, symbol: str, error: str) -> dict[str, Any]:
    return {
        "stocks": [],
        "symbol": symbol,
        "stock_code": stock_code,
        "provider": "yfinance",
        "status": "empty",
        "error": error,
    }
