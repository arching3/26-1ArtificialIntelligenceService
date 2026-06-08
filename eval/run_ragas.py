from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper
from ragas.metrics import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

from backend.src.rag_service import _sql_context, answer_question
from backend.src.company_lookup import resolve_company
from backend.src.config import EMBEDDING_MODEL, LLM_MODEL
from backend.src.finance_store import get_chunks_by_ids, init_db

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_DIR / "sample_ragas_dataset.jsonl"
DEFAULT_LOG = EVAL_DIR / "ragas_eval.log"
DEFAULT_RESULTS_DIR = EVAL_DIR / "results"
REQUEST_INTERVAL_SECONDS = 1.5
BATCH_SLEEP_SECONDS = 3.0
BATCH_SIZE = 5
DEFAULT_METRICS = "faithfulness,context_recall"
SCORE_COLUMNS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


def configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


logger = logging.getLogger("ragas_eval")


def load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fp:
        for line_no, line in enumerate(fp, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            for key in ("question", "ground_truth", "metadata"):
                if key not in row:
                    raise ValueError(f"{path}:{line_no} missing required key: {key}")
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def _xlsx_cell_value(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.get("t")
    value = cell.find("a:v", ns)
    inline = cell.find("a:is", ns)
    if cell_type == "s" and value is not None:
        return shared_strings[int(value.text or "0")]
    if cell_type == "inlineStr" and inline is not None:
        return "".join(text.text or "" for text in inline.findall(".//a:t", ns)).strip()
    return (value.text if value is not None else "").strip()


def _xlsx_column_number(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        return 0
    number = 0
    for char in match.group(1):
        number = number * 26 + ord(char) - ord("A") + 1
    return number


def _xlsx_rows(path: Path, sheet_name: str = "xl/worksheets/sheet1.xml") -> list[list[str]]:
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", ns):
                shared_strings.append("".join(text.text or "" for text in item.findall(".//a:t", ns)))

        root = ET.fromstring(archive.read(sheet_name))
        parsed_rows: list[list[str]] = []
        for row in root.findall("a:sheetData/a:row", ns):
            values: dict[int, str] = {}
            for cell in row.findall("a:c", ns):
                ref = cell.get("r", "")
                values[_xlsx_column_number(ref)] = _xlsx_cell_value(cell, shared_strings, ns)
            if not values:
                parsed_rows.append([])
                continue
            parsed_rows.append([values.get(index, "") for index in range(1, max(values) + 1)])
        return parsed_rows


def load_xlsx_dataset(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = _xlsx_rows(path)
    if not rows:
        return []

    header = [value.strip() for value in rows[0]]
    required = ["문항ID", "의도", "기업코드", "질문", "정답/기준답변", "예상 라우트"]
    missing = [name for name in required if name not in header]
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")

    index_by_name = {name: header.index(name) for name in header}
    loaded: list[dict[str, Any]] = []
    for row_no, values in enumerate(rows[1:], start=2):
        if not any(values):
            continue

        def cell(name: str) -> str:
            index = index_by_name[name]
            return values[index].strip() if index < len(values) else ""

        question = cell("질문")
        ground_truth = cell("정답/기준답변")
        company_code = cell("기업코드")
        if not question or not ground_truth:
            logger.warning("xlsx_row_skipped row=%s reason=missing_question_or_ground_truth", row_no)
            continue

        company = resolve_company(company_code)
        loaded.append(
            {
                "question": question,
                "ground_truth": ground_truth,
                "metadata": {
                    "question_id": cell("문항ID"),
                    "question_type": cell("의도"),
                    "company_code": company.stock_code if company else company_code,
                    "company_name": company.corp_name if company else "",
                    "expected_route": cell("예상 라우트"),
                },
            }
        )
        if limit and len(loaded) >= limit:
            break

    return loaded


def load_dataset(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".xlsx":
        return load_xlsx_dataset(path, limit=limit)
    return load_jsonl(path, limit=limit)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _stock_code_for_row(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") or {}
    company_value = metadata.get("company_code") or metadata.get("company_name") or ""
    company = resolve_company(str(company_value)) if company_value else None
    return company.stock_code if company else str(metadata.get("company_code") or "")


def _contexts_from_sources(sources: list[dict[str, Any]]) -> list[str]:
    chunk_ids = []
    for source in sources or []:
        chunk_id = source.get("chunk_id")
        if chunk_id is None:
            continue
        try:
            parsed = int(chunk_id)
        except (TypeError, ValueError):
            continue
        if parsed not in chunk_ids:
            chunk_ids.append(parsed)

    if not chunk_ids:
        return []
    chunks = get_chunks_by_ids(chunk_ids)
    return [str(chunk.get("content") or "").strip() for chunk in chunks if chunk.get("content")]


def _rag_contexts(row: dict[str, Any], answer_result: dict[str, Any], stock_code: str) -> list[str]:
    contexts = _contexts_from_sources(answer_result.get("sources") or [])
    sql_context = _sql_context(answer_result.get("query_info") or {}, [stock_code] if stock_code else [])
    if sql_context:
        return [sql_context, *contexts]
    return contexts


def collect_rag_outputs(
    seed_rows: list[dict[str, Any]],
    output_path: Path,
    request_interval: float,
) -> list[dict[str, Any]]:
    init_db()
    collected: list[dict[str, Any]] = []
    total = len(seed_rows)
    logger.info("collect_start samples=%s request_interval=%.1fs output=%s", total, request_interval, output_path)

    for index, row in enumerate(seed_rows, start=1):
        question = str(row["question"])
        stock_code = _stock_code_for_row(row)
        started_at = time.perf_counter()
        logger.info(
            "collect_sample_start index=%s/%s company=%s stock_code=%s question_chars=%s",
            index,
            total,
            (row.get("metadata") or {}).get("company_name", ""),
            stock_code,
            len(question),
        )
        try:
            result = answer_question(question, stock_codes=[stock_code] if stock_code else [])
            contexts = _rag_contexts(row, result, stock_code)
            item = {
                "question": question,
                "answer": result.get("answer") or "",
                "contexts": contexts,
                "ground_truth": row["ground_truth"],
                "metadata": row.get("metadata") or {},
                "rag": {
                    "route": result.get("route"),
                    "query_info": result.get("query_info") or {},
                    "sources": result.get("sources") or [],
                    "missing_indexes": result.get("missing_indexes") or [],
                },
            }
            collected.append(item)
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "collect_sample_complete index=%s/%s elapsed_ms=%.1f context_count=%s source_count=%s",
                index,
                total,
                elapsed_ms,
                len(contexts),
                len(result.get("sources") or []),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.exception("collect_sample_failed index=%s/%s elapsed_ms=%.1f error=%s", index, total, elapsed_ms, exc)
            collected.append(
                {
                    "question": question,
                    "answer": "",
                    "contexts": [],
                    "ground_truth": row["ground_truth"],
                    "metadata": row.get("metadata") or {},
                    "error": str(exc),
                }
            )

        write_jsonl(output_path, collected)
        if index < total:
            logger.info("collect_sleep seconds=%.1f", request_interval)
            time.sleep(request_interval)

    logger.info("collect_complete samples=%s output=%s", len(collected), output_path)
    return collected


def _sample_from_row(row: dict[str, Any]) -> SingleTurnSample:
    return SingleTurnSample(
        user_input=str(row["question"]),
        response=str(row.get("answer") or ""),
        retrieved_contexts=[str(context) for context in row.get("contexts") or []],
        reference=str(row["ground_truth"]),
    )


def _chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _score_value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value is None:
        return ""
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return value


def write_scores_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "index",
        "company_code",
        "company_name",
        "question_type",
        "question",
        *SCORE_COLUMNS,
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            metadata = row.get("metadata") or {}
            writer.writerow(
                {
                    "index": index,
                    "company_code": metadata.get("company_code", ""),
                    "company_name": metadata.get("company_name", ""),
                    "question_type": metadata.get("question_type", ""),
                    "question": row.get("question", ""),
                    **{column: _score_value(row, column) for column in SCORE_COLUMNS},
                }
            )


def _selected_metrics(metric_names: list[str], evaluator_llm: LangchainLLMWrapper) -> list[Any]:
    embeddings: LangchainEmbeddingsWrapper | None = None
    metrics: list[Any] = []
    for name in metric_names:
        normalized = name.strip().lower()
        if not normalized:
            continue
        if normalized in {"faithfulness", "faith"}:
            metrics.append(Faithfulness(llm=evaluator_llm))
        elif normalized in {"answer_relevancy", "answer_relevance", "response_relevancy", "response_relevance"}:
            if embeddings is None:
                embeddings = LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=EMBEDDING_MODEL))
            metrics.append(AnswerRelevancy(llm=evaluator_llm, embeddings=embeddings))
        elif normalized in {"context_precision", "ctx_precision", "context_precision_with_reference"}:
            metrics.append(ContextPrecision(llm=evaluator_llm))
        elif normalized in {"context_recall", "ctx_recall"}:
            metrics.append(ContextRecall(llm=evaluator_llm))
        else:
            raise ValueError(f"Unsupported metric: {name}")
    if not metrics:
        raise ValueError("At least one metric is required.")
    return metrics


def evaluate_batches(
    rows: list[dict[str, Any]],
    output_jsonl: Path,
    output_csv: Path,
    batch_size: int,
    batch_sleep: float,
    evaluator_model: str,
    metric_names: list[str],
) -> list[dict[str, Any]]:
    evaluator_llm = LangchainLLMWrapper(ChatOpenAI(model=evaluator_model, temperature=0))
    metrics = _selected_metrics(metric_names, evaluator_llm)
    scored_rows: list[dict[str, Any]] = []
    batches = list(_chunks(rows, batch_size))
    logger.info(
        "evaluate_start samples=%s batches=%s batch_size=%s batch_sleep=%.1fs metrics=%s evaluator_model=%s",
        len(rows),
        len(batches),
        batch_size,
        batch_sleep,
        ",".join(metric_names),
        evaluator_model,
    )

    for batch_index, batch_rows in enumerate(batches, start=1):
        started_at = time.perf_counter()
        logger.info("evaluate_batch_start batch=%s/%s size=%s", batch_index, len(batches), len(batch_rows))
        samples = [_sample_from_row(row) for row in batch_rows]
        dataset = EvaluationDataset(samples=samples)
        try:
            result = evaluate(dataset=dataset, metrics=metrics)
            frame = result.to_pandas()
            records = frame.to_dict(orient="records")
            for source_row, score_row in zip(batch_rows, records):
                merged = dict(source_row)
                for column in SCORE_COLUMNS:
                    if column in score_row:
                        merged[column] = score_row.get(column)
                scored_rows.append(merged)
        except Exception as exc:
            logger.exception("evaluate_batch_failed batch=%s/%s error=%s", batch_index, len(batches), exc)
            for source_row in batch_rows:
                merged = dict(source_row)
                for column in SCORE_COLUMNS:
                    if column in [metric.name for metric in metrics]:
                        merged[column] = None
                merged["evaluation_error"] = str(exc)
                scored_rows.append(merged)

        write_jsonl(output_jsonl, scored_rows)
        write_scores_csv(output_csv, scored_rows)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.info("evaluate_batch_complete batch=%s/%s elapsed_ms=%.1f", batch_index, len(batches), elapsed_ms)

        if batch_index < len(batches):
            logger.info("evaluate_batch_sleep seconds=%.1f", batch_sleep)
            time.sleep(batch_sleep)

    logger.info("evaluate_complete scored_samples=%s output_jsonl=%s output_csv=%s", len(scored_rows), output_jsonl, output_csv)
    return scored_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run throttled RAGAS evaluation for the DART RAG app.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--request-interval", type=float, default=REQUEST_INTERVAL_SECONDS)
    parser.add_argument("--batch-sleep", type=float, default=BATCH_SLEEP_SECONDS)
    parser.add_argument("--evaluator-model", default=os.getenv("RAGAS_EVALUATOR_MODEL", LLM_MODEL))
    parser.add_argument("--metrics", default=DEFAULT_METRICS)
    parser.add_argument("--answers-jsonl", type=Path, default=None)
    parser.add_argument("--skip-collect", action="store_true", help="Use --answers-jsonl and skip RAG answer collection.")
    parser.add_argument("--skip-evaluate", action="store_true", help="Only collect RAG answers and contexts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.log_path)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.results_dir.mkdir(parents=True, exist_ok=True)
    answers_path = args.answers_jsonl or args.results_dir / f"ragas_answers_{run_id}.jsonl"
    scores_jsonl = args.results_dir / f"ragas_scores_{run_id}.jsonl"
    scores_csv = args.results_dir / f"ragas_scores_{run_id}.csv"

    logger.info(
        "run_start dataset=%s limit=%s batch_size=%s request_interval=%.1fs batch_sleep=%.1fs skip_collect=%s skip_evaluate=%s",
        args.dataset,
        args.limit,
        args.batch_size,
        args.request_interval,
        args.batch_sleep,
        args.skip_collect,
        args.skip_evaluate,
    )
    metric_names = [name.strip() for name in args.metrics.split(",") if name.strip()]

    if args.skip_collect:
        rows = load_jsonl(answers_path, limit=args.limit)
        logger.info("loaded_existing_answers samples=%s path=%s", len(rows), answers_path)
    else:
        seed_rows = load_dataset(args.dataset, limit=args.limit)
        rows = collect_rag_outputs(seed_rows, answers_path, args.request_interval)

    if not args.skip_evaluate:
        evaluate_batches(
            rows,
            output_jsonl=scores_jsonl,
            output_csv=scores_csv,
            batch_size=args.batch_size,
            batch_sleep=args.batch_sleep,
            evaluator_model=args.evaluator_model,
            metric_names=metric_names,
        )

    logger.info("run_complete answers=%s scores_jsonl=%s scores_csv=%s log=%s", answers_path, scores_jsonl, scores_csv, args.log_path)


if __name__ == "__main__":
    main()
