import pandas as pd
from datasets import Dataset
from ragas import evaluate
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.metrics import answer_relevancy, faithfulness, context_precision, context_recall
from langchain_openai import OpenAIEmbeddings

from rag_engine import create_rag_chain
from data_loader import process_and_store_dart_data
from finance_store import get_financials, get_recent_events


TESTSET = [
    {
        "question": "삼성전자의 2025년 매출액은 얼마인가?",
        "ground_truth": "삼성전자의 2025년 매출액은 333,605,938,000,000원입니다.",
    },
    {
        "question": "삼성전자의 2025년 영업이익은 얼마인가?",
        "ground_truth": "삼성전자의 2025년 영업이익은 43,601,051,000,000원입니다.",
    },
    {
        "question": "삼성전자의 2025년 당기순이익은 얼마인가?",
        "ground_truth": "삼성전자의 2025년 당기순이익은 45,206,805,000,000원입니다.",
    },
    {
        "question": "삼성전자의 주요 사업 부문은 무엇인가?",
        "ground_truth": "삼성전자의 주요 사업 부문은 DX, DS, SDC, Harman입니다.",
    },
    {
        "question": "삼성전자의 주요 제품은 무엇인가?",
        "ground_truth": "삼성전자의 주요 제품은 TV, 모니터, 냉장고, 세탁기, 에어컨, 스마트폰, 네트워크시스템, PC, DRAM, NAND Flash, 모바일AP, OLED 패널, 디지털 콕핏, 카오디오, 포터블 스피커 등입니다.",
    },
    {
        "question": "삼성전자 DS 부문은 무엇을 생산하나?",
        "ground_truth": "삼성전자 DS 부문은 DRAM, NAND Flash, 모바일AP 등의 제품을 생산합니다.",
    },
    {
        "question": "삼성전자의 2025년말 연결대상 종속기업 수는 몇 개인가?",
        "ground_truth": "삼성전자의 2025년말 연결대상 종속기업 수는 308개입니다.",
    },
    {
        "question": "네이버의 주요 사업은 무엇인가?",
        "ground_truth": "네이버는 검색 포털 네이버를 기반으로 광고, 커머스, 핀테크, 클라우드 및 기업용 솔루션, 콘텐츠 사업 등을 영위합니다.",
    },
    {
        "question": "LG화학의 주요 사업부문은 무엇인가?",
        "ground_truth": "LG화학은 석유화학사업, 첨단소재사업, 생명과학사업, LG에너지솔루션, 팜한농 사업을 운영합니다.",
    },
    {
        "question": "삼성전자의 2030년 화성 식품 사업 매출은 얼마인가?",
        "ground_truth": "주어진 공시 자료에서는 해당 내용을 찾을 수 없습니다.",
    },
    {
        "question": "삼성전자와 네이버 중 2025년 매출액이 더 큰 회사는?",
        "ground_truth": "2025년 매출액은 삼성전자가 네이버보다 큽니다.",
    },
    {
        "question": "삼성전자와 LG화학 중 2025년 영업이익이 더 큰 회사는?",
        "ground_truth": "2025년 영업이익은 삼성전자가 LG화학보다 큽니다.",
    },
    {
        "question": "네이버의 2025년 영업이익은 얼마인가?",
        "ground_truth": "네이버의 2025년 영업이익은 2,208,138,388,720원입니다.",
    },
    {
        "question": "LG화학의 2025년 당기순이익은 얼마인가?",
        "ground_truth": "LG화학의 2025년 당기순이익은 -977,063,000,000원입니다.",
    },
    {
        "question": "삼성전자의 위험관리 관련 내용은 무엇인가?",
        "ground_truth": "삼성전자는 환위험, 이자율위험, 신용위험, 유동성위험 등 금융위험 관리 내용을 공시합니다.",
    },
    {
        "question": "넥사다이내믹스의 최근 CB 발행 결정은 무엇인가?",
        "ground_truth": "넥사다이내믹스는 최근 1년 내 복수의 전환사채 발행 결정을 공시했으며, 2026년 4월 13일 결정된 85억원 규모 전환사채 발행 등이 포함됩니다.",
    },
    {
        "question": "넥사다이내믹스의 최근 타법인 주식 취득 결정 내용은?",
        "ground_truth": "넥사다이내믹스는 더스타파트너 주식 21,000주를 200억원 수준에 취득하고, 취득 후 지분율 100%를 확보하는 타법인 주식 취득 결정을 공시했습니다.",
    },
    {
        "question": "넥사다이내믹스의 최근 주요사항 공시를 요약해줘",
        "ground_truth": "최근 주요사항 공시에는 전환사채 발행, 타법인 주식 취득, 유상증자 등 자금조달과 신사업 관련 이벤트가 포함됩니다.",
    },
    {
        "question": "넥사다이내믹스 전환사채의 전환가액과 전환가능주식수는?",
        "ground_truth": "2026년 4월 13일 결정된 85억원 규모 전환사채의 전환가액은 1,303원이며 전환가능주식수는 6,523,407주입니다.",
    },
    {
        "question": "삼성전자 최근 전환사채 발행 공시는?",
        "ground_truth": "주어진 공시 자료에서는 해당 내용을 찾을 수 없습니다.",
    },
]


def _ensure_data_ready(company_codes):
    for code in company_codes:
        if get_financials(code) is None or (code == "351320" and not get_recent_events(code, limit=1)):
            process_and_store_dart_data(code)


def _run_rag_questions():
    rows = []

    for item in TESTSET:
        # Create a new chain instance per query to avoid memory context bleeding
        chain = create_rag_chain()
        result = chain.invoke({"question": item["question"]})
        answer = result.get("answer", "")
        source_documents = result.get("source_documents", [])
        contexts = [document.page_content for document in source_documents]

        rows.append(
            {
                "user_input": item["question"],
                "reference": item["ground_truth"],
                "retrieved_contexts": contexts,
                "response": answer,
                "question": item["question"],
                "ground_truth": item["ground_truth"],
                "contexts": contexts,
                "answer": answer,
            }
        )

    return rows


def main() -> None:
    print("평가 데이터를 준비합니다...")
    _ensure_data_ready(["005930", "035420", "051910", "351320"])

    rows = _run_rag_questions()
    dataset = Dataset.from_list(rows)
    embeddings = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(model="text-embedding-3-small")
    )

    result = evaluate(
        dataset,
        metrics=[
            answer_relevancy,
            faithfulness,
            context_precision,
            context_recall,
        ],
        embeddings=embeddings,
    )

    result_df = result.to_pandas()
    result_df.to_csv("evaluate_result.csv", index=False, encoding="utf-8-sig")
    print(result_df)


if __name__ == "__main__":
    main()
