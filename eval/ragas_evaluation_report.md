# RAGAS 평가 준비 보고

## 평가 데이터

- 예시 데이터: `eval/sample_ragas_dataset.jsonl`
- 건수: 300개
- 중심 기업:
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

현재 평가셋은 30개 기업, 300개 질문으로 구성되어 있다. 초반 6개 기업은 기존 관심기업/기본 lookup 중심이며, 나머지는 기업별 10개 질문으로 확장된 평가셋이다.

## 데이터 포맷

각 JSONL row는 RAGAS 기본 평가 입력에 맞춰 구성했다.

- `question`: 평가 질문
- `answer`: 예시 답변
- `contexts`: 답변 근거 chunk 목록
- `ground_truth`: 기준 답변
- `metadata`: 기업코드, 기업명, 질문 유형

주의: 현재 파일의 `answer`와 `contexts`는 평가 파이프라인 예시다. 실제 점수 산출 시에는 이 값을 고정 샘플로 쓰지 말고, 현재 RAG 시스템이 생성한 답변과 retriever가 반환한 chunk로 교체해야 한다.

## 실행 환경

가상환경은 `~/projects/venv.sh`에 서술된 환경을 사용한다.

```bash
source ~/projects/venv.sh
```

## 평가 지표

이번 실행에서는 지표를 2개로 제한한다.

- `faithfulness`: 답변이 검색 context에 의해 뒷받침되는가
- `context_recall`: 정답 작성에 필요한 근거가 context에 충분히 포함되었는가

## 평가 절차

1. `eval/sample_ragas_dataset.jsonl`에서 `question`, `ground_truth`, `metadata`를 읽는다.
2. 각 질문을 현재 RAG 파이프라인에 입력한다.
3. 생성된 실제 `answer`와 검색된 실제 `contexts`를 수집한다. 샘플 간 요청 간격은 1.5초로 둔다.
4. 수집 결과를 RAGAS `Dataset`으로 변환한다.
5. RAGAS 지표를 5개 batch 단위로 실행한다.
6. batch 사이에는 3초 대기한다.
7. 질문별 점수를 수집한다.
8. 전체/기업별/질문유형별 통계를 산출한다.
9. 시각화 파일 생성을 준비한다.
10. 낮은 점수 사례는 원인을 `retrieval`, `chunking`, `generation`, `ground_truth` 문제로 분류한다.

## 실행 스크립트

- 스크립트: `eval/run_ragas.py`
- 로그: `eval/ragas_eval.log`
- 결과 디렉터리: `eval/results/`
- 평가 지표:
  - `Faithfulness`
  - `ContextRecall`
- 기본 요청 간격: 1.5초
- 기본 batch 크기: 5개
- 기본 batch 사이 대기: 3초

실행 예시:

```bash
source ~/projects/venv.sh
python eval/run_ragas.py
```

소량 dry-run:

```bash
source ~/projects/venv.sh
python eval/run_ragas.py --limit 5
```

답변과 context만 수집하고 RAGAS 평가는 건너뛰기:

```bash
source ~/projects/venv.sh
python eval/run_ragas.py --skip-evaluate
```

이미 수집된 답변 파일로 RAGAS 평가만 실행:

```bash
source ~/projects/venv.sh
python eval/run_ragas.py --skip-collect --answers-jsonl eval/results/ragas_answers_YYYYMMDD_HHMMSS.jsonl
```

스크립트는 실행 중 다음 이벤트를 로그에 남긴다.

- 평가 run 시작/종료
- 샘플별 RAG 답변 수집 시작/완료/실패
- 샘플별 소요 시간, context 수, source 수
- 요청 간 sleep
- batch별 RAGAS 평가 시작/완료/실패
- batch 사이 sleep
- 결과 파일 경로

## 로그 감시 계획

로그 감시 agent는 1개만 사용한다. 별도 세션에서 다음 로그를 실시간으로 본다.

```bash
tail -f eval/ragas_eval.log
```

감시 대상:

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

정상 진행은 batch 완료 단위로 보고하고, 실패 로그는 즉시 보고한다. 로그 감시 agent는 파일 수정이나 재실행 판단을 하지 않는다.

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

현재 `eval/run_ragas.py`는 기본 점수 CSV/JSONL을 생성한다. 후속 분석 스크립트에서는 이 결과를 읽어 통계와 시각화 자료를 만든다.

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

## 시각화 준비 계획

후속 분석 스크립트 후보: `eval/analyze_ragas.py`

생성 후보:

- `eval/results/ragas_metric_boxplot_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_by_company_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_by_question_type_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_scatter_YYYYMMDD_HHMMSS.png`
- `eval/results/ragas_low_score_cases_YYYYMMDD_HHMMSS.csv`
- `eval/results/ragas_summary_YYYYMMDD_HHMMSS.csv`
- `eval/results/ragas_report_YYYYMMDD_HHMMSS.md`

시각화는 `pandas`와 `matplotlib` 기반으로 준비한다. `matplotlib` 사용이 어려운 환경에서는 CSV와 Markdown 리포트만 먼저 생성한다.

## 실패 사례 분류

- `faithfulness` 낮음: LLM이 context에 없는 내용을 추가했을 가능성
- `context_recall` 낮음: 필요한 섹션이 chunking 또는 검색 결과에서 누락된 경우
- `missing_indexes` 존재: 인덱싱 미완료 또는 FAISS 파일 누락 가능성
- `evaluation_error` 존재: RAGAS 입력 형식, API 호출, evaluator 모델 설정 문제 가능성

## 다음 구현 후보

- `eval/analyze_ragas.py` 추가
- 질문별 `context_count`, `source_count`, `route`, `missing_indexes`를 CSV에도 포함
- 기업별/질문유형별 통계 CSV 생성
- 저점 사례 Markdown 리포트 생성
- matplotlib 기반 시각화 생성
