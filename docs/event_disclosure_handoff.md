# Event Disclosure RAG Handoff

## 목적

이 문서는 이벤트 공시 RAG 실패 사례를 다음 agent가 이어서 처리할 수 있도록 남기는 인수인계 메모입니다.

문제 사례:

```text
삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?
```

기대 답변은 삼성전자 최근 주요사항보고서의 자기주식 취득 결정 및 자기주식 처분 결정 요약입니다. 실제 실패 답변은 Galaxy S25 출시, Galaxy AI, Samsung Wallet/Health 등 정기보고서 사업 내용으로 흘렀습니다.

## 결론

1차 원인은 이벤트 공시 데이터 부재나 XML/원문 파싱 실패가 아닙니다.

현재 확인된 주 원인은 `src/query_router.py`의 이벤트 intent 키워드 누락입니다. 질문에 포함된 `이벤트 공시` 표현이 `event_disclosure`로 라우팅되지 않아 `intent=unknown`이 되고, retriever가 `regular + event`를 모두 검색합니다. 이때 regular index의 사업 내용 chunk가 상위에 올라와 잘못된 답변이 생성됩니다.

## 확인된 데이터 상태

삼성전자 `005930` 기준 이벤트 공시 원문과 cleaned 파일은 존재합니다.

```text
storage/companies/005930/raw/20260318001062.xml
storage/companies/005930/raw/20260318001203.xml
storage/companies/005930/cleaned/20260318001062.txt
storage/companies/005930/cleaned/20260318001203.txt
```

내용:

```text
20260318001062: 주요사항보고서(자기주식 취득 결정)
20260318001203: 주요사항보고서(자기주식 처분 결정)
```

event FAISS index도 존재합니다.

```text
storage/companies/005930/indexes/event/index.faiss
storage/companies/005930/indexes/event/index.pkl
```

DB active event chunk도 존재합니다.

```text
event active_chunks: 4

1010 20260318001203 event_text treasury_stock_disposal
1011 20260318001203 event_text treasury_stock_disposal
1012 20260318001062 event_text treasury_stock_acquisition
1013 20260318001062 event_text treasury_stock_acquisition
```

따라서 “없어서 못 가져오는” 상태가 아닙니다.

## 재현 결과

### 실패 질문

```text
삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?
```

라우팅:

```python
{
    "intent": "unknown",
    "company_codes": [],
    "stock_codes": [],
    "business_year": None,
    "metric": None,
    "event_types": [],
    "amounts": [],
}
```

검색 결과:

```text
route: both
sources: regular index chunks
```

대표적으로 `다. 사업부문별 현황 [DX 부문]`, `1. 사업의 개요`, `연구개발실적` 등 정기보고서 chunk가 반환됩니다.

### 정상 질문

```text
삼성전자의 최근 수시공시에는 어떤 내용이 포함되어 있나?
```

라우팅:

```python
{
    "intent": "event_disclosure",
    "event_types": [],
}
```

검색 결과:

```text
route: event_filing_rag
sources:
  1010 event 20260318001203 자기주식처분
  1013 event 20260318001062 자기주식취득
  1011 event 20260318001203 자기주식처분
  1012 event 20260318001062 자기주식취득
```

생성 답변은 자기주식 처분 결정과 자기주식 취득 결정을 정상 요약합니다.

## 관련 코드

### 라우터

파일:

```text
src/query_router.py
```

현재 `EVENT_KEYWORDS`에는 다음 표현들이 포함되어 있습니다.

```python
EVENT_KEYWORDS = [
    "CB", "전환사채", "신주인수권부사채", "교환사채",
    "유상증자", "무상증자", "감자",
    "주식 취득", "주식취득", "타법인", "출자증권",
    "합병", "분할", "소송", "영업정지", "자기주식",
    "주요사항", "수시공시", "공급계약", "최대주주",
    "벌금", "제재", "횡령", "배임", "상장폐지", "거래정지",
]
```

누락된 표현:

```text
이벤트
이벤트 공시
최근 공시
공시 내용
공시사항
주요 공시
```

`route_query()`는 `EVENT_KEYWORDS` 매칭에 실패하면 `intent=unknown`으로 보냅니다.

### Retriever

파일:

```text
src/retriever.py
```

중요 동작:

```python
def index_types_for_query(query_info):
    if intent == "event_disclosure":
        return [EVENT_INDEX]
    if intent in {"business_text", "risk_analysis", "financial_numeric", "comparison"}:
        return [REGULAR_INDEX]
    return [REGULAR_INDEX, EVENT_INDEX]
```

`event_disclosure`로만 라우팅되면 event index만 검색합니다. `unknown`이면 regular와 event를 모두 검색하므로, 추상적인 “최근 이벤트 공시” 질의에서 regular chunk가 상위에 올라갈 수 있습니다.

### 이벤트 파싱

파일:

```text
src/event_helpers.py
```

`_event_summary()`와 `_normalize_event()`가 event row에서 정형 필드를 추출합니다. 현재 자기주식 취득/처분의 raw text는 chunk에 잘 들어가지만, summary 필드는 충분히 풍부하지 않습니다.

관찰:

```text
자기주식취득 summary:
  이벤트, 보고서명, 접수번호, 접수일자, 목적은 존재
  취득예정금액, 취득예정주식수, 취득결정일은 summary에 충분히 반영되지 않음

자기주식처분 summary:
  이벤트, 보고서명, 접수번호, 접수일자는 존재
  처분예정금액, 처분예정주식수, 처분목적, 처분상대방은 raw text에는 있으나 summary 필드에는 제한적
```

따라서 파싱은 완전 실패가 아니라 “raw text 기반 답변은 가능하지만 summary 품질은 개선 여지 있음” 상태입니다.

## 다음 작업 권장 순서

### 1. 라우터 키워드 보강

가장 먼저 `src/query_router.py`의 `EVENT_KEYWORDS`에 다음 표현을 추가합니다.

```python
"이벤트",
"이벤트 공시",
"최근 공시",
"공시 내용",
"공시사항",
"주요 공시",
```

주의: `공시` 단독 키워드는 너무 넓습니다. 대부분의 질문이 공시 기반이므로 단독 `공시`는 `event_disclosure`로 보내지 않는 편이 안전합니다.

### 2. 자기주식 처분 event type 별도 추출

현재 `EVENT_TYPE_ALIASES`에서 `자기주식`은 `treasury_stock_acquisition` 쪽으로만 잡힙니다. 다음을 분리하는 것이 좋습니다.

```python
"treasury_stock_acquisition": ["자기주식 취득", "자기주식취득"],
"treasury_stock_disposal": ["자기주식 처분", "자기주식처분"],
```

단, “자기주식 취득 처분”처럼 둘 다 포함된 질문은 두 타입이 모두 잡히는지 테스트해야 합니다.

### 3. 추상적 최신 이벤트 질문의 검색 정렬 보강

`event_disclosure`이면서 `event_types=[]`인 경우에도 최신 receipt date 또는 receipt no 기준으로 summary chunk를 우선 반환하도록 정렬하면 안정적입니다.

현재 event 검색 결과에서 summary chunk와 후속 raw chunk가 섞입니다. `metadata.chunk_index == 1` 또는 `data_type == event_text` + 최신 `receipt_date`를 우선하는 정렬을 고려할 수 있습니다.

### 4. 이벤트 summary 정형 필드 보강

`src/event_helpers.py`의 `_normalize_event()`가 OpenDartReader event row의 자기주식 관련 컬럼을 더 읽도록 확장합니다.

우선 보강 대상:

```text
취득예정주식수
취득예정금액
취득예상기간
취득목적
취득방법
처분예정주식수
처분예정금액
처분예정기간
처분목적
처분상대방
결정일
```

현재 raw text에는 값이 있으므로, 정형 row 컬럼명을 확인한 뒤 summary에 넣으면 검색과 답변 모두 좋아집니다.

## 다음 agent용 확인 명령

가상환경:

```bash
source ~/projects/venv.sh
```

라우팅 확인:

```bash
python - <<'PY'
from backend.src.rag_service import route_query

queries = [
    "삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?",
    "삼성전자의 최근 수시공시에는 어떤 내용이 포함되어 있나?",
    "삼성전자의 최근 주요사항보고서에는 어떤 내용이 포함되어 있나?",
    "삼성전자 자기주식 취득 결정과 자기주식 처분 결정 내용을 요약해줘",
]

for query in queries:
    print(query)
    print(route_query(query))
    print()
PY
```

검색 결과 확인:

```bash
python - <<'PY'
from backend.src.finance_store import init_db
from backend.src.rag_service import retrieve_context_documents

init_db()

query = "삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?"
result = retrieve_context_documents(query, stock_codes=["005930"], k=8)

print(result["query_info"])
print("missing:", result["missing_indexes"])
for document in result["documents"]:
    metadata = document.metadata
    print(
        metadata.get("chunk_id"),
        metadata.get("index_type"),
        metadata.get("data_type"),
        metadata.get("event_type"),
        metadata.get("receipt_no"),
        metadata.get("section"),
    )
PY
```

답변 확인:

```bash
python - <<'PY'
from backend.src.rag_service import answer_question

queries = [
    "삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?",
    "삼성전자의 최근 수시공시에는 어떤 내용이 포함되어 있나?",
]

for query in queries:
    result = answer_question(query, ["005930"])
    print("QUERY:", query)
    print("ROUTE:", result.get("route"))
    print("QUERY_INFO:", result.get("query_info"))
    print("SOURCES:", [(s.get("chunk_id"), s.get("index_type"), s.get("receipt_no")) for s in result.get("sources", [])])
    print("ANSWER:", result.get("answer"))
    print()
PY
```

## 성공 기준

수정 후 아래 질문이 `event_disclosure`로 라우팅되어야 합니다.

```text
삼성전자의 최근 이벤트 공시에는 어떤 내용이 포함되어 있나?
```

성공 조건:

```text
intent: event_disclosure
route: event_filing_rag
sources: event index chunks
expected receipts:
  20260318001062
  20260318001203
answer includes:
  자기주식 취득 결정
  자기주식 처분 결정
  취득예정주식 또는 취득예정금액
  처분예정주식 또는 처분예정금액
```

## 관련 평가 산출물

RAG와 일반 LLM 비교 결과:

```text
eval/results/rag_vs_general_20260604_065901.md
eval/results/rag_vs_general_20260604_065901.jsonl
```

수정 질문 목록 평가 결과:

```text
eval/results/ragas_scores_20260604_063552.csv
eval/results/ragas_scores_20260604_063552.jsonl
eval/results/ragas_answers_20260604_063552.jsonl
```

운영 로그:

```text
eval/operator_log.md
```
