# Work Summary

작성일: 2026-06-09

## 큰 방향

오늘 작업의 중심은 DART 기반 기업 검색, 인덱싱 흐름, 프론트엔드 통합, logging, 그리고 공시 요약 카드 품질 개선이었다. 기존에는 공시 chunk를 그대로 잘라 summary 카드에 표시하는 수준이었고, DART 회사 검색도 저장된 SQLite/fallback 목록에 의존했다. 이를 실제 DART corp code 검색, summary cache layer, LLM 기반 카드 요약으로 확장했다.

## Backend 구조와 import 정리

- backend 패키지는 `backend/src` 기준으로 정리된 상태다.
- 기존 `src.*` 형태가 아니라 `backend.src.*` import를 사용한다.
- `backend/__init__.py`가 추가되어 package import가 가능하다.
- 기존에 과하게 나뉜 기능은 다음 방향으로 통합되어 있다.
  - 답변/검색 계층: `rag_service.py`
  - 문서 파싱/청킹/정형 추출: `document_processor.py`
  - DART 정기/이벤트 수집: `dart_service.py`

## Logging 및 run script

- backend logging 정책을 정리했다.
  - `backend/logs/app.log`: INFO/WARNING 중심
  - `backend/logs/error.log`: ERROR 이상
- 상위 `../run.sh`도 수정했다. 이 파일은 현재 repo 밖에 있어서 이번 commit에는 포함되지 않는다.
- `run.sh`는 로그를 `backend/logs` 아래로 모으도록 바뀌었다.
  - `backend.out.log`
  - `backend.err.log`
  - `frontend.out.log`
  - `frontend.err.log`
- screen monitor도 분리했다.
  - error monitor: error/stderr 추적
  - output monitor: 일반 stdout 추적

## Frontend 브랜치 반영

`frontend` 브랜치의 frontend 관련 변경을 현재 브랜치의 `frontend/` 아래로 가져왔다. 해당 브랜치는 루트에 frontend 파일들이 있었기 때문에 현재 구조에 맞게 매핑했다.

추가/변경된 주요 파일:

- `frontend/streamlit_app.py`
- `frontend/services/api_client.py`
- `frontend/ui/summary.py`
- `frontend/utils/text_cleaner.py`
- `frontend/styles/app.css`
- `frontend/README_FRONTEND.md`

변경 특징:

- API 호출 로직을 `frontend/services/api_client.py`로 분리했다.
- 요약 카드 렌더링을 `frontend/ui/summary.py`로 분리했다.
- 공시 원문/검색 context 정리를 `frontend/utils/text_cleaner.py`로 분리했다.
- 긴 inline CSS를 `frontend/styles/app.css`로 분리했다.
- 사용자가 요청한 대로 frontend 브랜치에서 새로 반영된 지점에는 주석을 남겼다.

## Frontend logging

새로 들어온 frontend 모듈에도 logging을 추가했다.

- `streamlit_app.py`
  - frontend 전용 logger 설정
  - stdout/stderr 분리
  - 기업 검색, watchlist 동기화, 인덱싱 상태, summary 요청, 주가/챗 흐름 로그 추가
- `services/api_client.py`
  - backend API 요청/응답/실패/JSON 파싱 실패 로그 추가
- `ui/summary.py`
  - summary render 상태 로그 추가
- `utils/text_cleaner.py`
  - 원문 내용은 남기지 않고 길이/축약 여부만 debug 로그로 기록

## DART 기업 검색 구현

`backend/src/company_lookup.py`의 `search_companies()`를 완성했다.

기존:

- SQLite `companies` 테이블
- hard-coded fallback 기업 목록

변경:

- DART corp code 목록을 사용해 실제 회사 검색을 수행한다.
- `OpenDartReader` 전체 객체를 초기화하지 않고 `OpenDartReader.dart_list.corp_codes()`를 직접 호출한다.
- 검색 결과는 `upsert_company()`로 SQLite에 캐시한다.
- 검색 순서는 fallback 대표 기업 -> SQLite 캐시 -> DART 결과다.
- DART API key 또는 dependency/network 문제가 있으면 warning log를 남기고 fallback으로 내려간다.

## Cache 경로 정리

캐시 생성 위치를 프로젝트 루트의 `cache/`로 모았다.

- `backend/src/config.py`
  - `CACHE_DIR = <project_root>/cache`
  - `ensure_cache_dir()`
- `backend/src/company_lookup.py`
  - DART corp code pickle을 `cache/opendartreader_corp_codes_YYYYMMDD.pkl`에 저장
  - 기존 `docs_cache/` 하드코딩 경로는 우회
- `.gitignore`
  - `cache/`
  - `docs_cache/`

기존 tracked cache였던 `docs_cache/opendartreader_corp_codes_20260608.pkl`는 삭제 대상으로 staged 할 계획이다.

## 인덱싱 흐름 파악

현재 인덱싱 흐름은 다음과 같다.

```text
frontend 기업 추가/선택
-> POST /api/companies/{company}/index
-> backend _queue_index_job()
-> 현재 index status 확인
-> 없으면 background task 큐잉
-> rebuild_company_indexes()
-> DART 정기공시/이벤트공시 수집
-> XML/text parsing
-> cleaned/raw 저장
-> SQLite filings/financials/event_disclosures/chunks 저장
-> OpenAI embedding
-> FAISS index 저장
-> frontend polling
-> summary 조회
```

확인한 한계:

- `/summary`는 원래 LLM 요약을 수행하지 않았다.
- 기존 summary는 chunk 앞부분 clipping과 정형 재무 line template에 가까웠다.
- index status는 regular/event 중 하나라도 usable이면 `ready`로 본다.
- summary는 `/index`가 먼저 호출된다는 frontend 전제에 기대고 있었다.

## LLM Summary Cache Layer

`backend/src/summary_service.py`를 추가했다.

목표:

- chunk를 직접 잘라 카드에 보여주는 대신, summary용 evidence package를 만들고 LLM 요약을 생성한다.
- 결과는 현재 frontend가 기대하는 7개 key dict로 유지한다.
- LLM 실패 시 기존 fallback summary를 사용한다.

추가된 저장소:

- `company_summaries`
  - `stock_code`
  - `corp_name`
  - `source_hash`
  - `summary_json`
  - `generated_by`
  - `status`
  - `error`
  - `updated_at`

동작:

```text
SummaryService.get_or_build(company)
-> source_hash 계산
-> company_summaries cache hit이면 반환
-> stale/miss이면 fallback 생성
-> OPENAI_API_KEY가 있으면 LLM JSON 요약 생성
-> 실패하면 fallback 사용
-> summary_json 저장
```

`api_server._summary_for_company()`는 이제 `SummaryService.get_or_build()`를 호출한다.

`pipeline.rebuild_company_indexes()` 완료 후에는 best-effort로 summary refresh를 시도한다. 실패해도 index rebuild 실패로 전파하지 않는다.

## Summary 카드 의미 조정

현재 summary key는 다음 의미로 정리했다.

- `overview`: 사업 개요
  - 무슨 회사인지
  - 주요 사업영역, 제품/서비스 범위, 고객/시장, 산업 내 역할
  - 실적 숫자는 사용하지 않도록 prompt에 명시
- `benefit`: 수익 구조
  - 어떻게 돈을 버는지
  - 제품/서비스/플랫폼/고객군/판매 방식/수수료/광고/구독/제조/용역/라이선스 등
  - 매출액/영업이익 숫자만 나열하지 않도록 prompt에 명시
- `earnings`: 실적 동향
  - financial data의 매출액/영업이익/당기순이익
  - 비교 기간 데이터가 없으면 증감 추세를 단정하지 않음
- `risk`: 주요 리스크
- `changing`: 주요 변화
- `status`: 공모 상태
  - 시스템 준비 상태가 아니라 IPO, 유상증자, 전환사채, 회사채, 증권 발행, 자금조달, 상장/상장폐지 등 공모/자금조달 상태
- `anomaly`: 특이사항

카드 혼동을 줄이기 위해 prompt version은 여러 차례 갱신했고 현재는 `summary_prompt.v5`다. 이 값은 `source_hash`에 포함되어 prompt가 바뀌면 기존 summary cache가 stale 처리된다.

## Frontend progress bar

인덱싱 progress bar 코드는 없어지지 않았지만, 표시 조건이 너무 엄격했다.

기존:

- `st.session_state.index_company == selected_company`가 정확히 일치해야 progress 표시

문제:

- backend 응답의 `corp_name`, `stock_code`, frontend 선택값이 다를 수 있어 상태가 있어도 표시되지 않을 수 있었다.

수정:

- `active_index_status()` helper 추가
- `company_name`, `index_company`, `corp_name`, `stock_code` 중 하나라도 매칭되면 현재 index 상태로 인정
- `render_index_progress()`, `monitor_initial_work()`, `fetch_summary()`가 이 helper를 사용

## 검증한 내용

작업 중 필요할 때 다음 검증을 실행했다.

- `py_compile` for backend/frontend 변경 파일
- DART company search 실제 호출
- frontend module import/compile

마지막 summary 관련 변경 후 확인:

- `~/projects/.venv/bin/python -m py_compile backend/src/summary_service.py`
- `~/projects/.venv/bin/python -m py_compile frontend/streamlit_app.py`

## 현재 주의할 점

- `backend/storage/companies/...`에 대량 삭제가 working tree에 잡혀 있다.
  - 이는 코드 변경이 아니라 추적 중인 생성 산출물이다.
  - 이번 commit에는 포함하지 않는다.
- `backend/storage/finance.db`도 DART 검색/summary 작업 중 변경되었다.
  - 생성 데이터 성격이 강하므로 이번 commit에는 포함하지 않는다.
- `backend/src/stock_service.py`에 `DEFAULT_PERIOD` 변경이 잡혀 있다.
  - 이 변경은 이번 summary/index 작업의 핵심 범위가 아니므로 commit에서 제외한다.
- repo 밖 `../run.sh`에 logging/screen monitor 변경이 있다.
  - 이 repo commit에는 포함되지 않는다.
  - 필요하면 상위 repo 또는 별도 관리 위치에서 커밋해야 한다.

## 다음에 볼 것

- summary card 실제 출력 샘플을 기업별로 확인해야 한다.
- `overview`, `benefit`, `earnings` 카드가 서로 충분히 구분되는지 확인해야 한다.
- `status` 카드가 공모 상태로 잘 요약되는지 확인해야 한다.
- `company_summaries` cache invalidation이 적절한지 확인해야 한다.
- storage 산출물을 git에서 계속 추적할지 정책을 정해야 한다.
