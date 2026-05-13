"""Knowledge graph and event evidence renderers for diagnostic results."""

from __future__ import annotations

import base64
from html import escape
from typing import Any, Dict, Iterable, List, Optional


def render_graph_step(
    *,
    kpi_id: str,
    validated: Iterable[Any],
    matched_events: Dict[str, List[Any]],
    kg_visualizer_cls: Optional[type],
) -> str:
    validated = list(validated or [])
    matched_events = matched_events or {}
    html = [
        '<div class="analysis-step">',
        '<div class="step-header"><span class="step-number">4</span><span class="step-title">지식그래프</span></div>',
        '<div class="step-content">',
        _render_event_matches(matched_events),
        '<p style="margin-bottom: 12px;">아래 지식그래프에서 KPI와 영향 요인, 관련 이벤트 간의 관계를 확인할 수 있습니다.</p>',
        _render_kg_iframe(kpi_id, validated, matched_events, kg_visualizer_cls),
        "</div>",
        "</div>",
    ]
    return "".join(html)


def _render_event_matches(matched_events: Dict[str, List[Any]]) -> str:
    if not matched_events:
        return ""

    total_events = sum(len(events) for events in matched_events.values())
    html = [
        '<div style="margin-bottom: 20px;">',
        f'<p style="font-weight: 600; font-size: 14px; margin-bottom: 12px;">관련 이벤트 ({total_events}건)</p>',
        '<div style="background: #F8FAFC; padding: 12px; border-radius: 6px; margin-bottom: 12px; font-size: 12px; color: #4B5563; line-height: 1.7;">',
        '<p style="margin: 0 0 10px 0; font-weight: 600;">이벤트 관련성 점수 산출 방식</p>',
        '<p style="margin: 0 0 6px 0;"><b>최종 점수</b> = 기본 점수 + 방향 보너스</p>',
        '<div style="margin-left: 12px; margin-bottom: 8px;">',
        '<p style="margin: 4px 0;"><b>1. 의미적 유사도 (70%)</b></p>',
        '<p style="margin: 2px 0 6px 12px; color: #6B7280;">가설 설명과 이벤트 간 Vector Cosine Similarity (OpenAI Embedding)</p>',
        '<p style="margin: 4px 0;"><b>2. 그래프 점수 (30%)</b> = 영향도(70%) + 신뢰도(30%)</p>',
        '<p style="margin: 2px 0 2px 12px; color: #6B7280;">• 영향도 = severity(critical/high/medium/low) × magnitude(관계 가중치)</p>',
        '<p style="margin: 2px 0 6px 12px; color: #6B7280;">• 신뢰도 = 정보 출처 신뢰도 (뉴스 1.0 / 보고서 0.8 / 추정 0.6)</p>',
        '<p style="margin: 4px 0;"><b>3. 방향 보너스 (+0.15)</b></p>',
        '<p style="margin: 2px 0 0 12px; color: #6B7280;">Driver 변화 방향과 Event의 polarity(INCREASES/DECREASES)가 일치하면 보너스 부여</p>',
        "</div>",
        "</div>",
        '<table style="width: 100%; border-collapse: collapse; font-size: 12px;">',
        '<tr style="background: #F3F4F6;">',
        '<th style="padding: 8px; text-align: left; border-bottom: 1px solid #E5E7EB;">이벤트</th>',
        '<th style="padding: 8px; text-align: left; border-bottom: 1px solid #E5E7EB;">출처</th>',
        '<th style="padding: 8px; text-align: center; width: 55px; border-bottom: 1px solid #E5E7EB;">최종</th>',
        '<th style="padding: 8px; text-align: center; width: 50px; border-bottom: 1px solid #E5E7EB;">의미</th>',
        '<th style="padding: 8px; text-align: center; width: 50px; border-bottom: 1px solid #E5E7EB;">그래프</th>',
        '<th style="padding: 8px; text-align: center; width: 55px; border-bottom: 1px solid #E5E7EB;">보너스</th>',
        "</tr>",
    ]

    for event in _sorted_events(matched_events):
        html.append(_render_event_row(event))

    html.extend(["</table>", "</div>"])
    return "".join(html)


def _sorted_events(matched_events: Dict[str, List[Any]]) -> List[Any]:
    all_events = [event for events in matched_events.values() for event in events]
    all_events.sort(key=lambda event: getattr(event, "total_score", 0), reverse=True)
    return all_events


def _render_event_row(event: Any) -> str:
    breakdown = getattr(event, "score_breakdown", {})
    final = breakdown.get("final", 0)
    text_similarity = breakdown.get("text_similarity", 0)
    graph_score = breakdown.get("graph_score", 0)
    direction_bonus = breakdown.get("direction_bonus", 0)
    bonus_text = f"+{direction_bonus:.2f}" if direction_bonus > 0 else "-"
    bonus_color = "#22C55E" if direction_bonus > 0 else "#9CA3AF"
    source_html = _source_link_html(getattr(event, "sources", []))

    return (
        '<tr style="border-bottom: 1px solid #E5E7EB;">'
        f'<td style="padding: 8px;">{escape(event.event_name)}<br><span style="color: #6B7280; font-size: 11px;">{escape(event.event_category)}</span></td>'
        f'<td style="padding: 8px; font-size: 11px;">{source_html}</td>'
        f'<td style="padding: 8px; text-align: center; font-weight: 600;">{final:.2f}</td>'
        f'<td style="padding: 8px; text-align: center;">{text_similarity:.2f}</td>'
        f'<td style="padding: 8px; text-align: center;">{graph_score:.2f}</td>'
        f'<td style="padding: 8px; text-align: center; color: {bonus_color}; font-weight: 600;">{bonus_text}</td>'
        "</tr>"
    )


def _source_link_html(sources: List[Dict[str, Any]]) -> str:
    if not sources:
        return '<span style="color: #9CA3AF;">-</span>'

    source = sources[0]
    title = source.get("title", "")
    title_short = title[:25] + "..." if len(title) > 25 else title
    url = source.get("url", source.get("link", ""))
    if url:
        return f'<a href="{escape(url, quote=True)}" target="_blank" style="color: #3B82F6; text-decoration: none;">{escape(title_short)}</a>'
    return escape(title_short)


def _render_kg_iframe(
    kpi_id: str,
    validated: List[Any],
    matched_events: Dict[str, List[Any]],
    kg_visualizer_cls: Optional[type],
) -> str:
    if not kg_visualizer_cls or not validated:
        return ""

    visualizer = None
    try:
        visualizer = kg_visualizer_cls()
        driver_ids = [
            driver_id
            for hypothesis in validated
            if (driver_id := getattr(hypothesis, "driver_id", None) or getattr(hypothesis, "factor", None))
        ]
        event_ids = [
            event_id
            for events in matched_events.values()
            for event in events
            if (event_id := getattr(event, "event_id", None))
        ]

        if not driver_ids:
            return ""

        subgraph = visualizer.build_subgraph(
            kpi_id=kpi_id,
            driver_ids=driver_ids,
            event_ids=event_ids if event_ids else None,
            max_drivers=20,
            max_events_per_driver=99,
        )
        if not subgraph.nodes:
            return ""

        graph_html = visualizer.generate_html(subgraph, height="500px")
        if not graph_html:
            return ""

        encoded = base64.b64encode(graph_html.encode()).decode()
        return (
            f'<iframe src="data:text/html;base64,{encoded}" '
            'style="width: 100%; height: 500px; border: 1px solid #E9E9E7; border-radius: 8px; margin-top: 12px;" '
            'frameborder="0"></iframe>'
        )
    except Exception:
        return ""
    finally:
        if visualizer:
            visualizer.close()
