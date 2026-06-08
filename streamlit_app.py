from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from services.api_client import (
    fetch_companies as api_fetch_companies,
    normalize_company_results,
    request_json as api_request_json,
)
from ui.summary import render_summary


DEFAULT_BACKEND_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 8
CHAT_REQUEST_TIMEOUT = 60
API_RETRY_MESSAGE = "데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요."
APP_DIR = Path(__file__).resolve().parent
HERO_IMAGE_PATH = APP_DIR / "assets" / "dart-lens-hero.png"


def image_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def load_css(path: Path) -> None:
    if path.exists():
        st.markdown(f"<style>{path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


HERO_IMAGE_URI = image_data_uri(HERO_IMAGE_PATH)
HERO_BACKGROUND_STYLE = f"background-image: linear-gradient(90deg, rgba(9, 13, 20, 0.94) 0%, rgba(9, 13, 20, 0.72) 46%, rgba(9, 13, 20, 0.28) 100%), url('{HERO_IMAGE_URI}');" if HERO_IMAGE_URI else ""



st.set_page_config(
    page_title="DART RAG 개인 투자 챗봇",
    page_icon="D",
    layout="wide",
    initial_sidebar_state="expanded",
)


load_css(APP_DIR / "styles" / "app.css")


def init_state() -> None:
    st.session_state.setdefault("backend_url", DEFAULT_BACKEND_URL)
    st.session_state.setdefault("watchlist", [])
    st.session_state.setdefault("selected_company", "")
    st.session_state.setdefault("search_results", [])
    st.session_state.setdefault("popular_companies", [])
    st.session_state.setdefault("dialog_search_results", [])
    st.session_state.setdefault("dialog_selected_company", "")
    st.session_state.setdefault("summary", None)
    st.session_state.setdefault("summary_status", "idle")
    st.session_state.setdefault("summary_expanded", False)
    st.session_state.setdefault("index_status", {})
    st.session_state.setdefault("index_company", "")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("stock_company", "")
    st.session_state.setdefault("weekly_stocks", pd.DataFrame(columns=["time", "price"]))
    st.session_state.setdefault("realtime_stocks", pd.DataFrame(columns=["time", "price"]))


def request_json(method: str, path: str, timeout: int = REQUEST_TIMEOUT, **kwargs: Any) -> tuple[bool, Any, str]:
    return api_request_json(
        method,
        path,
        backend_url=st.session_state.backend_url,
        timeout=timeout,
        **kwargs,
    )


def search_companies(query: str) -> None:
    ok, data, error = fetch_companies(query)
    if not ok:
        st.session_state.dialog_search_results = []
        st.info(API_RETRY_MESSAGE)
        return

    st.session_state.dialog_search_results = normalize_company_results(data)


def fetch_companies(query: str = "") -> tuple[bool, Any, str]:
    return api_fetch_companies(st.session_state.backend_url, query, timeout=REQUEST_TIMEOUT)


def add_company(company_name: str) -> None:
    if company_name not in st.session_state.watchlist:
        st.session_state.watchlist.append(company_name)
        sync_watchlist()
    select_company(company_name)


def select_company(company_name: str) -> None:
    st.session_state.selected_company = company_name
    st.session_state.messages = []
    st.session_state.summary_expanded = False
    start_initial_work(company_name)
    fetch_summary(company_name)
    fetch_initial_stocks(company_name)


def sync_watchlist() -> None:
    ok, data, error = request_json(
        "POST",
        "/api/companies/list",
        json={"companies": st.session_state.watchlist},
    )
    if ok and isinstance(data, dict) and data.get("index_jobs"):
        latest_job = data["index_jobs"][-1]
        st.session_state.index_status = latest_job
        st.session_state.index_company = latest_job.get("corp_name") or latest_job.get("stock_code") or ""


def start_initial_work(company_name: str) -> None:
    ok, data, error = request_json("POST", f"/api/companies/{company_name}/index")
    if not ok or not isinstance(data, dict):
        st.session_state.index_status = {"status": "unknown", "error": error}
        st.session_state.index_company = company_name
        return
    st.session_state.index_status = data
    st.session_state.index_company = company_name


def fetch_index_status(company_name: str) -> dict[str, Any]:
    ok, data, error = request_json("GET", f"/api/companies/{company_name}/index-status")
    if not ok or not isinstance(data, dict):
        data = {"status": "unknown", "error": error}
    st.session_state.index_status = data
    st.session_state.index_company = company_name
    return data


def index_progress_value(status: str) -> int:
    if status == "queued":
        return 12
    if status == "indexing":
        return 58
    if status == "ready":
        return 100
    if status == "failed":
        return 100
    return 0


def render_index_progress(company_name: str) -> None:
    status = st.session_state.index_status if st.session_state.index_company == company_name else {}
    state = str(status.get("status") or "")
    if state not in {"queued", "indexing", "failed"}:
        return

    progress = index_progress_value(state)
    if state == "failed":
        error = status.get("error") or "공시 인덱싱 작업이 실패했습니다."
        st.error(f"공시 인덱싱 실패: {error}")
        return

    label = "대기 중" if state == "queued" else "진행중..."
    st.caption(f"공시 인덱싱 {label}")
    st.progress(progress, text=f"{company_name} 공시 원문 수집 및 인덱스 생성 {label}")


@st.fragment(run_every=5)
def monitor_initial_work(company_name: str) -> None:
    status = st.session_state.index_status if st.session_state.index_company == company_name else {}
    if status.get("status") not in {"queued", "indexing"}:
        return

    latest = fetch_index_status(company_name)
    if latest.get("status") == "ready":
        fetch_summary(company_name)
        st.rerun()
    if latest.get("status") == "failed":
        st.rerun()


def fetch_summary(company_name: str) -> None:
    status = st.session_state.index_status if st.session_state.index_company == company_name else {}
    if status.get("status") in {"queued", "indexing"}:
        st.session_state.summary = None
        st.session_state.summary_status = "indexing"
        return
    if status.get("status") == "failed":
        st.session_state.summary = None
        st.session_state.summary_status = "failed"
        return

    st.session_state.summary_status = "loading"
    ok, data, error = request_json(
        "POST",
        f"/api/companies/{company_name}/summary",
        json={"name": company_name},
    )
    if not ok:
        st.session_state.summary = None
        st.session_state.summary_status = "connecting"
        return
    st.session_state.summary = data
    st.session_state.summary_status = "ready"


def fetch_initial_stocks(company_name: str) -> None:
    st.session_state.stock_company = company_name
    st.session_state.weekly_stocks = fetch_stocks("/api/companies/stocks", company_name)
    st.session_state.realtime_stocks = pd.DataFrame(columns=["time", "price"])


def fetch_stocks(path: str, company_name: str) -> pd.DataFrame:
    ok, data, error = request_json(
        "POST",
        path,
        json={"company": company_name},
    )
    if not ok:
        return pd.DataFrame(columns=["time", "price"])

    rows = data.get("stocks", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    parsed_rows = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        parsed_rows.append(
            {
                "time": parse_datetime(row[0]),
                "price": pd.to_numeric(row[1], errors="coerce"),
            }
        )

    frame = pd.DataFrame(parsed_rows).dropna()
    if frame.empty:
        return pd.DataFrame(columns=["time", "price"])
    return frame.sort_values("time")


def parse_datetime(value: Any) -> pd.Timestamp:
    text = str(value)
    text = text.replace("datetime.date(", "").replace(")", "")
    text = text.replace("|", " ")
    text = text.replace(".", "-")
    return pd.to_datetime(text, errors="coerce")


def send_chat(prompt: str, company_name: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    ok, data, error = request_json(
        "POST",
        "/api/chat",
        timeout=CHAT_REQUEST_TIMEOUT,
        json={
            "prompt": prompt,
            "company": company_name,
        },
    )
    if not ok:
        answer = API_RETRY_MESSAGE
    else:
        answer = data.get("answer", "답변 필드가 비어 있습니다.") if isinstance(data, dict) else str(data)
    st.session_state.messages.append({"role": "assistant", "content": answer})


def merge_stock_frames(*frames: pd.DataFrame) -> pd.DataFrame:
    valid_frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not valid_frames:
        return pd.DataFrame(columns=["time", "price"])

    merged = pd.concat(valid_frames, ignore_index=True)
    merged = merged.dropna(subset=["time", "price"])
    merged = merged.drop_duplicates(subset=["time"], keep="last")
    return merged.sort_values("time")


def render_stock_metrics(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info(API_RETRY_MESSAGE)
        return

    first_price = float(frame.iloc[0]["price"])
    last_price = float(frame.iloc[-1]["price"])
    change = last_price - first_price
    change_rate = (change / first_price * 100) if first_price else 0
    direction = "상승" if change > 0 else "하락" if change < 0 else "보합"
    tone = "up" if change > 0 else "down" if change < 0 else "flat"

    st.markdown(
        f"""
        <div class="stock-metric-grid">
          <div class="stock-metric-card stock-metric-card-main">
            <span>최근 가격</span>
            <strong>{last_price:,.2f}</strong>
          </div>
          <div class="stock-metric-card">
            <span>기간 변화</span>
            <strong class="metric-{tone}">{change:,.2f}</strong>
            <small>{change_rate:.2f}%</small>
          </div>
          <div class="stock-metric-card">
            <span>경향</span>
            <strong class="metric-{tone}">{direction}</strong>
            <small>선택 기간 기준</small>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every=10)
def render_realtime_stock_section(company_name: str) -> None:
    realtime = fetch_stocks("/api/companies/stocks_realtime", company_name)
    if not realtime.empty:
        st.session_state.realtime_stocks = merge_stock_frames(
            st.session_state.realtime_stocks,
            realtime,
        )

    chart_frame = merge_stock_frames(
        st.session_state.weekly_stocks,
        st.session_state.realtime_stocks,
    )

    st.markdown(
        """
        <div class="section-head">
          <div>
            <h3>최근 주가와 경향</h3>
            <p>초기에는 일주일치 주가를 표시하고, 이후 실시간 데이터는 10초마다 갱신합니다.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_stock_metrics(chart_frame)

    if not chart_frame.empty:
        st.line_chart(chart_frame.set_index("time")["price"])
        with st.expander("주가 데이터 보기"):
            st.dataframe(chart_frame, use_container_width=True, hide_index=True)


@st.dialog("관심기업 추가")
def company_add_dialog() -> None:
    st.markdown(
        """
        <div class="radar-panel">
          <h3>Market Radar</h3>
          <p>DART lens가 최근 많이 찾는 기업과 검색 결과를 관심기업 후보로 정리합니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not st.session_state.popular_companies:
        ok, data, error = fetch_companies()
        if ok:
            st.session_state.popular_companies = normalize_company_results(data)
        else:
            st.session_state.popular_companies = []
            st.info(API_RETRY_MESSAGE)

    st.caption("최근 인기 많은 기업")
    if st.session_state.popular_companies:
        for row_start in range(0, len(st.session_state.popular_companies), 3):
            cols = st.columns(3)
            for col, company in zip(cols, st.session_state.popular_companies[row_start : row_start + 3]):
                if col.button(company, key=f"popular-{company}", use_container_width=True):
                    st.session_state.dialog_selected_company = company
    else:
        st.info("표시할 인기 기업이 없습니다.")

    st.divider()
    selected_company = st.session_state.dialog_selected_company
    if selected_company:
        st.markdown(
            f'<div class="dialog-selected-company">선택된 기업: <strong>{selected_company}</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        st.caption("인기 기업 또는 검색 결과에서 추가할 기업을 선택하세요.")

    st.caption("원하는 기업이 없으면 검색하세요.")
    with st.form("dialog-company-search-form", clear_on_submit=False):
        search_cols = st.columns([0.62, 0.16, 0.22])
        query = search_cols[0].text_input(
            "기업 검색",
            key="dialog_company_query",
            label_visibility="collapsed",
            placeholder="예: 삼성",
        )
        if st.session_state.dialog_selected_company:
            add_submitted = search_cols[2].form_submit_button(
                "＋ 추가",
                use_container_width=True,
                type="primary",
                help="선택한 기업을 관심기업에 추가합니다. Enter를 눌러도 추가됩니다.",
            )
            search_submitted = search_cols[1].form_submit_button(
                "🔍",
                use_container_width=True,
                help="입력한 기업명을 검색합니다.",
            )
        else:
            search_submitted = search_cols[1].form_submit_button(
                "🔍",
                use_container_width=True,
                help="입력한 기업명을 검색합니다. Enter를 눌러도 검색됩니다.",
            )
            add_submitted = search_cols[2].form_submit_button(
                "＋ 추가",
                use_container_width=True,
                disabled=True,
                help="먼저 기업을 선택하세요.",
            )

    if search_submitted:
        search_companies(query)
    if add_submitted and st.session_state.dialog_selected_company:
        add_company(st.session_state.dialog_selected_company)
        st.session_state.dialog_selected_company = ""
        st.rerun()

    if st.session_state.dialog_search_results:
        st.caption("검색 결과")
        for company in st.session_state.dialog_search_results:
            if st.button(company, key=f"search-select-{company}", use_container_width=True):
                st.session_state.dialog_selected_company = company


init_state()

with st.sidebar:
    st.markdown(
        """
        <div class="brand-lockup">
          <div class="brand-mark">D</div>
          <div>
            <p class="brand-name">DART lens</p>
            <p class="brand-caption">공시 기반 투자 인사이트</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("관심기업 선택")
    if not st.session_state.watchlist:
        st.caption("관심기업을 추가하면 공시 요약과 주가 흐름을 바로 확인할 수 있습니다.")

    for company in st.session_state.watchlist:
        if st.button(company, key=f"select-{company}", use_container_width=True):
            select_company(company)

    st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
    if st.button("＋ 관심기업 추가", use_container_width=True):
        company_add_dialog()


selected_company = st.session_state.selected_company

selected_chip = (
    f'<div class="selected-chip">선택 기업: {selected_company}</div>'
    if selected_company
    else ""
)
if not selected_company:
    st.markdown(
        f"""
        <section class="hero" style="{HERO_BACKGROUND_STYLE}">
          <div class="hero-badge">DART lens · Personal RAG</div>
          <h1>공시를 읽고,<br>근거를 묶고,<br>투자 질문에 답합니다</h1>
          <p>관심기업의 사업보고서와 재무제표 요약, 챗봇, 주가 흐름을 한 화면에서 확인하세요.</p>
          <div class="signature-strip">
            <span>DART filings</span>
            <span>Financial statements</span>
            <span>Realtime stock trend</span>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    button_cols = st.columns([0.36, 0.28, 0.36])
    if button_cols[1].button("관심기업을 선택하세요", use_container_width=True, type="primary"):
        company_add_dialog()
    st.stop()

st.markdown(
    f"""
    <section class="hero compact" style="{HERO_BACKGROUND_STYLE}">
      <div class="hero-badge">DART lens · Active Brief</div>
      <h1>{selected_company} 공시 브리핑</h1>
      <p>재무제표와 사업보고서 요약, 챗봇, 주가 흐름을 압축해서 보여드립니다.</p>
      {selected_chip}
      <div class="signature-strip">
        <span>Disclosure summary</span>
        <span>AI Q&A</span>
        <span>Price trend</span>
      </div>
    </section>
    """,
    unsafe_allow_html=True,
)

monitor_initial_work(selected_company)
if st.session_state.stock_company != selected_company:
    fetch_initial_stocks(selected_company)

analysis_cols = st.columns([0.52, 0.48], gap="large")
with analysis_cols[0]:
    summary_heading = st.columns([0.62, 0.38])
    summary_heading[0].markdown(
        """
        <div class="section-head compact-head">
          <div>
            <h3>공시 요약</h3>
            <p>핵심 항목을 먼저 보고 필요 시 펼쳐봅니다.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if summary_heading[1].button("요약 새로고침", use_container_width=True):
        st.session_state.summary_expanded = False
        start_initial_work(selected_company)
        fetch_summary(selected_company)

    render_index_progress(selected_company)
    render_summary(st.session_state.summary, st.session_state.summary_status)

with analysis_cols[1]:
    render_realtime_stock_section(selected_company)

st.divider()
st.markdown(
    f"""
    <div class="section-head">
      <div>
        <h3>{selected_company} 챗봇</h3>
        <p>선택 기업을 기준으로 공시와 재무제표 맥락을 함께 질문합니다.</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

prompt = st.chat_input("예: 최근 사업보고서 기준으로 투자 리스크를 요약해줘")
if prompt and prompt.strip():
    with st.spinner("답변 생성 중..."):
        send_chat(prompt.strip(), selected_company)
    st.rerun()
