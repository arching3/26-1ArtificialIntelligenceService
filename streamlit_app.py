from __future__ import annotations

from typing import Any

import pandas as pd
import requests
import streamlit as st


DEFAULT_BACKEND_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 8
PERIOD_OPTIONS = ["최근 1주", "최근 1개월", "최근 3개월", "최근 6개월", "최근 1년", "최근 3년", "전체"]
DEFAULT_PERIOD = "최근 1년"


st.set_page_config(
    page_title="DART RAG 개인 투자 챗봇",
    page_icon="D",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
      :root {
        --dl-ink: #171b1f;
        --dl-muted: #707782;
        --dl-line: #e6e9ed;
        --dl-soft: #f7faf8;
        --dl-green: #56c56f;
        --dl-green-deep: #20864c;
      }
      .stApp {
        background:
          linear-gradient(rgba(17, 24, 39, 0.035) 1px, transparent 1px),
          linear-gradient(90deg, rgba(17, 24, 39, 0.035) 1px, transparent 1px),
          radial-gradient(circle at 50% 12%, rgba(86, 197, 111, 0.13), transparent 34%),
          #ffffff;
        background-size: 32px 32px, 32px 32px, auto, auto;
      }
      .block-container {
        max-width: 1120px;
        padding-top: 1.35rem;
        padding-bottom: 3rem;
      }
      [data-testid="stSidebar"] {
        background: #fbfcfb;
        border-right: 1px solid var(--dl-line);
      }
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.72rem;
      }
      h1, h2, h3 {
        color: var(--dl-ink);
        letter-spacing: 0;
      }
      .brand-lockup {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 0 22px;
      }
      .brand-mark {
        width: 38px;
        height: 38px;
        display: grid;
        place-items: center;
        border-radius: 10px;
        background: #111827;
        color: #ffffff;
        font-weight: 900;
      }
      .brand-name {
        margin: 0;
        color: var(--dl-ink);
        font-size: 1.24rem;
        font-weight: 900;
      }
      .brand-caption {
        margin: 2px 0 0;
        color: var(--dl-muted);
        font-size: 0.78rem;
      }
      .hero {
        padding: 28px 0 26px;
        text-align: center;
      }
      .hero-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 18px;
        padding: 8px 14px;
        border: 1px solid rgba(86, 197, 111, 0.55);
        border-radius: 999px;
        background: rgba(86, 197, 111, 0.12);
        color: var(--dl-green-deep);
        font-weight: 800;
        font-size: 0.86rem;
      }
      .hero h1 {
        max-width: 780px;
        margin: 0 auto;
        font-size: clamp(2.4rem, 5vw, 4.8rem);
        line-height: 1.08;
        font-weight: 950;
      }
      .hero p {
        max-width: 680px;
        margin: 18px auto 0;
        color: var(--dl-muted);
        font-size: 1.04rem;
        line-height: 1.65;
      }
      .selected-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-top: 18px;
        padding: 9px 14px;
        border: 1px solid var(--dl-line);
        border-radius: 999px;
        background: #ffffff;
        box-shadow: 0 10px 30px rgba(17, 24, 39, 0.06);
        color: var(--dl-ink);
        font-weight: 800;
        font-size: 0.9rem;
      }
      .section-head {
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 14px;
        margin: 28px 0 12px;
      }
      .section-head h3 {
        margin: 0;
        font-size: 1.55rem;
        font-weight: 900;
      }
      .section-head p {
        margin: 5px 0 0;
        color: var(--dl-muted);
      }
      .summary-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        overflow: hidden;
        border: 1px solid var(--dl-line);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.94);
        box-shadow: 0 22px 70px rgba(17, 24, 39, 0.08);
      }
      .summary-table th {
        width: 168px;
        padding: 18px 20px;
        border-bottom: 1px solid var(--dl-line);
        background: #f2fbf4;
        color: var(--dl-green-deep);
        text-align: left;
        vertical-align: top;
        font-size: 0.95rem;
        font-weight: 900;
      }
      .summary-table td {
        padding: 18px 20px;
        border-bottom: 1px solid var(--dl-line);
        color: #283039;
        line-height: 1.65;
        vertical-align: top;
        background: rgba(255, 255, 255, 0.84);
      }
      .summary-table tr:last-child th,
      .summary-table tr:last-child td {
        border-bottom: 0;
      }
      .sidebar-spacer { min-height: 30vh; }
      .stock-panel {
        margin-top: 8px;
      }
      .stButton > button,
      .stForm button {
        border-radius: 12px;
        border: 1px solid var(--dl-line);
        font-weight: 800;
      }
      .stButton > button p,
      .stForm button p {
        color: inherit;
      }
      [data-testid="baseButton-primary"] {
        border: 0 !important;
        background: var(--dl-green) !important;
        color: #ffffff !important;
        box-shadow: 0 10px 24px rgba(86, 197, 111, 0.28);
      }
      [data-testid="stSidebar"] .stButton > button {
        min-height: 44px;
        background: #ffffff;
      }
      [data-testid="stSidebar"] [data-testid="baseButton-primary"] {
        background: var(--dl-green) !important;
        color: #ffffff !important;
      }
      [data-testid="stMetric"] {
        padding: 18px;
        border: 1px solid var(--dl-line);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.92);
        box-shadow: 0 12px 34px rgba(17, 24, 39, 0.06);
      }
      [data-testid="stForm"] {
        padding: 16px;
        border: 1px solid var(--dl-line);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.92);
        box-shadow: 0 16px 48px rgba(17, 24, 39, 0.06);
      }
      .stTextInput input {
        border-radius: 12px;
      }
      [data-testid="stExpander"] {
        border-radius: 14px;
        border-color: var(--dl-line);
      }
      @media (max-width: 720px) {
        .hero {
          text-align: left;
        }
        .hero h1 {
          font-size: 2.35rem;
        }
        .section-head {
          align-items: flex-start;
          flex-direction: column;
        }
        .summary-table th,
        .summary-table td {
          display: block;
          width: 100%;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state() -> None:
    st.session_state.setdefault("backend_url", DEFAULT_BACKEND_URL)
    st.session_state.setdefault("watchlist", [])
    st.session_state.setdefault("selected_company", "")
    st.session_state.setdefault("selected_period", DEFAULT_PERIOD)
    st.session_state.setdefault("search_results", [])
    st.session_state.setdefault("popular_companies", [])
    st.session_state.setdefault("dialog_search_results", [])
    st.session_state.setdefault("summary", None)
    st.session_state.setdefault("summary_status", "idle")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("stock_company", "")
    st.session_state.setdefault("weekly_stocks", pd.DataFrame(columns=["time", "price"]))
    st.session_state.setdefault("realtime_stocks", pd.DataFrame(columns=["time", "price"]))


def api_url(path: str) -> str:
    base = st.session_state.backend_url.rstrip("/")
    return f"{base}{path}"


def request_json(method: str, path: str, **kwargs: Any) -> tuple[bool, Any, str]:
    try:
        response = requests.request(
            method,
            api_url(path),
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        return False, None, f"연결 실패: {exc}"

    if not response.ok:
        return False, None, f"HTTP {response.status_code}: {response.text[:240]}"

    if not response.content:
        return True, {}, ""

    try:
        return True, response.json(), ""
    except ValueError:
        return False, None, "응답이 JSON 형식이 아닙니다."


def search_companies(query: str) -> None:
    ok, data, error = fetch_companies(query)
    if not ok:
        st.session_state.dialog_search_results = []
        st.info("연결중입니다.")
        return

    st.session_state.dialog_search_results = normalize_company_results(data)


def fetch_companies(query: str = "") -> tuple[bool, Any, str]:
    payload = {"query": query.strip()} if query.strip() else {}
    return request_json(
        "GET",
        "/api/companies/search",
        params=payload,
        json=payload,
    )


def normalize_company_results(data: Any) -> list[str]:
    if isinstance(data, list):
        raw_items = data
    elif isinstance(data, dict):
        raw_items = (
            data.get("companies")
            or data.get("list")
            or data.get("results")
            or data.get("data")
            or data.get("items")
            or []
        )
    else:
        raw_items = []

    results: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            results.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("company") or item.get("company_name")
            if name:
                results.append(str(name))

    return list(dict.fromkeys(results))


def add_company(company_name: str) -> None:
    if company_name not in st.session_state.watchlist:
        st.session_state.watchlist.append(company_name)
        sync_watchlist()
    select_company(company_name)


def select_company(company_name: str) -> None:
    st.session_state.selected_company = company_name
    st.session_state.messages = []
    fetch_summary(company_name)
    fetch_initial_stocks(company_name)


def sync_watchlist() -> None:
    request_json(
        "POST",
        "/api/companies/list",
        json={"companies": st.session_state.watchlist},
    )


def fetch_summary(company_name: str) -> None:
    st.session_state.summary_status = "loading"
    ok, data, error = request_json(
        "POST",
        f"/api/companies/{company_name}/summary",
        json={"name": company_name, "period": st.session_state.selected_period},
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
        json={"company": company_name, "period": st.session_state.selected_period},
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
        json={
            "prompt": prompt,
            "company": company_name,
            "period": st.session_state.selected_period,
        },
    )
    if not ok:
        st.session_state.messages.append({"role": "assistant", "content": "연결중입니다."})
        return

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
        st.info("연결중입니다.")
        return

    first_price = float(frame.iloc[0]["price"])
    last_price = float(frame.iloc[-1]["price"])
    change = last_price - first_price
    change_rate = (change / first_price * 100) if first_price else 0
    direction = "상승" if change > 0 else "하락" if change < 0 else "보합"

    cols = st.columns(3)
    cols[0].metric("최근 가격", f"{last_price:,.2f}")
    cols[1].metric("기간 변화", f"{change:,.2f}", f"{change_rate:.2f}%")
    cols[2].metric("경향", direction)


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


def render_summary(summary: dict[str, Any] | None) -> None:
    fields = [
        ("overview", "사업 개요"),
        ("benefit", "수익 구조"),
        ("earnings", "실적 동향"),
        ("risk", "주요 리스크"),
        ("changing", "주요 변화"),
        ("status", "공모 상태"),
        ("anomaly", "특이사항"),
    ]

    if st.session_state.summary_status == "connecting":
        st.info("연결중입니다.")
        return

    if not summary:
        st.info("공시 요약을 불러오면 여기에 표시됩니다.")
        return

    rows = "\n".join(
        f"""
        <tr>
          <th>{label}</th>
          <td>{summary.get(key, "응답 없음")}</td>
        </tr>
        """
        for key, label in fields
    )
    st.markdown(
        f"""
        <table class="summary-table">
          <tbody>{rows}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )


@st.dialog("관심기업 추가")
def company_add_dialog() -> None:
    if not st.session_state.popular_companies:
        ok, data, error = fetch_companies()
        if ok:
            st.session_state.popular_companies = normalize_company_results(data)
        else:
            st.info("연결중입니다.")

    st.caption("최근 인기 많은 기업")
    if st.session_state.popular_companies:
        for row_start in range(0, len(st.session_state.popular_companies), 3):
            cols = st.columns(3)
            for col, company in zip(cols, st.session_state.popular_companies[row_start : row_start + 3]):
                if col.button(company, key=f"popular-{company}", use_container_width=True):
                    add_company(company)
                    st.rerun()
    else:
        st.info("표시할 인기 기업이 없습니다.")

    st.divider()
    st.caption("원하는 기업이 없으면 검색하세요.")
    search_cols = st.columns([0.78, 0.22])
    query = search_cols[0].text_input(
        "기업 검색",
        key="dialog_company_query",
        label_visibility="collapsed",
        placeholder="예: 삼성",
    )
    if search_cols[1].button("＋", key="dialog-search-button", use_container_width=True):
        search_companies(query)

    if st.session_state.dialog_search_results:
        st.caption("검색 결과")
        for company in st.session_state.dialog_search_results:
            cols = st.columns([0.78, 0.22])
            cols[0].write(company)
            if cols[1].button("+", key=f"search-add-{company}", use_container_width=True):
                add_company(company)
                st.rerun()


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

    st.divider()
    st.subheader("조회 기간")
    current_period = st.selectbox(
        "공시/재무제표 기간",
        PERIOD_OPTIONS,
        index=PERIOD_OPTIONS.index(st.session_state.selected_period),
        label_visibility="collapsed",
    )
    if current_period != st.session_state.selected_period:
        st.session_state.selected_period = current_period
        if st.session_state.selected_company:
            fetch_summary(st.session_state.selected_company)
            fetch_initial_stocks(st.session_state.selected_company)
            st.rerun()

    st.markdown('<div class="sidebar-spacer"></div>', unsafe_allow_html=True)
    if st.button("＋ 관심기업 추가", use_container_width=True):
        company_add_dialog()


selected_company = st.session_state.selected_company

selected_chip = (
    f'<div class="selected-chip">선택 기업: {selected_company} · {st.session_state.selected_period}</div>'
    if selected_company
    else ""
)
st.markdown(
    f"""
    <section class="hero">
      <div class="hero-badge">DART lens · Personal RAG</div>
      <h1>공시를 읽고, 근거를 묶고, 투자 질문에 답합니다</h1>
      <p>관심기업의 사업보고서와 재무제표 요약, 챗봇, 주가 흐름을 한 화면에서 확인하세요.</p>
      {selected_chip}
    </section>
    """,
    unsafe_allow_html=True,
)

if not selected_company:
    button_cols = st.columns([0.36, 0.28, 0.36])
    if button_cols[1].button("관심기업을 선택하세요", use_container_width=True, type="primary"):
        company_add_dialog()
    st.stop()

summary_heading = st.columns([0.76, 0.24])
summary_heading[0].markdown(
    """
    <div class="section-head">
      <div>
        <h3>공시 요약</h3>
        <p>선택한 기간의 재무제표와 사업보고서 요약을 표로 정리합니다.</p>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)
if summary_heading[1].button("요약 새로고침", use_container_width=True):
    fetch_summary(selected_company)

render_summary(st.session_state.summary)

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

with st.form("chat-form", clear_on_submit=True):
    chat_cols = st.columns([0.86, 0.14])
    prompt = chat_cols[0].text_input(
        "질문 입력",
        placeholder="예: 최근 사업보고서 기준으로 투자 리스크를 요약해줘",
        label_visibility="collapsed",
    )
    submitted = chat_cols[1].form_submit_button("전송", use_container_width=True)

if submitted and prompt.strip():
    send_chat(prompt.strip(), selected_company)
    st.rerun()

st.divider()
if st.session_state.stock_company != selected_company:
    fetch_initial_stocks(selected_company)
render_realtime_stock_section(selected_company)
