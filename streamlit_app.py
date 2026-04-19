from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from page_renderer import render_project_html  # noqa: E402


WATCH_DIRS = [
    ROOT / "data",
    ROOT / "notes",
    ROOT / "scripts",
    ROOT / "web",
    ROOT / "доп",
]


def latest_source_mtime() -> float:
    latest = 0.0
    for directory in WATCH_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
    return latest


@st.cache_data(show_spinner=False)
def build_runtime_html(source_stamp: float) -> str:
    del source_stamp
    return render_project_html(ROOT)


st.set_page_config(
    page_title="Интерактивная карта русских говоров Удмуртии",
    layout="wide",
)

st.title("Интерактивная карта русских говоров Удмуртии")
st.caption("Приложение работает напрямую через Streamlit и формирует карту во время запуска.")

with st.sidebar:
    st.subheader("Режим запуска")
    st.write("Проект больше не использует предварительную статическую сборку.")
    if st.button("Обновить данные и интерфейс"):
        build_runtime_html.clear()
        st.rerun()

html = build_runtime_html(latest_source_mtime())
components.html(html, height=980, scrolling=True)
