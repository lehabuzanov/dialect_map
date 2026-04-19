# Интерактивная карта русских говоров Удмуртии

Проект запускается напрямую через Streamlit. Предварительная статическая сборка больше не используется.

## Что нужно для запуска на Streamlit

- `streamlit_app.py` — точка входа приложения.
- `requirements.txt` — зависимости, которые Streamlit установит автоматически.
- `scripts/data_loader.py` — загрузка и нормализация данных.
- `scripts/area_generator.py` — построение предварительных ареалов и парных изоглосс.
- `scripts/page_renderer.py` — подготовка HTML-страницы карты во время запуска.
- `web/` — шаблон, стили и JavaScript карты.
- `data/`, `notes/`, `доп/` — исходные данные и текст инструкции.

## Запуск локально для разработки

```bash
streamlit run streamlit_app.py
```

## Публикация в Streamlit Community Cloud

1. Загрузите проект в GitHub.
2. В Streamlit Community Cloud выберите репозиторий.
3. В качестве entrypoint укажите `streamlit_app.py`.
4. Streamlit установит зависимости из `requirements.txt` и запустит приложение.

## Структура данных

- `data/csv/01_points_template.csv` — населённые пункты.
- `data/csv/03_observations_template.csv` — наблюдения по пунктам.
- `data/csv/04_map_styles_legend.csv` — коды оформления.
- `data/geojson/udmurtia_border.geojson` — граница Удмуртии.
- `data/geojson/districts.geojson` — районы и городские округа.
- `доп/02_features_catalog_expanded_utf8.csv` — каталог признаков.
- `доп/02_feature_examples_expanded_utf8.csv` — примеры по признакам.
- `notes/05_ui_notes.txt` — инструкция пользователя.

## Принцип работы

- Python загружает данные и подготавливает GeoJSON-слои.
- Для признаков без ручных полигонов строятся предварительные ареалы.
- Изоглоссы рассчитываются только для пары одновременно выбранных признаков.
- Готовая HTML-страница формируется во время запуска Streamlit и вставляется в интерфейс через `streamlit.components.v1.html`.
