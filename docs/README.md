# DART Lens RAG

이 저장소는 DART 공시를 수집해 정형 재무 데이터는 SQLite에, 비정형 공시는 FAISS에 저장한 뒤 질의응답하는 금융 RAG 프로젝트입니다.  
현재 권장 실행 경로는 `backend/`의 FastAPI 백엔드와 `frontend/`의 Streamlit UI입니다.

## 한눈에 보기

- 백엔드: `backend/src/api_server.py`
- 파이프라인: `backend/src/pipeline.py`
- 프론트엔드: `frontend/streamlit_app.py`
- 평가 스크립트: `eval/`
- 검증 스크립트: `tests/`
- 저장 산출물: `backend/storage/`

## 저장소 구조

```text
.
├── backend/
│   ├── src/
│   │   ├── api_server.py       # FastAPI 백엔드
│   │   ├── pipeline.py         # DART 수집 및 인덱스 재생성
│   │   ├── dart_service.py     # DART 수집/정규화
│   │   ├── document_processor.py
│   │   ├── finance_store.py    # SQLite 저장/조회
│   │   ├── index_manager.py    # FAISS 저장/검색
│   │   ├── rag_service.py      # 질의응답 로직
│   │   ├── summary_service.py  # 프론트엔드 요약 카드 생성
│   │   ├── stock_service.py    # 주가 데이터 조회
│   │   ├── company_lookup.py   # 기업 해석/검색
│   │   ├── config.py           # 경로/모델/상수 설정
│   │   └── logging_config.py
│   └── storage/
│       ├── finance.db
│       └── companies/{stock_code}/
│           ├── raw/
│           ├── cleaned/
│           └── indexes/{regular,event}/
├── frontend/
│   ├── streamlit_app.py        # Streamlit 진입점
│   ├── app.js
│   ├── index.html
│   ├── styles.css
│   ├── assets/
│   ├── services/
│   ├── ui/
│   └── utils/
├── eval/
├── tests/
├── docs/
├── requirements.txt
├── run.sh
└── LICENSE
```

## 실행 준비

의존성 설치:

```bash
pip install -r requirements.txt
```

필수 환경변수:

```dotenv
DART_API_KEY=...
OPENAI_API_KEY=...
```

코드가 `.env`를 자동으로 읽습니다. 실행 환경에 따라 `backend/.env`와 저장소 루트 `.env` 중 하나에 두면 됩니다.

## 실행 방법

### 전체 실행

```bash
./run.sh start
```

`run.sh`는 FastAPI 백엔드와 Streamlit 프론트엔드를 함께 올리고, 로그를 `backend/logs/`에 남깁니다.

### 백엔드만 실행

```bash
uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload
```

### 프론트엔드만 실행

```bash
streamlit run frontend/streamlit_app.py
```

기본 접속 주소:

- 백엔드: `http://127.0.0.1:8000`
- 프론트엔드: `http://127.0.0.1:8501`

## 파이프라인 재실행

기업별 인덱스를 다시 만들 때는 `backend/src/pipeline.py`를 직접 실행합니다.

```bash
python -m backend.src.pipeline 005930
python -m backend.src.pipeline 351320 --event-only
python -m backend.src.pipeline 005930 --regular-only
```

이 파이프라인은 다음을 수행합니다.

- DART 정기공시 및 수시공시 수집
- 원문 저장
- 텍스트 정제 및 chunk 생성
- SQLite 적재
- 기업별 FAISS 인덱스 생성
- 프론트엔드 요약 카드 갱신

## 주요 기능

- 정형 재무 수치 조회
  - 매출액, 영업이익, 당기순이익 같은 숫자 질문은 SQLite를 우선 사용합니다.
- 사업/리스크 질의
  - 사업 설명, 위험 요인, 공시 문단은 FAISS 검색 결과를 사용합니다.
- 이벤트 공시 질의
  - 전환사채, 유상증자, 합병, 소송, 주식 취득 같은 수시공시를 다룹니다.
- 요약 카드
  - `overview`, `benefit`, `earnings`, `risk`, `changing`, `status`, `anomaly`를 제공합니다.
- 투자 조언 차단
  - 매수/매도, 목표가, 포트폴리오 비중 제시는 응답하지 않습니다.

## 데이터 저장 구조

실제 산출물은 `backend/storage/` 아래에 저장됩니다.

- `backend/storage/finance.db`
  - 기업, 공시 메타데이터, 재무 수치, 이벤트 공시, chunk 매핑을 저장합니다.
- `backend/storage/companies/{stock_code}/raw/`
  - DART 원문 XML 파일이 저장됩니다.
- `backend/storage/companies/{stock_code}/cleaned/`
  - 정제된 텍스트 파일이 저장됩니다.
- `backend/storage/companies/{stock_code}/indexes/regular/`
  - 정기공시 FAISS 인덱스가 저장됩니다.
- `backend/storage/companies/{stock_code}/indexes/event/`
  - 수시공시 FAISS 인덱스가 저장됩니다.

## 검증 스크립트

```bash
python tests/check_summary_cards.py 삼성전자
python tests/check_realtime_stock.py 005930
python tests/check_frontend_add_company_indexing.py 현대자동차
```

이 스크립트들은 현재 저장소 상태에서 다음을 확인합니다.

- DART 파일 수집 결과가 존재하는지
- FAISS 인덱스가 생성됐는지
- 프론트엔드 요약 카드가 비어 있지 않은지
- 주가 응답 형식이 올바른지
- 프론트엔드의 기업 추가 흐름이 인덱싱으로 이어지는지

## 평가

`eval/`에는 RAG 성능 비교와 RAGAS 평가용 스크립트와 결과가 있습니다.

- `eval/run_ragas.py`
- `eval/compare_rag_vs_general.py`
- `eval/sample_ragas_dataset.jsonl`
- `eval/ragas_evaluation_report.md`

## 관련 문서

- [백엔드 상세 설명](./README_V2_BACKEND.md)
- [프론트엔드 상세 설명](./README_FRONTEND.md)
- [저장소 구조 개요](./structure.md)
- [작업 인수인계](./handover.md)

