# DART RAG Streamlit UI

개인 관심기업의 DART 공시 요약, 주가 데이터, 채팅 답변을 백엔드 API와 연결해 보여주는 Streamlit UI입니다.

## 실행

```bash
pip install -r requirements.txt
uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload
```

다른 터미널에서:

```bash
streamlit run streamlit_app.py
```

현재 미리보기 주소:

```text
http://127.0.0.1:8501
```

## 연결 API

- `GET /api/health`
- `GET /api/companies/search`
- `POST /api/companies/list`
- `POST /api/companies/{company_name}/summary`
- `POST /api/chat`
- `POST /api/companies/stocks`
- `POST /api/companies/stocks_realtime`

왼쪽 사이드바에서 Backend URL을 바꾸면 다른 백엔드 서버에 연결할 수 있습니다.

백엔드 실행 예:

```bash
uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload
```

## Requester GUI

`tests/requester.py`를 이용해 `backend/src/api_server.py`의 엔드포인트를 자유롭게 호출하는 테스트 GUI입니다.

```bash
uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload
streamlit run tests/requester_gui.py
```

GUI에서 GET/POST, 경로, 헤더, 쿼리 파라미터, POST JSON body를 직접 바꿔 요청할 수 있습니다.

## 로컬 연결 테스트

`backend/src/api_server.py`는 프론트엔드가 기대하는 `/api/...` 엔드포인트를 제공합니다.

- 기본 API 주소: `http://127.0.0.1:8000`
- 기본 프론트 주소: `http://127.0.0.1:8501`
- DART/OpenAI/FAISS 연결이 준비되어 있지 않아도 삼성전자, SK하이닉스 샘플 데이터로 화면을 확인할 수 있습니다.
