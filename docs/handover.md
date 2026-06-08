# Handover

## 현재 기준

이 repo는 v2 기준으로 정리되어 있습니다.

- v2 백엔드: `src/`
- FastAPI 엔트리포인트: `src/api_server.py`
- Streamlit 프론트엔드: `streamlit_app.py`
- v1 프로토타입: `legacy/`

루트에 있던 v1 파일들은 `legacy/`로 이동했습니다. 새 백엔드 작업은 `src/` 기준으로만 이어가면 됩니다.

## 실행 방법

가상환경:

```bash
source ../venv.sh
```

백엔드:

```bash
uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload
```

프론트엔드:

```bash
streamlit run streamlit_app.py
```

필수 환경변수:

```dotenv
DART_API_KEY=...
OPENAI_API_KEY=...
```

LLM 모델은 `gpt-4o-mini`로 고정되어 있습니다.

## 주요 구조

```text
src/
  api_server.py       # FastAPI API 서버
  pipeline.py         # DART 수집, SQLite 저장, FAISS 재생성
  dart_collector.py   # 정기공시 수집
  event_processor.py  # 최근 3개월 이벤트 공시 수집
  data_processor.py   # 정기공시 정제/섹션 추출 helper
  event_helpers.py    # 이벤트 공시 정제/정규화 helper
  finance_store.py    # SQLite schema 및 조회/저장 함수
  index_manager.py    # 기업별 FAISS 인덱스 생성/로드/검색
  retriever.py        # 질문 intent별 regular/event 인덱스 검색
  answer_engine.py    # 공시 기반 답변 생성 및 투자 조언 guardrail
  company_lookup.py   # 기업명/종목코드 해석
  config.py           # storage path, 모델명, lookback 설정

legacy/
  main.py
  data_loader.py
  data_processor.py
  event_processor.py
  rag_engine.py
  evaluate.py
  ...
```

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

## 구현된 API

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

현재 `stocks`, `stocks_realtime`은 Streamlit UX 확인용 deterministic mock 데이터입니다. 실시간/과거 주가 API 연동은 아직 아닙니다.

## 동작 요약

- 개발 인증은 `POST /api/dev-login`으로 username만 받습니다. OIDC는 추후 교체 예정입니다.
- 관심 기업 watchlist는 현재 프로세스 메모리에 저장됩니다.
- 기업 검색은 SQLite 적재 기업을 우선 보고, 개발용 fallback 기업 목록을 함께 사용합니다.
- `POST /api/companies/{company}/index`는 FastAPI background task로 인덱싱을 시작합니다.
- 인덱스 상태는 FAISS 파일 존재만 보지 않고 SQLite active chunk가 있어야 `ready`로 판단합니다.
- 정기공시와 이벤트공시는 물리적으로 분리된 FAISS index로 관리합니다.
- 최근 이벤트 공시는 현재일 기준 3개월 lookback입니다.
- `answer_engine`은 공시 context 밖 내용을 지어내지 않도록 prompt를 제한하고, 주가 예측/매수매도/목표가/포트폴리오 비중 조언은 차단합니다.

## 실제 검증 결과

2026-05-29 기준 삼성전자 `005930`으로 실제 DART/OpenAI 연동을 확인했습니다.

- 정기공시 수집: 4건
- 정기공시 chunk: 95개
- 이벤트 공시 수집: 2건
- 이벤트 공시 chunk: 4개
- index status: `ready`
- OpenAI embedding 호출: 인덱싱 regular/event 각 1회, chat 검색 1회
- OpenAI chat completion 호출: 1회
- `/api/chat` 응답: 200
- route: `raw_filing_rag`
- source count: 8
- missing indexes: 없음

검증 명령:

```bash
python -m py_compile src/*.py legacy/*.py streamlit_app.py
uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8765
```

FastAPI `TestClient`로 `health`, `index-status`, `summary`, `chat` smoke test도 통과했습니다.

## 작업 중 수정한 주의점

- `OpenDartReader` import 방식은 설치된 패키지 형태에 맞춰 `import OpenDartReader`로 통일했습니다.
- 모델명은 레거시 코드까지 `gpt-4o-mini`로 맞췄습니다.
- 요약 카드 재무 문구는 `2026년 기준`처럼 모호하지 않게 `분기보고서 (2026.03) 3개월 누적 기준` 형태로 표시되도록 바꿨습니다.
- v2가 legacy helper를 import하지 않도록 `src/data_processor.py`, `src/event_helpers.py`를 추가했고 `src/text_processor.py`, `src/event_processor.py`는 relative import로 변경했습니다.

## 남은 작업

- Streamlit UX 직접 확인 후 API response shape 조정
- watchlist/user 상태를 DB로 영속화
- OIDC 로그인 연결
- 주가 mock API를 실제 데이터 소스로 교체
- 장기 인덱싱 작업 상태를 프로세스 메모리가 아닌 DB/job queue로 관리
- DART API 실패/부분 실패 메시지를 UI에서 더 명확히 표시
- RAGAS 평가 dataset과 평가 파이프라인을 v2 기준으로 재정리

## 현재 git 상태 관련 메모

commit은 아직 하지 않았습니다.

실제 DART 테스트로 `storage/companies/005930/` 아래 raw/cleaned/index 파일들이 생성 또는 갱신되었습니다. 이 산출물을 commit할지, 테스트 산출물로 제외할지는 팀에서 결정하면 됩니다.
