import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import OpenDartReader

from .config import REGULAR_INDEX, REGULAR_LOOKBACK_DAYS, cleaned_dir, raw_dir

logger = logging.getLogger(__name__)
MAX_LOOKBACK_YEARS = 7
REGULAR_REPORT_PATTERNS = {
    "annual": "사업보고서",
    "semiannual": "반기보고서",
    "quarterly": "분기보고서",
}


@dataclass
class CollectedFiling:
    stock_code: str
    receipt_no: str
    report_name: str
    receipt_date: str
    corp_name: str
    corp_code: str
    index_type: str
    raw_path: Path
    report_kind: str = ""
    cleaned_path: Path | None = None
    row: Any = None

    def filing_record(self) -> Dict[str, Any]:
        return {
            "receipt_no": self.receipt_no,
            "stock_code": self.stock_code,
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "report_name": self.report_name,
            "receipt_date": self.receipt_date,
            "filing_type": "regular" if self.index_type == REGULAR_INDEX else "event",
            "filing_detail_type": self.report_kind,
            "index_type": self.index_type,
            "raw_path": str(self.raw_path),
            "cleaned_path": str(self.cleaned_path or ""),
            "metadata": {"report_kind": self.report_kind},
        }


def classify_regular_report(report_name: str) -> str:
    text = str(report_name or "")
    for report_kind, pattern in REGULAR_REPORT_PATTERNS.items():
        if pattern in text:
            return report_kind
    return ""


def _validate_report_list(reports: pd.DataFrame, stock_code: str) -> None:
    if reports is None or getattr(reports, "empty", True):
        raise ValueError(f"정기공시 목록이 없습니다: {stock_code}")
    required_columns = {"report_nm", "rcept_dt", "rcept_no"}
    missing = required_columns - set(reports.columns)
    if missing:
        raise ValueError(f"DART 공시 목록 컬럼 누락: {sorted(missing)}")


def _find_latest_annual_report(dart: OpenDartReader, stock_code: str) -> pd.Series:
    today = datetime.today()
    start = f"{today.year - MAX_LOOKBACK_YEARS}-01-01"
    end = today.strftime("%Y-%m-%d")
    reports = dart.list(stock_code, start=start, end=end, kind="A", final=False)
    _validate_report_list(reports, stock_code)
    annual_reports = reports[reports["report_nm"].astype(str).str.contains("사업보고서", na=False)].copy()
    if annual_reports.empty:
        raise ValueError(f"최근 사업보고서를 찾지 못했습니다: {stock_code}")
    return annual_reports.sort_values("rcept_dt", ascending=False).iloc[0]


def _find_recent_regular_reports(
    dart: OpenDartReader,
    stock_code: str,
    lookback_days: int = REGULAR_LOOKBACK_DAYS,
) -> pd.DataFrame:
    end_date = datetime.today()
    start_date = end_date - timedelta(days=lookback_days)
    reports = dart.list(
        stock_code,
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        kind="A",
        final=False,
    )
    _validate_report_list(reports, stock_code)
    reports = reports.copy()
    reports["report_kind"] = reports["report_nm"].map(classify_regular_report)
    reports = reports[reports["report_kind"].astype(bool)].copy()
    if reports.empty:
        raise ValueError(f"최근 {lookback_days}일 정기보고서를 찾지 못했습니다: {stock_code}")
    reports = reports.drop_duplicates(subset=["rcept_no"], keep="first")
    return reports.sort_values("rcept_dt", ascending=True)


def _collect_regular_filing_from_row(
    dart: OpenDartReader,
    stock_code: str,
    row: Any,
    sleep_seconds: float,
) -> tuple[CollectedFiling, str]:
    receipt_no = str(row.get("rcept_no", ""))
    if not receipt_no:
        raise ValueError("정기보고서 접수번호가 비어 있습니다.")
    time.sleep(sleep_seconds)
    raw_document = dart.document(receipt_no)
    if not raw_document:
        raise ValueError(f"정기보고서 원문 다운로드 실패: {receipt_no}")

    path = raw_dir(stock_code) / f"{receipt_no}.xml"
    path.write_text(raw_document, encoding="utf-8")
    filing = CollectedFiling(
        stock_code=stock_code,
        receipt_no=receipt_no,
        report_name=str(row.get("report_nm", "")),
        receipt_date=str(row.get("rcept_dt", "")),
        corp_name=str(row.get("corp_name", row.get("flr_nm", ""))),
        corp_code=str(row.get("corp_code", "")),
        index_type=REGULAR_INDEX,
        raw_path=path,
        report_kind=str(row.get("report_kind") or classify_regular_report(str(row.get("report_nm", "")))),
        row=row,
    )
    return filing, raw_document


def collect_latest_annual_filing(dart: OpenDartReader, stock_code: str, sleep_seconds: float = 0.3) -> tuple[CollectedFiling, str]:
    latest = _find_latest_annual_report(dart, stock_code)
    latest = latest.copy()
    latest["report_kind"] = "annual"
    return _collect_regular_filing_from_row(dart, stock_code, latest, sleep_seconds)


def collect_recent_regular_filings(
    dart: OpenDartReader,
    stock_code: str,
    lookback_days: int = REGULAR_LOOKBACK_DAYS,
    sleep_seconds: float = 0.3,
) -> Dict[str, Any]:
    reports = _find_recent_regular_reports(dart, stock_code, lookback_days=lookback_days)
    collected: List[tuple[CollectedFiling, str]] = []
    failed_list: List[Dict[str, str]] = []

    for _, series in reports.iterrows():
        row = series.copy()
        try:
            collected.append(_collect_regular_filing_from_row(dart, stock_code, row, sleep_seconds))
        except Exception as exc:
            receipt_no = str(row.get("rcept_no", ""))
            report_name = str(row.get("report_nm", ""))
            logger.warning("[%s] 정기보고서 수집 실패(%s): %s", stock_code, receipt_no, exc)
            failed_list.append({"receipt_no": receipt_no, "report_name": report_name, "reason": str(exc)})

    if not collected:
        raise ValueError(f"저장 가능한 최근 정기보고서가 없습니다: {stock_code}")
    return {"filings": collected, "failed_list": failed_list}


def save_cleaned_text(stock_code: str, receipt_no: str, text: str) -> Path:
    path = cleaned_dir(stock_code) / f"{receipt_no}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def normalize_stock_code(value: Any) -> str:
    code = str(value or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"유효하지 않은 6자리 종목코드입니다: {value!r}")
    return code
