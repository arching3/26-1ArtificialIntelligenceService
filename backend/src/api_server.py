from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .company_lookup import Company, resolve_company, search_companies
from .config import EVENT_INDEX, REGULAR_INDEX, index_dir
from .finance_store import (
    get_filing,
    get_active_chunks,
    init_db,
    list_filings,
)
from .logging_config import configure_logging
from .pipeline import rebuild_company_indexes
from .rag_service import answer_question
from .summary_service import SummaryService
from .stock_service import fetch_realtime_stock, fetch_stock_history


configure_logging()
logger = logging.getLogger(__name__)
summary_service = SummaryService()

app = FastAPI(title="DART Lens Backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.perf_counter()
    path = request.url.path
    method = request.method
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.exception("request_failed method=%s path=%s elapsed_ms=%.1f", method, path, elapsed_ms)
        raise

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    log_payload = "request_complete method=%s path=%s status=%s elapsed_ms=%.1f"
    if response.status_code >= 500:
        logger.error(log_payload, method, path, response.status_code, elapsed_ms)
    elif response.status_code >= 400:
        logger.warning(log_payload, method, path, response.status_code, elapsed_ms)
    else:
        logger.info(log_payload, method, path, response.status_code, elapsed_ms)
    return response


class WatchlistPayload(BaseModel):
    companies: list[str] = []


class SummaryRequest(BaseModel):
    name: str | None = None
    period: str | None = None


class StockRequest(BaseModel):
    company: str | None = None
    name: str | None = None
    period: str | None = None


class ChatRequest(BaseModel):
    prompt: str | None = None
    message: str | None = None
    company: str | None = None
    company_name: str | None = None
    corp_code: str | None = None
    stock_code: str | None = None
    period: str | None = None


class DevLoginRequest(BaseModel):
    username: str = "dev"


class IndexJob(BaseModel):
    stock_code: str
    status: Literal["queued", "indexing", "ready", "failed"]
    started_at: str
    updated_at: str
    error: str = ""
    result: dict[str, Any] | None = None


_jobs: dict[str, IndexJob] = {}
_jobs_lock = threading.Lock()
_watchlist: list[str] = []
_dev_user = {"username": "dev"}


@app.on_event("startup")
def startup() -> None:
    logger.info("backend_startup")
    init_db()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "dart-lens-backend",
        "time": datetime.now().isoformat(timespec="seconds"),
    }


@app.get("/api/me")
def me() -> dict[str, Any]:
    return {"username": _dev_user["username"], "auth": "dev"}


@app.post("/api/dev-login")
def dev_login(payload: DevLoginRequest) -> dict[str, Any]:
    username = payload.username.strip() or "dev"
    _dev_user["username"] = username
    logger.info("dev_login username=%s", username)
    return {"username": username, "auth": "dev"}


@app.get("/api/me/watchlist")
def get_watchlist() -> dict[str, Any]:
    return {"username": _dev_user["username"], "companies": _watchlist}


@app.post("/api/me/watchlist")
def post_watchlist(payload: WatchlistPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return _set_watchlist(payload, background_tasks)


@app.delete("/api/me/watchlist/{company_value}")
def delete_watchlist_item(company_value: str) -> dict[str, Any]:
    global _watchlist
    company = resolve_company(company_value)
    names = {company_value}
    if company:
        names.update({company.corp_name, company.stock_code})
    _watchlist = [item for item in _watchlist if item not in names]
    logger.info("watchlist_delete value=%s resolved_stock_code=%s size=%s", company_value, company.stock_code if company else "", len(_watchlist))
    return {"username": _dev_user["username"], "companies": _watchlist}


@app.get("/api/companies/search")
def companies_search(query: str = Query(default="")) -> dict[str, Any]:
    companies = search_companies(query)
    logger.info("companies_search query=%r result_count=%s", query, len(companies))
    return {"companies": [company.to_dict() for company in companies]}


@app.post("/api/companies/list")
def set_watchlist(payload: WatchlistPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    return _set_watchlist(payload, background_tasks)


def _set_watchlist(payload: WatchlistPayload, background_tasks: BackgroundTasks) -> dict[str, Any]:
    global _watchlist
    _watchlist = list(dict.fromkeys(payload.companies))
    logger.info("watchlist_set size=%s companies=%s", len(_watchlist), _watchlist)
    index_jobs = []
    for company_value in _watchlist:
        company = resolve_company(company_value)
        if not company:
            logger.warning("watchlist_index_skip_unresolved value=%r", company_value)
            continue
        index_result = _queue_index_job(company, background_tasks)
        if index_result["status"] in {"queued", "indexing"}:
            index_jobs.append(index_result)
    return {"ok": True, "companies": _watchlist, "index_jobs": index_jobs}


@app.post("/api/companies/{company_value}/index")
def start_index(company_value: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    company = _require_company(company_value)
    return _queue_index_job(company, background_tasks)


def _queue_index_job(company: Company, background_tasks: BackgroundTasks) -> dict[str, Any]:
    current = _current_index_status(company.stock_code)
    if current["status"] == "ready":
        logger.info("index_request_already_ready stock_code=%s company=%s", company.stock_code, company.corp_name)
        return {"stock_code": company.stock_code, "corp_name": company.corp_name, **current}

    with _jobs_lock:
        existing = _jobs.get(company.stock_code)
        if existing and existing.status in {"queued", "indexing"}:
            logger.info("index_request_existing_job stock_code=%s status=%s", company.stock_code, existing.status)
            return {"stock_code": company.stock_code, "corp_name": company.corp_name, **_job_dump(existing)}
        now = datetime.now().isoformat(timespec="seconds")
        _jobs[company.stock_code] = IndexJob(
            stock_code=company.stock_code,
            status="queued",
            started_at=now,
            updated_at=now,
        )
    background_tasks.add_task(_run_index_job, company.stock_code)
    logger.info("index_request_queued stock_code=%s company=%s", company.stock_code, company.corp_name)
    return {"stock_code": company.stock_code, "corp_name": company.corp_name, **_job_dump(_jobs[company.stock_code])}


@app.get("/api/companies/{company_value}/index-status")
def index_status(company_value: str) -> dict[str, Any]:
    company = _require_company(company_value)
    with _jobs_lock:
        job = _jobs.get(company.stock_code)
        if job and job.status in {"queued", "indexing", "failed"}:
            return {"stock_code": company.stock_code, "corp_name": company.corp_name, **_job_dump(job)}
    return {"stock_code": company.stock_code, "corp_name": company.corp_name, **_current_index_status(company.stock_code)}


@app.get("/api/companies/{company_value}/summary")
def get_summary(company_value: str) -> dict[str, str]:
    company = _require_company(company_value)
    return _summary_for_company(company)


@app.post("/api/companies/{company_value}/summary")
def post_summary(company_value: str, payload: SummaryRequest | None = None) -> dict[str, str]:
    company = _require_company(payload.name if payload and payload.name else company_value)
    return _summary_for_company(company)


@app.get("/api/companies/{company_value}/filings")
def company_filings(company_value: str, index_type: str | None = None, limit: int = 50) -> dict[str, Any]:
    company = _require_company(company_value)
    filings = list_filings(company.stock_code, index_type=index_type, limit=limit)
    return {"stock_code": company.stock_code, "corp_name": company.corp_name, "filings": [_normalize_filing(row) for row in filings]}


@app.get("/api/filings/{receipt_no}")
def filing_detail(receipt_no: str) -> dict[str, Any]:
    filing = get_filing(receipt_no)
    if not filing:
        raise HTTPException(status_code=404, detail="filing not found")
    return _normalize_filing(filing)


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    question = (payload.prompt or payload.message or "").strip()
    company_value = payload.stock_code or payload.corp_code or payload.company or payload.company_name or ""
    company = resolve_company(company_value) if company_value else None
    stock_codes = [company.stock_code] if company else []
    logger.info("chat_request company_value=%r resolved_stock_codes=%s question_chars=%s", company_value, stock_codes, len(question))
    result = answer_question(question, stock_codes=stock_codes)
    logger.info(
        "chat_response route=%s source_count=%s missing_indexes=%s",
        result.get("route"),
        len(result.get("sources") or []),
        result.get("missing_indexes") or [],
    )
    return result


@app.post("/api/companies/stocks")
def stocks(payload: StockRequest) -> dict[str, Any]:
    company = resolve_company(payload.company or payload.name or "") or Company(stock_code="000000", corp_name=payload.company or payload.name or "선택 기업")
    result = fetch_stock_history(company.stock_code, payload.period)
    return {"stock_code": company.stock_code, "corp_name": company.corp_name, **result}


@app.post("/api/companies/stocks_realtime")
def stocks_realtime(payload: StockRequest) -> dict[str, Any]:
    company = resolve_company(payload.company or payload.name or "") or Company(stock_code="000000", corp_name=payload.company or payload.name or "선택 기업")
    result = fetch_realtime_stock(company.stock_code)
    return {"stock_code": company.stock_code, "corp_name": company.corp_name, **result}


def _run_index_job(stock_code: str) -> None:
    _set_job(stock_code, status="indexing")
    logger.info("index_job_started stock_code=%s", stock_code)
    try:
        result = rebuild_company_indexes(stock_code)
        _set_job(stock_code, status="ready", result=result)
        logger.info("index_job_ready stock_code=%s result=%s", stock_code, result)
    except Exception as exc:
        _set_job(stock_code, status="failed", error=str(exc))
        logger.exception("index_job_failed stock_code=%s", stock_code)


def _set_job(stock_code: str, status: Literal["queued", "indexing", "ready", "failed"], error: str = "", result: dict[str, Any] | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _jobs_lock:
        existing = _jobs.get(stock_code)
        started_at = existing.started_at if existing else now
        _jobs[stock_code] = IndexJob(
            stock_code=stock_code,
            status=status,
            started_at=started_at,
            updated_at=now,
            error=error,
            result=result,
        )


def _job_dump(job: IndexJob) -> dict[str, Any]:
    if hasattr(job, "model_dump"):
        return job.model_dump()
    return job.dict()


def _require_company(value: str | None) -> Company:
    company = resolve_company(value or "")
    if not company:
        logger.warning("company_not_found value=%r", value)
        raise HTTPException(status_code=404, detail=f"company not found: {value}")
    return company


def _current_index_status(stock_code: str) -> dict[str, Any]:
    regular_ready = (index_dir(stock_code, REGULAR_INDEX) / "index.faiss").exists()
    event_ready = (index_dir(stock_code, EVENT_INDEX) / "index.faiss").exists()
    regular_chunks = len(get_active_chunks(stock_code, REGULAR_INDEX))
    event_chunks = len(get_active_chunks(stock_code, EVENT_INDEX))
    regular_usable = regular_ready and regular_chunks > 0
    event_usable = event_ready and event_chunks > 0
    status = "ready" if regular_usable or event_usable else "not_indexed"
    return {
        "status": status,
        "indexes": {
            "regular": {
                "ready": regular_usable,
                "index_file_exists": regular_ready,
                "active_chunks": regular_chunks,
                "path": str(index_dir(stock_code, REGULAR_INDEX)),
            },
            "event": {
                "ready": event_usable,
                "index_file_exists": event_ready,
                "active_chunks": event_chunks,
                "path": str(index_dir(stock_code, EVENT_INDEX)),
            },
        },
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _summary_for_company(company: Company) -> dict[str, str]:
    return summary_service.get_or_build(company)


def _normalize_filing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "rcept_no": row.get("receipt_no"),
        "receipt_no": row.get("receipt_no"),
        "report_name": row.get("report_name"),
        "rcept_dt": row.get("receipt_date"),
        "receipt_date": row.get("receipt_date"),
        "filing_type": row.get("filing_type"),
        "detail_type": row.get("filing_detail_type"),
        "index_type": row.get("index_type"),
        "raw_path": row.get("raw_path"),
        "cleaned_path": row.get("cleaned_path"),
    }
