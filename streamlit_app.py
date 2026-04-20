from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitSecretNotFoundError


ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT / "scripts"
APP_VERSION = "2026-04-20-google-sheets-editor-v1"
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1uAIyIL0ySGi4tOnh3dMss27fmmA6s6LnZqWn2IaFltQ/edit?usp=sharing"
REPOSITORY_URL = "https://github.com/lehabuzanov/dialect_map"
THEME_OPTIONS = {
    "night": "Тёмно-синяя",
    "classic": "Текущая светлая",
}

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import EXPECTED_MAP_FIELDS, load_csv_rows  # noqa: E402
from page_renderer import render_project_html  # noqa: E402
from sheet_store import (  # noqa: E402
    dataframe_to_rows,
    fetch_public_sheet_rows,
    get_google_service_account_info,
    make_rows_signature,
    normalize_rows,
    rows_to_csv_bytes,
    rows_to_dataframe,
    save_rows_to_google_sheet,
)


WATCH_DIRS = [
    ROOT / "notes",
    ROOT / "scripts",
    ROOT / "web",
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


@st.cache_data(show_spinner=False, ttl=300)
def load_remote_rows(sheet_url: str) -> list[dict]:
    return fetch_public_sheet_rows(sheet_url)


@st.cache_data(show_spinner=False)
def load_local_rows() -> list[dict]:
    return load_csv_rows(ROOT / "data" / "csv" / "dialect_map_data.csv", EXPECTED_MAP_FIELDS)


def load_source_rows(sheet_url: str) -> tuple[list[dict], dict]:
    try:
        rows = load_remote_rows(sheet_url)
        return rows, {"mode": "google_sheets", "status": "ok", "message": "Данные загружены из Google Sheets."}
    except Exception as exc:
        rows = load_local_rows()
        return rows, {
            "mode": "local_fallback",
            "status": "fallback",
            "message": f"Не удалось получить Google Sheets, показан локальный резерв: {exc}",
        }


def build_source_meta(sheet_url: str, rows: list[dict], source_state: dict) -> dict:
    frame = rows_to_dataframe(rows)
    question_count = int(frame["question"].replace("", pd.NA).dropna().nunique())
    settlement_count = int(
        frame[["region", "district", "settlement", "lat", "lon"]]
        .replace("", pd.NA)
        .dropna(subset=["settlement"])
        .drop_duplicates()
        .shape[0]
    )
    return {
        "label": "Google Sheets" if source_state["mode"] == "google_sheets" else "Локальный резервный CSV",
        "url": sheet_url,
        "status": source_state["status"],
        "message": source_state["message"],
        "row_count": len(rows),
        "question_count": question_count,
        "settlement_count": settlement_count,
        "signature": make_rows_signature(rows),
    }


def get_streamlit_credentials() -> Optional[dict]:
    try:
        if "google_service_account" in st.secrets:
            raw_value = st.secrets["google_service_account"]
            if isinstance(raw_value, str):
                return json.loads(raw_value)
            return dict(raw_value)
    except StreamlitSecretNotFoundError:
        pass
    return get_google_service_account_info()


def reset_editor_state(sheet_url: str) -> None:
    rows, source_state = load_source_rows(sheet_url)
    st.session_state.editor_sheet_url = sheet_url
    st.session_state.editor_rows = normalize_rows(rows)
    st.session_state.editor_source_state = source_state
    st.session_state.editor_source_signature = make_rows_signature(rows)


def ensure_editor_state(sheet_url: str) -> None:
    if st.session_state.get("editor_sheet_url") != sheet_url or "editor_rows" not in st.session_state:
        reset_editor_state(sheet_url)


def apply_rows_update(rows: list[dict], success_message: str) -> None:
    st.session_state.editor_rows = normalize_rows(rows)
    st.session_state.editor_flash = success_message
    st.rerun()


def build_settlement_frame(frame: pd.DataFrame) -> pd.DataFrame:
    settlement_frame = frame.groupby(["region", "district", "settlement", "lat", "lon"], dropna=False).agg(
        row_count=("settlement", "size"),
        question_count=("question", lambda series: series.replace("", pd.NA).dropna().nunique()),
    )
    settlement_frame = settlement_frame.reset_index()
    settlement_frame["label"] = settlement_frame.apply(
        lambda row: (
            f"{row['settlement'] or 'Без названия'} · {row['district'] or 'Без района'}"
            f" · {row['lat'] or '—'}, {row['lon'] or '—'}"
            f" · строк: {row['row_count']}"
        ),
        axis=1,
    )
    return settlement_frame.sort_values(["district", "settlement", "lat", "lon"], na_position="last")


def filter_frame_by_text(frame: pd.DataFrame, columns: list[str], query: str) -> pd.DataFrame:
    query = (query or "").strip().lower()
    if not query:
        return frame
    haystack = frame[columns].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    return frame[haystack.str.contains(query, regex=False)]


def rename_settlement(rows: list[dict], original: dict, updated: dict) -> list[dict]:
    updated_rows: list[dict] = []
    for row in rows:
        if all(str(row.get(key, "")) == str(original.get(key, "")) for key in ["region", "district", "settlement", "lat", "lon"]):
            next_row = dict(row)
            next_row.update(updated)
            updated_rows.append(next_row)
        else:
            updated_rows.append(dict(row))
    return updated_rows


def delete_settlement(rows: list[dict], original: dict) -> list[dict]:
    return [
        dict(row)
        for row in rows
        if not all(str(row.get(key, "")) == str(original.get(key, "")) for key in ["region", "district", "settlement", "lat", "lon"])
    ]


def rename_question(rows: list[dict], old_question: str, new_question: str) -> list[dict]:
    updated_rows: list[dict] = []
    for row in rows:
        next_row = dict(row)
        if row.get("question", "") == old_question:
            next_row["question"] = new_question
        updated_rows.append(next_row)
    return updated_rows


def delete_question(rows: list[dict], question_text: str) -> list[dict]:
    return [dict(row) for row in rows if row.get("question", "") != question_text]


def update_observation(rows: list[dict], row_index: int, updated_row: dict) -> list[dict]:
    next_rows = [dict(row) for row in rows]
    next_rows[row_index] = {field: updated_row.get(field, "") for field in EXPECTED_MAP_FIELDS}
    return next_rows


def delete_observation(rows: list[dict], row_index: int) -> list[dict]:
    return [dict(row) for index, row in enumerate(rows) if index != row_index]


def add_blank_settlement_row(region: str, district: str, settlement: str, lat: str, lon: str) -> dict:
    return {
        "region": region,
        "district": district,
        "settlement": settlement,
        "lat": lat,
        "lon": lon,
        "question": "",
        "unit1": "",
        "unit2": "",
        "comment": "",
    }


def add_observation_row(
    region: str,
    district: str,
    settlement: str,
    lat: str,
    lon: str,
    question: str,
    unit1: str,
    unit2: str,
    comment: str,
) -> dict:
    return {
        "region": region,
        "district": district,
        "settlement": settlement,
        "lat": lat,
        "lon": lon,
        "question": question,
        "unit1": unit1,
        "unit2": unit2,
        "comment": comment,
    }


def inject_streamlit_theme(theme_key: str) -> None:
    is_night = theme_key == "night"
    if is_night:
        style = """
        <style>
        .stApp {
          background:
            radial-gradient(circle at 16% 18%, rgba(92, 130, 191, 0.18), rgba(92, 130, 191, 0) 22%),
            radial-gradient(circle at 84% 10%, rgba(63, 96, 156, 0.22), rgba(63, 96, 156, 0) 24%),
            linear-gradient(160deg, rgba(18, 40, 77, 0.98) 0%, rgba(8, 23, 49, 1) 100%);
          color: #eaf2ff;
        }
        .stApp::before {
          content: "";
          position: fixed;
          inset: 0;
          pointer-events: none;
          background:
            radial-gradient(circle at 12% 28%, transparent 0 78px, rgba(141, 177, 232, 0.11) 79px 82px, transparent 83px 100%),
            radial-gradient(circle at 78% 18%, transparent 0 110px, rgba(118, 162, 225, 0.10) 111px 114px, transparent 115px 100%),
            radial-gradient(circle at 55% 76%, transparent 0 140px, rgba(118, 162, 225, 0.08) 141px 144px, transparent 145px 100%),
            linear-gradient(115deg, transparent 0 34%, rgba(132, 171, 229, 0.08) 35%, transparent 36% 64%, rgba(132, 171, 229, 0.06) 65%, transparent 66%);
          opacity: 0.95;
        }
        .stApp h1, .stApp h2, .stApp h3, .stApp label, .stApp [data-testid="stMarkdownContainer"],
        .stApp [data-testid="stCaptionContainer"], .stApp p, .stApp li, .stApp span {
          color: #eaf2ff;
        }
        [data-testid="stSidebar"] {
          background:
            radial-gradient(circle at 18% 14%, rgba(78, 119, 188, 0.34), rgba(78, 119, 188, 0) 20%),
            linear-gradient(180deg, rgba(13, 30, 58, 0.98) 0%, rgba(9, 22, 44, 0.98) 100%);
          border-right: 1px solid rgba(137, 170, 219, 0.22);
        }
        [data-testid="stSidebar"] > div:first-child {
          background:
            radial-gradient(circle at 12% 18%, rgba(98, 137, 200, 0.24), rgba(98, 137, 200, 0) 22%),
            radial-gradient(circle at 78% 82%, rgba(98, 137, 200, 0.18), rgba(98, 137, 200, 0) 28%),
            linear-gradient(180deg, rgba(13, 30, 58, 0.98) 0%, rgba(9, 22, 44, 0.98) 100%);
        }
        [data-testid="stSidebar"] > div:first-child::before {
          content: "";
          position: absolute;
          inset: 0;
          pointer-events: none;
          background:
            radial-gradient(circle at 14% 22%, transparent 0 62px, rgba(146, 183, 235, 0.11) 63px 65px, transparent 66px 100%),
            radial-gradient(circle at 74% 18%, transparent 0 96px, rgba(146, 183, 235, 0.10) 97px 99px, transparent 100px 100%),
            radial-gradient(circle at 48% 72%, transparent 0 126px, rgba(146, 183, 235, 0.08) 127px 129px, transparent 130px 100%);
        }
        .stApp [data-baseweb="input"] > div,
        .stApp [data-baseweb="select"] > div,
        .stApp textarea,
        .stApp input,
        .stApp .stTextInput input,
        .stApp .stTextArea textarea,
        .stApp .stSelectbox [data-baseweb="select"] > div {
          background: rgba(15, 34, 66, 0.92);
          color: #f3f7ff;
          border-color: rgba(132, 167, 219, 0.34);
        }
        .stApp .stButton > button,
        .stApp .stDownloadButton > button {
          background: linear-gradient(180deg, #163968 0%, #0f2b52 100%);
          color: #eef5ff;
          border: 1px solid rgba(133, 170, 223, 0.34);
        }
        .stApp .stButton > button:hover,
        .stApp .stDownloadButton > button:hover {
          border-color: rgba(171, 200, 241, 0.6);
          color: #ffffff;
        }
        .stApp .stTabs [data-baseweb="tab-list"] {
          gap: 0.25rem;
        }
        .stApp .stTabs [data-baseweb="tab"] {
          background: rgba(13, 29, 56, 0.66);
          border-radius: 0.7rem 0.7rem 0 0;
          color: #d7e7ff;
        }
        .stApp .stTabs [aria-selected="true"] {
          background: rgba(27, 59, 107, 0.96);
          color: #ffffff;
        }
        .stApp a {
          color: #9fccff;
        }
        .stApp [data-testid="stDataFrame"], .stApp [data-testid="stForm"] {
          background: rgba(9, 20, 40, 0.36);
          border-radius: 14px;
        }
        </style>
        """
    else:
        style = """
        <style>
        .stApp::before {
          content: none;
        }
        </style>
        """
    st.markdown(style, unsafe_allow_html=True)


def render_map_tab(rows: list[dict], source_meta: dict, theme_key: str) -> None:
    st.markdown(
        f"""
        **Источник данных:** [{source_meta['label']}]({source_meta['url']})  
        **Строк в наборе:** {source_meta['row_count']} · **вопросов:** {source_meta['question_count']} · **пунктов:** {source_meta['settlement_count']}
        """
    )
    if source_meta["status"] == "fallback":
        st.warning(source_meta["message"])
    else:
        st.caption(source_meta["message"])

    html = render_project_html(
        ROOT,
        map_rows=rows,
        data_source_meta=source_meta,
        ui_theme=theme_key,
    )
    components.html(html, height=980, scrolling=True)


def render_settlement_editor(frame: pd.DataFrame, rows: list[dict]) -> None:
    settlement_frame = build_settlement_frame(frame)
    search_query = st.text_input("Поиск населённого пункта", key="settlement_search", placeholder="Название, район или координаты")
    filtered = filter_frame_by_text(settlement_frame, ["region", "district", "settlement", "lat", "lon"], search_query)

    if filtered.empty:
        st.info("По текущему фильтру населённые пункты не найдены.")
    else:
        selected_label = st.selectbox("Выберите населённый пункт", filtered["label"].tolist(), key="selected_settlement_label")
        selected_row = filtered.loc[filtered["label"] == selected_label].iloc[0].to_dict()

        with st.form("edit_settlement_form"):
            st.markdown("**Изменить выбранный населённый пункт**")
            region = st.text_input("Регион", value=selected_row["region"])
            district = st.text_input("Район", value=selected_row["district"])
            settlement = st.text_input("Населённый пункт", value=selected_row["settlement"])
            lat = st.text_input("Широта", value=selected_row["lat"])
            lon = st.text_input("Долгота", value=selected_row["lon"])
            submitted = st.form_submit_button("Сохранить изменения")
            if submitted:
                updated = {"region": region, "district": district, "settlement": settlement, "lat": lat, "lon": lon}
                apply_rows_update(rename_settlement(rows, selected_row, updated), "Населённый пункт обновлен.")

        if st.button("Удалить выбранный населённый пункт", key="delete_selected_settlement"):
            apply_rows_update(delete_settlement(rows, selected_row), "Населённый пункт удален вместе со связанными строками.")

    with st.form("add_settlement_form"):
        st.markdown("**Добавить новый населённый пункт**")
        region = st.text_input("Регион", value="Удмуртская Республика", key="new_settlement_region")
        district = st.text_input("Район", key="new_settlement_district")
        settlement = st.text_input("Населённый пункт", key="new_settlement_name")
        lat = st.text_input("Широта", key="new_settlement_lat")
        lon = st.text_input("Долгота", key="new_settlement_lon")
        submitted = st.form_submit_button("Добавить населённый пункт")
        if submitted:
            if not settlement.strip():
                st.warning("Для нового населённого пункта нужно указать название.")
            else:
                new_row = add_blank_settlement_row(region, district, settlement, lat, lon)
                apply_rows_update(rows + [new_row], "Новый населённый пункт добавлен.")


def render_question_editor(frame: pd.DataFrame, rows: list[dict]) -> None:
    question_frame = (
        frame[frame["question"].astype(str).str.strip() != ""]
        .groupby("question", dropna=False)
        .agg(row_count=("question", "size"))
        .reset_index()
        .sort_values("question")
    )
    search_query = st.text_input("Поиск вопроса", key="question_search", placeholder="Текст вопроса")
    filtered = filter_frame_by_text(question_frame, ["question"], search_query)

    if filtered.empty:
        st.info("Вопросы по текущему фильтру не найдены.")
    else:
        selected_question = st.selectbox("Выберите вопрос", filtered["question"].tolist(), key="selected_question")
        with st.form("edit_question_form"):
            st.markdown("**Изменить выбранный вопрос**")
            new_question = st.text_input("Новый текст вопроса", value=selected_question)
            submitted = st.form_submit_button("Сохранить вопрос")
            if submitted:
                if not new_question.strip():
                    st.warning("Текст вопроса не может быть пустым.")
                else:
                    apply_rows_update(rename_question(rows, selected_question, new_question), "Вопрос обновлен во всех связанных строках.")

        if st.button("Удалить выбранный вопрос", key="delete_selected_question"):
            apply_rows_update(delete_question(rows, selected_question), "Вопрос удален вместе со связанными наблюдениями.")

    settlement_frame = build_settlement_frame(frame)
    settlement_label = st.selectbox(
        "Первый пункт для нового вопроса",
        settlement_frame["label"].tolist() if not settlement_frame.empty else ["Нет доступных пунктов"],
        key="new_question_settlement",
        disabled=settlement_frame.empty,
    )
    selected_settlement = settlement_frame.loc[settlement_frame["label"] == settlement_label].iloc[0].to_dict() if not settlement_frame.empty else None

    with st.form("add_question_form"):
        st.markdown("**Добавить новый вопрос**")
        question = st.text_input("Текст вопроса", key="new_question_text", placeholder="Например: ЛАРНГ: Как называется ...?")
        unit1 = st.text_input("Основной ответ", key="new_question_unit1")
        unit2 = st.text_input("Дополнительный ответ", key="new_question_unit2")
        comment = st.text_input("Комментарий", key="new_question_comment")
        submitted = st.form_submit_button("Добавить вопрос")
        if submitted and selected_settlement is not None:
            if not question.strip():
                st.warning("Для нового вопроса нужен текст вопроса.")
            else:
                new_row = add_observation_row(
                    region=selected_settlement["region"],
                    district=selected_settlement["district"],
                    settlement=selected_settlement["settlement"],
                    lat=selected_settlement["lat"],
                    lon=selected_settlement["lon"],
                    question=question,
                    unit1=unit1,
                    unit2=unit2,
                    comment=comment,
                )
                apply_rows_update(rows + [new_row], "Новый вопрос добавлен с первым наблюдением.")


def render_observation_editor(frame: pd.DataFrame, rows: list[dict]) -> None:
    observation_frame = frame.reset_index(names="row_index")
    observation_frame["label"] = observation_frame.apply(
        lambda row: f"#{row['row_index'] + 1} · {row['settlement'] or 'Без пункта'} · {row['question'] or 'Без вопроса'}",
        axis=1,
    )
    search_query = st.text_input("Поиск наблюдения", key="observation_search", placeholder="Пункт, вопрос, ответ, комментарий")
    filtered = filter_frame_by_text(
        observation_frame,
        ["region", "district", "settlement", "question", "unit1", "unit2", "comment"],
        search_query,
    )

    if filtered.empty:
        st.info("Наблюдения по текущему фильтру не найдены.")
    else:
        selected_label = st.selectbox("Выберите наблюдение", filtered["label"].tolist(), key="selected_observation")
        selected_row = filtered.loc[filtered["label"] == selected_label].iloc[0].to_dict()

        with st.form("edit_observation_form"):
            st.markdown("**Изменить выбранное наблюдение**")
            region = st.text_input("Регион", value=selected_row["region"])
            district = st.text_input("Район", value=selected_row["district"])
            settlement = st.text_input("Населённый пункт", value=selected_row["settlement"])
            lat = st.text_input("Широта", value=selected_row["lat"])
            lon = st.text_input("Долгота", value=selected_row["lon"])
            question = st.text_input("Вопрос", value=selected_row["question"])
            unit1 = st.text_input("Основной ответ", value=selected_row["unit1"])
            unit2 = st.text_input("Дополнительный ответ", value=selected_row["unit2"])
            comment = st.text_input("Комментарий", value=selected_row["comment"])
            submitted = st.form_submit_button("Сохранить наблюдение")
            if submitted:
                updated_row = add_observation_row(region, district, settlement, lat, lon, question, unit1, unit2, comment)
                apply_rows_update(update_observation(rows, int(selected_row["row_index"]), updated_row), "Наблюдение обновлено.")

        if st.button("Удалить выбранное наблюдение", key="delete_selected_observation"):
            apply_rows_update(delete_observation(rows, int(selected_row["row_index"])), "Наблюдение удалено.")

    settlement_frame = build_settlement_frame(frame)
    settlement_label = st.selectbox(
        "Пункт для нового наблюдения",
        settlement_frame["label"].tolist() if not settlement_frame.empty else ["Нет доступных пунктов"],
        key="new_observation_settlement",
        disabled=settlement_frame.empty,
    )
    selected_settlement = settlement_frame.loc[settlement_frame["label"] == settlement_label].iloc[0].to_dict() if not settlement_frame.empty else None

    with st.form("add_observation_form"):
        st.markdown("**Добавить новое наблюдение**")
        question = st.text_input("Вопрос", key="new_observation_question")
        unit1 = st.text_input("Основной ответ", key="new_observation_unit1")
        unit2 = st.text_input("Дополнительный ответ", key="new_observation_unit2")
        comment = st.text_input("Комментарий", key="new_observation_comment")
        submitted = st.form_submit_button("Добавить наблюдение")
        if submitted and selected_settlement is not None:
            if not question.strip():
                st.warning("Для нового наблюдения нужен текст вопроса.")
            else:
                new_row = add_observation_row(
                    region=selected_settlement["region"],
                    district=selected_settlement["district"],
                    settlement=selected_settlement["settlement"],
                    lat=selected_settlement["lat"],
                    lon=selected_settlement["lon"],
                    question=question,
                    unit1=unit1,
                    unit2=unit2,
                    comment=comment,
                )
                apply_rows_update(rows + [new_row], "Новое наблюдение добавлено.")


def render_table_editor(frame: pd.DataFrame) -> None:
    with st.form("full_table_editor_form"):
        edited_frame = st.data_editor(
            frame,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="full_table_editor",
        )
        submitted = st.form_submit_button("Применить изменения из таблицы")
        if submitted:
            apply_rows_update(dataframe_to_rows(edited_frame), "Таблица обновлена.")


def main() -> None:
    st.set_page_config(
        page_title="Интерактивная карта русских говоров Удмуртии",
        layout="wide",
    )

    st.title("Интерактивная карта русских говоров Удмуртии")
    st.caption("Приложение теперь читает данные из Google Sheets и позволяет редактировать их прямо в интерфейсе.")
    st.caption(f"Версия сборки: {APP_VERSION}")
    st.caption(f"Репозиторий проекта: [{REPOSITORY_URL}]({REPOSITORY_URL})")

    sheet_url = st.sidebar.text_input("Ссылка на Google Sheets", value=st.session_state.get("editor_sheet_url", DEFAULT_SHEET_URL))
    ensure_editor_state(sheet_url)

    if flash_message := st.session_state.pop("editor_flash", None):
        st.success(flash_message)

    rows = normalize_rows(st.session_state.editor_rows)
    source_state = st.session_state.editor_source_state
    source_meta = build_source_meta(sheet_url, rows, source_state)
    credentials_info = get_streamlit_credentials()
    selected_theme_label = st.session_state.get("ui_theme_label", THEME_OPTIONS["night"])
    selected_theme_key = next(
        (key for key, label in THEME_OPTIONS.items() if label == selected_theme_label),
        "night",
    )
    inject_streamlit_theme(selected_theme_key)

    with st.sidebar:
        selected_theme_label = st.radio(
            "Тема интерфейса",
            options=list(THEME_OPTIONS.values()),
            index=list(THEME_OPTIONS.values()).index(selected_theme_label),
            key="ui_theme_label",
        )
        selected_theme_key = next(
            (key for key, label in THEME_OPTIONS.items() if label == selected_theme_label),
            "night",
        )
        inject_streamlit_theme(selected_theme_key)
        st.markdown(f"[Открыть репозиторий GitHub]({REPOSITORY_URL})")

        st.subheader("Источник данных")
        st.markdown(f"[Открыть Google Sheets]({sheet_url})")
        st.caption(source_meta["message"])
        st.caption(
            f"Строк: {source_meta['row_count']} · "
            f"вопросов: {source_meta['question_count']} · "
            f"пунктов: {source_meta['settlement_count']}"
        )
        if st.button("Перезагрузить из Google Sheets"):
            load_remote_rows.clear()
            reset_editor_state(sheet_url)
            st.rerun()
        if st.button("Сбросить локальные правки"):
            reset_editor_state(sheet_url)
            st.rerun()

        st.subheader("Сохранение")
        if credentials_info:
            st.caption("Прямое сохранение обратно в Google Sheets доступно.")
            if st.button("Сохранить текущие изменения в Google Sheets"):
                try:
                    with st.spinner("Записываю изменения в Google Sheets..."):
                        save_rows_to_google_sheet(sheet_url, rows, credentials_info)
                        load_remote_rows.clear()
                        reset_editor_state(sheet_url)
                    st.success("Google Sheets обновлена.")
                except Exception as exc:
                    st.error(
                        "Не удалось записать изменения в Google Sheets. "
                        "Проверьте, что сервисный аккаунт добавлен в доступ к таблице. "
                        f"Техническая причина: {exc}"
                    )
        else:
            st.info(
                "Прямую запись в Google Sheets можно включить через `st.secrets[\"google_service_account\"]` "
                "или переменную `GOOGLE_SERVICE_ACCOUNT_JSON`. До этого момента источник уже читается из таблицы, "
                "а для правок доступна ссылка на саму Google Sheets и встроенный редактор-предпросмотр."
            )

    tabs = st.tabs(["Карта", "Редактирование", "Таблица"])

    with tabs[0]:
        render_map_tab(rows, source_meta, selected_theme_key)

    with tabs[1]:
        st.markdown(f"**Текущий источник:** [{source_meta['label']}]({sheet_url})")
        st.caption("После каждого сохранения в редакторе карта автоматически будет строиться из обновленного набора строк.")
        editor_tabs = st.tabs(["Населённые пункты", "Вопросы", "Наблюдения"])
        frame = rows_to_dataframe(rows)
        with editor_tabs[0]:
            render_settlement_editor(frame, rows)
        with editor_tabs[1]:
            render_question_editor(frame, rows)
        with editor_tabs[2]:
            render_observation_editor(frame, rows)

    with tabs[2]:
        st.markdown(f"**Редактирование всей таблицы:** [{sheet_url}]({sheet_url})")
        st.caption("Здесь можно править весь набор строк целиком. После применения карта на вкладке выше обновится.")
        render_table_editor(rows_to_dataframe(rows))
        st.download_button(
            "Скачать текущую таблицу CSV",
            data=rows_to_csv_bytes(rows),
            file_name="dialect_map_data_current.csv",
            mime="text/csv",
        )

    # Обращение к функции оставлено для зависимости от файлов интерфейса и автоматического пересчета на dev-цикле.
    latest_source_mtime()


if __name__ == "__main__":
    main()
