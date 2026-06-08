from __future__ import annotations

import logging
from typing import Any

import re


logger = logging.getLogger(__name__)


# frontend 브랜치 변경: 공시 원문/검색 context를 카드에 맞는 짧은 문장으로 정리합니다.
def clean_disclosure_text(value: Any, max_sentences: int = 3, max_chars: int = 260) -> str:
    text = str(value or "").strip()
    if not text:
        logger.debug("frontend_disclosure_text_empty")
        return "응답 없음"

    raw_chars = len(text)
    text = re.sub(r"\[[^\]]*(?:비정형|SQLite|FAISS|Context|공시)[^\]]*\]", " ", text)
    text = re.sub(r"기업코드\s*:\s*\d+", " ", text)
    text = re.sub(r"회사명\s*:\s*.*?(?=\s+(?:보고서|접수번호|섹션|청크)\s*:|$)", " ", text)
    text = re.sub(r"보고서\s*:\s*.*?(?=\s+(?:접수번호|섹션|청크)\s*:|$)", " ", text)
    text = re.sub(r"접수번호\s*:\s*\d+", " ", text)
    text = re.sub(r"섹션\s*:\s*.*?(?=\s+청크\s*:|$)", " ", text)
    text = re.sub(r"청크\s*:\s*\d+/\d+", " ", text)
    text = re.sub(r"\([^)]*단위\s*:\s*[^)]*\)", " ", text)
    text = re.sub(r"\|[^.\n]{12,}\|", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+", text)
    readable = " ".join(sentence.strip() for sentence in sentences[:max_sentences] if sentence.strip())
    if not readable:
        readable = text
    if len(readable) > max_chars:
        readable = readable[:max_chars].rstrip() + "..."
        logger.debug("frontend_disclosure_text_truncated raw_chars=%s output_chars=%s", raw_chars, len(readable))
    else:
        logger.debug("frontend_disclosure_text_cleaned raw_chars=%s output_chars=%s", raw_chars, len(readable))
    return readable or "응답 없음"
