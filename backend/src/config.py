from pathlib import Path
import logging
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
logging.getLogger("dotenv.main").setLevel(logging.ERROR)
load_dotenv(BASE_DIR / ".env")

STORAGE_DIR = BASE_DIR / "storage"
CACHE_DIR = BASE_DIR.parent / "cache"
DB_PATH = STORAGE_DIR / "finance.db"
COMPANIES_DIR = STORAGE_DIR / "companies"
LOG_DIR = BASE_DIR / "logs"
APP_LOG_PATH = LOG_DIR / "app.log"
ERROR_LOG_PATH = LOG_DIR / "error.log"

EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4o-mini"

QUERY_ANALYZER_MODES = {"rules", "llm", "hybrid"}
QUERY_ANALYZER_MODE = os.getenv("QUERY_ANALYZER_MODE", "rules").strip().lower()
if QUERY_ANALYZER_MODE not in QUERY_ANALYZER_MODES:
    QUERY_ANALYZER_MODE = "rules"

QUERY_ANALYZER_MODEL = os.getenv("QUERY_ANALYZER_MODEL", LLM_MODEL).strip() or LLM_MODEL
try:
    QUERY_ANALYZER_TIMEOUT_SECONDS = float(
        os.getenv("QUERY_ANALYZER_TIMEOUT_SECONDS", "5")
    )
    if QUERY_ANALYZER_TIMEOUT_SECONDS <= 0:
        raise ValueError
except ValueError:
    QUERY_ANALYZER_TIMEOUT_SECONDS = 5.0

REGULAR_INDEX = "regular"
EVENT_INDEX = "event"
INDEX_TYPES = {REGULAR_INDEX, EVENT_INDEX}

EVENT_LOOKBACK_DAYS = 90
REGULAR_LOOKBACK_DAYS = 365
REGULAR_CHUNK_SIZE = 2500
REGULAR_CHUNK_OVERLAP = 300
EVENT_CHUNK_SIZE = 2500
EVENT_CHUNK_OVERLAP = 200


def ensure_storage_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    COMPANIES_DIR.mkdir(parents=True, exist_ok=True)


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def company_dir(stock_code: str) -> Path:
    return COMPANIES_DIR / stock_code


def raw_dir(stock_code: str) -> Path:
    path = company_dir(stock_code) / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleaned_dir(stock_code: str) -> Path:
    path = company_dir(stock_code) / "cleaned"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_dir(stock_code: str, index_type: str) -> Path:
    path = company_dir(stock_code) / "indexes" / index_type
    path.mkdir(parents=True, exist_ok=True)
    return path
