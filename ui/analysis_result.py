"""Public diagnostic analysis result renderer."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, Optional

import markdown

from .diagnostic import (
    render_debug_step,
    render_graph_step,
    render_hypothesis_step,
    render_kpi_step,
    render_validation_step,
)


def build_diagnostic_result_html(
    query: str,
    payload: Any,
    *,
    debug_mode: bool = False,
    kg_visualizer_cls: Optional[type] = None,
) -> str:
    """Build the HTML result card for a diagnostic analysis payload."""

    detail_sections = [
        render_kpi_step(payload.kpi_change),
        render_hypothesis_step(payload.hypotheses),
        render_validation_step(
            hypotheses=payload.hypotheses,
            validated=payload.validated,
            validation_result=payload.validation_result,
            analysis_plan=payload.analysis_plan,
        ),
    ]

    if debug_mode:
        detail_sections.append(render_debug_step(payload.validated, payload.validation_result))

    detail_sections.append(
        render_graph_step(
            kpi_id=payload.kpi_id,
            validated=payload.validated,
            matched_events=payload.matched_events,
            kg_visualizer_cls=kg_visualizer_cls,
        )
    )

    return (
        '<div class="analysis-result-box">'
        f'<div class="box-query">{escape(query)}</div>'
        f'<div class="box-summary">{_summary_html(payload.summary_result)}</div>'
        '<details class="box-details">'
        "<summary>분석 과정 자세히 보기</summary>"
        f'<div class="details-content">{"".join(detail_sections)}</div>'
        "</details>"
        "</div>"
    )


def build_diagnostic_current_result(query: str, intent_result: Dict[str, Any], payload: Any) -> Dict[str, Any]:
    """Build the compact diagnostic result saved in Streamlit session state."""

    kpi_change = payload.kpi_change
    summary_result = payload.summary_result
    matched_events = payload.matched_events or {}

    return {
        "query": query,
        "intent": intent_result,
        "kpi_change": {
            "kpi_name": kpi_change.kpi_name if kpi_change else None,
            "qoq_change_percent": kpi_change.qoq_change_percent if kpi_change else None,
            "yoy_change_percent": kpi_change.yoy_change_percent if kpi_change else None,
        } if kpi_change else None,
        "hypotheses": len(payload.hypotheses or []),
        "validated": len(payload.validated or []),
        "matched_events": sum(len(events) for events in matched_events.values()),
        "summary": summary_result.get("summary", "") if isinstance(summary_result, dict) else summary_result,
        "sources": summary_result.get("sources", []) if isinstance(summary_result, dict) else [],
    }


def _summary_html(summary_result: Any) -> str:
    summary = summary_result.get("summary", "") if isinstance(summary_result, dict) else summary_result
    if not summary:
        return "분석이 완료되었습니다."
    return markdown.markdown(str(summary), extensions=["extra", "nl2br"])
