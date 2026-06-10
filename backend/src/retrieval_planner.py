from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field

from .query_analysis import QueryAnalysis


IndexType = Literal["regular", "event"]


class RetrievalPlan(BaseModel):
    use_sql: bool = False
    use_financial_sql: bool = False
    use_event_sql: bool = False
    index_types: List[IndexType] = Field(default_factory=list)
    preferred_data_types: List[str] = Field(default_factory=list)
    candidate_count: int = Field(default=8, ge=1)
    final_count: int = Field(default=8, ge=1)

    @property
    def candidate_k(self) -> int:
        return self.candidate_count

    @property
    def final_k(self) -> int:
        return self.final_count

    @property
    def use_regular_index(self) -> bool:
        return "regular" in self.index_types

    @property
    def use_event_index(self) -> bool:
        return "event" in self.index_types

    @property
    def data_type_priority(self) -> List[str]:
        return self.preferred_data_types


def plan_retrieval(
    analysis: QueryAnalysis,
    *,
    final_count: int = 8,
) -> RetrievalPlan:
    """Convert query analysis into storage and index retrieval choices."""
    intents = set(analysis.intents)
    use_financial_sql = bool(
        (intents & {"financial_numeric", "comparison"} or analysis.metrics)
        and analysis.scope not in {"segment", "product", "region"}
    )
    use_event_sql = bool("event_disclosure" in intents or analysis.event_types)
    use_sql = use_financial_sql or use_event_sql

    index_types: List[IndexType] = []
    if intents & {"financial_numeric", "comparison", "risk_analysis", "business_text"}:
        index_types.append("regular")
    if "event_disclosure" in intents:
        index_types.append("event")
    if not index_types and "stock_code_lookup" not in intents:
        index_types = ["regular", "event"]

    final_count = max(1, final_count)
    high_recall = bool(
        len(intents - {"unknown"}) > 1
        or len(analysis.metrics) > 1
        or len(index_types) > 1
        or analysis.scope in {"segment", "product", "region"}
    )
    multiplier = 4 if high_recall or intents & {
        "financial_numeric",
        "comparison",
        "event_disclosure",
        "risk_analysis",
    } else 2

    return RetrievalPlan(
        use_sql=use_sql,
        use_financial_sql=use_financial_sql,
        use_event_sql=use_event_sql,
        index_types=index_types,
        preferred_data_types=analysis.preferred_data_types,
        candidate_count=final_count * multiplier,
        final_count=final_count,
    )
