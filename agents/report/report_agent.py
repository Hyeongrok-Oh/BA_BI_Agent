"""Report agent for turning analysis outputs into an executive report."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..analysis.analysis_agent import AnalysisAgent
from ..base import AgentContext, BaseAgent
from ..tools.sql_executor import SQLExecutor


class ReportType(str, Enum):
    """Supported report type for the thesis demo."""

    INTEGRATED_KPI_REPORT = "integrated_kpi_report"

    @classmethod
    def from_value(cls, value: str) -> "ReportType":
        normalized = (value or "").lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "performance_summary": cls.INTEGRATED_KPI_REPORT,
            "kpi_diagnosis": cls.INTEGRATED_KPI_REPORT,
            "driver_deep_dive": cls.INTEGRATED_KPI_REPORT,
            "risk_monitoring": cls.INTEGRATED_KPI_REPORT,
            "integrated_kpi_report": cls.INTEGRATED_KPI_REPORT,
        }
        return aliases.get(normalized, cls.INTEGRATED_KPI_REPORT)


@dataclass
class ReportRequest:
    """Parameters for an integrated KPI report."""

    report_type: ReportType = ReportType.INTEGRATED_KPI_REPORT
    year: int = 2025
    quarter: int = 4
    region: Optional[str] = None
    company: str = "LGE"
    threshold_pct: float = 10.0
    max_analyzed_kpis: int = 3
    kpis: List[str] = field(
        default_factory=lambda: ["매출", "판매량", "평균판매가", "OLED비중", "물류비", "마케팅비"]
    )


@dataclass
class KpiSnapshot:
    """Quarterly KPI movement used by the report agent."""

    name: str
    current_value: float
    previous_value: float
    change_pct: float
    risk_direction: str
    query: str
    is_significant: bool


class ReportAgent(BaseAgent):
    """Create a report by reformatting SQL snapshots and AnalysisAgent outputs."""

    name = "report_agent"
    description = "분석 에이전트 결과를 경영진 보고서 형태로 재구성합니다."

    KPI_DEFINITIONS = {
        "매출": {
            "risk_direction": "decrease",
            "query": "SELECT SUM(REVENUE_USD) AS value FROM TR_SALES WHERE SALES_DATE BETWEEN '{start}' AND '{end}'",
        },
        "판매량": {
            "risk_direction": "decrease",
            "query": "SELECT SUM(QTY) AS value FROM TR_SALES WHERE SALES_DATE BETWEEN '{start}' AND '{end}'",
        },
        "평균판매가": {
            "risk_direction": "decrease",
            "query": "SELECT SUM(REVENUE_USD) / NULLIF(SUM(QTY), 0) AS value FROM TR_SALES WHERE SALES_DATE BETWEEN '{start}' AND '{end}'",
        },
        "OLED비중": {
            "risk_direction": "decrease",
            "query": """
                SELECT SUM(CASE WHEN p.DISPLAY_TYPE = 'OLED' THEN s.QTY ELSE 0 END) * 100.0
                       / NULLIF(SUM(s.QTY), 0) AS value
                FROM TR_SALES s
                JOIN MD_PRODUCT p ON s.PRODUCT_ID = p.PRODUCT_ID
                WHERE s.SALES_DATE BETWEEN '{start}' AND '{end}'
            """,
        },
        "물류비": {
            "risk_direction": "increase",
            "query": "SELECT SUM(LOGISTICS_COST) AS value FROM TR_EXPENSE WHERE EXPENSE_DATE BETWEEN '{start}' AND '{end}'",
        },
        "마케팅비": {
            "risk_direction": "increase",
            "query": "SELECT SUM(MARKETING_COST) AS value FROM TR_EXPENSE WHERE EXPENSE_DATE BETWEEN '{start}' AND '{end}'",
        },
    }

    def __init__(self, api_key: str = None, db_path: str = None):
        super().__init__(api_key)
        self.db_path = db_path
        self.sql_executor = SQLExecutor(db_path)
        self.analysis_agent = AnalysisAgent(api_key, db_path)

    def generate(self, request: ReportRequest, verbose: bool = True) -> Dict[str, Any]:
        snapshots = self._scan_kpis(request)
        significant = [item for item in snapshots if item.is_significant]
        significant.sort(key=lambda item: abs(item.change_pct), reverse=True)

        analyses = []
        for snapshot in significant[: request.max_analyzed_kpis]:
            try:
                result = self.analysis_agent.analyze(
                    question=f"{request.year}년 Q{request.quarter} {snapshot.name} 변동 정합성 분석",
                    period={"year": request.year, "quarter": request.quarter},
                    region=request.region,
                    company=request.company,
                    verbose=verbose,
                )
                analyses.append({"kpi": snapshot.name, "analysis": result})
            except Exception as exc:
                analyses.append({"kpi": snapshot.name, "error": str(exc)})

        report = self._compose_report(request, snapshots, analyses)
        return {
            "title": report["title"],
            "report_type": request.report_type.value,
            "period": f"{request.year}년 Q{request.quarter}",
            "markdown": report["markdown"],
            "sections": report["sections"],
            "summary": report["summary"],
            "generated_at": report["generated_at"],
            "metadata": {
                "threshold_pct": request.threshold_pct,
                "significant_kpis": [item.name for item in significant],
                "source": "sql_snapshot_plus_analysis_agent",
            },
        }

    def run(self, context: AgentContext) -> Dict[str, Any]:
        metadata = context.metadata or {}
        request = ReportRequest(
            report_type=ReportType.from_value(metadata.get("report_type")),
            year=metadata.get("year", 2025),
            quarter=metadata.get("quarter", 4),
            region=metadata.get("region"),
            company=metadata.get("company", "LGE"),
            threshold_pct=metadata.get("threshold_pct", 10.0),
        )
        return self.generate(request, verbose=metadata.get("verbose", True))

    def _scan_kpis(self, request: ReportRequest) -> List[KpiSnapshot]:
        current_range = self._quarter_range(request.year, request.quarter)
        previous_range = self._previous_quarter_range(request.year, request.quarter)

        snapshots = []
        for kpi_name in request.kpis:
            definition = self.KPI_DEFINITIONS.get(kpi_name)
            if not definition:
                continue

            current_query = definition["query"].format(start=current_range[0], end=current_range[1])
            previous_query = definition["query"].format(start=previous_range[0], end=previous_range[1])
            current_value = self._execute_scalar(current_query)
            previous_value = self._execute_scalar(previous_query)
            change_pct = self._change_pct(current_value, previous_value)
            risk_direction = definition["risk_direction"]
            is_bad_direction = (
                (risk_direction == "decrease" and change_pct <= -request.threshold_pct)
                or (risk_direction == "increase" and change_pct >= request.threshold_pct)
            )

            snapshots.append(
                KpiSnapshot(
                    name=kpi_name,
                    current_value=current_value,
                    previous_value=previous_value,
                    change_pct=change_pct,
                    risk_direction=risk_direction,
                    query=current_query,
                    is_significant=is_bad_direction,
                )
            )

        return snapshots

    def _compose_report(
        self,
        request: ReportRequest,
        snapshots: List[KpiSnapshot],
        analyses: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        title = f"{request.year}년 Q{request.quarter} 통합 KPI 분석 보고서"
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        status_lines = [
            "| KPI | 현재값 | 전분기값 | QoQ | 상태 |",
            "|---|---:|---:|---:|---|",
        ]
        for item in snapshots:
            status = "검토 필요" if item.is_significant else "정상 범위"
            status_lines.append(
                f"| {item.name} | {item.current_value:,.2f} | {item.previous_value:,.2f} | {item.change_pct:+.1f}% | {status} |"
            )

        detail_lines = []
        source_lines = []
        for item in analyses:
            if item.get("error"):
                detail_lines.append(f"### {item['kpi']}\n\n분석 에이전트 실행 오류: {item['error']}")
                continue

            analysis = item["analysis"]
            detail_lines.append(f"### {item['kpi']}\n\n{analysis.summary or '정합한 후보 요인을 찾지 못했습니다.'}")
            for source in getattr(analysis, "sources", []) or []:
                title_text = source.get("title") or "source"
                url = source.get("url") or source.get("link") or ""
                if url:
                    source_lines.append(f"- {item['kpi']}: [{title_text}]({url})")

        significant_count = sum(1 for item in snapshots if item.is_significant)
        summary = (
            f"{len(snapshots)}개 KPI를 점검했고, {significant_count}개 KPI가 임계값을 초과했습니다. "
            "보고서는 정합성이 확인된 후보 요인만 요약하며 인과를 단정하지 않습니다."
        )

        sections = [
            {"title": "전체 KPI 현황 요약", "content": summary, "data": {"kpi_count": len(snapshots), "significant_count": significant_count}},
            {"title": "현황 표", "content": "\n".join(status_lines), "data": {"snapshots": [item.__dict__ for item in snapshots]}},
            {"title": "상세 분석", "content": "\n\n".join(detail_lines) if detail_lines else "임계값을 초과한 KPI가 없습니다.", "data": {"analyses_count": len(analyses)}},
            {"title": "권장 조치", "content": self._recommendations(snapshots), "data": {}},
        ]

        source_block = "\n".join(source_lines) if source_lines else "- 외부 이벤트 출처 없음"
        markdown = f"""# {title}

**생성일시**: {generated_at}
**분석 기간**: {request.year}년 Q{request.quarter}

## 1. 전체 KPI 현황 요약

{summary}

## 2. 현황 표

{chr(10).join(status_lines)}

## 3. 상세 분석

{sections[2]["content"]}

## 4. 권장 조치

{sections[3]["content"]}

## 출처

{source_block}

---

주의: 본 보고서는 후보 요인과 KPI가 정합한 방향으로 함께 움직였는지를 요약합니다. 인과관계를 단정하지 않습니다.
"""

        return {
            "title": title,
            "generated_at": generated_at,
            "summary": summary,
            "sections": sections,
            "markdown": markdown,
        }

    def _recommendations(self, snapshots: List[KpiSnapshot]) -> str:
        flagged = [item for item in snapshots if item.is_significant]
        if not flagged:
            return "현재 임계값을 초과한 KPI는 없습니다. 다음 분기에도 동일 기준으로 모니터링하세요."

        lines = []
        for item in flagged:
            direction = "하락" if item.change_pct < 0 else "상승"
            lines.append(f"- {item.name}: {abs(item.change_pct):.1f}% {direction}이 관찰되어 담당 부서의 원자료 검토와 추가 확인이 필요합니다.")
        return "\n".join(lines)

    def _execute_scalar(self, query: str) -> float:
        result = self.sql_executor.execute(query)
        if not result.success or result.data is None or result.data.empty:
            return 0.0
        value = result.data.iloc[0].get("value")
        return float(value or 0.0)

    def _change_pct(self, current: float, previous: float) -> float:
        if previous == 0:
            return 0.0
        return (current - previous) / abs(previous) * 100

    def _quarter_range(self, year: int, quarter: int) -> Tuple[str, str]:
        ranges = {
            1: ("01-01", "03-31"),
            2: ("04-01", "06-30"),
            3: ("07-01", "09-30"),
            4: ("10-01", "12-31"),
        }
        start, end = ranges.get(quarter, ranges[4])
        return f"{year}-{start}", f"{year}-{end}"

    def _previous_quarter_range(self, year: int, quarter: int) -> Tuple[str, str]:
        if quarter == 1:
            return self._quarter_range(year - 1, 4)
        return self._quarter_range(year, quarter - 1)

    @staticmethod
    def get_available_report_types() -> List[Dict[str, str]]:
        return [
            {
                "type": ReportType.INTEGRATED_KPI_REPORT.value,
                "name": "통합 KPI 분석 보고서",
                "description": "주요 KPI 변동을 점검하고 분석 에이전트 결과를 보고서 구조로 재구성",
            }
        ]
