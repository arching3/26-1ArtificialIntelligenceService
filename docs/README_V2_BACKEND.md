# dart-inform-v2 Backend

현재 권장 백엔드는 `src/api_server.py` FastAPI 서버와 `src/` 기반 v2 파이프라인입니다.
v1 프로토타입은 `legacy/` 아래로 분리했습니다.

## 실행

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

`DART_API_KEY`가 없으면 서버는 실행되지만 신규 인덱싱 작업은 `failed` 상태가 됩니다.
`OPENAI_API_KEY`가 없으면 인덱스 재생성과 LLM 답변 생성이 불가능합니다.

질의 분석기 설정:

```dotenv
QUERY_ANALYZER_MODE=rules
QUERY_ANALYZER_MODEL=gpt-4o-mini
QUERY_ANALYZER_TIMEOUT_SECONDS=5
```

- `QUERY_ANALYZER_MODE`: `rules`는 규칙 기반 분석만, `llm`은 LLM 분석을, `hybrid`는 규칙과 LLM 분석을 함께 사용합니다. 기본값과 잘못된 값의 fallback은 `rules`입니다.
- `QUERY_ANALYZER_MODEL`: 질의 분석에 사용할 모델이며 기본값은 백엔드 기본 LLM 모델입니다.
- `QUERY_ANALYZER_TIMEOUT_SECONDS`: LLM 질의 분석 제한 시간(초)이며 기본값은 `5`입니다. 0 이하이거나 숫자가 아니면 기본값을 사용합니다.
- LLM 분석이 비활성화되었거나 API 키 누락, timeout, 호출 오류가 발생하면 규칙 기반 분석으로 fallback합니다.

## API

```http
GET  /api/health
GET  /api/me
POST /api/dev-login
GET  /api/me/watchlist
POST /api/me/watchlist
DELETE /api/me/watchlist/{company_value}
GET  /api/companies/search
POST /api/companies/list
POST /api/companies/{company_value}/index
GET  /api/companies/{company_value}/index-status
GET  /api/companies/{company_value}/summary
POST /api/companies/{company_value}/summary
GET  /api/companies/{company_value}/filings
GET  /api/filings/{receipt_no}
POST /api/chat
POST /api/companies/stocks
POST /api/companies/stocks_realtime
```

## 동작 구조

- 개발 인증: `POST /api/dev-login`으로 username만 받는 dev login을 둡니다. OIDC는 추후 교체 지점입니다.
- 관심 기업: 현재 프로세스 메모리에 watchlist를 저장합니다. 영속 사용자 저장소는 추후 DB로 분리합니다.
- 기업 검색: SQLite에 적재된 기업을 우선 찾고, 개발용 fallback 기업 목록을 함께 사용합니다.
- 인덱싱: `POST /api/companies/{company}/index`가 백그라운드 작업을 등록합니다.
- 인덱스 상태: FAISS 파일만 보지 않고 SQLite active chunk가 있어야 `ready`로 판단합니다.
- 요약 카드: SQLite 정형 재무, 정기공시 chunk, 이벤트공시 chunk를 조합해 `overview`, `benefit`, `earnings`, `risk`, `changing`, `status`, `anomaly`를 반환합니다.
- 채팅: 공시 기반 질문은 SQLite/FAISS context로 답하고, 주가 예측/매수매도/목표가/포트폴리오 비중 조언은 차단합니다.
- 주가 API: 현재 Streamlit UI 연결용 deterministic mock 데이터를 반환합니다. 실데이터 연동은 별도 작업입니다.

## 데이터 파이프라인

```bash
python -m backend.src.pipeline 005930
python -m backend.src.pipeline 351320 --event-only
```

파이프라인은 다음 산출물을 만듭니다.

- SQLite: 기업, 공시 metadata, 정형 재무, 이벤트 공시, chunk 원문, FAISS vector mapping
- FAISS: 기업별 `regular`, `event` 물리 인덱스
- 파일: `storage/companies/{stock_code}/raw`, `cleaned`, `indexes`

## 저장 구조

```text
storage/
  finance.db
  companies/
    {stock_code}/
      raw/
      cleaned/
      indexes/
        regular/
          index.faiss
          index.pkl
        event/
          index.faiss
          index.pkl
```

## 검색 스모크 체크

```python
from backend.src.rag_service import retrieve_context_text
print(retrieve_context_text("삼성전자 DS 부문은 무엇을 생산하나?", ["005930"])["context"][:1000])
```
