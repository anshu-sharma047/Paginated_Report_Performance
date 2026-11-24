from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

BASE_DIR = Path(__file__).parent

html = (BASE_DIR / "index.html").read_text(encoding="utf-8")
css = (BASE_DIR / "style.css").read_text(encoding="utf-8")
js = (BASE_DIR / "app.js").read_text(encoding="utf-8")

html = html.replace(
    '<link rel="stylesheet" href="style.css">',
    f"<style>{css}</style>"
)

html = html.replace(
    '<script src="app.js"></script>',
    f"<script>{js}</script>"
)

st.set_page_config(layout="wide", page_title="Xebia Performance Analyzer")

components.html(
    html,
    height=1800,
    scrolling=True
)
