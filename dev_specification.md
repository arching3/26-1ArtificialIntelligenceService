# 개발 작업 명세

## 목적

이 문서는 지금까지 이 저장소에서 진행된 개발 작업을 개발자가 이어받을 수 있도록 정리한 문서입니다.

프로젝트의 현재 목표는 DART 공시를 수집하고, SQLite와 FAISS에 저장한 뒤, 사용자가 회사에 대해 질문하면 공시 기반으로 답변하는 금융 RAG 서비스를 만드는 것입니다.

## 현재 기준

- 현재 권장 백엔드는 `src/`입니다.
- FastAPI 엔트리포인트는 `src/api_server.py`입니다.
- 현재 권장 프론트엔드는 `streamlit_app.py`입니다.
- v1 프로토타입 코드는 `legacy/`로 분리했습니다.
- 루트에 있던 v1 파일들은 삭제 상태로 표시되고, 대응 파일은 `legacy/` 아래에 있습니다.
- 개발 문서로 `handover.md`, `kid.md`, `structure.md`가 추가되어 있습니다.

## 주요 작업 내용

### 1. v2 백엔드 구조 정리

`src/` 기준으로 백엔드와 데이터 파이프라인을 정리했습니다.

- `src/api_server.py`
  - FastAPI 서버를 제공합니다.
  - 회사 검색, 관심 기업, 인덱싱, 요약, 공시 목록, 공시 상세, 채팅, 주가 API를 제공합니다.
  - 요청 로그 미들웨어를 추가했습니다.
  - 인덱싱은 FastAPI background task로 실행합니다.
- `src/pipeline.py`
  - DART 공시 수집, SQLite 저장, FAISS 인덱스 재생성을 담당합니다.
- `src/dart_collector.py`
  - 정기공시 수집을 담당합니다.
- `src/event_processor.py`
  - 최근 이벤트 공시 수집을 담당합니다.
- `src/data_processor.py`
  - 정기공시 정제와 섹션/재무 데이터 추출 helper입니다.
- `src/event_helpers.py`
  - 이벤트 공시 정제, 정규화, chunk 생성을 담당합니다.
- `src/finance_store.py`
  - SQLite schema, 저장, 조회 로직을 담당합니다.
- `src/index_manager.py`
  - FAISS 인덱스 생성, 저장, 로드, 검색을 담당합니다.
- `src/retriever.py`
  - 질문 의도에 따라 regular/event 인덱스를 검색합니다.
- `src/answer_engine.py`
  - 공시 기반 답변을 생성하고 투자 조언성 답변을 차단합니다.
- `src/company_lookup.py`
  - 회사명과 종목코드 해석을 담당합니다.
- `src/stock_service.py`
  - `yfinance` 기반 주가 히스토리와 실시간 조회를 담당합니다.
- `src/logging_config.py`
  - 런타임 로그 파일 설정을 담당합니다.
- `src/config.py`
  - 저장 경로, 모델명, 인덱스 타입, lookback 설정을 모읍니다.

### 2. v1 코드 분리

기존 프로토타입 코드는 `legacy/`로 옮겼습니다.

주요 파일은 다음과 같습니다.

- `legacy/main.py`
- `legacy/data_loader.py`
- `legacy/data_processor.py`
- `legacy/event_processor.py`
- `legacy/query_router.py`
- `legacy/rag_engine.py`
- `legacy/finance_store.py`
- `legacy/company_resolver.py`
- `legacy/evaluate.py`

새 기능 개발은 `src/` 기준으로 진행하는 것이 원칙입니다.

### 3. API 구현

현재 구현된 주요 API는 다음과 같습니다.

```http
GET    /api/health
GET    /api/me
POST   /api/dev-login
GET    /api/me/watchlist
POST   /api/me/watchlist
DELETE /api/me/watchlist/{company_value}

GET    /api/companies/search
POST   /api/companies/list
POST   /api/companies/{company_value}/index
GET    /api/companies/{company_value}/index-status
GET    /api/companies/{company_value}/summary
POST   /api/companies/{company_value}/summary
GET    /api/companies/{company_value}/filings
GET    /api/filings/{receipt_no}

POST   /api/chat
POST   /api/companies/stocks
POST   /api/companies/stocks_realtime
```

인증은 아직 실제 인증이 아닙니다.

- `POST /api/dev-login`은 username만 받는 개발용 로그인입니다.
- watchlist는 현재 프로세스 메모리에 저장됩니다.
- OIDC와 DB 기반 사용자 저장은 후속 작업입니다.

### 4. 데이터 저장 구조

v2 저장소는 `storage/`를 사용합니다.

```text
storage/
  finance.db
  companies/{stock_code}/
    raw/
    cleaned/
    indexes/
      regular/
      event/
```

- `raw/`: DART XML 원문
- `cleaned/`: 정제된 텍스트
- `indexes/regular/`: 정기공시 FAISS 인덱스
- `indexes/event/`: 이벤트 공시 FAISS 인덱스
- `finance.db`: 기업, 공시, 재무, chunk 메타데이터 저장용 SQLite DB

현재 저장소에는 삼성전자 `005930`과 넥사다이내믹스 `351320` 관련 산출물이 보입니다.

### 5. RAG 동작

현재 질의 응답 흐름은 다음과 같습니다.

1. 사용자가 회사와 질문을 입력합니다.
2. `company_lookup`이 회사명 또는 종목코드를 해석합니다.
3. `retriever`가 질문 의도를 분류합니다.
4. 질문 의도에 따라 regular/event FAISS 인덱스를 검색합니다.
5. `answer_engine`이 검색된 공시 context를 바탕으로 답변합니다.
6. 매수, 매도, 목표가, 수익률 예측, 포트폴리오 비중 같은 투자 조언은 차단합니다.

인덱스 상태는 FAISS 파일 존재만으로 판단하지 않습니다. SQLite에 active chunk가 있어야 usable index로 봅니다.

### 6. 주가 API 변경

`src/stock_service.py`를 통해 주가 API를 분리했습니다.

- `fetch_stock_history(stock_code, requested_period)`
- `fetch_realtime_stock(stock_code)`

구현 특징은 다음과 같습니다.

- `yfinance`를 사용합니다.
- 한국 6자리 종목코드는 `.KS`, `.KQ` 후보로 조회합니다.
- 짧은 TTL cache를 사용합니다.
- 데이터가 없거나 provider 실패 시 `status: "empty"`와 error 메시지를 반환합니다.

주의: 외부 네트워크와 provider 상태에 따라 테스트 결과가 달라질 수 있습니다.

### 7. 로깅 추가

`src/logging_config.py`와 FastAPI 미들웨어로 로그를 추가했습니다.

- 일반 요청 로그
- 4xx warning 로그
- 5xx error 로그
- 인덱싱 job 상태 로그
- 주가 provider 요청/실패 로그

로그는 `logs/` 아래에 쌓이도록 구성되어 있고, `.gitignore`에 `logs/`가 포함되어 있습니다.

### 8. 문서 추가

다음 문서를 추가했습니다.

- `handover.md`
  - 개발자 인수인계용 요약입니다.
- `kid.md`
  - 비전공자도 이해할 수 있는 짧은 요약입니다.
- `structure.md`
  - 저장소 구조와 파일 역할 설명입니다.
- `dev_specification.md`
  - 지금까지의 개발 작업 명세입니다.

## 실행 방법

가상환경 활성화:

```bash
source ../venv.sh
```

필수 환경변수:

```dotenv
DART_API_KEY=...
OPENAI_API_KEY=...
```

백엔드 실행:

```bash
uvicorn src.api_server:app --host 127.0.0.1 --port 8000 --reload
```

Streamlit 프론트엔드 실행:

```bash
streamlit run streamlit_app.py
```

단일 기업 파이프라인 실행 예시:

```bash
python -m src.pipeline 005930
```

이벤트 공시만 재적재하는 예시:

```bash
python -m src.pipeline 351320 --event-only
```

## 검증 내용

`handover.md` 기준으로 삼성전자 `005930`에 대해 실제 DART/OpenAI 연동을 확인했습니다.

- 정기공시 수집: 4건
- 정기공시 chunk: 95개
- 이벤트 공시 수집: 2건
- 이벤트 공시 chunk: 4개
- index status: `ready`
- `/api/chat` 응답: 200
- route: `raw_filing_rag`
- source count: 8
- missing indexes: 없음

기본 컴파일 검증:

```bash
python -m py_compile src/*.py legacy/*.py streamlit_app.py
```

FastAPI smoke test로 `health`, `index-status`, `summary`, `chat` 경로를 확인했습니다.

추가 검증 스크립트는 `tests/`에 있습니다.

- `tests/check_summary_cards.py`
  - 공시 산출물과 프론트엔드 요약 카드 필드 검증
- `tests/check_realtime_stock.py`
  - 주가 히스토리와 실시간 응답 shape 검증
- `tests/check_frontend_add_company_indexing.py`
  - 프론트엔드 기업 추가 흐름과 인덱싱 연결 검증

## 현재 git 상태에서 보이는 변경 범위

수정 또는 추가된 범주는 다음과 같습니다.

- README 계열 문서 수정
- `.gitignore` 수정
- v1 루트 파일 삭제 및 `legacy/` 추가
- `src/` v2 백엔드 파일 다수 수정/추가
- `tests/` 검증 스크립트 추가
- `handover.md`, `kid.md`, `structure.md`, `dev_specification.md` 문서 추가
- `storage/companies/005930/`, `storage/companies/351320/` 산출물 생성 또는 갱신
- `.env.txt` 미추적 파일 존재

주의: `.env.txt`는 비밀값이 들어 있을 수 있으므로 commit 전에 반드시 확인해야 합니다.

## 후속 작업

우선순위가 높은 후속 작업은 다음과 같습니다.

1. Streamlit UX 직접 실행 확인 및 API response shape 최종 조정
2. watchlist와 사용자 상태를 SQLite 또는 별도 DB에 영속화
3. OIDC 로그인 연결
4. 주가 API의 provider 실패/빈 응답 UI 처리 강화
5. 장기 인덱싱 job 상태를 프로세스 메모리가 아닌 DB 또는 job queue로 관리
6. DART API 실패와 부분 실패 메시지를 UI에서 더 명확히 표시
7. RAGAS 평가 데이터셋과 평가 파이프라인을 v2 기준으로 재정리
8. `storage/` 산출물을 commit할지, 테스트 산출물로 제외할지 팀 기준 확정
9. `.env.txt`와 실제 API key가 저장소에 포함되지 않도록 보안 점검

## 개발 시 주의사항

- 새 백엔드 작업은 `src/` 기준으로 진행합니다.
- `legacy/`는 참고용으로 두고, v2 코드가 legacy helper를 import하지 않도록 유지합니다.
- 정기공시와 이벤트 공시는 별도 FAISS 인덱스로 관리합니다.
- index ready 여부는 FAISS 파일과 SQLite active chunk를 함께 확인해야 합니다.
- OpenAI 모델명은 현재 `gpt-4o-mini` 기준입니다.
- 투자 조언 guardrail은 완화하지 않는 것이 기본 방침입니다.
- 실제 DART/OpenAI/yfinance 호출은 네트워크와 API quota 영향을 받습니다.
- commit 전에는 `storage/`, `.env.txt`, 로그, 테스트 산출물 포함 여부를 반드시 확인해야 합니다.
- 가상환경은 run.sh을 읽어보면 어떤 식으로 처리할지 알 수 있습니다.