from __future__ import annotations

import html
from typing import Any

import streamlit as st

from utils.text_cleaner import clean_disclosure_text


def render_summary(summary: dict[str, Any] | None, summary_status: str) -> None:
    primary_fields = [
        ("overview", "사업 개요"),
        ("benefit", "수익 구조"),
        ("earnings", "실적 동향"),
        ("risk", "주요 리스크"),
    ]
    extra_fields = [
        ("changing", "주요 변화"),
        ("status", "공모 상태"),
        ("anomaly", "특이사항"),
    ]

    if summary_status == "connecting":
        st.info("데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.")
        return
    if summary_status == "indexing":
        st.info("공시 인덱싱이 완료되면 요약을 불러옵니다.")
        return
    if summary_status == "failed":
        st.info("공시 인덱싱 상태를 확인해 주세요.")
        return

    if not summary:
        st.info("공시 요약을 불러오면 여기에 표시됩니다.")
        return

    expanded = st.session_state.get("summary_expanded", False)
    fields = primary_fields + (extra_fields if expanded else [])

    cards = "\n".join(
        f"""
        <article class="summary-card">
          <div class="summary-card-label">{html.escape(label)}</div>
          <div class="summary-card-body">{html.escape(clean_disclosure_text(summary.get(key, "응답 없음")))}</div>
        </article>
        """
        for key, label in fields
    )
    st.markdown(
        f"""
        <div class="summary-card-grid">
          {cards}
        </div>
        """,
        unsafe_allow_html=True,
    )

    button_label = "공시 요약 접기" if expanded else "공시 요약 더보기"
    st.markdown('<div class="summary-toggle-spacer"></div>', unsafe_allow_html=True)
    if st.button(button_label, key="summary-expand-toggle", use_container_width=True):
        st.session_state.summary_expanded = not expanded
        st.rerun()
