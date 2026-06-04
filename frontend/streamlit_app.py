from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st


DEFAULT_BACKEND_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 8
CHAT_REQUEST_TIMEOUT = 60
PERIOD_OPTIONS = ["최근 1주", "최근 1개월", "최근 3개월", "최근 6개월", "최근 1년", "최근 3년", "전체"]
DEFAULT_PERIOD = "최근 1년"
APP_DIR = Path(__file__).resolve().parent
HERO_IMAGE_PATH = APP_DIR / "assets" / "dart-lens-hero.png"


def image_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


HERO_IMAGE_URI = image_data_uri(HERO_IMAGE_PATH)
HERO_BACKGROUND_STYLE = f"background-image: linear-gradient(90deg, rgba(9, 13, 20, 0.94) 0%, rgba(9, 13, 20, 0.72) 46%, rgba(9, 13, 20, 0.28) 100%), url('{HERO_IMAGE_URI}');" if HERO_IMAGE_URI else ""

SAMPLE_SUMMARIES = {
    "삼성전자": {
        "overview": "반도체, 모바일, 디스플레이, 가전 사업을 운영하는 글로벌 종합 전자 기업입니다. 최근 공시 기준 핵심 축은 메모리 업황 회복과 AI 서버향 고부가 제품 확대입니다.",
        "benefit": "수익 구조는 메모리 반도체와 스마트폰 판매가 중심이며, 고대역폭 메모리와 프리미엄 모바일 제품 비중이 수익성 개선에 기여합니다.",
        "earnings": "최근 실적은 메모리 가격 회복과 재고 정상화 효과로 개선 흐름을 보입니다. 다만 파운드리와 대규모 설비투자 부담은 이익 변동성을 키울 수 있습니다.",
        "risk": "반도체 가격 사이클, 미중 수출 규제, 경쟁사의 HBM 증설, 환율 변동이 주요 리스크입니다.",
        "changing": "AI 인프라 수요 증가로 HBM, 첨단 패키징, 서버용 SSD 관련 투자가 확대되는 흐름입니다.",
        "status": "현금성 자산과 낮은 부채 부담을 감안하면 재무 안정성은 양호한 편입니다.",
        "anomaly": "단기 주가보다 다음 실적 발표에서 HBM 수주와 메모리 가격 흐름 확인이 중요합니다.",
    },
    "SK하이닉스": {
        "overview": "메모리 반도체에 특화된 기업으로 DRAM, NAND, HBM 제품이 핵심입니다. AI 서버 투자 확대와 함께 HBM 경쟁력이 공시 해석의 중심입니다.",
        "benefit": "수익 구조는 DRAM과 HBM 판매 비중이 높고, 고부가 서버향 제품이 평균 판매가격과 마진을 끌어올리는 구조입니다.",
        "earnings": "최근 실적은 AI 서버향 수요 증가와 메모리 업황 회복에 힘입어 개선세입니다. NAND 부문 회복 속도는 추가 확인이 필요합니다.",
        "risk": "고객사 수요 집중, 증설 경쟁, 메모리 가격 조정, 설비투자 부담이 주요 리스크입니다.",
        "changing": "HBM 세대 전환과 패키징 역량 확보가 기업 가치 평가의 핵심 변수로 부각되고 있습니다.",
        "status": "업황 회복 구간에서는 현금흐름 개선이 기대되지만 투자 지출 규모를 함께 봐야 합니다.",
        "anomaly": "HBM 관련 기대가 이미 주가에 반영된 구간에서는 실적 확인 전 변동성이 커질 수 있습니다.",
    },
}

SAMPLE_STOCKS = {
    "삼성전자": [71400, 71900, 71600, 72400, 72800, 73300, 73100],
    "SK하이닉스": [188500, 191000, 194500, 193000, 198500, 201000, 204000],
}


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
        --dl-navy: #111722;
        --dl-panel: #171f2b;
        --dl-violet: #7b3ff2;
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
        padding-top: 1rem;
        padding-bottom: 3rem;
      }
      [data-testid="stSidebar"] {
        background: #101722;
        border-right: 1px solid rgba(255, 255, 255, 0.08);
      }
      [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.72rem;
      }
      h1, h2, h3 {
        color: var(--dl-ink);
        letter-spacing: 0;
      }
      [data-testid="stSidebar"] h1,
      [data-testid="stSidebar"] h2,
      [data-testid="stSidebar"] h3,
      [data-testid="stSidebar"] p,
      [data-testid="stSidebar"] label,
      [data-testid="stSidebar"] span {
        color: rgba(255, 255, 255, 0.86);
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
        background: linear-gradient(135deg, #56c56f, #22d3ee);
        color: #ffffff;
        font-weight: 900;
        box-shadow: 0 14px 34px rgba(86, 197, 111, 0.28);
      }
      .brand-name {
        margin: 0;
        color: #ffffff;
        font-size: 1.24rem;
        font-weight: 900;
      }
      .brand-caption {
        margin: 2px 0 0;
        color: rgba(255, 255, 255, 0.58);
        font-size: 0.78rem;
      }
      .hero {
        position: relative;
        overflow: hidden;
        min-height: 430px;
        margin: 8px 0 28px;
        padding: 56px 52px;
        border: 1px solid rgba(255, 255, 255, 0.13);
        border-radius: 28px;
        background:
          linear-gradient(90deg, rgba(9, 13, 20, 0.92) 0%, rgba(9, 13, 20, 0.72) 46%, rgba(9, 13, 20, 0.2) 100%),
          radial-gradient(circle at 16% 22%, rgba(86, 197, 111, 0.28), transparent 32%),
          #111722;
        background-position: center;
        background-size: cover;
        box-shadow: 0 32px 90px rgba(17, 24, 39, 0.28);
        text-align: left;
      }
      .hero.compact {
        min-height: 186px;
        margin-bottom: 18px;
        padding: 28px 34px;
        border-radius: 22px;
      }
      .hero::after {
        content: "";
        position: absolute;
        inset: 0;
        background:
          linear-gradient(rgba(255, 255, 255, 0.04) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255, 255, 255, 0.04) 1px, transparent 1px);
        background-size: 42px 42px;
        pointer-events: none;
      }
      .hero-badge {
        position: relative;
        z-index: 1;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 18px;
        padding: 8px 14px;
        border: 1px solid rgba(86, 197, 111, 0.5);
        border-radius: 999px;
        background: rgba(86, 197, 111, 0.15);
        color: #a7f3bd;
        font-weight: 800;
        font-size: 0.86rem;
        backdrop-filter: blur(14px);
      }
      .hero h1 {
        position: relative;
        z-index: 1;
        max-width: 720px;
        margin: 0;
        color: #ffffff;
        font-size: clamp(2.55rem, 4.6vw, 4.25rem);
        line-height: 1.14;
        font-weight: 950;
      }
      .hero.compact h1 {
        max-width: 760px;
        font-size: clamp(1.9rem, 3.2vw, 3rem);
        line-height: 1.12;
      }
      .hero p {
        position: relative;
        z-index: 1;
        max-width: 640px;
        margin: 18px 0 0;
        color: rgba(255, 255, 255, 0.72);
        font-size: 1.04rem;
        line-height: 1.65;
      }
      .hero.compact p {
        max-width: 760px;
        margin-top: 12px;
        font-size: 0.96rem;
      }
      .selected-chip {
        position: relative;
        z-index: 1;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        margin-top: 24px;
        padding: 11px 16px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.12);
        box-shadow: 0 10px 30px rgba(17, 24, 39, 0.14);
        color: #ffffff;
        font-weight: 800;
        font-size: 0.9rem;
        backdrop-filter: blur(14px);
      }
      .signature-strip {
        position: relative;
        z-index: 1;
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 28px;
      }
      .hero.compact .signature-strip {
        margin-top: 18px;
      }
      .signature-strip span {
        padding: 8px 10px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.1);
        color: rgba(255, 255, 255, 0.74);
        font-size: 0.8rem;
        font-weight: 800;
        backdrop-filter: blur(14px);
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
        background: rgba(255, 255, 255, 0.08);
        border-color: rgba(255, 255, 255, 0.1);
        color: #ffffff;
      }
      [data-testid="stSidebar"] [data-testid="baseButton-primary"] {
        background: var(--dl-green) !important;
        color: #ffffff !important;
      }
      [data-testid="stSidebar"] [data-testid="stSelectbox"] {
        border-radius: 14px;
      }
      [data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: rgba(255, 255, 255, 0.08);
        border-color: rgba(255, 255, 255, 0.1);
        color: #ffffff;
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
      div[role="dialog"] {
        border-radius: 28px !important;
        background: linear-gradient(180deg, #101722 0%, #161f2d 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.12) !important;
        box-shadow: 0 34px 100px rgba(0, 0, 0, 0.38) !important;
      }
      div[role="dialog"] h2,
      div[role="dialog"] h3,
      div[role="dialog"] p,
      div[role="dialog"] label,
      div[role="dialog"] span {
        color: rgba(255, 255, 255, 0.88);
      }
      div[role="dialog"] .stButton > button {
        min-height: 42px;
        border: 1px solid rgba(255, 255, 255, 0.1);
        background: rgba(255, 255, 255, 0.08);
        color: #ffffff;
      }
      .radar-panel {
        margin: -6px 0 14px;
        padding: 16px;
        border: 1px solid rgba(86, 197, 111, 0.28);
        border-radius: 20px;
        background:
          radial-gradient(circle at 86% 10%, rgba(34, 211, 238, 0.2), transparent 30%),
          rgba(255, 255, 255, 0.06);
      }
      .radar-panel h3 {
        margin: 0;
        color: #ffffff;
      }
      .radar-panel p {
        margin: 6px 0 0;
        color: rgba(255, 255, 255, 0.62);
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
    st.session_state.setdefault("index_status", {})
    st.session_state.setdefault("index_company", "")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("stock_company", "")
    st.session_state.setdefault("weekly_stocks", pd.DataFrame(columns=["time", "price"]))
    st.session_state.setdefault("realtime_stocks", pd.DataFrame(columns=["time", "price"]))


def sample_key(company_name: str) -> str | None:
    compact = company_name.replace(" ", "").lower()
    if "삼성" in compact or "samsung" in compact:
        return "삼성전자"
    if "하이닉스" in compact or "hynix" in compact or "sk하이닉스" in compact:
        return "SK하이닉스"
    return None


def sample_summary(company_name: str) -> dict[str, str] | None:
    key = sample_key(company_name)
    return SAMPLE_SUMMARIES.get(key) if key else None


def sample_stock_frame(company_name: str, realtime: bool = False) -> pd.DataFrame:
    key = sample_key(company_name)
    if not key:
        return pd.DataFrame(columns=["time", "price"])

    base_prices = SAMPLE_STOCKS[key]
    base_times = pd.date_range(end=pd.Timestamp.now().floor("h"), periods=len(base_prices), freq="D")
    if realtime:
        offset = len(st.session_state.realtime_stocks) + 1
        latest = float(base_prices[-1] + offset * (120 if key == "삼성전자" else 650))
        return pd.DataFrame(
            [{"time": pd.Timestamp.now().floor("min"), "price": latest}],
            columns=["time", "price"],
        )

    return pd.DataFrame(
        [{"time": time, "price": float(price)} for time, price in zip(base_times, base_prices)],
        columns=["time", "price"],
    )


def api_url(path: str) -> str:
    base = st.session_state.backend_url.rstrip("/")
    return f"{base}{path}"


def request_json(method: str, path: str, timeout: int = REQUEST_TIMEOUT, **kwargs: Any) -> tuple[bool, Any, str]:
    try:
        response = requests.request(
            method,
            api_url(path),
            timeout=timeout,
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
        sample_candidates = ["삼성전자", "SK하이닉스"]
        st.session_state.dialog_search_results = [
            company for company in sample_candidates if query.strip() in company
        ] or sample_candidates
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
        json={"name": company_name, "period": st.session_state.selected_period},
    )
    if not ok:
        fallback = sample_summary(company_name)
        st.session_state.summary = fallback
        st.session_state.summary_status = "ready" if fallback else "connecting"
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
        return sample_stock_frame(company_name, realtime=path.endswith("stocks_realtime"))

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
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        with st.spinner("답변 생성 중..."):
            ok, data, error = request_json(
                "POST",
                "/api/chat",
                timeout=CHAT_REQUEST_TIMEOUT,
                json={
                    "prompt": prompt,
                    "company": company_name,
                    "period": st.session_state.selected_period,
                },
            )
        if not ok:
            key = sample_key(company_name)
            if key:
                answer = f"{key} 샘플 기준으로 보면, 선택 기간({st.session_state.selected_period})에는 공시 요약과 주가 흐름 모두 업황 회복 기대가 반영된 모습입니다. 다만 실제 투자 판단은 백엔드 공시 데이터 연결 후 최신 사업보고서와 재무제표를 함께 확인해야 합니다."
            else:
                answer = "연결중입니다."
        else:
            answer = data.get("answer", "답변 필드가 비어 있습니다.") if isinstance(data, dict) else str(data)
        st.write(answer)
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
    if st.session_state.summary_status == "indexing":
        st.info("공시 인덱싱이 완료되면 요약을 불러옵니다.")
        return
    if st.session_state.summary_status == "failed":
        st.info("공시 인덱싱 상태를 확인해 주세요.")
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
            st.session_state.popular_companies = ["삼성전자", "SK하이닉스"]
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
      <p>{st.session_state.selected_period} 기준 재무제표와 사업보고서 요약, 챗봇, 주가 흐름을 압축해서 보여드립니다.</p>
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
    start_initial_work(selected_company)
    fetch_summary(selected_company)

monitor_initial_work(selected_company)
render_index_progress(selected_company)
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

st.divider()
if st.session_state.stock_company != selected_company:
    fetch_initial_stocks(selected_company)
render_realtime_stock_section(selected_company)
