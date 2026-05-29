from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

STORAGE_DIR = BASE_DIR / "storage"
DB_PATH = STORAGE_DIR / "finance.db"
COMPANIES_DIR = STORAGE_DIR / "companies"

EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-5.4"

REGULAR_INDEX = "regular"
EVENT_INDEX = "event"
INDEX_TYPES = {REGULAR_INDEX, EVENT_INDEX}

EVENT_LOOKBACK_DAYS = 365
REGULAR_LOOKBACK_DAYS = 365
REGULAR_CHUNK_SIZE = 2500
REGULAR_CHUNK_OVERLAP = 300
EVENT_CHUNK_SIZE = 2500
EVENT_CHUNK_OVERLAP = 200


def ensure_storage_dirs() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    COMPANIES_DIR.mkdir(parents=True, exist_ok=True)


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
