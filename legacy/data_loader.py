import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Tuple

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
import OpenDartReader

from data_processor import (
    DartProcessingError,
    make_business_chunk_text,
    make_structured_financial_text,
    process_company,
)
from event_processor import EVENT_LOOKBACK_DAYS, process_event_disclosures
from finance_store import init_db, upsert_company, upsert_event_disclosure, upsert_financials


logging.getLogger("dotenv.main").setLevel(logging.ERROR)
load_dotenv()

FAISS_INDEX_DIR = "./faiss_index"
EMBEDDING_MODEL = "text-embedding-3-small"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

RISK_PATTERNS = {
    "legal": ["소송", "제재", "영업정지", "법률", "분쟁"],
    "financial": ["우발부채", "차입", "재무", "손상", "채무"],
    "business": ["수주", "경쟁", "사업위험", "영업환경"],
    "market": ["시장위험", "환율", "외환", "이자율", "가격위험"],
    "safety": ["안전", "사고", "품질"],
    "reputation": ["평판", "브랜드", "신뢰"],
    "liquidity": ["유동성"],
    "credit": ["신용위험", "신용"],
}


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or value.startswith("your_"):
        raise ValueError(f"{name} 환경변수가 설정되어 있지 않습니다.")
    return value


def _detect_risk_type(text: str) -> str:
    for risk_type, keywords in RISK_PATTERNS.items():
        if any(keyword in text for keyword in keywords):
            return risk_type
    return "general"


def _is_risk_related(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return any(keyword in compact for keywords in RISK_PATTERNS.values() for keyword in keywords)


def _base_metadata(company_result, data_type: str, section: str) -> dict:
    structured_data = company_result.structured_data
    return {
        "company_code": company_result.company_code,
        "company_name": structured_data.get("company_name", ""),
        "report_name": structured_data.get("report_name", ""),
        "receipt_no": structured_data.get("receipt_no", ""),
        "receipt_date": structured_data.get("receipt_date", ""),
        "section": section,
        "data_type": data_type,
        "source_type": "DART",
        "risk_type": "",
    }


def _build_documents(company_result) -> List[Document]:
    structured_data = company_result.structured_data
    company_code = company_result.company_code
    receipt_no = structured_data.get("receipt_no", "")
    documents: List[Document] = []

    structured_metadata = _base_metadata(
        company_result,
        data_type="structured_financials",
        section="정형 재무 요약",
    )
    structured_metadata.update({"chunk_index": 0, "chunk_total": 1})
    documents.append(
        Document(
            page_content=make_structured_financial_text(structured_data),
            metadata=structured_metadata,
        )
    )

    chunk_total = len(company_result.chunks)
    for index, chunk in enumerate(company_result.chunks, start=1):
        business_metadata = _base_metadata(
            company_result,
            data_type="business_text",
            section="II. 사업의 내용",
        )
        business_metadata.update({"chunk_index": index, "chunk_total": chunk_total})
        business_doc = Document(
            page_content=make_business_chunk_text(
                chunk=chunk,
                structured_data=structured_data,
                chunk_index=index,
                chunk_total=chunk_total,
            ),
            metadata=business_metadata,
        )
        documents.append(business_doc)

        if _is_risk_related(chunk):
            risk_metadata = dict(business_metadata)
            risk_metadata.update(
                {
                    "data_type": "risk_text",
                    "section": "II. 사업의 내용 - 위험 관련 문단",
                    "risk_type": _detect_risk_type(chunk),
                }
            )
            documents.append(
                Document(
                    page_content=business_doc.page_content.replace("[비정형 사업 내용]", "[비정형 리스크 내용]", 1),
                    metadata=risk_metadata,
                )
            )

    logger.info(
        "[%s] FAISS 저장 문서 생성: structured=1, business=%s, risk=%s, receipt_no=%s",
        company_code,
        chunk_total,
        sum(1 for doc in documents if doc.metadata.get("data_type") == "risk_text"),
        receipt_no,
    )
    return documents


def _load_faiss_index(embeddings: OpenAIEmbeddings) -> FAISS | None:
    index_dir = Path(FAISS_INDEX_DIR)
    if not (index_dir / "index.faiss").exists() or not (index_dir / "index.pkl").exists():
        return None
    return FAISS.load_local(
        FAISS_INDEX_DIR,
        embeddings,
        allow_dangerous_deserialization=True,
    )


def _extract_documents(vector_store: FAISS | None) -> List[Document]:
    if vector_store is None:
        return []
    raw_docs = getattr(vector_store.docstore, "_dict", {})
    return [doc for doc in raw_docs.values() if isinstance(doc, Document)]


def _rebuild_faiss_index(new_documents: List[Document], embeddings: OpenAIEmbeddings, company_code: str) -> Tuple[int, int]:
    existing_store = _load_faiss_index(embeddings)
    existing_documents = _extract_documents(existing_store)
    preserved_documents = [
        doc for doc in existing_documents if doc.metadata.get("company_code") != company_code
    ]
    merged_documents = preserved_documents + new_documents
    if not merged_documents:
        raise ValueError("FAISS에 저장할 문서가 없습니다.")

    Path(FAISS_INDEX_DIR).mkdir(parents=True, exist_ok=True)
    rebuilt_store = FAISS.from_texts(
        texts=[doc.page_content for doc in merged_documents],
        embedding=embeddings,
        metadatas=[doc.metadata for doc in merged_documents],
    )
    rebuilt_store.save_local(FAISS_INDEX_DIR)
    return len(preserved_documents), len(new_documents)


def process_and_store_dart_data(company_code: str) -> bool:
    """
    DART 최신 사업보고서를 수집한 뒤 정형 재무 데이터는 SQLite에,
    비정형 공시 문서는 FAISS에 저장합니다.
    """
    try:
        company_code = company_code.strip()
        if not company_code:
            raise ValueError("company_code는 비어 있을 수 없습니다.")

        dart_api_key = _get_required_env("DART_API_KEY")
        _get_required_env("OPENAI_API_KEY")

        dart = OpenDartReader(dart_api_key)
        company_result = process_company(dart, company_code)
        if company_result.status != "success":
            raise DartProcessingError(company_result.error or "기업 데이터 처리 실패")

        documents = _build_documents(company_result)
        event_result = process_event_disclosures(
            dart,
            company_code,
            lookback_days=EVENT_LOOKBACK_DAYS,
        )
        documents.extend(event_result.documents)
        if len(documents) < 2:
            raise ValueError("FAISS에 저장할 문서가 부족합니다.")

        structured_data = company_result.structured_data
        init_db()
        upsert_company(company_code, structured_data.get("company_name", ""))
        upsert_financials(structured_data)
        for event_data in event_result.events:
            upsert_event_disclosure(event_data)

        embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
        preserved_count, new_count = _rebuild_faiss_index(documents, embeddings, company_code)

        logger.info(
            "[%s] SQLite/FAISS 저장 완료: preserved=%s, new=%s, events=%s, event_failed=%s, 경로=%s",
            company_code,
            preserved_count,
            new_count,
            len(event_result.events),
            len(event_result.failed_list),
            Path(FAISS_INDEX_DIR).resolve(),
        )
        return True

    except Exception:
        logger.exception("DART 데이터 처리 및 저장 중 오류가 발생했습니다.")
        return False


def process_batch_companies(company_list: Iterable[str]) -> dict:
    results = {}
    failed_list = []
    for raw_code in company_list:
        code = str(raw_code or "").strip()
        success = process_and_store_dart_data(code)
        results[code] = success
        if not success:
            failed_list.append(code)

    return {
        "results": results,
        "failed_list": failed_list,
        "summary": {
            "requested": len(results),
            "succeeded": sum(1 for ok in results.values() if ok),
            "failed": len(failed_list),
        },
    }
