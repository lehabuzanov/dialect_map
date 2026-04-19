from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


EXPECTED_MAP_FIELDS = [
    "region",
    "district",
    "settlement",
    "lat",
    "lon",
    "question",
    "unit1",
    "unit2",
    "comment",
]

ADMIN_NAME_REPAIRS = {
    "Udmurt": ("Удмуртская Республика", "республика"),
    "Mozhga": ("г. Можга", "городской округ"),
    "Glazov": ("г. Глазов", "городской округ"),
    "Sarapul": ("г. Сарапул", "городской округ"),
    "Votkinsk": ("г. Воткинск", "городской округ"),
    "Alnashskiyrayon": ("Алнашский район", "район"),
    "Balezinskiyrayon": ("Балезинский район", "район"),
    "Debesskiyrayon": ("Дебёсский район", "район"),
    "Glazovskiyrayon": ("Глазовский район", "район"),
    "Grakhovskiyrayon": ("Граховский район", "район"),
    "Igrinskiyrayon": ("Игринский район", "район"),
    "Kambarskiyrayon": ("Камбарский район", "район"),
    "Karakulinskiyrayon": ("Каракулинский район", "район"),
    "Kezskiyrayon": ("Кезский район", "район"),
    "Kiyasovskiyrayon": ("Киясовский район", "район"),
    "Kiznerskiyrayon": ("Кизнерский район", "район"),
    "Krasnogorskiyrayon": ("Красногорский район", "район"),
    "Malopurginskiyrayon": ("Малопургинский район", "район"),
    "Mozhginskiyrayon": ("Можгинский район", "район"),
    "Sarapul'skiyrayon": ("Сарапульский район", "район"),
    "Seltinskiyrayon": ("Селтинский район", "район"),
    "Sharkanskiyrayon": ("Шарканский район", "район"),
    "Syumsinskiyrayon": ("Сюмсинский район", "район"),
    "Uvinskiyrayon": ("Увинский район", "район"),
    "Vavozhskiyrayon": ("Вавожский район", "район"),
    "Votkinskiyrayon": ("Воткинский район", "район"),
    "Yakshur-Bod'inskiyrayon": ("Якшур-Бодьинский район", "район"),
    "Yarskiyrayon": ("Ярский район", "район"),
    "Yukamenskiyrayon": ("Юкаменский район", "район"),
    "Zav'yalovskiyrayon": ("Завьяловский район", "район"),
}


def load_project_data(project_root: Path) -> dict:
    csv_root = project_root / "data" / "csv"
    geojson_root = project_root / "data" / "geojson"
    notes_root = project_root / "notes"

    map_rows = load_csv_rows(csv_root / "dialect_map_data.csv", EXPECTED_MAP_FIELDS)
    points, features, observations = normalize_map_rows(map_rows)

    border_geojson = repair_admin_geojson_names(load_geojson(geojson_root / "udmurtia_border.geojson"))
    districts_geojson = repair_admin_geojson_names(load_geojson(geojson_root / "districts.geojson"))
    areas = load_geojson_directory(geojson_root / "areas", geometry_type="polygon")
    isoglosses = load_geojson_directory(geojson_root / "isoglosses", geometry_type="line")
    ui_notes = read_text_with_fallback(notes_root / "05_ui_notes.txt")

    sections = sorted({feature["section"] for feature in features if feature.get("section")})
    manual_area_keys = {
        build_scope_key(item["properties"].get("feature_id", ""), item["properties"].get("attested_value"))
        for item in areas
        if item.get("properties")
    }
    manual_isogloss_keys = {
        build_scope_key(item["properties"].get("feature_id", ""), item["properties"].get("attested_value"))
        for item in isoglosses
        if item.get("properties")
    }

    return {
        "meta": {
            "title": "Интерактивная карта русских говоров Удмуртии",
            "subtitle": "Рабочая версия по материалам ЛАРНГ и ДАРЯ",
            "demo_mode": False,
            "demo_notice": "",
            "sections": sections,
            "map": {
                "base_label": "OpenFreeMap с локальными тематическими слоями",
                "min_zoom": 7,
                "max_zoom": 11,
                "focus_zoom": 9,
            },
            "boundary_sources": [
                {
                    "name": "GADM 4.1",
                    "usage": "Границы Удмуртии и районов/городских округов",
                    "url": "https://geodata.ucdavis.edu/gadm/gadm4.1/json/",
                }
            ],
        },
        "ui_notes": ui_notes,
        "points": points,
        "features": features,
        "observations": observations,
        "map_styles": [],
        "geojson": {
            "border": border_geojson,
            "districts": districts_geojson,
            "landscapes": [],
            "areas": areas,
            "isoglosses": isoglosses,
        },
        "stats": {
            "demo_point_count": 0,
            "active_feature_count": len(features),
            "active_feature_ids": [feature["feature_id"] for feature in features],
        },
        "manual_area_keys": sorted(manual_area_keys),
        "manual_isogloss_keys": sorted(manual_isogloss_keys),
    }


def load_csv_rows(path: Path, expected_fields: Iterable[str]) -> List[dict]:
    if not path.exists():
        return []

    text = read_text_with_fallback(path)
    reader = csv.DictReader(text.splitlines())
    rows: List[dict] = []
    for row in reader:
        normalized = {field: (row.get(field, "") or "").strip() for field in expected_fields}
        if any(normalized.values()):
            rows.append(normalized)
    return rows


def normalize_map_rows(rows: Sequence[dict]) -> Tuple[List[dict], List[dict], List[dict]]:
    point_index: Dict[Tuple[str, str, str, str, str], str] = {}
    feature_index: Dict[str, str] = {}
    points: List[dict] = []
    features: List[dict] = []
    observations: List[dict] = []
    answers_by_question: Dict[str, List[str]] = {}
    point_counter = 1
    feature_counter = 1
    observation_counter = 1

    for row in rows:
        question = row.get("question", "")
        if not question:
            continue

        point_key = (
            row.get("region", ""),
            row.get("district", ""),
            row.get("settlement", ""),
            row.get("lat", ""),
            row.get("lon", ""),
        )
        point_id = point_index.get(point_key)
        if point_id is None:
            point_id = f"P{point_counter:03d}"
            point_counter += 1
            point_index[point_key] = point_id
            points.append(
                {
                    "point_id": point_id,
                    "region": row.get("region", ""),
                    "district": row.get("district", ""),
                    "settlement": row.get("settlement", ""),
                    "latitude": parse_float(row.get("lat")),
                    "longitude": parse_float(row.get("lon")),
                    "landscape": "",
                    "source": "Рабочая таблица",
                    "comment": row.get("comment", ""),
                    "is_demo": False,
                }
            )

        feature_id = feature_index.get(question)
        if feature_id is None:
            atlas = derive_atlas_name(question)
            feature_id = f"Q{feature_counter:03d}"
            feature_counter += 1
            feature_index[question] = feature_id
            answers_by_question[question] = []
            features.append(
                {
                    "feature_id": feature_id,
                    "section": atlas,
                    "subsection": "Вопросы",
                    "feature_name": question,
                    "description": question,
                    "source_file": "dialect_map_data.csv",
                    "source_pages": "",
                    "notes": "",
                    "alphabet_key": question,
                    "question_text": question,
                    "linguistic_unit_1": "",
                    "linguistic_unit_2": "",
                    "linguistic_unit_3": "",
                    "example_answer": "",
                    "example_list": [],
                    "map_style": "question_palette",
                    "is_demo": False,
                }
            )

        for answer in [row.get("unit1", ""), row.get("unit2", "")]:
            cleaned = answer.strip()
            if cleaned and cleaned not in answers_by_question[question]:
                answers_by_question[question].append(cleaned)

        observations.append(
            {
                "obs_id": f"O{observation_counter:04d}",
                "point_id": point_id,
                "feature_id": feature_id,
                "attested_value": row.get("unit1", ""),
                "secondary_value": row.get("unit2", ""),
                "answer_type": "рабочая выборка",
                "source_year": "",
                "collector": derive_atlas_name(question),
                "comment": row.get("comment", ""),
                "is_demo": False,
            }
        )
        observation_counter += 1

    feature_lookup = {feature["feature_name"]: feature for feature in features}
    for question, answers in answers_by_question.items():
        feature = feature_lookup[question]
        feature["example_list"] = answers
        feature["example_answer"] = answers[0] if answers else ""
        feature["linguistic_unit_1"] = answers[0] if len(answers) > 0 else ""
        feature["linguistic_unit_2"] = answers[1] if len(answers) > 1 else ""
        feature["linguistic_unit_3"] = answers[2] if len(answers) > 2 else ""

    features.sort(key=lambda item: (item["section"], item["feature_name"]))
    return points, features, observations


def derive_atlas_name(question: str) -> str:
    match = re.match(r"\s*([^:]+)\s*:", question)
    if match:
        return match.group(1).strip().upper()
    return "ВОПРОСЫ"


def parse_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    normalized = str(value).replace(",", ".").strip()
    try:
        return float(normalized)
    except ValueError:
        return None


def read_text_with_fallback(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def load_geojson(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(read_text_with_fallback(path))


def repair_admin_geojson_names(payload: Optional[dict]) -> Optional[dict]:
    if not payload:
        return payload

    if payload.get("type") == "FeatureCollection":
        payload["features"] = [repair_admin_feature(feature) for feature in payload.get("features", [])]
        return payload

    if payload.get("type") == "Feature":
        return repair_admin_feature(payload)

    return payload


def repair_admin_feature(feature: dict) -> dict:
    properties = dict(feature.get("properties") or {})
    source_name = properties.get("source_name") or ""
    repaired = ADMIN_NAME_REPAIRS.get(source_name)
    if repaired:
        properties["name"], properties["admin_type"] = repaired
    feature["properties"] = properties
    return feature


def load_geojson_directory(path: Path, geometry_type: str) -> List[dict]:
    if not path.exists():
        return []

    feature_list: List[dict] = []
    for geojson_path in sorted(path.glob("*.geojson")):
        payload = load_geojson(geojson_path)
        if not payload:
            continue
        feature_list.extend(
            normalize_geojson_payload(
                payload,
                source_name=geojson_path.stem,
                geometry_type=geometry_type,
            )
        )
    return feature_list


def normalize_geojson_payload(payload: dict, source_name: str, geometry_type: str) -> List[dict]:
    if payload.get("type") == "FeatureCollection":
        source_features = payload.get("features", [])
    elif payload.get("type") == "Feature":
        source_features = [payload]
    elif payload.get("type"):
        source_features = [{"type": "Feature", "properties": {}, "geometry": payload}]
    else:
        source_features = []

    normalized_features: List[dict] = []
    for item in source_features:
        properties = dict(item.get("properties") or {})
        feature_id = (properties.get("feature_id") or "").strip()
        attested_value = (properties.get("attested_value") or "").strip()
        if not feature_id:
            feature_id = source_name
        properties.setdefault("feature_id", feature_id)
        properties.setdefault("attested_value", attested_value)
        properties.setdefault("source", "manual")
        properties.setdefault("geometry_type", geometry_type)
        properties.setdefault("style_code", "")
        properties.setdefault("source_name", source_name)
        normalized_features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": item.get("geometry"),
            }
        )

    return normalized_features


def build_scope_key(feature_id: str, attested_value: Optional[str]) -> str:
    value = (attested_value or "").strip().lower()
    return f"{feature_id}::{value}"
