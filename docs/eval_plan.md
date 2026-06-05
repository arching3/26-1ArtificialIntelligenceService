# RAGAS 평가 실행 계획

## 목표

- `eval/sample_ragas_dataset.jsonl`의 300개 질문으로 RAG 품질을 평가한다.
- 평가 지표는 `faithfulness`, `context_recall` 2개만 사용한다.
- 평가 전 대상 기업의 DART 인덱스를 준비한다.
- 로그 감시는 `tail -f` 기반 subagent 1개로 분리한다.
- 질문별 점수를 수집하고 통계/시각화 산출 준비까지 진행한다.

## 실행 환경

가상환경은 `~/projects/venv.sh`에 서술된 환경을 사용한다.

```bash
source ~/projects/venv.sh
```

## 평가 대상 기업

- 삼성전자 `005930`
- SK하이닉스 `000660`
- 현대자동차 `005380`
- NAVER `035420`
- LG화학 `051910`
- 넥사다이내믹스 `351320`
- POSCO홀딩스 `005490`
- LG전자 `066570`
- LG에너지솔루션 `373220`
- 삼성SDI `006400`
- 카카오 `035720`
- 크래프톤 `259960`
- HMM `011200`
- HD한국조선해양 `009540`
- 삼성중공업 `010140`
- SK `034730`
- SK이노베이션 `096770`
- LG `003550`
- 삼성생명 `032830`
- 신한지주 `055550`
- 하나금융지주 `086790`
- KB금융 `105560`
- SK텔레콤 `017670`
- KT `030200`
- 한국전력공사 `015760`
- 엔씨소프트 `036570`
- 삼성에스디에스 `018260`
- 현대모비스 `012330`
- 기아 `000270`
- 포스코퓨처엠 `003670`

## 사전 인덱싱

평가 전 backend indexing API를 통해 대상 기업의 인덱싱을 큐잉한다.

```bash
POST /api/companies/{company}/index
GET  /api/companies/{company}/index-status
```

인덱싱 확인 기준:

- regular index active chunk 수가 0보다 큰지
- FAISS index 파일이 존재하는지
- 가능하면 event index도 준비되어 있는지
- 실패 시 `missing_indexes`, `failed`, backend log를 확인한다.

## 로그 감시 subagent

subagent는 1개만 사용한다.

역할:

- `tail -f eval/ragas_eval.log`로 평가 로그를 실시간 감시한다.
- 실패/오류 로그는 즉시 보고한다.
- 정상 진행은 batch 완료 단위로 보고한다.
- 코드 수정, 재실행 판단, 파일 변경은 하지 않는다.

감시 패턴:

- `collect_sample_failed`
- `evaluate_batch_failed`
- `missing_indexes`
- `no_context_found`
- `llm_answer_failed`
- `retrieve_search_failed`
- `rate_limit`
- `timeout`
- `evaluate_batch_complete`
- `run_complete`

## 작업자 로그

평가 로그(`eval/ragas_eval.log`)와 별도로, 장기 작업 중 main agent가 수행한 판단과 작업 상태를 남긴다.

로그 파일:

```text
eval/operator_log.md
```

기록 항목:

- 작업 시작/종료 시각
- 실행한 명령
- dry-run 시작/완료 여부
- 전체 평가 시작/완료 여부
- 생성된 결과 파일 경로
- 감지한 오류와 대응
- 중단/재시도 판단 근거
- 사용자가 돌아왔을 때 바로 확인해야 할 항목

기록 예시:

```markdown
## 2026-06-03 15:30 KST

- action: dry-run started
- command: `source ~/projects/venv.sh && python eval/run_ragas.py --limit 5`
- expected output:
  - `eval/ragas_eval.log`
  - `eval/results/ragas_answers_*.jsonl`
  - `eval/results/ragas_scores_*.csv`
- monitor: `tail -f eval/ragas_eval.log`
- next check: dry-run completion and context_count distribution
```

운영 원칙:

- 정상 진행은 주요 단계 단위로 기록한다.
- 오류 발생 시 오류 메시지 원문 일부, 원인 추정, 다음 조치를 기록한다.
- rate limit, authentication error, repeated `context_count=0`, repeated batch failure가 발생하면 무리하게 전체 평가를 계속하지 않고 operator log에 중단 사유를 남긴다.
- 평가 자체 로그는 `eval/ragas_eval.log`, 작업 판단 로그는 `eval/operator_log.md`로 분리한다.

## 평가 설정

- metrics:
  - `Faithfulness`
  - `ContextRecall`
- request interval: 1.5초
- batch size: 5
- batch sleep: 3초

## Dry-run

먼저 5개만 실행한다.

```bash
source ~/projects/venv.sh
python eval/run_ragas.py --limit 5
```

확인 항목:

- `eval/ragas_eval.log` 생성
- `collect_sample_complete` 로그
- `context_count`가 0으로만 반복되지 않는지
- `evaluate_batch_complete` 로그
- `eval/results/`에 answers/scores 파일 생성
- CSV에 `faithfulness`, `context_recall` 점수 생성

## 전체 평가

dry-run이 정상인 경우 전체 300개를 실행한다.

```bash
source ~/projects/venv.sh
python eval/run_ragas.py
```

생성 결과:

- `eval/results/ragas_answers_YYYYMMDD_HHMMSS.jsonl`
- `eval/results/ragas_scores_YYYYMMDD_HHMMSS.jsonl`
- `eval/results/ragas_scores_YYYYMMDD_HHMMSS.csv`
- `eval/ragas_eval.log`

## 질문별 점수 수집

각 질문마다 다음 필드를 확보한다.

- `index`
- `company_code`
- `company_name`
- `question_type`
- `question`
- `faithfulness`
- `context_recall`
- `route`
- `context_count`
- `source_count`
- `missing_indexes`
- `evaluation_error`

## 통계 산출 계획

대상 metric:

- `faithfulness`
- `context_recall`

전체 통계:

- `count`
- `mean`
- `std`
- `median`
- `min`
- `q1`
- `q3`
- `max`

그룹 통계:

- `company_name`별 `mean`, `std`, `median`, `q1`, `q3`
- `question_type`별 `mean`, `std`, `median`, `q1`, `q3`

저점 사례:

- `faithfulness < 0.6`
- `context_recall < 0.6`
- 두 지표 모두 `< 0.6`
- `missing_indexes` 존재
- `evaluation_error` 존재

## 시각화 준비

후속 분석 스크립트 후보:

```text
eval/analyze_ragas.py
```

생성 후보:

- `eval/results/ragas_metric_boxplot_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_by_company_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_by_question_type_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_scatter_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_low_score_cases_YYYYMMDD_HHMMSS.csv`
- `eval/results/ragas_summary_YYYYMMDD_HHMMSS.csv`
- `eval/results/ragas_report_YYYYMMDD_HHMMSS.md`

## 완료 후 리포트

최종 리포트에는 다음을 포함한다.

- 전체 평균, 표준편차, 중앙값, 사분위수
- 기업별 점수
- 질문 유형별 점수
- 저점 질문 목록
- `missing_indexes` 발생 여부
- 평가 실패 여부
- 원인 분류: `indexing`, `retrieval`, `chunking`, `generation`, `ground_truth`
- 개선 우선순위
