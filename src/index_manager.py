from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Iterable, List

import faiss
import numpy as np
from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from .config import EMBEDDING_MODEL, INDEX_TYPES, index_dir
from .finance_store import get_active_chunks, replace_faiss_mappings

logger = logging.getLogger(__name__)


def _embedding_client() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def _validate_index_type(index_type: str) -> None:
    if index_type not in INDEX_TYPES:
        raise ValueError(f"Unsupported index_type: {index_type}")


def rebuild_index(stock_code: str, index_type: str) -> Dict[str, int | str]:
    _validate_index_type(index_type)
    chunks = get_active_chunks(stock_code, index_type)
    target_dir = index_dir(stock_code, index_type)
    if not chunks:
        raise ValueError(f"No active chunks to index: {stock_code}/{index_type}")

    embeddings = _embedding_client()
    texts = [chunk["content"] for chunk in chunks]
    vectors = embeddings.embed_documents(texts)
    if not vectors:
        raise ValueError(f"Embedding returned no vectors: {stock_code}/{index_type}")

    vector_array = np.array(vectors, dtype="float32")
    dimension = int(vector_array.shape[1])
    index = faiss.IndexFlatL2(dimension)
    index.add(vector_array)

    docstore = InMemoryDocstore(
        {
            str(chunk["id"]): Document(
                page_content="",
                metadata={
                    "chunk_id": int(chunk["id"]),
                    "stock_code": chunk["stock_code"],
                    "receipt_no": chunk.get("receipt_no") or "",
                    "index_type": chunk["index_type"],
                    "data_type": chunk["data_type"],
                    "section": chunk.get("section") or "",
                },
            )
            for chunk in chunks
        }
    )
    index_to_docstore_id = {vector_id: str(chunk["id"]) for vector_id, chunk in enumerate(chunks)}
    vector_store = FAISS(
        embedding_function=embeddings,
        index=index,
        docstore=docstore,
        index_to_docstore_id=index_to_docstore_id,
    )
    vector_store.save_local(str(target_dir))
    replace_faiss_mappings(
        stock_code,
        index_type,
        [(vector_id, int(chunk["id"])) for vector_id, chunk in enumerate(chunks)],
    )
    logger.info("[%s/%s] FAISS rebuilt: chunks=%s path=%s", stock_code, index_type, len(chunks), target_dir)
    return {
        "stock_code": stock_code,
        "index_type": index_type,
        "chunk_count": len(chunks),
        "path": str(target_dir),
    }


def load_index(stock_code: str, index_type: str) -> FAISS:
    _validate_index_type(index_type)
    target_dir = index_dir(stock_code, index_type)
    if not (target_dir / "index.faiss").exists() or not (target_dir / "index.pkl").exists():
        raise FileNotFoundError(f"FAISS index not found: {target_dir}")
    return FAISS.load_local(
        str(target_dir),
        _embedding_client(),
        allow_dangerous_deserialization=True,
    )


def search_chunk_ids(stock_code: str, index_type: str, query: str, k: int = 8, fetch_k: int = 40) -> List[int]:
    vector_store = load_index(stock_code, index_type)
    try:
        docs = vector_store.max_marginal_relevance_search(query, k=k, fetch_k=fetch_k, lambda_mult=0.35)
    except Exception:
        docs = vector_store.similarity_search(query, k=k)
    chunk_ids: List[int] = []
    for doc in docs:
        chunk_id = doc.metadata.get("chunk_id")
        if chunk_id is not None and int(chunk_id) not in chunk_ids:
            chunk_ids.append(int(chunk_id))
    return chunk_ids


def rebuild_indexes(stock_code: str, index_types: Iterable[str]) -> Dict[str, Dict[str, int | str]]:
    results = {}
    for index_type in index_types:
        results[index_type] = rebuild_index(stock_code, index_type)
    return results
