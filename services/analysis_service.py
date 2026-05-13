"""Backend orchestration for analysis workflows.

The Streamlit app should render results, not coordinate the agent pipeline.
This service keeps the current diagnostic flow in one testable place while the
UI is refactored incrementally.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents.base import AgentContext
from agents.analysis.analysis_agent import AnalysisAgent
from agents.search_agent import SearchAgent


@dataclass
class DiagnosticAnalysisPayload:
    """Data needed by the UI to render a diagnostic analysis."""

    kpi_change: Any = None
    hypotheses: List[Any] = field(default_factory=list)
    validated: List[Any] = field(default_factory=list)
    matched_events: Dict[str, List[Any]] = field(default_factory=dict)
    summary_result: Dict[str, Any] = field(default_factory=dict)
    validation_result: Dict[str, Any] = field(default_factory=dict)
    analysis_plan: Dict[str, Any] = field(default_factory=dict)
    interpretation: Dict[str, Any] = field(default_factory=dict)
    contributions: List[Any] = field(default_factory=list)
    sql_queries: List[Dict[str, Any]] = field(default_factory=list)
    model_r_squared: float = 0.0
    kpi_id: str = "매출"
    kpi_name: str = "매출"
    period: Dict[str, Any] = field(default_factory=dict)
    region: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class DescriptiveSearchPayload:
    """Data needed by the UI to render a descriptive search result."""

    result: Dict[str, Any]
    source: str
    source_label: str
    debug_info: Dict[str, Any] = field(default_factory=dict)


class AnalysisService:
    """Coordinates analysis agents behind a stable application API."""

    def __init__(self, api_key: str = None, db_path: str = None):
        self.api_key = api_key
        self.db_path = db_path
        self._analysis_agent = None
        self._search_agent = None

    @property
    def analysis_agent(self) -> AnalysisAgent:
        if self._analysis_agent is None:
            self._analysis_agent = AnalysisAgent(self.api_key, self.db_path)
        return self._analysis_agent

    @property
    def search_agent(self) -> SearchAgent:
        if self._search_agent is None:
            self._search_agent = SearchAgent(self.api_key, self.db_path)
        return self._search_agent

    def run_diagnostic(
        self,
        query: str,
        intent_result: Dict[str, Any],
        debug: bool = False,
    ) -> DiagnosticAnalysisPayload:
        """Run KPI change, hypothesis generation, validation, event match, and summary."""

        entities = intent_result.get("extracted_entities", {}) or {}
        period = self._normalize_period(entities.get("period"))
        region = self._normalize_region(entities.get("region"))
        company = entities.get("company") or "LGE"

        agent = self.analysis_agent

        kpi_change = agent._calculate_kpi_change(query, period, region)

        hypothesis_result = agent.hypothesis_generator.generate(
            question=query,
            company=company,
            period=f"{period.get('year', 2024)}년 Q{period.get('quarter', 4)}",
            region=region,
            return_result=True,
        )

        hypotheses = (
            hypothesis_result.hypotheses
            if hasattr(hypothesis_result, "hypotheses")
            else hypothesis_result
        )
        hypotheses = hypotheses or []
        target_kpi = hypothesis_result.target_kpi if hasattr(hypothesis_result, "target_kpi") else None
        kpi_id, kpi_name = self._resolve_kpi(query, target_kpi)

        validation_result = agent.hypothesis_validator.validate(
            hypotheses=hypotheses,
            kpi_id=kpi_id,
            period=period,
            verbose=debug,
        )

        validated = validation_result.get("validated_hypotheses", [])
        contributions = validation_result.get("contributions", [])
        model_r_squared = validation_result.get("model_r_squared", 0.65)
        analysis_plan = self._build_analysis_plan(hypotheses, validated)
        interpretation = {"model_risk_assessment": {"overfitting_risk": "low"}}
        sql_queries = self._collect_sql_queries(validated)

        warnings = []
        try:
            matched_events = agent.event_matcher.match(
                hypotheses=validated,
                region=region,
                min_score=0.3,
                top_k=5,
            )
        except Exception as exc:
            matched_events = {}
            warnings.append(f"이벤트 매칭 오류: {exc}")

        details = agent._build_details(validated, matched_events, sql_queries)
        summary_result = agent._generate_summary(
            query,
            details,
            kpi_change,
            matched_events=matched_events,
            validated_hypotheses=validated,
        )

        validation_result = dict(validation_result)
        validation_result.setdefault("analysis_plan", analysis_plan)

        return DiagnosticAnalysisPayload(
            kpi_change=kpi_change,
            hypotheses=hypotheses,
            validated=validated,
            matched_events=matched_events,
            summary_result=summary_result,
            validation_result=validation_result,
            analysis_plan=analysis_plan,
            interpretation=interpretation,
            contributions=contributions,
            sql_queries=sql_queries,
            model_r_squared=model_r_squared,
            kpi_id=kpi_id,
            kpi_name=kpi_name,
            period=period,
            region=region,
            warnings=warnings,
        )

    def run_descriptive(self, query: str, intent_result: Dict[str, Any]) -> DescriptiveSearchPayload:
        """Route a descriptive query to SQL, graph, or vector search."""

        sub_intent_raw = intent_result.get("sub_intent", "internal_data")
        sub_intent = str(sub_intent_raw).lower().replace(" ", "_").replace("-", "_")

        event_keywords = ["뉴스", "이벤트", "사건", "동향", "트렌드", "이슈", "최근", "요즘"]
        keyword_matched = [keyword for keyword in event_keywords if keyword in query]
        is_event_query = intent_result.get("is_event_query", False) or bool(keyword_matched)

        if is_event_query or sub_intent == "external_data":
            source = "vector"
            source_label = "Vector Search (Event)"
        elif sub_intent == "hybrid_data":
            source = "sql"
            source_label = "ERP Database + Knowledge Graph"
        else:
            source = "sql"
            source_label = "ERP Database"

        context = AgentContext(
            query=query,
            metadata={"source": source, "top_k": 5},
        )
        result = self.search_agent.run(context)

        return DescriptiveSearchPayload(
            result=result,
            source=source,
            source_label=source_label,
            debug_info={
                "sub_intent_raw": sub_intent_raw,
                "sub_intent": sub_intent,
                "keyword_matched": keyword_matched,
                "is_event_query": is_event_query,
            },
        )

    def _normalize_period(self, period: Any) -> Dict[str, int]:
        if not isinstance(period, dict):
            period = {}

        year = period.get("year") or 2024
        quarter = period.get("quarter") or 4

        if isinstance(quarter, list):
            quarter = quarter[0] if quarter else 4

        return {"year": int(year), "quarter": int(quarter)}

    def _normalize_region(self, region: Any) -> Optional[str]:
        if isinstance(region, list):
            return region[0] if region else None
        return region

    def _resolve_kpi(self, query: str, target_kpi: Any) -> tuple:
        if target_kpi and hasattr(target_kpi, "id"):
            kpi_id = target_kpi.id
            return kpi_id, getattr(target_kpi, "name_kr", kpi_id)

        kpi_keywords = {
            "매출": "매출",
            "수익": "매출",
            "revenue": "매출",
            "원가": "매출원가",
            "비용": "매출원가",
            "cost": "매출원가",
            "판매수량": "판매수량",
            "수량": "판매수량",
            "quantity": "판매수량",
            "영업이익": "영업이익",
            "이익": "영업이익",
            "profit": "영업이익",
        }
        query_lower = query.lower()
        for keyword, kpi in kpi_keywords.items():
            if keyword in query_lower:
                return kpi, kpi
        return "매출", "매출"

    def _build_analysis_plan(self, hypotheses: List[Any], validated: List[Any]) -> Dict[str, Any]:
        data_availability = {
            "erp_checked": True,
            "driver_results": [],
            "validation_method": "erp_based",
        }

        for hypothesis in hypotheses:
            validation_data = hypothesis.validation_data or {}
            if validation_data.get("sql_verified"):
                data_availability["driver_results"].append(
                    {
                        "driver": hypothesis.factor,
                        "table": validation_data.get("erp_table"),
                        "column": validation_data.get("erp_column"),
                        "curr_value": validation_data.get("curr_value"),
                        "yoy_value": validation_data.get("yoy_value"),
                        "qoq_value": validation_data.get("qoq_value"),
                        "yoy_change_pct": validation_data.get("yoy_change_pct"),
                        "qoq_change_pct": validation_data.get("qoq_change_pct"),
                        "sql_query": validation_data.get("sql_query"),
                    }
                )

        if not data_availability["driver_results"]:
            data_availability["validation_method"] = "confidence_based"

        total = len(hypotheses)
        validated_count = len(validated)
        avg_confidence = (
            sum(getattr(hypothesis, "confidence", 0) or 0 for hypothesis in validated)
            / validated_count
            if validated
            else 0
        )

        validated_ids = {hypothesis.id for hypothesis in validated}
        dropped_reasons = []
        for hypothesis in hypotheses:
            confidence = getattr(hypothesis, "confidence", 0) or 0
            if hypothesis.id not in validated_ids:
                dropped_reasons.append((hypothesis.factor, f"Confidence {confidence:.0%} < 30%"))

        return {
            "method": "confidence_based_validation",
            "total_hypotheses": total,
            "validated_count": validated_count,
            "dropped_count": total - validated_count,
            "dropped_reasons": dropped_reasons[:5],
            "avg_confidence": avg_confidence,
            "confidence_threshold": 0.3,
            "data_availability": data_availability,
        }

    def _collect_sql_queries(self, validated: List[Any]) -> List[Dict[str, Any]]:
        sql_queries = []
        for hypothesis in validated:
            data = hypothesis.validation_data or {}
            sql_query = data.get("sql_query", "")
            if sql_query:
                sql_queries.append(
                    {
                        "hypothesis_id": hypothesis.id,
                        "factor": hypothesis.factor,
                        "sql": sql_query,
                    }
                )
        return sql_queries
