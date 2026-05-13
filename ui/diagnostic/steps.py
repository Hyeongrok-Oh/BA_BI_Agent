"""HTML fragments for diagnostic analysis steps."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, Iterable, List


def render_kpi_step(kpi_change: Any) -> str:
    html = [
        '<div class="analysis-step">',
        '<div class="step-header"><span class="step-number">1</span><span class="step-title">KPI 변동 확인</span></div>',
    ]

    if not kpi_change:
        html.append('<div class="step-content"><p>KPI 변동 데이터를 가져올 수 없습니다.</p></div>')
        html.append("</div>")
        return "".join(html)

    qoq_sign = "+" if kpi_change.qoq_change_percent > 0 else ""
    qoq_direction = "상승" if kpi_change.qoq_change_percent > 0 else "하락"
    qoq_class = "positive" if kpi_change.qoq_change_percent > 0 else "negative"
    yoy_sign = "+" if kpi_change.yoy_change_percent > 0 else ""
    yoy_direction = "상승" if kpi_change.yoy_change_percent > 0 else "하락"
    yoy_class = "positive" if kpi_change.yoy_change_percent > 0 else "negative"
    sql_escaped = escape(kpi_change.sql_query) if getattr(kpi_change, "sql_query", None) else ""

    html.extend(
        [
            '<div class="step-content">',
            f'<p>ERP 데이터베이스에서 <strong>{escape(kpi_change.kpi_name)}</strong>의 변동을 확인했습니다.</p>',
            '<div style="margin-bottom: 12px; padding: 8px; background: #f8fafc; border-radius: 6px;">',
            f'<span style="font-weight: 600;">{escape(kpi_change.current_period)} 현재:</span> ',
            f'<span style="font-size: 1.1em; font-weight: 700; color: #1e293b;">{kpi_change.current_value:,.0f}</span>',
            "</div>",
            '<div class="kpi-comparison" style="margin-bottom: 8px;">',
            f'<div class="kpi-value"><span class="kpi-label">전분기</span><span class="kpi-num">{kpi_change.qoq_previous_value:,.0f}</span></div>',
            '<div class="kpi-arrow">→</div>',
            f'<div class="kpi-value"><span class="kpi-label">현재</span><span class="kpi-num">{kpi_change.current_value:,.0f}</span></div>',
            f'<div class="kpi-change {qoq_class}">QoQ {qoq_sign}{kpi_change.qoq_change_percent:.1f}% {qoq_direction}</div>',
            "</div>",
            '<div class="kpi-comparison">',
            f'<div class="kpi-value"><span class="kpi-label">전년 동기</span><span class="kpi-num">{kpi_change.yoy_previous_value:,.0f}</span></div>',
            '<div class="kpi-arrow">→</div>',
            f'<div class="kpi-value"><span class="kpi-label">현재</span><span class="kpi-num">{kpi_change.current_value:,.0f}</span></div>',
            f'<div class="kpi-change {yoy_class}">YoY {yoy_sign}{kpi_change.yoy_change_percent:.1f}% {yoy_direction}</div>',
            "</div>",
        ]
    )

    if sql_escaped:
        html.append(f'<details class="sql-details"><summary>실행된 SQL 쿼리 보기</summary><pre>{sql_escaped}</pre></details>')

    html.extend(["</div>", "</div>"])
    return "".join(html)


def render_hypothesis_step(hypotheses: Iterable[Any]) -> str:
    hypotheses = list(hypotheses or [])
    html = [
        '<div class="analysis-step">',
        '<div class="step-header"><span class="step-number">2</span><span class="step-title">가설 생성</span></div>',
        '<div class="step-content">',
        f'<p>Knowledge Graph에서 KPI 변동과 관련된 <strong>{len(hypotheses)}개 요인</strong>을 식별했습니다.</p>',
    ]

    if hypotheses:
        html.append('<div class="hypothesis-list">')
        for hypothesis in hypotheses[:10]:
            confidence = getattr(hypothesis, "confidence", 0.0) or 0.0
            html.append(
                '<div class="hypothesis-item">'
                f'<span class="hypothesis-name">{escape(hypothesis.factor)}</span>'
                f'<span class="hypothesis-conf">{confidence * 100:.0f}%</span>'
                "</div>"
            )
        if len(hypotheses) > 10:
            html.append(f'<div class="hypothesis-more">외 {len(hypotheses) - 10}개 요인...</div>')
        html.append(
            '<p class="confidence-note">'
            "* Confidence = (학계 합의 비율 × 0.5) + (증거 다양성 × 0.3) + (관계 강도 × 0.2)"
            "</p>"
        )
        html.append("</div>")

    html.extend(["</div>", "</div>"])
    return "".join(html)


def render_validation_step(
    *,
    hypotheses: Iterable[Any],
    validated: Iterable[Any],
    validation_result: Dict[str, Any],
    analysis_plan: Dict[str, Any],
) -> str:
    hypotheses = list(hypotheses or [])
    validated = list(validated or [])
    validated_ids = {getattr(hypothesis, "id", None) for hypothesis in validated}
    rejected = [hypothesis for hypothesis in hypotheses if getattr(hypothesis, "id", None) not in validated_ids]

    html = [
        '<div class="analysis-step">',
        '<div class="step-header"><span class="step-number">3</span><span class="step-title">가설 검증 및 분석 해석</span></div>',
        '<div class="step-content">',
        '<div class="validation-methodology">',
        _render_driver_data_step(analysis_plan),
        _render_candidate_selection_step(hypotheses, validated, validation_result, analysis_plan),
        _render_candidate_summary_step(validation_result),
        _render_analysis_outcome_step(hypotheses, validated, rejected),
        "</div>",
        _render_validated_factor_cards(validated),
        "</div>",
        "</div>",
    ]
    return "".join(html)


def render_debug_step(validated: Iterable[Any], validation_result: Dict[str, Any]) -> str:
    analysis_plan = validation_result.get("analysis_plan", {})
    html = [
        '<div class="analysis-step" style="background: #FFF7ED; border: 1px solid #FDBA74;">',
        '<div class="step-header"><span class="step-number">D</span><span class="step-title">진단 정보</span></div>',
        '<div class="step-content">',
        "<p><strong>분석 설정:</strong></p>",
        '<pre style="background: #FFF; padding: 8px; border-radius: 4px; font-size: 11px; overflow-x: auto;">',
        f'method: {escape(str(analysis_plan.get("method", "unknown")))}\n',
        f'total_yoy_change_sum: {analysis_plan.get("total_yoy_change_sum", 0)}\n',
        f'erp_data_available: {analysis_plan.get("erp_data_available", False)}\n',
        f'kpi_id: {escape(str(analysis_plan.get("kpi_id", "")))}',
        "</pre>",
        '<p style="margin-top: 12px;"><strong>요인별 상세 데이터:</strong></p>',
        '<div style="max-height: 300px; overflow-y: auto;">',
    ]

    for hypothesis in validated or []:
        validation_data = hypothesis.validation_data or {}
        html.extend(
            [
                '<details style="margin-bottom: 8px;">',
                f'<summary style="cursor: pointer; font-weight: 600;">{escape(hypothesis.factor)}</summary>',
                '<pre style="background: #FFF; padding: 8px; border-radius: 4px; font-size: 11px; margin-top: 4px;">',
                f'method: {escape(str(validation_data.get("method", "N/A")))}\n',
                f'contribution_pct: {validation_data.get("contribution_pct", 0)}\n',
                f'sql_verified: {validation_data.get("sql_verified", False)}\n',
                f'erp_table: {escape(str(validation_data.get("erp_table", "N/A")))}\n',
                f'erp_column: {escape(str(validation_data.get("erp_column", "N/A")))}\n',
                f'curr_value: {validation_data.get("curr_value", 0)}\n',
                f'yoy_value: {validation_data.get("yoy_value", 0)}\n',
                f'yoy_change_pct: {validation_data.get("yoy_change_pct", 0)}\n',
                f'qoq_value: {validation_data.get("qoq_value", 0)}\n',
                f'qoq_change_pct: {validation_data.get("qoq_change_pct", 0)}\n',
                f'confidence: {validation_data.get("confidence", 0)}',
                "</pre>",
                "</details>",
            ]
        )

    html.extend(["</div>", "</div>", "</div>"])
    return "".join(html)


def _render_driver_data_step(analysis_plan: Dict[str, Any]) -> str:
    data_availability = analysis_plan.get("data_availability", {})
    driver_results = data_availability.get("driver_results", [])
    html = [
        '<div class="method-step-prose">',
        "<p><strong>1. 데이터 조회</strong></p>",
        '<p style="color: #4B5563; line-height: 1.7;">',
    ]

    if not driver_results:
        html.extend(
            [
                "Knowledge Graph의 Driver들과 ERP 컬럼 간 매핑이 불완전하여 Confidence 기반으로 분석합니다.",
                "</p>",
                "</div>",
            ]
        )
        return "".join(html)

    html.extend(
        [
            f"ERP 데이터베이스에서 {len(driver_results)}개 요인에 대해 전년 동기(YoY) 및 전분기(QoQ) 대비 변화율을 계산했습니다.",
            "</p>",
            '<table style="width: 100%; margin-top: 12px; border-collapse: collapse; font-size: 13px;">',
            '<tr style="background: #F3F4F6;">',
            '<th style="padding: 8px; text-align: left; border-bottom: 1px solid #E5E7EB;">요인</th>',
            '<th style="padding: 8px; text-align: right; border-bottom: 1px solid #E5E7EB;">현재</th>',
            '<th style="padding: 8px; text-align: right; border-bottom: 1px solid #E5E7EB;">YoY</th>',
            '<th style="padding: 8px; text-align: right; border-bottom: 1px solid #E5E7EB;">QoQ</th>',
            "</tr>",
        ]
    )

    for driver_result in driver_results[:5]:
        curr_value = driver_result.get("curr_value", 0) or 0
        yoy_change = driver_result.get("yoy_change_pct", 0) or 0
        qoq_change = driver_result.get("qoq_change_pct", 0) or 0
        yoy_color = "#DC2626" if yoy_change > 0 else "#059669" if yoy_change < 0 else "#6B7280"
        qoq_color = "#DC2626" if qoq_change > 0 else "#059669" if qoq_change < 0 else "#6B7280"
        yoy_sign = "+" if yoy_change > 0 else ""
        qoq_sign = "+" if qoq_change > 0 else ""
        curr_fmt = f"{curr_value:,.0f}" if curr_value >= 1000 else f"{curr_value:.2f}"

        html.append(
            f'<tr><td style="padding: 8px; border-bottom: 1px solid #E5E7EB;">{escape(driver_result["driver"])}</td>'
            f'<td style="padding: 8px; text-align: right; border-bottom: 1px solid #E5E7EB;">{curr_fmt}</td>'
            f'<td style="padding: 8px; text-align: right; border-bottom: 1px solid #E5E7EB; color: {yoy_color};">{yoy_sign}{yoy_change}%</td>'
            f'<td style="padding: 8px; text-align: right; border-bottom: 1px solid #E5E7EB; color: {qoq_color};">{qoq_sign}{qoq_change}%</td></tr>'
        )

    html.append("</table>")
    sample_query = (driver_results[0].get("sql_query") or "").strip() if driver_results else ""
    if sample_query:
        html.append(
            '<details style="margin-top: 12px;">'
            '<summary style="cursor: pointer; color: #6B7280; font-size: 12px;">SQL 쿼리 예시 보기</summary>'
            f'<pre style="background: #F9FAFB; padding: 8px; font-size: 11px; overflow-x: auto; margin-top: 8px; border-radius: 4px;">{escape(sample_query)}</pre>'
            "</details>"
        )

    html.append("</div>")
    return "".join(html)


def _render_candidate_selection_step(
    hypotheses: List[Any],
    validated: List[Any],
    validation_result: Dict[str, Any],
    analysis_plan: Dict[str, Any],
) -> str:
    total = analysis_plan.get("total_hypotheses", len(hypotheses))
    passed = analysis_plan.get("passed_count", len(validated))
    threshold = analysis_plan.get("threshold", 1.0)
    rejected_hypotheses = validation_result.get("rejected_hypotheses", [])

    html = [
        '<div class="method-step-prose">',
        "<p><strong>2. 후보 요인 선별</strong></p>",
        '<p style="color: #4B5563; line-height: 1.7;">',
        f"Knowledge Graph에서 추출한 {total}개 요인 중 {passed}개가 후보로 선별되었습니다. ",
        "</p>",
        '<ul style="color: #4B5563; line-height: 1.8; margin: 8px 0 8px 16px;">',
        "<li><b>A)</b> KPI 변화량이 임계값 이상인지 확인</li>",
        f"<li><b>B)</b> Driver 변화량이 임계값({threshold}%) 이상인지 확인 (노이즈 제거)</li>",
        "<li><b>C)</b> 기대 부호(expected_sign)와 실제 변화 방향이 일치하는지 확인</li>",
        "</ul>",
    ]

    if rejected_hypotheses:
        threshold_rejected = [item for item in rejected_hypotheses if item.get("reason") == "threshold"]
        alignment_rejected = [item for item in rejected_hypotheses if item.get("reason") == "alignment"]
        html.append('<p style="color: #6B7280; font-size: 13px; margin-top: 8px;">')
        if threshold_rejected:
            html.append(_rejected_reason_text("노이즈로 제외", threshold_rejected))
            html.append("<br>")
        if alignment_rejected:
            html.append(_rejected_reason_text("정합성 불일치로 제외", alignment_rejected))
        html.append("</p>")

    html.append("</div>")
    return "".join(html)


def _rejected_reason_text(label: str, rejected_items: List[Dict[str, Any]]) -> str:
    names = [escape(str(item.get("driver_id", ""))) for item in rejected_items[:3]]
    text = f'{label}({len(rejected_items)}개): {", ".join(names)}'
    if len(rejected_items) > 3:
        text += f" 외 {len(rejected_items) - 3}개"
    return text


def _render_candidate_summary_step(validation_result: Dict[str, Any]) -> str:
    natural_summary = validation_result.get("natural_language_summary", "")
    html = [
        '<div class="method-step-prose">',
        "<p><strong>3. 후보 요인 요약</strong></p>",
    ]

    if natural_summary:
        for line in str(natural_summary).split("\n"):
            if line.strip():
                html.append(
                    f'<p style="color: #4B5563; line-height: 1.7; margin: 4px 0;">{escape(line.strip())}</p>'
                )
    else:
        html.append('<p style="color: #6B7280;">후보 요인이 없습니다.</p>')

    html.append("</div>")
    return "".join(html)


def _render_analysis_outcome_step(
    hypotheses: List[Any],
    validated: List[Any],
    rejected: List[Any],
) -> str:
    html = [
        '<div class="method-step-prose">',
        "<p><strong>4. 분석 결과</strong></p>",
        '<p style="color: #4B5563; line-height: 1.7;">',
        f"분석된 {len(hypotheses)}개 요인 중 {len(validated)}개가 후보로 선별되었습니다. ",
        "선별 기준: ① KPI/Driver 임계값 통과 ② 기대 방향(expected_sign)과 실제 변화 정합성. ",
    ]
    if rejected:
        html.append(f"제외된 {len(rejected)}개 요인은 변화량이 임계값 미만이거나 방향성이 일치하지 않았습니다.")
    html.extend(["</p>", "</div>"])
    return "".join(html)


def _render_validated_factor_cards(validated: List[Any]) -> str:
    if not validated:
        return ""

    html = ['<p style="margin-top: 16px;"><strong>선별된 후보 요인 상세:</strong></p>', '<div class="validated-factors">']
    for hypothesis in validated[:5]:
        data = hypothesis.validation_data or {}
        delta_pct = data.get("delta_pct", 0)
        method = data.get("method", "confidence_based")
        reasoning = getattr(hypothesis, "reasoning", "") or ""
        reasoning_text = reasoning[:150] + "..." if len(reasoning) > 150 else reasoning

        html.append('<div class="factor-card">')
        if method == "candidate_selection":
            html.append(_render_candidate_factor_header(hypothesis, data, delta_pct))
        else:
            html.append(f'<div class="factor-header"><span class="factor-name">{escape(hypothesis.factor)}</span></div>')

        if reasoning_text:
            html.append(f'<div class="factor-reasoning">{escape(reasoning_text)}</div>')
        html.append("</div>")

    html.append("</div>")
    return "".join(html)


def _render_candidate_factor_header(hypothesis: Any, data: Dict[str, Any], delta_pct: float) -> str:
    alignment_type = data.get("alignment_type", "")
    alignment_type_kr = data.get("alignment_type_kr", "")
    aligned_qoq = data.get("aligned_qoq", True)
    aligned_yoy = data.get("aligned_yoy", True)
    qoq_pct = data.get("qoq_delta_pct", delta_pct)
    yoy_pct = data.get("yoy_delta_pct", 0)
    type_badge = _alignment_badge(alignment_type)
    qoq_mark = "✓" if aligned_qoq else "✗"
    yoy_mark = "✓" if aligned_yoy else "✗"
    qoq_color = "#22C55E" if aligned_qoq else "#9CA3AF"
    yoy_color = "#22C55E" if aligned_yoy else "#9CA3AF"

    html = [
        f'<div class="factor-header"><span class="factor-name">{escape(hypothesis.factor)} {type_badge}</span></div>',
        '<div style="display: flex; gap: 16px; margin: 4px 0; font-size: 13px;">',
        f'<span style="color: {qoq_color};">QoQ: {qoq_pct:+.1f}% {qoq_mark}</span>',
        f'<span style="color: {yoy_color};">YoY: {yoy_pct:+.1f}% {yoy_mark}</span>',
        "</div>",
    ]
    if alignment_type_kr:
        html.append(f'<div class="factor-reasoning" style="color: #6B7280; font-size: 12px;">{escape(alignment_type_kr)}</div>')
    return "".join(html)


def _alignment_badge(alignment_type: str) -> str:
    if alignment_type == "both":
        return '<span style="background: #DCFCE7; color: #166534; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600;">단기·장기 정합</span>'
    if alignment_type == "qoq_only":
        return '<span style="background: #FEF3C7; color: #92400E; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600;">단기 정합</span>'
    if alignment_type == "yoy_only":
        return '<span style="background: #DBEAFE; color: #1E40AF; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600;">장기 정합</span>'
    return ""
