import streamlit as st
from pathlib import Path

st.set_page_config(
    page_title="Xebia | Paginated Report Performance Analyzer",
    page_icon="⚡",
    layout="wide"
)

HTML_FILE = Path(__file__).parent / "index.html"

if not HTML_FILE.exists():
    st.error("HTML frontend file not found.")
else:
    st.iframe(
        HTML_FILE,
        width="stretch",
        height="content"
    )
