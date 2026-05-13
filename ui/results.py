"""Reusable result renderers for Streamlit views."""

from typing import Any, Dict, List

import streamlit as st


def display_vector_search_results(events: List[Dict[str, Any]]) -> None:
    """Render vector-search event results."""

    if not events:
        st.warning("관련 이벤트를 찾지 못했습니다.")
        return

    st.success(f"**{len(events)}개** 유사 이벤트 발견")

    for index, event in enumerate(events, 1):
        score = event.get("score", 0)
        score_label = _score_label(score)
        severity = event.get("severity", "medium")
        category = event.get("category", "")
        category_label = _category_label(category)

        with st.expander(
            f"{score_label} [{index}] {event.get('name', 'Unknown Event')} ({category_label} {category})",
            expanded=(index <= 2),
        ):
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("유사도", f"{score:.2%}")
            with col2:
                st.write(f"**심각도**: {_severity_label(severity)}")
            with col3:
                st.write(f"**카테고리**: {category}")

            related_factors = event.get("related_factors", [])
            if related_factors:
                st.write("**영향 Factor:**")
                st.write(", ".join([f"`{factor}`" for factor in related_factors[:5]]))

            evidence = event.get("evidence", "")
            if evidence:
                st.write("**근거:**")
                st.caption(evidence[:500] + ("..." if len(evidence) > 500 else ""))

            source_urls = event.get("source_urls", [])
            source_titles = event.get("source_titles", [])
            if source_urls:
                st.write("**출처:**")
                for source_index, url in enumerate(source_urls[:3]):
                    title = (
                        source_titles[source_index]
                        if source_index < len(source_titles)
                        else f"출처 {source_index + 1}"
                    )
                    st.markdown(f"- [{title}]({url})")


def _score_label(score: float) -> str:
    if score > 0.8:
        return "[High]"
    if score > 0.6:
        return "[Mid]"
    return "[Low]"


def _severity_label(severity: str) -> str:
    return {"high": "High", "medium": "Medium", "low": "Low"}.get(severity, "Medium")


def _category_label(category: str) -> str:
    return {
        "geopolitical": "[GEO]",
        "policy": "[P]",
        "market": "[M]",
        "company": "[CO]",
        "macro_economy": "[ME]",
        "technology": "[T]",
    }.get(category, "[N]")
