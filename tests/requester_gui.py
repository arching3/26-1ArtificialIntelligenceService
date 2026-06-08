from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from requester import Requester


ENDPOINT_PRESETS = {
    "Health": {"method": "GET", "path": "/api/health", "data": {}},
    "Me": {"method": "GET", "path": "/api/me", "data": {}},
    "Delete Watchlist Item": {"method": "DELETE", "path": "/api/me/watchlist/005930", "data": {}},
    "Company Search": {"method": "GET", "path": "/api/companies/search", "data": {"query": "삼성"}},
    "Set Watchlist": {"method": "POST", "path": "/api/companies/list", "data": {"companies": ["삼성전자", "005930"]}},
    "Index Company": {"method": "POST", "path": "/api/companies/005930/index", "data": {}},
    "Index Status": {"method": "GET", "path": "/api/companies/005930/index-status", "data": {}},
    "Company Summary": {"method": "GET", "path": "/api/companies/005930/summary", "data": {}},
    "Company Filings": {"method": "GET", "path": "/api/companies/005930/filings", "data": {"limit": 5}},
    "Filing Detail": {"method": "GET", "path": "/api/filings/RECEIPT_NO", "data": {}},
    "Chat": {"method": "POST", "path": "/api/chat", "data": {"company": "삼성전자", "prompt": "최근 핵심 리스크를 요약해줘"}},
    "Stock History": {"method": "POST", "path": "/api/companies/stocks", "data": {"company": "삼성전자", "period": "최근 1개월"}},
    "Realtime Stock": {"method": "POST", "path": "/api/companies/stocks_realtime", "data": {"company": "삼성전자"}},
}


def parse_json_object(raw: str, label: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} JSON 형식이 올바르지 않습니다: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label}는 JSON object여야 합니다.")
    return parsed


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_requester(port: int, method: str, path: str, headers: dict[str, Any], data: dict[str, Any], json_body: bool) -> Requester:
    requester = Requester(port=port)
    requester.url = path
    requester.method(method)
    requester.headers(**headers)
    requester.data(**data)
    requester.use_json_body(json_body)
    return requester


def render_response(result: Any, requester: Requester, elapsed_ms: float) -> None:
    response = requester.last_response
    status_code = response.status_code if response is not None else "unknown"
    st.success(f"HTTP {status_code} · {elapsed_ms:.1f} ms")
    st.json(result)
    if response is not None:
        with st.expander("Response headers"):
            st.json(dict(response.headers))


def main() -> None:
    st.set_page_config(page_title="Requester GUI", page_icon="API", layout="wide")
    st.title("src/api_server.py 테스트 GUI")
    st.caption("`tests/requester.py`의 `Requester` 클래스로 FastAPI 엔드포인트를 호출합니다.")

    with st.sidebar:
        st.header("Backend")
        host = st.text_input("Host", value="localhost", disabled=True)
        port = st.number_input("Port", min_value=1, max_value=65535, value=8000, step=1)
        st.code(f"http://{host}:{int(port)}", language="text")
        st.divider()
        st.header("Presets")
        preset_name = st.selectbox("Endpoint", options=list(ENDPOINT_PRESETS))
        preset = ENDPOINT_PRESETS[preset_name]

    left, right = st.columns([0.9, 1.1], gap="large")

    with left:
        st.subheader("Request")
        method_options = ["GET", "POST", "DELETE"]
        method = st.radio("Method", method_options, index=method_options.index(preset["method"]), horizontal=True)
        path = st.text_input("Path", value=preset["path"], placeholder="/api/health")
        json_body = st.toggle("POST data를 JSON body로 전송", value=method == "POST")

        headers_text = st.text_area(
            "Headers JSON",
            value=pretty_json({"Content-Type": "application/json"} if method == "POST" and json_body else {}),
            height=120,
        )
        data_text = st.text_area("Params / Body JSON", value=pretty_json(preset["data"]), height=220)

        send = st.button("Send request", type="primary", use_container_width=True)

    with right:
        st.subheader("Response")
        if not send:
            st.info("요청을 보내면 응답 JSON과 헤더가 여기에 표시됩니다.")
            st.markdown(
                """
                실행 예:
                ```bash
                uvicorn backend.src.api_server:app --host 127.0.0.1 --port 8000 --reload
                streamlit run tests/requester_gui.py
                ```
                """
            )
            return

        try:
            headers = parse_json_object(headers_text, "Headers")
            data = parse_json_object(data_text, "Params / Body")
            requester = build_requester(int(port), method, path, headers, data, json_body=json_body)
            started_at = time.perf_counter()
            result = requester.query()
            elapsed_ms = (time.perf_counter() - started_at) * 1000
        except ValueError as exc:
            st.error(str(exc))
            return
        except requests.HTTPError as exc:
            response = exc.response
            st.error(f"HTTP {response.status_code}: {response.reason}")
            try:
                st.json(response.json())
            except ValueError:
                st.code(response.text, language="text")
            with st.expander("Response headers"):
                st.json(dict(response.headers))
            return
        except requests.RequestException as exc:
            st.error(f"요청 실패: {exc}")
            return

        render_response(result, requester, elapsed_ms)

    st.divider()
    st.caption(f"GUI 파일: {Path(__file__).relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
