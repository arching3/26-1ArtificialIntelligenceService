# 구현 계획: 관심기업 인덱싱과 LLM 대기 UX

## 문제

현재 Streamlit 프론트엔드에서 관심기업을 추가하면 watchlist 저장과 요약 조회는 실행되지만, 신규 기업의 DART 공시 인덱싱이 사용자 흐름과 충분히 연결되어 있지 않았다. 또한 LLM 채팅 요청은 백엔드 응답이 늦으면 화면이 멈춘 것처럼 보이고, 기존 8초 timeout 때문에 “연결중입니다” fallback이 반복될 수 있었다.

## 목표

- 관심기업 추가/선택 시 신규 기업의 공시 인덱싱을 자동으로 시작한다.
- UI를 크게 바꾸지 않고 요약 영역에 인덱싱 진행 상태와 progress bar를 표시한다.
- LLM 답변 생성 중에는 사용자가 기다림 상태를 알 수 있도록 “답변 생성 중...” spinner를 표시한다.
- 채팅 요청에는 일반 API보다 긴 timeout을 적용한다.

## 구현 범위

### 백엔드

- `POST /api/companies/list`
- `POST /api/me/watchlist`

두 watchlist API에서 기업을 resolve한 뒤, 인덱스가 준비되지 않은 기업에 대해 기존 background indexing job을 큐잉한다.

기존 `/api/companies/{company_value}/index` 로직은 `_queue_index_job()` helper로 분리해 재사용한다.

### 프론트엔드

- 선택 기업별 인덱싱 상태를 `st.session_state`에 저장한다.
- `/api/companies/{company}/index-status`를 `st.fragment(run_every=5)`로 polling한다.
- `queued`, `indexing`, `failed` 상태를 요약 영역 근처에 작게 표시한다.
- progress bar는 현재 백엔드 상태 기반 coarse progress를 사용한다.
  - `queued`: 12%
  - `indexing`: 58%
  - `failed`: 100% with error
- 인덱싱 중에는 fallback 요약을 고정하지 않고 “공시 인덱싱이 완료되면 요약을 불러옵니다.”를 표시한다.
- 채팅 요청 중에는 `st.spinner("답변 생성 중...")`를 표시한다.
- 채팅 API는 `CHAT_REQUEST_TIMEOUT = 60`을 사용한다.

## 범위 밖

- 정확한 단계별 progress percent 계산
- 백엔드 job 상태 DB 영속화
- LLM summary card cache
- streaming chat 응답
- 대규모 UI 레이아웃 변경

## 후속 작업 후보

- `IndexJob`에 `phase`, `progress`, `message` 필드를 추가한다.
- `pipeline.py`의 정기공시/이벤트공시 단계별로 progress를 갱신한다.
- 채팅 응답을 streaming으로 전환한다.
- 인덱싱 완료 후 summary cache invalidate 및 LLM 요약 재생성을 연결한다.
