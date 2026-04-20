from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional, Sequence

from area_generator import generate_provisional_areas, generate_provisional_isoglosses
from data_loader import load_project_data


def render_project_html(
    project_root: Path,
    map_rows: Optional[Sequence[dict]] = None,
    data_source_meta: Optional[dict] = None,
) -> str:
    project_data = load_project_data(project_root, map_rows=map_rows, data_source_meta=data_source_meta)
    provisional_areas = generate_provisional_areas(
        points=project_data["points"],
        observations=project_data["observations"],
        manual_area_keys=project_data["manual_area_keys"],
    )
    provisional_isoglosses = generate_provisional_isoglosses(
        points=project_data["points"],
        observations=project_data["observations"],
        border_geojson=project_data["geojson"].get("border"),
        manual_isogloss_keys=project_data["manual_isogloss_keys"],
    )
    project_data["geojson"]["areas_provisional"] = provisional_areas
    project_data["geojson"]["isoglosses_provisional"] = provisional_isoglosses

    template = read_text(project_root / "web" / "templates" / "index.template.html")
    app_css = read_text(project_root / "web" / "assets" / "style.css")
    app_js = read_text(project_root / "web" / "assets" / "app.js")
    leaflet_js = read_text(project_root / "web" / "assets" / "leaflet" / "leaflet.js")
    leaflet_css = inline_leaflet_assets(
        project_root / "web" / "assets" / "leaflet" / "leaflet.css",
        project_root / "web" / "assets" / "leaflet",
    )

    return (
        template.replace("{{PAGE_TITLE}}", project_data["meta"]["title"])
        .replace("{{INLINE_LEAFLET_CSS}}", leaflet_css)
        .replace("{{INLINE_APP_CSS}}", app_css)
        .replace("{{APP_DATA_JSON}}", json.dumps(project_data, ensure_ascii=False))
        .replace("{{INLINE_LEAFLET_JS}}", leaflet_js)
        .replace("{{INLINE_APP_JS}}", app_js)
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def inline_leaflet_assets(css_path: Path, asset_dir: Path) -> str:
    css = read_text(css_path)
    replacements = {
        "images/layers.png": asset_dir / "layers.png",
        "images/layers-2x.png": asset_dir / "layers-2x.png",
        "images/marker-icon.png": asset_dir / "marker-icon.png",
        "images/marker-icon-2x.png": asset_dir / "marker-icon-2x.png",
        "images/marker-shadow.png": asset_dir / "marker-shadow.png",
    }

    for _, absolute_path in replacements.items():
        if not absolute_path.exists():
            continue
        encoded = base64.b64encode(absolute_path.read_bytes()).decode("ascii")
        mime_type = guess_mime_type(absolute_path.suffix.lower())
        css = css.replace(
            f"url(images/{absolute_path.name})",
            f"url(data:{mime_type};base64,{encoded})",
        )

    return css


def guess_mime_type(suffix: str) -> str:
    if suffix == ".png":
        return "image/png"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"
