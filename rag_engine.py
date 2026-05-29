import os
from typing import Iterable, List, Optional

from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from data_loader import EMBEDDING_MODEL, FAISS_INDEX_DIR
from finance_store import compare_metric, get_financials, get_recent_events
from query_router import COMPANY_ALIASES, route_query


load_dotenv()

RETRIEVER_K = 8
RETRIEVER_FETCH_K = 60
RETRIEVER_LAMBDA_MULT = 0.35

SYSTEM_PROMPT = """
당신은 금융 데이터 분석 전문가입니다.
반드시 주어진 Context(DART 공시 내용과 SQLite 재무 조회 결과)만을 바탕으로 답변하세요.
Context에 없는 내용은 절대 지어내지 말고, "주어진 공시 자료에서는 해당 내용을 찾을 수 없습니다"라고 답변하세요.
숫자는 정확하게 명시해야 합니다.
매출액, 영업이익, 당기순이익, 기업 간 비교 등 숫자 질문은 [SQLite 정형 재무 조회 결과]를 최우선 근거로 사용하세요.
사업 부문, 제품, 전략 질문은 [FAISS 검색 공시 Context]의 business_text 문서를 우선 사용하세요.
리스크, 위험, 소송, 제재, PF, 안전 질문은 risk_text 문서를 우선 사용하고, 부족하면 business_text 문서에서 보완하세요.
CB 발행, 타법인 주식 취득, 유상증자, 합병, 소송 등 수시공시 이벤트 질문은 [SQLite 수시공시 이벤트 조회 결과]와 event_text 문서를 우선 사용하세요.
이벤트 간 교차 참조 시 반드시 다음 규칙을 지키세요:
- 서로 다른 접수번호의 공시 문서끼리는, 같은 문서 안에서 명시적으로 연결되어 있을 때만 관계를 언급하세요.
- "A 전환사채의 목적이 타법인 취득이고 별도 B 타법인 취득 공시가 있다"는 것만으로 A=B로 단정하지 마세요.
- 특정 전환사채의 대상 법인을 찾을 때는, 해당 전환사채 공시 원문(같은 접수번호의 event_text)에 기재된 법인명을 우선 사용하세요.
- 연결 근거가 불충분하면 "해당 전환사채 공시만으로는 구체적 대상 법인을 특정할 수 없습니다"라고 답하세요.
Context에 마크다운 표 형식의 데이터가 포함된 경우 행과 열의 의미를 주의 깊게 파악하세요.
Context에 보고서명과 접수번호가 있으면 답변 마지막에 출처를 간단히 덧붙이세요.

Context:
{context}

질문:
{question}

답변:
""".strip()


def _format_krw(value) -> str:
    if value is None:
        return "정보 없음"
    return f"{int(value):,}원"


def _metric_label(metric: Optional[str]) -> str:
    return {
        "revenue": "매출액",
        "operating_profit": "영업이익",
        "net_income": "당기순이익",
    }.get(metric or "", "재무 수치")


def _company_label(company_code: str) -> str:
    aliases = COMPANY_ALIASES.get(company_code, [company_code])
    return next((alias for alias in aliases if not alias.isdigit()), company_code)


def _format_financial_row(row: dict) -> str:
    return "\n".join(
        [
            "[SQLite 정형 재무 조회 결과]",
            f"기업코드: {row.get('company_code')}",
            f"회사명: {row.get('company_name') or _company_label(row.get('company_code', ''))}",
            f"사업연도: {row.get('business_year')}",
            f"매출액: {_format_krw(row.get('revenue'))}",
            f"영업이익: {_format_krw(row.get('operating_profit'))}",
            f"당기순이익: {_format_krw(row.get('net_income'))}",
            f"보고서: {row.get('report_name') or '정보 없음'}",
            f"접수번호: {row.get('receipt_no') or '정보 없음'}",
        ]
    )


def _format_event_row(row: dict) -> str:
    fields = [
        ("이벤트", row.get("event_label")),
        ("이벤트유형", row.get("event_type")),
        ("기업코드", row.get("company_code")),
        ("회사명", row.get("company_name") or _company_label(row.get("company_code", ""))),
        ("보고서", row.get("report_name")),
        ("접수번호", row.get("receipt_no")),
        ("접수일자", row.get("receipt_date")),
        ("결정일", row.get("decision_date")),
        ("금액", _format_krw(row.get("amount")) if row.get("amount") is not None else None),
        ("대상회사", row.get("target_company")),
        ("목적", row.get("purpose")),
        ("전환가액", _format_krw(row.get("conversion_price")) if row.get("conversion_price") is not None else None),
        ("전환가능주식수", f"{int(row.get('conversion_shares')):,}주" if row.get("conversion_shares") is not None else None),
        ("취득주식수", f"{int(row.get('acquisition_shares')):,}주" if row.get("acquisition_shares") is not None else None),
        ("취득후 지분율", row.get("acquisition_ratio")),
        ("지급방법", row.get("payment_method")),
        ("대상법인 상세(LLM추출)", row.get("target_detail")),
    ]
    lines = ["[SQLite 수시공시 이벤트 조회 결과]"]
    for label, value in fields:
        if value not in (None, ""):
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _filter_by_company(documents: Iterable[Document], company_codes: List[str]) -> List[Document]:
    if not company_codes:
        return list(documents)
    allowed = set(company_codes)
    return [doc for doc in documents if doc.metadata.get("company_code") in allowed]


def _prefer_data_type(documents: List[Document], preferred: str) -> List[Document]:
    preferred_docs = [doc for doc in documents if doc.metadata.get("data_type") == preferred]
    remaining = [doc for doc in documents if doc.metadata.get("data_type") != preferred]
    return preferred_docs + remaining


class HybridRAGChain:
    def __init__(self, vector_store: FAISS, llm: ChatOpenAI, company_codes: Optional[List[str]] = None):
        self.vector_store = vector_store
        self.llm = llm
        self.company_codes = company_codes or []
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("human", "{question}"),
        ])
        self.chat_history: List[tuple[str, str]] = []

    def _sql_context(self, query_info: dict) -> tuple[str, List[str]]:
        """Returns (context_string, matched_receipt_nos)."""
        intent = query_info["intent"]
        metric = query_info.get("metric")
        business_year = query_info.get("business_year")
        routed_codes = query_info.get("company_codes") or []
        company_codes = routed_codes or self.company_codes

        if intent == "comparison" and metric and len(company_codes) >= 2:
            rows = compare_metric(company_codes, metric, business_year=business_year)
            if not rows:
                return ""
            lines = [f"[SQLite 정형 재무 비교 결과] 지표: {_metric_label(metric)}"]
            for rank, row in enumerate(rows, start=1):
                lines.append(
                    f"{rank}. {row.get('company_name') or _company_label(row.get('company_code', ''))} "
                    f"({row.get('company_code')}), 사업연도 {row.get('business_year')}, "
                    f"{_metric_label(metric)} {_format_krw(row.get(metric))}, "
                    f"보고서 {row.get('report_name')}, 접수번호 {row.get('receipt_no')}"
                )
            return "\n".join(lines), []

        if intent in {"financial_numeric", "comparison"} and company_codes:
            rows = [
                get_financials(code, business_year=business_year)
                for code in company_codes
            ]
            return "\n\n".join(_format_financial_row(row) for row in rows if row), []

        if intent == "event_disclosure" and company_codes:
            event_types = query_info.get("event_types") or []
            rows = []
            seen_keys = set()
            for code in company_codes:
                # 1) Fetch type-filtered events first (higher relevance)
                if event_types:
                    for event_type in event_types:
                        for row in get_recent_events(code, event_type=event_type, limit=10):
                            key = (row.get("receipt_no"), row.get("event_type"))
                            if key not in seen_keys:
                                seen_keys.add(key)
                                rows.append(row)
                # 2) Always also fetch ALL recent events for cross-referencing
                #    (e.g., CB purpose says "타법인 취득자금" → equity_acquisition has the target)
                for row in get_recent_events(code, limit=15):
                    key = (row.get("receipt_no"), row.get("event_type"))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        rows.append(row)
            # Collect receipt_nos; if amounts in query, prioritize matching events
            receipt_nos = [r.get("receipt_no") for r in rows if r.get("receipt_no")]
            amounts = query_info.get("amounts") or []
            if amounts:
                matched = [r.get("receipt_no") for r in rows
                           if r.get("amount") in amounts and r.get("receipt_no")]
                if matched:
                    receipt_nos = matched + [rn for rn in receipt_nos if rn not in matched]
            return "\n\n".join(_format_event_row(row) for row in rows[:20]), receipt_nos

        # Fallback: for unknown intent with loaded companies, provide recent events
        # so the LLM can answer follow-up questions about related entities
        if intent == "unknown" and self.company_codes:
            rows = []
            for code in self.company_codes:
                rows.extend(get_recent_events(code, limit=10))
            if rows:
                receipt_nos = [r.get("receipt_no") for r in rows if r.get("receipt_no")]
                return "\n\n".join(_format_event_row(row) for row in rows[:15]), receipt_nos

        return "", []

    def _faiss_context(self, query: str, query_info: dict, receipt_nos: Optional[List[str]] = None) -> List[Document]:
        company_codes = query_info.get("company_codes") or self.company_codes
        base_kwargs = {
                "k": RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "lambda_mult": RETRIEVER_LAMBDA_MULT,
        }

        # Step 1: Receipt-aware retrieval — fetch event_text docs matching specific receipt_nos
        receipt_docs = []
        seen = set()
        if receipt_nos and query_info.get("intent") in {"event_disclosure", "unknown"}:
            for receipt_no in receipt_nos[:5]:  # Limit to top 5 receipt_nos
                try:
                    rn_retriever = self.vector_store.as_retriever(
                        search_type="mmr",
                        search_kwargs={
                            **base_kwargs,
                            "filter": {"receipt_no": receipt_no},
                        },
                    )
                    for doc in rn_retriever.invoke(query):
                        key = (
                            doc.metadata.get("receipt_no"),
                            doc.metadata.get("chunk_index"),
                            doc.page_content[:80],
                        )
                        if key not in seen:
                            seen.add(key)
                            receipt_docs.append(doc)
                except Exception:
                    pass  # FAISS filter may fail if no docs match

        # Step 2: Standard company-code-based retrieval
        if company_codes:
            documents = []
            for code in company_codes:
                retriever = self.vector_store.as_retriever(
                    search_type="mmr",
                    search_kwargs={**base_kwargs, "filter": {"company_code": code}},
                )
                for doc in retriever.invoke(query):
                    key = (
                        doc.metadata.get("company_code"),
                        doc.metadata.get("data_type"),
                        doc.metadata.get("chunk_index"),
                        doc.page_content[:80],
                    )
                    if key not in seen:
                        seen.add(key)
                        documents.append(doc)
        else:
            retriever = self.vector_store.as_retriever(
                search_type="mmr",
                search_kwargs=base_kwargs,
            )
            documents = retriever.invoke(query)

        documents = _filter_by_company(documents, company_codes)

        if query_info["intent"] == "risk_analysis":
            documents = _prefer_data_type(documents, "risk_text")
        elif query_info["intent"] == "event_disclosure":
            documents = [doc for doc in documents if doc.metadata.get("data_type") == "event_text"]
        elif query_info["intent"] == "business_text":
            documents = _prefer_data_type(documents, "business_text")
        elif query_info["intent"] in {"financial_numeric", "comparison"}:
            documents = _prefer_data_type(documents, "structured_financials")

        # Merge: receipt-specific docs first, then standard docs
        merged = receipt_docs + [d for d in documents if d not in receipt_docs]
        return merged[:RETRIEVER_K + len(receipt_docs)]  # Allow extra slots for receipt docs

    def invoke(self, inputs: dict) -> dict:
        question = (inputs.get("question") or inputs.get("query") or "").strip()
        query_info = route_query(question)
        sql_context, receipt_nos = self._sql_context(query_info)
        source_documents = self._faiss_context(question, query_info, receipt_nos=receipt_nos)
        faiss_context = "\n\n".join(doc.page_content for doc in source_documents)

        context_parts = []
        if sql_context:
            context_parts.append(sql_context)
        if faiss_context:
            context_parts.append("[FAISS 검색 공시 Context]\n" + faiss_context)
        if self.chat_history:
            recent_history = "\n".join(
                f"사용자: {user}\n답변: {assistant}"
                for user, assistant in self.chat_history[-5:]
            )
            context_parts.append("[최근 대화 기록]\n" + recent_history)

        context = "\n\n".join(context_parts) if context_parts else "검색된 Context가 없습니다."
        response = self.llm.invoke(self.prompt.format_messages(context=context, question=question))
        answer = getattr(response, "content", str(response))
        self.chat_history.append((question, answer))
        if len(self.chat_history) > 10:
            self.chat_history = self.chat_history[-10:]

        return {
            "answer": answer,
            "source_documents": source_documents,
            "query_info": query_info,
            "sql_context": sql_context,
        }


def create_rag_chain(
    model_name: str = "gpt-5.4",
    company_codes: Optional[List[str]] = None,
    company_code: Optional[str] = None,
):
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다.")

    requested_codes = company_codes or ([company_code] if company_code else None)
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    vector_store = FAISS.load_local(
        FAISS_INDEX_DIR,
        embeddings,
        allow_dangerous_deserialization=True,
    )
    llm = ChatOpenAI(model=model_name, temperature=0)
    return HybridRAGChain(vector_store=vector_store, llm=llm, company_codes=requested_codes)


def get_answer(query: str, chain) -> str:
    if not query or not query.strip():
        return "질문을 입력해 주세요."

    result = chain.invoke({"question": query.strip()})
    return result.get("answer", "답변을 생성하지 못했습니다.")
