import logging
import os
import traceback

from dotenv import load_dotenv

logging.getLogger("dotenv.main").setLevel(logging.ERROR)
load_dotenv()

import streamlit as st

from company_resolver import ResolveResult, resolve_company_inputs
from data_loader import process_and_store_dart_data
from rag_engine import create_rag_chain, get_answer


st.set_page_config(page_title="DART AI 분석기", layout="wide")


def _initialize_session_state() -> None:
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "rag_chain" not in st.session_state:
        st.session_state["rag_chain"] = None
    if "loaded_company_codes" not in st.session_state:
        st.session_state["loaded_company_codes"] = []
    if "loaded_company_labels" not in st.session_state:
        st.session_state["loaded_company_labels"] = []


def _api_keys_ready() -> bool:
    dart_key = os.getenv("DART_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    return bool(dart_key and openai_key) and not dart_key.startswith("your_") and not openai_key.startswith("your_")


def _split_company_inputs(raw_value: str) -> list[str]:
    return [value.strip() for value in raw_value.split(",") if value.strip()]


def _candidate_label(candidate) -> str:
    if not candidate:
        return ""
    return f"{candidate.corp_name} ({candidate.stock_code})" if candidate.corp_name else candidate.stock_code


def _show_resolution_issue(result: ResolveResult) -> None:
    if result.status == "ambiguous":
        st.warning(f"'{result.query}'에 대한 후보가 여러 개입니다.")
        for candidate in result.candidates[:10]:
            st.write(f"- {_candidate_label(candidate)}")
        if len(result.candidates) > 10:
            st.caption(f"외 {len(result.candidates) - 10}개 후보가 더 있습니다.")
    elif result.status == "not_found":
        st.error(f"'{result.query}' 기업을 찾을 수 없습니다. 더 정확한 회사명 또는 6자리 종목코드를 입력해 주세요.")


def _resolved_company_codes(results: list[ResolveResult]) -> tuple[list[str], list[str]]:
    codes: list[str] = []
    labels: list[str] = []
    for result in results:
        if result.status != "resolved" or result.selected is None:
            continue
        code = result.selected.stock_code
        if code not in codes:
            codes.append(code)
            labels.append(_candidate_label(result.selected))
    return codes, labels


_initialize_session_state()

with st.sidebar:
    st.title("설정 및 데이터 로드")
    company_code_input = st.text_input(
        "회사명 또는 종목코드",
        value="삼성전자,네이버,LG화학",
        placeholder="예: 삼성전자, 네이버, 005930",
    )

    if not _api_keys_ready():
        st.warning(".env 파일에 DART_API_KEY와 OPENAI_API_KEY를 설정해 주세요.")

    if st.button("공시 데이터 학습하기", type="primary"):
        company_inputs = _split_company_inputs(company_code_input)
        if not company_inputs:
            st.error("회사명 또는 6자리 종목코드를 입력해 주세요.")
        else:
            resolved_results = resolve_company_inputs(company_inputs)
            issue_results = [result for result in resolved_results if result.status != "resolved"]
            if issue_results:
                for result in issue_results:
                    _show_resolution_issue(result)
            else:
                company_codes, company_labels = _resolved_company_codes(resolved_results)
                with st.spinner("DART 사업보고서와 최근 1년 주요사항 공시를 가져오고 SQLite/FAISS에 저장 중입니다..."):
                    results = {code: process_and_store_dart_data(code) for code in company_codes}
                    success = all(results.values())

                if success:
                    st.session_state["loaded_company_codes"] = company_codes
                    st.session_state["loaded_company_labels"] = company_labels
                    st.session_state["rag_chain"] = create_rag_chain(company_codes=company_codes)
                    st.session_state["messages"] = []
                    st.success(f"공시 데이터 학습이 완료되었습니다: {', '.join(company_labels)}")
                else:
                    failed = [code for code, ok in results.items() if not ok]
                    st.error(f"데이터 학습 중 오류가 발생했습니다: {', '.join(failed)}. 터미널 로그를 확인해 주세요.")

    if st.session_state["loaded_company_codes"]:
        st.divider()
        st.caption("📌 현재 로드된 기업")
        labels = st.session_state.get("loaded_company_labels") or st.session_state["loaded_company_codes"]
        for label in labels:
            st.text(f"  • {label}")
        st.caption(f"LLM: gpt-4o-mini")

st.title("📊 DART 기업 공시 분석 챗봇")

for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("공시 내용에 대해 질문해 보세요.")
if prompt:
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if st.session_state["rag_chain"] is None:
            try:
                st.session_state["rag_chain"] = create_rag_chain(
                    company_codes=st.session_state.get("loaded_company_codes")
                )
            except Exception:
                answer = "먼저 사이드바에서 공시 데이터 학습을 완료해 주세요."
                st.markdown(answer)
                st.session_state["messages"].append({"role": "assistant", "content": answer})
                st.stop()

        with st.spinner("공시 자료를 검색하고 답변을 생성하는 중입니다..."):
            try:
                answer = get_answer(prompt, st.session_state["rag_chain"])
            except Exception as e:
                logging.exception("RAG 답변 생성 중 오류")
                answer = f"답변 생성 중 오류가 발생했습니다: {type(e).__name__}. 터미널 로그를 확인해 주세요."

        st.markdown(answer)
        st.session_state["messages"].append({"role": "assistant", "content": answer})
