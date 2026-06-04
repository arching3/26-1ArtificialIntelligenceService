# RAGAS Operator Log

## 2026-06-03 KST

- action: evaluation preparation checkpoint
- status: ready for dry-run, final evaluation not started
- dataset: `eval/sample_ragas_dataset.jsonl`
- dataset_size: 300 questions
- company_count: 30
- metrics: `faithfulness`, `context_recall`
- throttling:
  - request_interval: 1.5 seconds
  - batch_size: 5
  - batch_sleep: 3 seconds
- log_monitor: `tail -f eval/ragas_eval.log`
- evaluation_log: `eval/ragas_eval.log`
- result_dir: `eval/results/`
- note: all 30 target companies have regular indexes prepared. Event indexes are absent for companies with no recent event filings.

Next planned steps:

1. Start log monitoring.
2. Run dry-run with `source ~/projects/venv.sh && python eval/run_ragas.py --limit 5`.
3. Check dry-run output files and `context_count` behavior.
4. If dry-run is healthy, run full evaluation with `source ~/projects/venv.sh && python eval/run_ragas.py`.
5. Record result file paths and any failure conditions here.

## 2026-06-03 KST - Evaluation Start

- action: user requested evaluation execution
- plan:
  1. Start log monitor subagent.
  2. Run dry-run with 5 samples.
  3. Inspect dry-run logs and output files.
  4. Run full 300-question evaluation if dry-run is healthy.
- safety:
  - Do not run full evaluation if dry-run has repeated `context_count=0`, authentication failure, rate limit failure, or RAGAS batch failure.

## 2026-06-03 KST - Dry-run Issue

- action: dry-run executed with 5 samples
- result: RAG answer/context collection succeeded for all 5 samples
- observed:
  - `context_count=8` for all 5 samples
  - `missing_indexes=[]`
- failure: RAGAS evaluation failed before batch execution
- cause: `ragas.metrics.collections` metrics require modern `InstructorLLM`, but the current project uses `LangchainLLMWrapper`
- fix: reverted metric imports in `eval/run_ragas.py` from `ragas.metrics.collections` to `ragas.metrics`
- next: rerun evaluation phase only using `--skip-collect --answers-jsonl eval/results/ragas_answers_20260603_153023.jsonl`

## 2026-06-03 KST - Dry-run Passed

- action: dry-run evaluation phase rerun using collected answers
- command: `source ~/projects/venv.sh && python eval/run_ragas.py --skip-collect --answers-jsonl eval/results/ragas_answers_20260603_153023.jsonl`
- result: success
- output:
  - answers: `eval/results/ragas_answers_20260603_153023.jsonl`
  - scores_jsonl: `eval/results/ragas_scores_20260603_153142.jsonl`
  - scores_csv: `eval/results/ragas_scores_20260603_153142.csv`
- observations:
  - rows: 5
  - `faithfulness`: populated for all rows
  - `context_recall`: populated for all rows
  - no missing indexes observed
- next: run full 300-question evaluation.

## 2026-06-03 KST - Full Evaluation Interrupted

- action: full 300-question evaluation started.
- result: interrupted during the RAGAS scoring phase.
- completed:
  - answer/context collection: 300/300
  - partial scoring: 240/300
- partial output:
  - answers: `eval/results/ragas_answers_20260603_153254.jsonl`
  - scores_jsonl: `eval/results/ragas_scores_20260603_153254.jsonl`
  - scores_csv: `eval/results/ragas_scores_20260603_153254.csv`
- observation:
  - no `run_complete` marker was written for the full run.
  - the last observed scoring log was around batch 49/60.

## 2026-06-04 KST - Full Evaluation Resumed And Completed

- action: evaluated the remaining 60 answer/context rows using `--skip-collect`.
- command: `source ~/projects/venv.sh && python eval/run_ragas.py --skip-collect --answers-jsonl eval/results/ragas_answers_20260603_153254_remaining_241_300.jsonl`
- result: success.
- resumed output:
  - scores_jsonl: `eval/results/ragas_scores_20260604_060607.jsonl`
  - scores_csv: `eval/results/ragas_scores_20260604_060607.csv`
- final merged output:
  - scores_jsonl: `eval/results/ragas_scores_20260603_153254_complete.jsonl`
  - scores_csv: `eval/results/ragas_scores_20260603_153254_complete.csv`
- final validation:
  - answers rows: 300
  - final score rows: 300
  - `faithfulness` count: 300
  - `context_recall` count: 300
- summary statistics:
  - `faithfulness`: mean 0.7649, std 0.3078, median 0.8856, q1 0.6667, q3 1.0000
  - `context_recall`: mean 0.7600, std 0.4271, median 1.0000, q1 1.0000, q3 1.0000
- observations:
  - rows with `context_count=0`: 11
  - rows with `missing_indexes`: 55
  - missing indexes were concentrated in event-index-missing companies and were expected from the prepared index state.

## 2026-06-04 KST - Revised XLSX Four-Metric Evaluation Completed

- action: evaluated `eval/RAGAS_수정질문목록.xlsx` with four metrics.
- command: `source ~/projects/venv.sh && python eval/run_ragas.py --dataset eval/RAGAS_수정질문목록.xlsx --metrics faithfulness,answer_relevancy,context_precision,context_recall --batch-size 5 --log-path eval/ragas_eval_revised.log`
- result: success.
- input observation:
  - sheet1 contained 10 evaluation rows.
  - all rows targeted Samsung Electronics (`005930`).
- output:
  - answers: `eval/results/ragas_answers_20260604_063552.jsonl`
  - scores_jsonl: `eval/results/ragas_scores_20260604_063552.jsonl`
  - scores_csv: `eval/results/ragas_scores_20260604_063552.csv`
  - log: `eval/ragas_eval_revised.log`
- validation:
  - answers rows: 10
  - score rows: 10
  - rows with `context_count=0`: 0
  - rows with `missing_indexes`: 0
- summary statistics:
  - `faithfulness`: mean 0.9500, std 0.1067, median 1.0000, q1 1.0000, q3 1.0000
  - `answer_relevancy`: mean 0.6200, std 0.1794, median 0.6296, q1 0.4752, q3 0.7257
  - `context_precision`: mean 0.5872, std 0.2588, median 0.6148, q1 0.5363, q3 0.6597
  - `context_recall`: mean 0.7000, std 0.4583, median 1.0000, q1 0.2500, q3 1.0000
- observations:
  - RAGAS emitted non-blocking deprecation warnings for legacy metric/wrapper imports.
  - `AnswerRelevancy` emitted non-blocking warnings that the LLM returned 1 generation instead of the requested 3 for some checks.

## 2026-06-04 KST - RAG vs General LLM Comparison

- action: compared plain LLM answers against existing service RAG answers for 10 revised XLSX questions.
- command: `source ~/projects/venv.sh && python eval/compare_rag_vs_general.py --rag-answers eval/results/ragas_answers_20260604_063552.jsonl --limit 10 --interval 1.5`
- result: success.
- output:
  - jsonl: `eval/results/rag_vs_general_20260604_065901.jsonl`
  - markdown: `eval/results/rag_vs_general_20260604_065901.md`
- sample mix:
  - `business_text`: 5
  - `risk_analysis`: 3
  - `financial_numeric`: 1
  - `event_disclosure`: 1
- observations:
  - RAG produced more source-grounded and filing-specific answers for business sections, risk disclosures, and stored financial figures.
  - Plain LLM answers were often plausible and broad but lacked filing receipt numbers, stored-report specificity, and exact numeric retrieval.
  - The event-disclosure sample exposed a retrieval/routing weakness: the RAG answer was specific but did not match the expected recent event-disclosure content.
