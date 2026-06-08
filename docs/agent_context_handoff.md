# Agent Context Handoff

## 범위

이 문서는 이 저장소에서 최근 작업하며 파악한 전체 맥락을 다음 agent에게 넘기기 위한 메모입니다. 코드 구조 설명보다는, 실제로 어떤 문제가 있었고 어떤 결론과 산출물이 남았는지에 집중합니다.

## 현재 저장소 방향

이 프로젝트는 DART 공시 기반 금융 RAG 서비스입니다. 현재 실질 작업 기준은 v2 백엔드인 `src/`와 프론트엔드 `frontend/`입니다.

핵심 실행 단위:

```text
src/api_server.py      FastAPI 백엔드
src/pipeline.py        DART 수집, 정제, SQLite 저장, FAISS 인덱싱
src/retriever.py       질문 intent별 regular/event index 검색
src/answer_engine.py   검색 context 기반 LLM 답변 생성
frontend/              정적 프론트엔드
eval/                  RAGAS 평가 스크립트와 결과
storage/               SQLite, raw/cleaned 공시, FAISS index 산출물
```

가상환경은 다음을 사용합니다.

```bash
source ~/projects/venv.sh
```

`backend.src.config`가 `.env`를 로드하므로, 단순 shell 환경에서는 `OPENAI_API_KEY`가 없어 보여도 `backend.src.config` import 이후에는 로드될 수 있습니다.

## 프론트엔드 관심기업 추가와 인덱싱

초기 문제는 프론트엔드에서 관심기업을 추가해도 공시 인덱싱이 제대로 이어지지 않아 “준비되지 않았습니다” 상태가 남는 것이었습니다.

파악한 구조:

```text
frontend -> backend watchlist/index API -> backend.src.api_server background task -> backend.src.pipeline -> storage/companies/{stock_code}/indexes
```

중요한 판단:

- index ready 여부는 FAISS 파일 존재만으로 보면 안 됩니다.
- SQLite active chunk와 FAISS index가 같이 있어야 실제 검색 가능 상태입니다.
- 인덱싱 진행 상태를 프론트엔드에 보여주려면 backend index status를 polling하고, UI는 기존 디자인을 해치지 않는 선에서 progress 상태를 표시하는 방식이 적절합니다.

관련 문서:

```text
docs/implement_plan.md
docs/dev_specification.md
docs/handover.md
```

## LLM 연결 상태 문제

LLM 질문 중 “연결중입니다”만 반복되는 문제가 있었습니다. 조사 방향은 다음이었습니다.

- frontend가 backend 응답 완료 상태를 제대로 받는지
- backend `/api/chat` 또는 관련 endpoint가 실제로 answer를 반환하는지
- streaming이 아니라 일반 요청/응답이라면 frontend pending state가 clear되는지
- 오류가 발생했을 때 frontend가 계속 loading state로 남는지

이후 진행 상태 표시와 답변 생성 중 애니메이션을 추가하는 방향으로 구현했습니다.

주의:

- UI 변경은 사용자가 한때 “UI 수정 X”라고 했던 구간이 있었으나, 이후 진행바와 답변 생성 애니메이션 구현은 명시적으로 승인되었습니다.
- 다음 agent는 이 맥락을 혼동하지 말고 최신 사용자 요청을 기준으로 판단해야 합니다.

## 청킹과 XML 파싱

이 저장소의 중요한 개선 방향은 기존 단순 텍스트 청킹에서 DART XML 구조를 더 활용하는 것입니다.

현재 관련 파일:

```text
src/filing_parser.py
src/text_processor.py
src/data_processor.py
src/pipeline.py
src/config.py
```

설정상 기본 chunk 크기:

```text
REGULAR_CHUNK_SIZE = 2500
REGULAR_CHUNK_OVERLAP = 300
EVENT_CHUNK_SIZE = 2500
EVENT_CHUNK_OVERLAP = 200
```

작업 중 논의된 방향:

- DART 정기공시는 XML이므로 heading, section, table을 구조적으로 파싱하는 것이 단순 문자열 분할보다 낫습니다.
- 사업 내용, 위험, 표 데이터를 metadata와 함께 분리 저장해야 검색 품질이 좋아집니다.
- 재무 수치는 RAG chunk가 아니라 SQLite 정형 데이터로 처리하는 것이 안정적입니다.
- 이벤트 공시는 정기공시와 다른 index type으로 분리하는 것이 맞습니다.

## RAGAS 평가 준비와 실행

평가 관련 핵심 산출물은 `eval/` 아래에 있습니다.

주요 스크립트:

```text
eval/run_ragas.py
eval/compare_rag_vs_general.py
```

`eval/run_ragas.py`는 다음 기능을 갖도록 확장되었습니다.

- JSONL dataset 읽기
- XLSX dataset 읽기
- RAG answer/context collect
- `--skip-collect`로 기존 answer/context만 scoring
- metric 선택 옵션
- 결과 JSONL/CSV 저장
- batch sleep, request interval 설정
- logging

지원 metric:

```text
faithfulness
answer_relevancy
context_precision
context_recall
```

요청 간격 정책:

```text
request interval: 1.5s
batch sleep: 3.0s
batch size: 기본 5
```

## 300건 RAGAS 평가 결과

300건 평가를 한 번 장기 실행했고, token/context 문제로 중간에 끊긴 뒤 나머지 60건을 resume하여 병합했습니다.

최종 파일:

```text
eval/results/ragas_answers_20260603_153254.jsonl
eval/results/ragas_scores_20260603_153254_complete.jsonl
eval/results/ragas_scores_20260603_153254_complete.csv
```

최종 통계:

```text
faithfulness:
  mean 0.7649
  std 0.3078
  median 0.8856
  q1 0.6667
  q3 1.0000

context_recall:
  mean 0.7600
  std 0.4271
  median 1.0000
  q1 1.0000
  q3 1.0000
```

관찰:

```text
context_count=0: 11
missing_indexes rows: 55
```

해석:

- retrieval이 되는 질문에서는 recall이 높은 편입니다.
- 하지만 일부 기업 또는 이벤트 index가 준비되지 않은 경우 context 자체가 비어 평가가 크게 흔들립니다.
- faithfulness 평균은 나쁘지 않지만, 검색 실패/부정확 context가 있는 질문에서 분산이 큽니다.

상세 기록:

```text
eval/operator_log.md
```

## 수정 질문 목록 XLSX 평가

사용자가 제공한 파일:

```text
eval/RAGAS_수정질문목록.xlsx
```

주의:

- 이 XLSX의 평가 질문 sheet에는 실제로 10개 문항만 있었습니다.
- 모두 삼성전자 `005930` 대상입니다.
- 두 번째 sheet에는 동료가 계산한 것으로 보이는 기존 요약 점수가 들어 있었습니다.

새로 실행한 fresh evaluation 결과:

```text
eval/results/ragas_answers_20260604_063552.jsonl
eval/results/ragas_scores_20260604_063552.jsonl
eval/results/ragas_scores_20260604_063552.csv
eval/ragas_eval_revised.log
```

통계:

```text
faithfulness       mean 0.9500, std 0.1067, median 1.0000
answer_relevancy   mean 0.6200, std 0.1794, median 0.6296
context_precision  mean 0.5872, std 0.2588, median 0.6148
context_recall     mean 0.7000, std 0.4583, median 1.0000
```

동료 점수와 차이:

```text
0.986, 0.799, 0.705, 0.800
```

이 값은 XLSX 두 번째 sheet에 이미 들어 있던 기존 요약값과 일치합니다. 현재 실행 결과와 다른 이유는 fresh run이 현재 answer/context를 새로 생성했기 때문으로 판단했습니다. RAGAS는 LLM judge와 embedding을 사용하므로 version, model, answer/context, metric class가 다르면 점수가 달라질 수 있습니다.

평가 중 특이사항:

- `AnswerRelevancy`에서 “3 generations requested, 1 returned” 경고가 있었습니다.
- RAGAS legacy metric/wrapper deprecation warning이 있었습니다.
- 둘 다 실행 중단 원인은 아니었습니다.

## 일반 LLM 호출 vs 서비스 RAG 비교

RAG 필요성을 설명하기 위해 XLSX 10개 질문에 대해 일반 LLM 호출과 서비스 RAG 답변을 비교했습니다.

스크립트:

```text
eval/compare_rag_vs_general.py
```

결과:

```text
eval/results/rag_vs_general_20260604_065901.md
eval/results/rag_vs_general_20260604_065901.jsonl
```

결론:

- RAG는 공시 기준 사업부문명, 출처, 접수번호, 저장 보고서 기준 수치, 공시상 리스크에서 필요성이 분명합니다.
- 일반 LLM은 자연스럽고 넓게 답하지만 최신 저장 공시 기준 수치와 구체 출처를 제공하지 못합니다.
- 이벤트 공시 질문에서는 RAG가 오히려 잘못된 regular context를 가져와 실패했습니다. 이는 RAG 불필요성이 아니라 라우팅/검색 문제입니다.

## 이벤트 공시 실패 분석

별도 상세 문서:

```text
docs/event_disclosure_handoff.md
```

핵심 결론:

- 삼성전자 이벤트 공시는 존재합니다.
- raw/cleaned 파일도 있고 event index도 있으며 DB active event chunk도 있습니다.
- “수시공시”, “주요사항보고서”, “자기주식”이라고 질문하면 정상적으로 event index를 검색합니다.
- “이벤트 공시”라는 표현은 `src/query_router.py`의 `EVENT_KEYWORDS`에 없어 `intent=unknown`으로 분류됩니다.
- `unknown`은 `regular + event`를 모두 검색하므로 regular chunk가 상위에 올라와 오답이 생성됩니다.

권장 수정:

```text
1. EVENT_KEYWORDS에 "이벤트", "이벤트 공시", "최근 공시", "공시 내용", "공시사항", "주요 공시" 추가
2. "자기주식취득"과 "자기주식처분" event type alias 분리
3. event_disclosure + event_types=[]일 때 최신 summary chunk 우선 정렬
4. 자기주식 취득/처분 summary 정형 필드 보강
```

## 현재 중요한 산출물 목록

문서:

```text
docs/handover.md
docs/dev_specification.md
docs/implement_plan.md
docs/eval_plan.md
docs/event_disclosure_handoff.md
docs/agent_context_handoff.md
```

평가:

```text
eval/operator_log.md
eval/run_ragas.py
eval/compare_rag_vs_general.py
eval/RAGAS_수정질문목록.xlsx
eval/results/ragas_scores_20260603_153254_complete.csv
eval/results/ragas_scores_20260604_063552.csv
eval/results/rag_vs_general_20260604_065901.md
```

## 작업 시 주의할 점

- 저장소에는 실제 DART/OpenAI 호출로 생성된 `storage/` 산출물이 많을 수 있습니다. 코드 변경과 데이터 산출물 변경을 구분해야 합니다.
- 같은 기업을 다시 인덱싱하면 `storage/companies/{stock_code}`와 `storage/finance.db`가 바뀔 수 있습니다.
- 평가를 다시 실행하면 `eval/results/`에 새 timestamp 파일이 생성됩니다.
- RAGAS 평가는 deterministic하지 않습니다. answer/context 파일을 고정하지 않으면 점수 비교가 어렵습니다.
- `--skip-collect`를 사용하면 기존 answer/context 기준으로 scoring만 재실행할 수 있습니다.
- `공시` 단독 키워드를 event intent로 보내면 일반 사업/재무 공시 질문까지 오분류될 가능성이 있습니다.

## 다음 agent에게 추천하는 첫 작업

가장 작은 효과적 수정은 이벤트 라우터 보강입니다.

수정 후보:

```text
src/query_router.py
```

검증 질문:

```text
삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?
삼성전자의 최근 수시공시에는 어떤 내용이 포함되어 있나?
삼성전자 자기주식 취득 결정과 자기주식 처분 결정 내용을 요약해줘
```

성공 기준:

```text
intent == event_disclosure
route == event_filing_rag
sources index_type == event
answer includes 자기주식 취득 결정 and 자기주식 처분 결정
```

이후 평가를 다시 돌린다면 먼저 10개 XLSX 문항만 대상으로 빠르게 확인하고, 그 다음 300건 평가로 확장하는 것이 비용과 시간 면에서 낫습니다.
