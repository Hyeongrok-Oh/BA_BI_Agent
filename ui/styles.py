"""Global style loading for the Streamlit UI."""

from pathlib import Path

import streamlit as st


_STYLE_PATH = Path(__file__).with_name("styles.css")


def load_global_styles() -> None:
    """Inject the shared CSS used across Streamlit views."""

    css = _STYLE_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
