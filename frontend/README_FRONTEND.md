# DART RAG Streamlit UI

개인 관심기업의 DART 공시 요약, 주가 데이터, 채팅 답변을 백엔드 API와 연결해 보여주는 Streamlit UI입니다.

## 실행

<!-- frontend 브랜치 변경: 현재 브랜치의 backend/src 패키지 구조에 맞춰 실행 경로를 보정했습니다. -->
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
## 로컬 연결 테스트

백엔드는 `backend.src.api_server:app`이 프론트엔드가 기대하는 `/api/...` 엔드포인트를 제공합니다.

- 기본 API 주소: `http://127.0.0.1:8000`
- 기본 프론트 주소: `http://127.0.0.1:8501`
