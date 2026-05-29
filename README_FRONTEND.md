# DART RAG Streamlit UI

개인 관심기업의 DART 공시 요약, 주가 데이터, 채팅 답변을 백엔드 API와 연결해 보여주는 Streamlit UI입니다.

## 실행

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

현재 미리보기 주소:

```text
http://127.0.0.1:8501
```

## 연결 API

- `GET /api/health`
- `GET /api/companies/search`
- `POST /api/companies/{companies_name}/summary`
- `POST /api/chat`
- `POST /api/companies/stocks`
- `POST /api/companies/stocks_realtime`

왼쪽 사이드바에서 Backend URL을 바꾸면 다른 백엔드 서버에 연결할 수 있습니다.
