"""Chat message rendering for the Streamlit app."""

from typing import Any, Dict

import pandas as pd
import streamlit as st

from .results import display_vector_search_results


USER_ICON_SVG = """<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <circle cx="12" cy="8" r="4"/>
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
</svg>"""

ASSISTANT_ICON_SVG = """<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 2L14.4 8.4L21 9.2L16 14L17.5 21L12 17.5L6.5 21L8 14L3 9.2L9.6 8.4L12 2Z"/>
</svg>"""


def render_user_message(content: str) -> str:
    """Return HTML for a user chat message."""

    return (
        '<div class="chat-message user">'
        f'<div class="message-icon">{USER_ICON_SVG}</div>'
        f'<div class="message-content">{content}</div>'
        "</div>"
    )


def render_assistant_message(content: str, analysis_html: str = "") -> str:
    """Return HTML for an assistant chat message."""

    return (
        '<div class="chat-message assistant">'
        f'<div class="message-icon">{ASSISTANT_ICON_SVG}</div>'
        f'<div class="message-content">{content}{analysis_html}</div>'
        "</div>"
    )


def render_welcome_state() -> str:
    """Return HTML for the empty-chat welcome state."""

    return (
        '<div class="welcome-container">'
        f'<div class="welcome-icon">{ASSISTANT_ICON_SVG}</div>'
        '<div class="welcome-title">LG HE Business Intelligence</div>'
        '<div class="welcome-subtitle">비즈니스 데이터에 대해 질문하세요. '
        "매출 분석, 성과 트렌드, 진단 인사이트를 제공합니다.</div>"
        "</div>"
    )


def render_typing_indicator() -> str:
    """Return HTML for the assistant typing indicator."""

    return (
        '<div class="chat-message assistant">'
        f'<div class="message-icon">{ASSISTANT_ICON_SVG}</div>'
        '<div class="message-content"><div class="typing-indicator">'
        "<span></span><span></span><span></span>"
        "</div></div></div>"
    )


def display_chat_messages() -> None:
    """Render the chat transcript from Streamlit session state."""

    if not st.session_state.chat_messages:
        st.markdown(render_welcome_state(), unsafe_allow_html=True)
        return

    for message in st.session_state.chat_messages:
        _display_chat_message(message)


def _display_chat_message(message: Dict[str, Any]) -> None:
    if message["role"] == "user":
        st.markdown(render_user_message(message["content"]), unsafe_allow_html=True)
        return

    if message.get("analysis_html"):
        st.markdown(message["analysis_html"], unsafe_allow_html=True)
    else:
        st.markdown(render_assistant_message(message["content"]), unsafe_allow_html=True)

    data = message.get("data")
    source = message.get("source")
    if not data or not source:
        return

    if source == "vector":
        display_vector_search_results(data)
    elif isinstance(data, list):
        st.dataframe(pd.DataFrame(data), use_container_width=True)
