const companies = [
  {
    id: "samsung",
    name: "삼성전자",
    code: "005930",
    sector: "반도체 · 모바일",
    status: "관망",
    metrics: {
      revenue: "258.9조",
      revenueDelta: "전년 대비 +14.3%",
      profit: "32.7조",
      profitDelta: "마진 12.6%",
      debt: "27.8%",
      debtDelta: "안정 구간",
      signal: "관망",
      signalDelta: "근거 4개 문서",
      confidence: "근거 일치 86%",
    },
    filings: [
      {
        title: "2025 사업보고서",
        date: "2026.03.18",
        type: "정기공시",
        summary: "메모리 업황 회복과 고부가 제품 비중 확대로 수익성이 개선됐으나, 설비투자 부담은 유지됩니다.",
      },
      {
        title: "2026 1분기보고서",
        date: "2026.05.15",
        type: "분기공시",
        summary: "AI 서버향 HBM 매출이 증가했고 모바일 부문은 원가 개선 효과가 반영됐습니다.",
      },
      {
        title: "주요사항보고서",
        date: "2026.04.02",
        type: "수시공시",
        summary: "첨단 패키징 라인 증설 계획이 확인되어 중장기 투자 지출이 확대될 가능성이 있습니다.",
      },
    ],
    brief: [
      ["재무", "매출과 영업이익 모두 회복 구간입니다. 현금성 자산이 충분해 단기 유동성 위험은 낮게 보입니다."],
      ["사업", "메모리, 파운드리, 모바일이 핵심 축입니다. AI 서버 수요가 실적 회복의 주요 변수입니다."],
      ["리스크", "반도체 가격 변동, 대규모 설비투자, 미중 수출 규제는 밸류에이션 할인 요인입니다."],
      ["조언", "단기 추격 매수보다 실적 발표와 HBM 수주 확인 후 분할 접근이 더 합리적입니다."],
    ],
  },
  {
    id: "hyundai",
    name: "현대자동차",
    code: "005380",
    sector: "자동차 · 모빌리티",
    status: "긍정",
    metrics: {
      revenue: "162.7조",
      revenueDelta: "전년 대비 +8.1%",
      profit: "15.4조",
      profitDelta: "마진 9.5%",
      debt: "62.4%",
      debtDelta: "금융 부문 포함",
      signal: "긍정",
      signalDelta: "근거 5개 문서",
      confidence: "근거 일치 82%",
    },
    filings: [
      {
        title: "2025 사업보고서",
        date: "2026.03.21",
        type: "정기공시",
        summary: "SUV와 제네시스 판매 비중이 높아지며 제품 믹스가 개선됐고 환율 효과도 일부 반영됐습니다.",
      },
      {
        title: "2026 1분기보고서",
        date: "2026.05.14",
        type: "분기공시",
        summary: "북미 판매 호조가 이어졌지만 전기차 가격 경쟁과 인센티브 확대는 부담입니다.",
      },
      {
        title: "타법인 주식 취득",
        date: "2026.04.26",
        type: "수시공시",
        summary: "배터리와 자율주행 생태계 강화를 위한 전략 투자가 확인됩니다.",
      },
    ],
    brief: [
      ["재무", "영업 현금흐름이 견조하고 주주환원 여력이 유지됩니다. 자동차 본업의 수익성이 핵심 강점입니다."],
      ["사업", "내연기관 고수익 차종과 전기차 전환 투자가 동시에 진행되고 있습니다."],
      ["리스크", "전기차 수요 둔화, 관세, 원자재 비용, 금융 자회사 건전성 변화를 추적해야 합니다."],
      ["조언", "중장기 보유 관점은 유효하지만 전기차 가격 경쟁 심화 시 목표 비중을 낮춰야 합니다."],
    ],
  },
  {
    id: "naver",
    name: "NAVER",
    code: "035420",
    sector: "인터넷 · AI",
    status: "선별",
    metrics: {
      revenue: "10.1조",
      revenueDelta: "전년 대비 +11.8%",
      profit: "1.6조",
      profitDelta: "마진 15.8%",
      debt: "43.2%",
      debtDelta: "보통 구간",
      signal: "선별",
      signalDelta: "근거 3개 문서",
      confidence: "근거 일치 79%",
    },
    filings: [
      {
        title: "2025 사업보고서",
        date: "2026.03.25",
        type: "정기공시",
        summary: "검색 광고와 커머스가 안정적이며 AI 인프라 투자가 비용 증가 요인으로 나타납니다.",
      },
      {
        title: "2026 1분기보고서",
        date: "2026.05.16",
        type: "분기공시",
        summary: "커머스 거래액은 증가했지만 콘텐츠와 클라우드 수익성 회복 속도는 제한적입니다.",
      },
      {
        title: "기업설명회 자료",
        date: "2026.04.08",
        type: "IR",
        summary: "생성형 AI 검색과 광고 상품 고도화 전략이 제시됐습니다.",
      },
    ],
    brief: [
      ["재무", "매출 성장률은 양호하지만 AI 관련 비용 증가로 이익 레버리지 확인이 필요합니다."],
      ["사업", "검색, 커머스, 핀테크, 콘텐츠, 클라우드가 연결된 플랫폼 구조를 가지고 있습니다."],
      ["리스크", "광고 경기 둔화, 경쟁 플랫폼 부상, AI 투자 회수 시점 지연이 주요 리스크입니다."],
      ["조언", "성장성은 남아 있으나 밸류에이션 부담이 있어 실적 개선 확인 후 선별 접근이 적절합니다."],
    ],
  },
];

const prompts = [
  "최근 공시 기준 핵심 리스크는?",
  "사업보고서에서 성장 동력만 요약해줘",
  "재무제표 기준 투자 매력도는?",
  "다음 업데이트 때 추적할 항목은?",
];

let activeCompany = companies[0];
let activeMode = "summary";

const elements = {
  companyList: document.querySelector("#companyList"),
  companySearch: document.querySelector("#companySearch"),
  selectedCompanyName: document.querySelector("#selectedCompanyName"),
  revenueMetric: document.querySelector("#revenueMetric"),
  revenueDelta: document.querySelector("#revenueDelta"),
  profitMetric: document.querySelector("#profitMetric"),
  profitDelta: document.querySelector("#profitDelta"),
  debtMetric: document.querySelector("#debtMetric"),
  debtDelta: document.querySelector("#debtDelta"),
  signalMetric: document.querySelector("#signalMetric"),
  signalDelta: document.querySelector("#signalDelta"),
  filingList: document.querySelector("#filingList"),
  briefContent: document.querySelector("#briefContent"),
  confidenceLabel: document.querySelector("#confidenceLabel"),
  quickPrompts: document.querySelector("#quickPrompts"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  syncButton: document.querySelector("#syncButton"),
  syncStatus: document.querySelector("#syncStatus"),
};

function renderCompanies(filter = "") {
  const normalized = filter.trim().toLowerCase();
  const visibleCompanies = companies.filter((company) => {
    return `${company.name} ${company.code} ${company.sector}`.toLowerCase().includes(normalized);
  });

  elements.companyList.innerHTML = visibleCompanies
    .map(
      (company) => `
        <button class="company-button ${company.id === activeCompany.id ? "active" : ""}" type="button" data-company-id="${company.id}">
          <span>
            <strong>${company.name}</strong>
            <span>${company.code} · ${company.sector}</span>
          </span>
          <span class="pill">${company.status}</span>
        </button>
      `,
    )
    .join("");
}

function matchingCompanies(filter = "") {
  const normalized = filter.trim().toLowerCase();
  return companies.filter((company) => {
    return `${company.name} ${company.code} ${company.sector}`.toLowerCase().includes(normalized);
  });
}

function renderCompany() {
  const { metrics } = activeCompany;
  elements.selectedCompanyName.textContent = activeCompany.name;
  elements.revenueMetric.textContent = metrics.revenue;
  elements.revenueDelta.textContent = metrics.revenueDelta;
  elements.profitMetric.textContent = metrics.profit;
  elements.profitDelta.textContent = metrics.profitDelta;
  elements.debtMetric.textContent = metrics.debt;
  elements.debtDelta.textContent = metrics.debtDelta;
  elements.signalMetric.textContent = metrics.signal;
  elements.signalDelta.textContent = metrics.signalDelta;
  elements.confidenceLabel.textContent = metrics.confidence;

  elements.filingList.innerHTML = activeCompany.filings
    .map(
      (filing) => `
        <article class="filing-item">
          <div class="filing-meta">
            <span>${filing.date}</span>
            <span>${filing.type}</span>
          </div>
          <strong>${filing.title}</strong>
          <p>${filing.summary}</p>
        </article>
      `,
    )
    .join("");

  elements.briefContent.innerHTML = activeCompany.brief
    .map(
      ([label, text]) => `
        <div class="brief-row">
          <strong>${label}</strong>
          <p>${text}</p>
        </div>
      `,
    )
    .join("");

  renderCompanies(elements.companySearch.value);
}

function renderPrompts() {
  elements.quickPrompts.innerHTML = prompts
    .map((prompt) => `<button class="prompt-button" type="button" data-prompt="${prompt}">${prompt}</button>`)
    .join("");
}

function addMessage(role, text, source = "") {
  const message = document.createElement("article");
  message.className = `message ${role}`;
  message.innerHTML = `<p>${text}</p>${source ? `<small>${source}</small>` : ""}`;
  elements.messages.append(message);
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function buildAnswer(question) {
  const riskLine = activeCompany.brief.find(([label]) => label === "리스크")?.[1] || "";
  const adviceLine = activeCompany.brief.find(([label]) => label === "조언")?.[1] || "";
  const source = activeCompany.filings.slice(0, 2).map((filing) => filing.title).join(", ");

  if (activeMode === "risk" || question.includes("리스크")) {
    return {
      text: `${activeCompany.name}의 핵심 리스크는 ${riskLine} 현재 신호는 '${activeCompany.status}'로 분류됩니다.`,
      source,
    };
  }

  if (activeMode === "advice" || question.includes("매수") || question.includes("투자")) {
    return {
      text: `${adviceLine} 재무 지표만 보면 매출 ${activeCompany.metrics.revenue}, 영업이익 ${activeCompany.metrics.profit} 수준이며, 단일 가격 예측보다 공시 변화 추적이 우선입니다.`,
      source,
    };
  }

  return {
    text: `${activeCompany.name}은 ${activeCompany.brief[0][1]} ${activeCompany.brief[1][1]}`,
    source,
  };
}

elements.companyList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-company-id]");
  if (!button) return;
  activeCompany = companies.find((company) => company.id === button.dataset.companyId) || activeCompany;
  renderCompany();
  addMessage("bot", `${activeCompany.name} 공시 문서로 대화 컨텍스트를 전환했습니다.`, "워치리스트");
});

elements.companySearch.addEventListener("input", (event) => {
  const matches = matchingCompanies(event.target.value);
  if (matches.length > 0 && !matches.some((company) => company.id === activeCompany.id)) {
    activeCompany = matches[0];
    renderCompany();
    return;
  }

  renderCompanies(event.target.value);
});

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll("[data-mode]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    activeMode = button.dataset.mode;
  });
});

elements.quickPrompts.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (!button) return;
  elements.chatInput.value = button.dataset.prompt;
  elements.chatInput.focus();
});

elements.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = elements.chatInput.value.trim();
  if (!question) return;

  addMessage("user", question);
  elements.chatInput.value = "";

  window.setTimeout(() => {
    const answer = buildAnswer(question);
    addMessage("bot", answer.text, `출처: ${answer.source}`);
  }, 260);
});

elements.syncButton.addEventListener("click", () => {
  elements.syncButton.classList.add("syncing");
  elements.syncStatus.textContent = "DART 공시 확인 중";

  window.setTimeout(() => {
    elements.syncButton.classList.remove("syncing");
    elements.syncStatus.textContent = "방금 동기화";
    addMessage("bot", "새 공시 3건을 확인했고 요약 인덱스를 갱신했습니다.", "DART Open API");
  }, 900);
});

renderCompanies();
renderCompany();
renderPrompts();
addMessage("bot", "관심 기업의 최신 DART 공시를 기준으로 재무제표, 사업보고서, 리스크, 투자 관점을 함께 답변합니다.", "시스템");
