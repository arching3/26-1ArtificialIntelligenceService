# DART 기반 FAISS + SQLite Hybrid RAG

사용자가 입력한 기업 코드로 DART 최신 사업보고서를 가져오고, 정형 재무 수치는 SQLite에, 비정형 공시 문서는 FAISS에 저장한 뒤 질문 유형별로 근거를 조합해 답변하는 금융 RAG 프로토타입입니다.

## 파일 구조

```text
dart-inform
├── main.py             # Streamlit UI
├── data_processor.py   # DART 원문 수집, 정형/비정형 전처리
├── event_processor.py  # 최근 1년 주요사항 수시공시 전처리
├── data_loader.py      # SQLite + FAISS 적재
├── finance_store.py    # SQLite 저장/조회
├── query_router.py     # 질문 유형 라우팅
├── rag_engine.py       # Hybrid RAG 답변 생성
├── evaluate.py         # RAGAS 평가
├── requirements.txt
├── finance.db          # SQLite 산출물
├── faiss_index/        # FAISS 산출물
└── chroma_db/          # legacy 산출물, 사용하지 않음
```

## 핵심 구조

- 정형 재무 데이터: `finance.db`에 기업명, 사업연도, 매출액, 영업이익, 당기순이익, 보고서명, 접수번호를 저장합니다.
- 수시공시 이벤트 데이터: `finance.db`의 `event_disclosures` 테이블에 CB 발행, 타법인 주식 취득, 유상증자, 합병, 소송 등 최근 1년 주요사항을 저장합니다.
- 비정형 데이터: `faiss_index/`에 `II. 사업의 내용`, 위험 관련 chunk, 수시공시 원문 chunk를 저장합니다.
- 질문 라우팅: `query_router.py`가 질문을 `financial_numeric`, `comparison`, `business_text`, `risk_analysis`, `event_disclosure`, `unknown`으로 분류합니다.
- 답변 생성: `rag_engine.py`가 SQLite 조회 결과와 FAISS 검색 Context를 함께 LLM에 전달합니다.

## 데이터 파이프라인

`data_processor.py`는 DART API를 호출해 최신 사업보고서를 찾고 다음 데이터를 분리합니다.

- 정형 재무 수치: 매출액, 영업이익, 당기순이익
- 비정형 사업 내용: 엄격한 heading 기준의 `II. 사업의 내용`
- 정제 처리: HTML 태그, 엔티티, 이미지 참조, 탭/다중 공백, 3중 줄바꿈 제거
- 표 처리: HTML 표를 Markdown 표 또는 행 단위 텍스트로 변환
- Chunking: `RecursiveCharacterTextSplitter(chunk_size=2500, chunk_overlap=300)`

`event_processor.py`는 DART `OpenDartReader.event()`와 주요사항보고 목록을 사용해 최근 1년 수시공시 이벤트를 수집합니다.

- 대상 이벤트: CB/BW/EB 발행, 유상/무상증자, 감자, 타법인 주식 및 출자증권 양수·양도, 유형자산 양수·양도, 영업양수도, 자기주식, 합병·분할, 소송, 영업정지 등
- 정형화: `amount`, `target_company`, `purpose`, `conversion_price`, `conversion_shares`, `acquisition_shares`, `acquisition_ratio`, `payment_method`를 가능한 범위에서 추출합니다.
- 원문 처리: `rcept_no`가 있으면 공시 원문을 가져와 정제 후 `event_text`로 FAISS에 저장합니다.
- 원문 다운로드 실패 시에도 DART 이벤트 API row 기반의 정형 요약은 SQLite에 저장합니다.

`data_loader.py`는 동일 기업을 다시 학습할 때 기존 FAISS 문서 중 해당 `company_code` 문서를 제외하고 새 문서와 합쳐 재생성합니다. 이 방식으로 중복 chunk와 오염된 이전 chunk를 방지합니다.

FAISS metadata 주요 필드:

- `company_code`
- `company_name`
- `report_name`
- `receipt_no`
- `receipt_date`
- `section`
- `chunk_index`
- `chunk_total`
- `data_type`: `structured_financials`, `business_text`, `risk_text`, `event_text`
- `event_type`, `event_label`, `decision_date`
- `risk_type`: `legal`, `financial`, `business`, `market`, `safety`, `reputation`, `liquidity`, `credit`, `general`
- `source_type`: `DART`

## SQL을 쓰는 이유

RAG 검색만으로 숫자 질문을 처리하면 비슷한 chunk가 섞이거나 표의 행/열 해석이 틀릴 수 있습니다. 매출액, 영업이익, 당기순이익, 기업 간 비교처럼 정확한 수치가 중요한 질문은 SQLite에서 먼저 조회하고, LLM은 그 결과를 문장으로 설명하는 역할을 맡습니다.

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run main.py
```

`.env`에는 실제 키가 필요합니다.

```dotenv
DART_API_KEY=...
OPENAI_API_KEY=...
```

사용 모델:

- LLM: `gpt-5.4` (OpenAI, temperature=0)
- Embedding: `text-embedding-3-small` (OpenAI)

## 데이터 적재 검증

```bash
python -B -c "from data_loader import process_and_store_dart_data; [print(code, process_and_store_dart_data(code)) for code in ['005930','035420','051910']]"
```

통과 기준:

- 각 기업이 `True`를 반환합니다.
- `finance.db`에 기업별 `revenue`, `operating_profit`, `net_income`, `business_year`, `receipt_no`가 저장됩니다.
- `faiss_index/index.faiss`, `faiss_index/index.pkl`이 생성됩니다.
- 기업별 `structured_financials`, `business_text` 문서가 존재합니다.
- 위험 관련 문단이 감지되면 `risk_text`와 `risk_type`이 저장됩니다.
- 최근 1년 주요사항 공시가 있으면 SQLite `event_disclosures`와 FAISS `event_text`에 저장됩니다.
- 같은 기업을 다시 적재해도 해당 기업의 문서 수가 중복 증가하지 않습니다.

## 질문 처리 예시

- “삼성전자 2025년 매출액과 영업이익은?” → SQLite 정형 재무 조회
- “삼성전자와 네이버 중 2025년 매출액이 더 큰 회사는?” → SQLite 비교 조회
- “삼성전자 DS 부문은 무엇을 생산하나?” → FAISS 사업 내용 검색
- “HDC현대산업개발의 리스크는?” → FAISS 리스크 문서 검색
- “넥사다이내믹스의 최근 CB 발행 및 주식 취득 결정은?” → SQLite 이벤트 조회 + FAISS 수시공시 검색
- “삼성전자 최근 전환사채 발행 공시는?” → 최근 1년 이벤트 공시가 없으면 찾을 수 없다고 답변
- “공시 자료에 없는 내용” → 찾을 수 없다고 답변

## 평가 실행

```bash
python evaluate.py
```

`evaluate.py`는 SQL형 질문, 사업 내용 질문, 리스크 질문, 수시공시 이벤트 질문을 포함한 20개 QA를 실행하고 `evaluate_result.csv`를 생성합니다. 평가 지표는 `answer_relevancy`, `faithfulness`, `context_precision`, `context_recall`입니다.

## 2026-05-28 검증 결과

대상 기업 `005930`, `035420`, `051910` 기준으로 실제 DART/OpenAI API를 사용해 적재와 평가를 확인했습니다.

- 정적 검증: `python -B -m py_compile data_processor.py data_loader.py rag_engine.py evaluate.py finance_store.py query_router.py main.py` 통과
- FAISS 문서 수: 총 156개
- 기업별 FAISS 문서 수:
  - 삼성전자 `005930`: 42개
  - NAVER `035420`: 48개
  - LG화학 `051910`: 66개
- 기업별 필수 문서:
  - 각 기업마다 `structured_financials` 1개 존재
  - 각 기업마다 `business_text` 존재
  - 각 기업마다 `risk_text` 존재
- SQLite 저장 확인:
  - 삼성전자 2025년 매출액 `333,605,938,000,000원`, 영업이익 `43,601,051,000,000원`, 당기순이익 `45,206,805,000,000원`
  - NAVER 2025년 매출액 `12,035,007,218,975원`, 영업이익 `2,208,138,388,720원`, 당기순이익 `1,818,746,310,015원`
  - LG화학 2025년 매출액 `45,932,167,000,000원`, 영업이익 `1,180,900,000,000원`, 당기순이익 `-977,063,000,000원`
- 중복 방지: 삼성전자 재적재 후 총 FAISS 문서 수가 156개로 유지됨
- RAGAS 결과:
  - 평가 행 수: 15개
  - `answer_relevancy`: `0.6343`
  - `faithfulness`: `0.8556`
  - `context_precision`: `0.7332`
  - `context_recall`: `0.9333`
  - 4개 지표 모두 NaN 없음

## 2026-05-28 수시공시 이벤트 RAG 검증 결과

넥사다이내믹스 `351320` 기준으로 실제 DART/OpenAI API를 사용해 최근 1년 주요사항 이벤트 적재와 답변을 확인했습니다.

- 이벤트 처리: 최근 1년 이벤트 6건, `event_text` 문서 29개 생성
- FAISS 전체 문서 수: 196개
- 넥사다이내믹스 FAISS 문서 수:
  - `structured_financials`: 1개
  - `business_text`: 5개
  - `risk_text`: 5개
  - `event_text`: 29개
- SQLite `event_disclosures` 저장 확인:
  - 전환사채 발행 4건
  - 타법인 주식 및 출자증권 양수 1건
  - 유상증자 1건
- 주요 이벤트 예시:
  - 2026년 4월 13일 결정 85억원 전환사채 발행, 전환가액 1,303원, 전환가능주식수 6,523,407주
  - 더스타파트너 주식 21,000주 취득, 취득금액 20,000,001,000원, 취득 후 지분율 100.00%
- 중복 방지: 넥사다이내믹스 재적재 후 전체 FAISS 문서 수가 196개로 유지됨
- RAG 답변 확인:
  - “넥사다이내믹스의 최근 CB 발행 및 주식 취득 결정은?” 질문에 CB 금액, 전환가액, 전환가능주식수, 더스타파트너 취득금액과 지분율을 답변
  - “삼성전자 최근 전환사채 발행 공시는?” 질문은 이벤트 근거가 없어 찾을 수 없다고 답변

## 현재 범위

- v1 Hybrid RAG는 DART 공식 공시만 사용합니다.
- 외부 뉴스, 증권사 리포트, 실시간 주가 데이터는 v2 확장 항목입니다.
- 기존 `chroma_db/`는 legacy 산출물로 남겨 두지만 새 코드에서는 사용하지 않습니다.
