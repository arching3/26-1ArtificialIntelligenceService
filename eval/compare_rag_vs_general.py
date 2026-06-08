from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from backend.src.config import LLM_MODEL

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_RAG_ANSWERS = EVAL_DIR / "results" / "ragas_answers_20260604_063552.jsonl"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"


GENERAL_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "당신은 한국 상장기업과 공시를 설명하는 분석가입니다. "
            "검색 문맥이나 공시 원문은 제공되지 않습니다. "
            "질문에 간결하게 답하되, 확실하지 않은 최신 공시 수치나 최근 이벤트는 확정적으로 꾸며내지 마세요.",
        ),
        ("human", "{question}"),
    ]
)


COMPARE_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "두 답변을 평가 질문의 기준답변과 비교합니다. "
            "반드시 한국어로, 2~3문장으로만 답하세요. "
            "일반호출 답변과 RAG 답변의 핵심 차이, RAG가 도움이 된 지점 또는 부족한 지점을 구체적으로 말하세요.",
        ),
        (
            "human",
            "질문:\n{question}\n\n"
            "기준답변:\n{ground_truth}\n\n"
            "일반호출 답변:\n{general_answer}\n\n"
            "RAG 답변:\n{rag_answer}",
        ),
    ]
)


def load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _compact(text: str, limit: int = 260) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# RAG vs General LLM Comparison",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- model: {LLM_MODEL}",
        f"- samples: {len(rows)}",
        "",
        "## Summary",
        "",
    ]

    for row in rows:
        metadata = row.get("metadata") or {}
        lines.extend(
            [
                f"### {metadata.get('question_id') or row['index']}. {row['question']}",
                "",
                f"- question_type: `{metadata.get('question_type', '')}`",
                f"- RAG route: `{row.get('rag', {}).get('route', '')}`",
                f"- RAG context_count: `{row.get('rag_context_count', 0)}`",
                f"- 기준답변: {_compact(row.get('ground_truth', ''), 360)}",
                f"- 일반호출: {_compact(row.get('general_answer', ''), 420)}",
                f"- RAG 답변: {_compact(row.get('rag_answer', ''), 420)}",
                f"- 비교: {row.get('comparison', '')}",
                "",
            ]
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare plain LLM answers with service RAG answers.")
    parser.add_argument("--rag-answers", type=Path, default=DEFAULT_RAG_ANSWERS)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--interval", type=float, default=1.5)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    args = parser.parse_args()

    rows = load_jsonl(args.rag_answers, limit=args.limit)
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)

    output_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        question = str(row.get("question") or "")
        general_response = llm.invoke(GENERAL_PROMPT.format_messages(question=question))
        general_answer = str(getattr(general_response, "content", general_response))
        time.sleep(args.interval)

        comparison_response = llm.invoke(
            COMPARE_PROMPT.format_messages(
                question=question,
                ground_truth=row.get("ground_truth") or "",
                general_answer=general_answer,
                rag_answer=row.get("answer") or "",
            )
        )
        comparison = str(getattr(comparison_response, "content", comparison_response))
        time.sleep(args.interval)

        output_rows.append(
            {
                "index": index,
                "question": question,
                "ground_truth": row.get("ground_truth") or "",
                "general_answer": general_answer,
                "rag_answer": row.get("answer") or "",
                "comparison": comparison,
                "metadata": row.get("metadata") or {},
                "rag": row.get("rag") or {},
                "rag_context_count": len(row.get("contexts") or []),
            }
        )
        print(f"completed {index}/{len(rows)}: {question[:40]}", flush=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    jsonl_path = args.results_dir / f"rag_vs_general_{run_id}.jsonl"
    markdown_path = args.results_dir / f"rag_vs_general_{run_id}.md"
    write_jsonl(jsonl_path, output_rows)
    write_markdown(markdown_path, output_rows)
    print(f"jsonl={jsonl_path}")
    print(f"markdown={markdown_path}")


if __name__ == "__main__":
    main()
