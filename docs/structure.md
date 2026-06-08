# 저장소 구조 개요

이 저장소는 DART 공시를 수집하고, 정형 재무 데이터는 SQLite로, 비정형 공시는 FAISS로 저장해 질의 응답하는 금융 RAG 프로젝트입니다.  
루트에는 백엔드, 스트림릿 프론트엔드, 정적 프론트엔드, 테스트, 샘플 데이터, 문서 파일이 함께 있습니다.

## 루트 기준 구성

```text
.
├── src/                # 현재 권장 백엔드/파이프라인 코드
├── legacy/             # v1 프로토타입 코드
├── tests/              # 동작 검증용 스크립트
├── storage/            # 기업별 DART 원문, 정제본, FAISS 산출물
├── assets/             # Streamlit 프론트엔드에서 쓰는 이미지
├── streamlit_app.py    # Streamlit 프론트엔드 진입점
├── index.html          # 정적 프론트엔드 진입점
├── app.js              # 정적 프론트엔드 로직
├── styles.css          # 정적 프론트엔드 스타일
├── requirements.txt    # Python 의존성
├── README.md           # 전체 개요와 실행 방법
├── README_V2_BACKEND.md  # v2 백엔드 설명
├── README_FRONTEND.md  # 프론트엔드 설명
├── handover.md         # 추가 문서
├── kid.md              # 추가 문서
└── LICENSE
```

## 실행 진입점

- `uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload`
  - FastAPI 백엔드 진입점입니다. `src/api_server.py`의 `app`을 실행합니다.
- `streamlit run streamlit_app.py`
  - 현재 권장 프론트엔드 진입점입니다. Streamlit UI를 띄웁니다.
- `python -m backend.src.pipeline 005930`
  - 단일 기업의 정기공시/이벤트 공시 인덱싱 파이프라인을 직접 실행합니다.
- `python -m backend.src.pipeline 351320 --event-only`
  - 이벤트 공시만 다시 적재할 때 사용하는 실행 경로입니다.
- `streamlit run legacy/main.py`
  - `legacy/` 아래 v1 프로토타입용 실행 경로입니다.

## `src/` 디렉터리

현재 권장 백엔드와 데이터 파이프라인이 들어 있습니다.

- `src/api_server.py`
  - FastAPI 서버입니다.
  - `/api/health`, `/api/companies/search`, `/api/companies/{company}/index`, `/api/chat` 같은 엔드포인트를 제공합니다.
  - 인덱싱 작업을 백그라운드 태스크로 돌리고, 요약 카드와 채팅 응답을 API로 제공합니다.
- `src/pipeline.py`
  - DART 공시를 수집하고 SQLite/FAISS 산출물을 다시 만드는 파이프라인입니다.
  - 정기공시와 이벤트 공시를 분리해 저장하고, 기업별 인덱스를 재생성합니다.
- `src/dart_collector.py`
  - 정기공시 목록 조회, 원문 다운로드, 정제본 저장을 담당합니다.
- `src/event_processor.py`
  - 최근 수시공시 이벤트를 수집하고, 이벤트 원문을 문서화합니다.
- `src/event_helpers.py`
  - 이벤트 공시의 정규화, 원문 정제, chunk 생성, 세부 정보 추출 보조 로직이 있습니다.
- `src/data_processor.py`
  - 정기공시 원문 정제, 사업 섹션 추출, 재무 수치 파싱, 위험 문단 판별 같은 저수준 텍스트 처리 헬퍼입니다.
- `src/text_processor.py`
  - `pipeline.py`가 사용하는 v2용 텍스트 처리 계층입니다.
  - `data_processor.py`의 저수준 함수들을 조합해 정형 재무 청크와 사업/리스크 청크를 만듭니다.
- `src/finance_store.py`
  - SQLite 스키마 생성과 기업/공시/재무/이벤트/chunk 저장, 조회를 담당합니다.
- `src/index_manager.py`
  - FAISS 인덱스를 생성, 저장, 로드, 검색합니다.
- `src/retriever.py`
  - 질문 의도를 분류한 뒤 regular/event 인덱스에서 검색 컨텍스트를 모읍니다.
- `src/answer_engine.py`
  - SQLite 결과와 FAISS 검색 결과를 합쳐 최종 답변을 만듭니다.
  - 투자 조언, 매수/매도 판단, 목표가 제시는 차단합니다.
- `src/query_router.py`
  - 질문을 `financial_numeric`, `comparison`, `business_text`, `risk_analysis`, `event_disclosure`, `unknown`으로 분류합니다.
- `src/company_lookup.py`
  - 종목코드와 회사명을 해석하고, SQLite 데이터와 하드코딩된 fallback 회사를 함께 검색합니다.
- `src/stock_service.py`
  - `yfinance`를 이용한 주가 히스토리와 실시간 조회를 제공합니다.
- `src/logging_config.py`
  - 파일 로그 설정을 담당합니다.
- `src/config.py`
  - 저장 경로, 모델명, chunk 크기, 인덱스 타입 같은 공통 설정을 모읍니다.
- `src/__init__.py`
  - `src` 패키지 마커입니다.

## `legacy/` 디렉터리

v1 프로토타입이 들어 있습니다. 현재 README 기준으로는 새 v2 코드와 분리된 상태입니다.

- `legacy/main.py`
  - v1 Streamlit 진입점입니다.
- `legacy/data_loader.py`
  - DART 데이터 적재와 저장을 담당하는 v1 로더입니다.
- `legacy/data_processor.py`
  - v1 정제/추출 로직입니다.
- `legacy/event_processor.py`
  - v1 이벤트 공시 처리 로직입니다.
- `legacy/query_router.py`
  - v1 질문 분류 로직입니다.
- `legacy/rag_engine.py`
  - v1 RAG 답변 엔진입니다.
- `legacy/finance_store.py`
  - v1 저장소 접근 코드입니다.
- `legacy/company_resolver.py`
  - v1 기업 해석 로직입니다.
- `legacy/evaluate.py`
  - v1 평가 실행 스크립트입니다.

## `tests/` 디렉터리

독립적인 테스트 프레임워크보다는, 현재 동작을 직접 확인하는 검증 스크립트가 들어 있습니다.

- `tests/check_summary_cards.py`
  - 기업 선택 후 요약 카드와 파일 산출물이 제대로 존재하는지 확인합니다.
- `tests/check_realtime_stock.py`
  - 주가 히스토리와 실시간 응답 형태를 검사합니다.
- `tests/check_frontend_add_company_indexing.py`
  - 프론트엔드의 기업 추가 흐름이 인덱싱으로 이어지는지 FastAPI TestClient로 점검합니다.

## `storage/` 디렉터리

실데이터와 인덱스 산출물이 들어가는 저장 영역입니다. 코드상 SQLite DB 경로는 `storage/finance.db`이지만, 현재 저장소에는 기업별 산출물이 더 분명하게 보입니다.

- `storage/companies/005930/`
  - 삼성전자 샘플 데이터입니다.
  - `raw/`에는 DART XML 원문이, `cleaned/`에는 정제 텍스트가, `indexes/`에는 FAISS 인덱스가 있습니다.
- `storage/companies/351320/`
  - 넥사다이내믹스 샘플 데이터입니다.
  - `raw/`, `cleaned/`, `indexes/` 구조가 동일합니다.
- `storage/companies/{stock_code}/indexes/regular/`
  - 정기공시 FAISS 인덱스(`index.faiss`, `index.pkl`)가 저장됩니다.
- `storage/companies/{stock_code}/indexes/event/`
  - 이벤트 공시 FAISS 인덱스(`index.faiss`, `index.pkl`)가 저장됩니다.

이 저장소에 포함된 샘플 파일은 실제로 `raw/*.xml`, `cleaned/*.txt`, `indexes/*/index.faiss`, `indexes/*/index.pkl` 형태로 확인됩니다.

## 프론트엔드 파일

- `streamlit_app.py`
  - 백엔드 API와 연결되는 Streamlit UI입니다.
  - `assets/dart-lens-hero.png`를 히어로 이미지로 사용합니다.
- `index.html`
  - 정적 프론트엔드의 마크업입니다.
- `app.js`
  - 정적 프론트엔드의 인터랙션과 예시 데이터 렌더링을 담당합니다.
- `styles.css`
  - 정적 프론트엔드의 스타일 정의입니다.
- `assets/dart-lens-hero.png`
  - Streamlit 화면의 배경 이미지로 사용됩니다.

## 문서와 설정 파일

- `README.md`
  - 전체 프로젝트 개요, 실행 경로, 데이터 파이프라인, 평가 결과가 정리돼 있습니다.
- `README_V2_BACKEND.md`
  - v2 백엔드 API와 저장 구조를 설명합니다.
- `README_FRONTEND.md`
  - Streamlit 프론트엔드 실행 방법과 연결 API를 설명합니다.
- `requirements.txt`
  - Python 의존성 목록입니다.
- `handover.md`, `kid.md`
  - 추가 문서 파일로 존재합니다.
- `LICENSE`
  - 라이선스 파일입니다.

## 구조상 읽히는 역할 분담

- 백엔드/파이프라인: `src/`
- 이전 프로토타입: `legacy/`
- 검증 스크립트: `tests/`
- 생성 산출물: `storage/`
- 프론트엔드 자산: `streamlit_app.py`, `index.html`, `app.js`, `styles.css`, `assets/`
- 문서와 실행 안내: `README*.md`, `requirements.txt`
