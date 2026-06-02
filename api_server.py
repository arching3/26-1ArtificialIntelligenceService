from __future__ import annotations

import json
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


HOST = "127.0.0.1"
PORT = 8000

POPULAR_COMPANIES = ["삼성전자", "SK하이닉스", "NAVER", "LG화학", "현대자동차"]

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


def company_key(value: str) -> str:
    compact = str(value or "").replace(" ", "").lower()
    if "삼성" in compact or "samsung" in compact or "005930" in compact:
        return "삼성전자"
    if "하이닉스" in compact or "hynix" in compact or "000660" in compact:
        return "SK하이닉스"
    return str(value or "").strip() or "삼성전자"


def search_companies(query: str = "") -> list[str]:
    try:
        from company_resolver import learned_company_candidates

        learned = [candidate.corp_name for candidate in learned_company_candidates() if candidate.corp_name]
    except Exception:
        learned = []

    candidates = list(dict.fromkeys(learned + POPULAR_COMPANIES))
    if not query:
        return candidates[:8]
    compact_query = query.replace(" ", "").lower()
    matched = [name for name in candidates if compact_query in name.replace(" ", "").lower()]
    return matched or [name for name in POPULAR_COMPANIES if compact_query in name.replace(" ", "").lower()]


def summary_for(company: str, period: str = "") -> dict[str, str]:
    key = company_key(company)
    summary = SAMPLE_SUMMARIES.get(key)
    if summary:
        return summary
    return {
        "overview": f"{company}의 사업 개요 데이터는 아직 백엔드 인덱스에 충분히 연결되지 않았습니다.",
        "benefit": "수익 구조는 공시 원문 연결 후 표시됩니다.",
        "earnings": f"{period or '선택 기간'} 기준 실적 동향은 데이터 적재 후 확인할 수 있습니다.",
        "risk": "주요 리스크는 사업보고서 위험 문단 연결 후 표시됩니다.",
        "changing": "주요 변화는 최근 공시 수집 이후 표시됩니다.",
        "status": "재무 상태는 정형 재무 데이터 연결 후 표시됩니다.",
        "anomaly": "특이사항은 아직 없습니다.",
    }


def stock_rows(company: str, realtime: bool = False) -> list[list[Any]]:
    key = company_key(company)
    prices = SAMPLE_STOCKS.get(key, SAMPLE_STOCKS["삼성전자"])
    now = datetime.now().replace(second=0, microsecond=0)
    if realtime:
        minute_bucket = now.minute // 10
        bump = minute_bucket * (110 if key == "삼성전자" else 480)
        return [[now.strftime("datetime.date(%Y.%m.%d|%H:%M)"), float(prices[-1] + bump)]]
    start = now - timedelta(days=len(prices) - 1)
    return [
        [(start + timedelta(days=index)).strftime("datetime.date(%Y.%m.%d|%H:%M)"), float(price)]
        for index, price in enumerate(prices)
    ]


def chat_answer(prompt: str, company: str, period: str = "") -> str:
    key = company_key(company)
    try:
        from company_resolver import resolve_company
        from rag_engine import create_rag_chain, get_answer

        resolved = resolve_company(key)
        if resolved.selected:
            chain = create_rag_chain(company_codes=[resolved.selected.stock_code])
            return get_answer(prompt, chain)
    except Exception:
        pass

    return (
        f"{key} 기준 샘플 답변입니다. {period or '선택 기간'}에는 공시 요약과 주가 흐름 모두 "
        "업황 회복 기대를 일부 반영하고 있습니다. 실제 답변은 DART/OpenAI 키와 FAISS 인덱스가 연결되면 "
        "공시 근거 기반으로 생성됩니다."
    )


class ApiHandler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if parsed.path == "/api/companies/search":
            body = self._read_json()
            search_query = query.get("query", [""])[0] or body.get("query", "")
            self._send_json({"list": search_companies(str(search_query))})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body = self._read_json()
        if parsed.path == "/api/companies/list":
            self._send_json({"ok": True, "companies": body.get("companies", [])})
            return
        if parsed.path.startswith("/api/companies/") and parsed.path.endswith("/summary"):
            raw_name = parsed.path.removeprefix("/api/companies/").removesuffix("/summary")
            company = body.get("name") or unquote(raw_name.strip("/"))
            self._send_json(summary_for(str(company), str(body.get("period", ""))))
            return
        if parsed.path == "/api/chat":
            self._send_json(
                {
                    "answer": chat_answer(
                        str(body.get("prompt", "")),
                        str(body.get("company", "")),
                        str(body.get("period", "")),
                    )
                }
            )
            return
        if parsed.path == "/api/companies/stocks":
            self._send_json({"stocks": stock_rows(str(body.get("company", "")), realtime=False)})
            return
        if parsed.path == "/api/companies/stocks_realtime":
            self._send_json({"stocks": stock_rows(str(body.get("company", "")), realtime=True)})
            return
        self._send_json({"error": "not found"}, status=404)


if __name__ == "__main__":
    print(f"Serving API on http://{HOST}:{PORT}")
    HTTPServer((HOST, PORT), ApiHandler).serve_forever()
