from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from area_generator import build_scope_key, coordinates_to_polygon


EXPECTED_POINT_FIELDS = [
    "point_id",
    "region",
    "district",
    "settlement",
    "latitude",
    "longitude",
    "landscape",
    "source",
    "comment",
]

EXPECTED_FEATURE_FIELDS = [
    "feature_id",
    "section",
    "subsection",
    "feature_name",
    "description",
    "source_file",
    "source_pages",
    "example_1",
    "example_2",
    "example_3",
    "example_4",
    "notes",
]

EXPECTED_EXAMPLE_FIELDS = [
    "example_id",
    "feature_id",
    "section",
    "subsection",
    "feature_name",
    "transcription_example",
    "source_file",
    "source_pages",
    "notes",
]

EXPECTED_OBSERVATION_FIELDS = [
    "obs_id",
    "point_id",
    "feature_id",
    "attested_value",
    "answer_type",
    "source_year",
    "collector",
    "comment",
]

EXPECTED_STYLE_FIELDS = [
    "style_code",
    "geometry_type",
    "display_name",
    "intended_use",
    "icon_or_style_hint",
]

ADMIN_NAME_REPAIRS = {
    "Udmurt": ("Удмуртская Республика", "республика"),
    "Mozhga": ("Можга", "городской округ"),
    "Glazov": ("Глазов", "городской округ"),
    "Sarapul": ("Сарапул", "городской округ"),
    "Votkinsk": ("Воткинск", "городской округ"),
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
    data_root = project_root / "data"
    csv_root = data_root / "csv"
    geojson_root = data_root / "geojson"
    notes_root = project_root / "notes"
    extra_root = project_root / "доп"

    features = load_csv_rows(
        resolve_data_file(
            project_root,
            extra_root / "02_features_catalog_expanded_utf8.csv",
            "02_features_catalog_expanded_utf8.csv",
        ),
        EXPECTED_FEATURE_FIELDS,
    )
    examples = load_csv_rows(
        resolve_data_file(
            project_root,
            extra_root / "02_feature_examples_expanded_utf8.csv",
            "02_feature_examples_expanded_utf8.csv",
        ),
        EXPECTED_EXAMPLE_FIELDS,
    )
    points = load_csv_rows(
        resolve_data_file(project_root, csv_root / "01_points_template.csv", "01_points_template.csv"),
        EXPECTED_POINT_FIELDS,
    )
    observations = load_csv_rows(
        resolve_data_file(project_root, csv_root / "03_observations_template.csv", "03_observations_template.csv"),
        EXPECTED_OBSERVATION_FIELDS,
    )
    map_styles = load_csv_rows(
        resolve_data_file(project_root, csv_root / "04_map_styles_legend.csv", "04_map_styles_legend.csv"),
        EXPECTED_STYLE_FIELDS,
    )

    border_geojson = repair_admin_geojson_names(load_geojson(geojson_root / "udmurtia_border.geojson"))
    districts_geojson = repair_admin_geojson_names(load_geojson(geojson_root / "districts.geojson"))
    areas = load_geojson_directory(geojson_root / "areas", geometry_type="polygon")
    isoglosses = load_geojson_directory(geojson_root / "isoglosses", geometry_type="line")
    ui_notes = read_text_with_fallback(
        resolve_data_file(project_root, notes_root / "05_ui_notes.txt", "05_ui_notes.txt")
    )

    normalized_points = [normalize_point(row) for row in points]
    normalized_features = normalize_features(features, examples)
    normalized_observations = [normalize_observation(row) for row in observations]
    normalized_styles = [normalize_style(row) for row in map_styles]

    normalized_points = [point for point in normalized_points if point_has_content(point)]
    normalized_observations = [
        observation for observation in normalized_observations if observation_has_content(observation)
    ]

    valid_point_ids = {
        point["point_id"]
        for point in normalized_points
        if point.get("latitude") is not None and point.get("longitude") is not None
    }

    demo_points = build_demo_points(districts_geojson)
    demo_observations = build_demo_observations_v2(normalized_features)

    if len(valid_point_ids) < 8:
        normalized_points = merge_by_id(normalized_points, demo_points, "point_id")

    if len(normalized_observations) < 20:
        normalized_observations = merge_by_id(normalized_observations, demo_observations, "obs_id")

    normalized_points = align_demo_points_to_districts(normalized_points, districts_geojson)
    landscape_zones = build_landscape_features(normalized_points)

    demo_mode = any(item.get("is_demo") for item in normalized_points) or any(
        item.get("is_demo") for item in normalized_observations
    )

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

    active_feature_ids = sorted(
        {
            observation["feature_id"]
            for observation in normalized_observations
            if observation.get("feature_id")
        }
    )

    return {
        "meta": {
            "title": "Интерактивная карта русских говоров Удмуртии",
            "subtitle": "Предфинальная учебная демонстрационная версия",
            "demo_mode": demo_mode,
            "demo_notice": (
                "Демо-режим включён: точки, наблюдения, ареалы и описания встроены только "
                "для демонстрации интерфейса и не являются итоговой научной картой."
            ),
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
        "points": normalized_points,
        "features": normalized_features,
        "observations": normalized_observations,
        "map_styles": normalized_styles,
        "geojson": {
            "border": border_geojson,
            "districts": districts_geojson,
            "landscapes": landscape_zones,
            "areas": areas,
            "isoglosses": isoglosses,
        },
        "stats": {
            "demo_point_count": len([point for point in normalized_points if point.get("is_demo")]),
            "active_feature_count": len(active_feature_ids),
            "active_feature_ids": active_feature_ids,
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
        normalized_row = {field: (row.get(field, "") or "").strip() for field in expected_fields}
        if any(normalized_row.values()):
            rows.append(normalized_row)
    return rows


def read_text_with_fallback(path: Path) -> str:
    if not path.exists():
        return ""
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_data_file(project_root: Path, preferred_path: Path, fallback_name: str) -> Path:
    if preferred_path.exists():
        return preferred_path
    fallback_path = project_root / fallback_name
    return fallback_path if fallback_path.exists() else preferred_path


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
    if repaired and ("?" in str(properties.get("name", "")) or "?" in str(properties.get("admin_type", ""))):
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
            if "__" in source_name:
                feature_id, raw_value = source_name.split("__", 1)
                attested_value = attested_value or raw_value.replace("_", " ")
            else:
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


def normalize_point(row: dict) -> dict:
    point = dict(row)
    point["latitude"] = parse_float(point.get("latitude"))
    point["longitude"] = parse_float(point.get("longitude"))
    point["is_demo"] = point["point_id"].startswith("DP")
    return point


def normalize_features(rows: Sequence[dict], examples: Sequence[dict]) -> List[dict]:
    examples_by_feature: Dict[str, List[str]] = {}

    for example in examples:
        feature_id = (example.get("feature_id") or "").strip()
        text = (example.get("transcription_example") or "").strip()
        if not feature_id or not text:
            continue
        examples_by_feature.setdefault(feature_id, []).append(text)

    return [normalize_feature(row, examples_by_feature.get(row.get("feature_id", ""), [])) for row in rows]


def normalize_feature(row: dict, linked_examples: Sequence[str]) -> dict:
    feature = dict(row)
    seeded_examples = [
        (feature.get("example_1") or "").strip(),
        (feature.get("example_2") or "").strip(),
        (feature.get("example_3") or "").strip(),
        (feature.get("example_4") or "").strip(),
    ]
    merged_examples: List[str] = []
    for item in list(linked_examples) + seeded_examples:
        if item and item not in merged_examples:
            merged_examples.append(item)

    feature["alphabet_key"] = feature.get("feature_name", "")
    feature["question_text"] = feature.get("description", "")
    feature["linguistic_unit_1"] = seeded_examples[0] if len(seeded_examples) > 0 else ""
    feature["linguistic_unit_2"] = seeded_examples[1] if len(seeded_examples) > 1 else ""
    feature["linguistic_unit_3"] = seeded_examples[2] if len(seeded_examples) > 2 else ""
    feature["example_answer"] = seeded_examples[0] if seeded_examples else ""
    feature["example_list"] = merged_examples
    feature["map_style"] = infer_feature_style(feature)
    feature["is_demo"] = False
    return feature


def normalize_observation(row: dict) -> dict:
    observation = dict(row)
    observation["is_demo"] = observation["obs_id"].startswith("DO")
    return observation


def normalize_style(row: dict) -> dict:
    return dict(row)


def infer_feature_style(feature: dict) -> str:
    section = (feature.get("section") or "").strip()
    subsection = (feature.get("subsection") or "").strip().lower()

    if section == "Гласные":
        return "area_blue" if "удар" in subsection else "area_cyan"
    if section == "Согласные":
        if "аффрикат" in subsection or "шип" in subsection:
            return "area_red"
        if "сонор" in subsection:
            return "area_indigo"
        return "area_green"
    if section == "Морфология":
        if "существ" in subsection:
            return "area_brown"
        if "глаг" in subsection:
            return "area_yellow"
        return "area_indigo"
    return "area_blue"


def point_has_content(point: dict) -> bool:
    return bool(
        point.get("settlement")
        or (
            point.get("latitude") is not None
            and point.get("longitude") is not None
        )
    )


def observation_has_content(observation: dict) -> bool:
    return bool(
        observation.get("attested_value")
        or observation.get("comment")
        or observation.get("collector")
        or observation.get("source_year")
    )


def merge_by_id(existing_rows: List[dict], demo_rows: List[dict], key: str) -> List[dict]:
    merged = {row[key]: row for row in existing_rows if row.get(key)}
    for row in demo_rows:
        merged.setdefault(row[key], row)
    return list(merged.values())


def parse_float(value: Optional[str]) -> Optional[float]:
    if value in (None, ""):
        return None
    normalized = str(value).replace(",", ".").strip()
    try:
        return float(normalized)
    except ValueError:
        return None


def align_demo_points_to_districts(points: List[dict], districts_geojson: Optional[dict]) -> List[dict]:
    district_lookup = build_district_feature_lookup(districts_geojson)
    aligned_points: List[dict] = []

    for point in points:
        if not point.get("is_demo"):
            aligned_points.append(point)
            continue

        district_feature = district_lookup.get(point.get("district"))
        latitude = point.get("latitude")
        longitude = point.get("longitude")
        if district_feature and (latitude is None or longitude is None):
            representative_point = geometry_representative_point(district_feature.get("geometry") or {})
            if representative_point:
                updated = dict(point)
                updated["latitude"], updated["longitude"] = representative_point
                aligned_points.append(updated)
                continue
        if (
            district_feature
            and latitude is not None
            and longitude is not None
            and not point_in_geometry(longitude, latitude, district_feature.get("geometry") or {})
        ):
            representative_point = geometry_representative_point(district_feature.get("geometry") or {})
            if representative_point:
                updated = dict(point)
                updated["latitude"], updated["longitude"] = representative_point
                aligned_points.append(updated)
                continue

        aligned_points.append(point)

    return aligned_points


def build_landscape_features(points: Sequence[dict]) -> List[dict]:
    grouped: Dict[str, dict] = {}

    for point in points:
        if point.get("latitude") is None or point.get("longitude") is None:
            continue
        landscape_label = (point.get("landscape") or "").strip()
        if not landscape_label:
            continue
        zone = get_landscape_zone(landscape_label)
        item = grouped.setdefault(
            zone["id"],
            {
                "zone": zone,
                "coordinates": [],
                "point_count": 0,
            },
        )
        item["coordinates"].append((point["longitude"], point["latitude"]))
        item["point_count"] += 1

    features: List[dict] = []
    for item in grouped.values():
        polygon = coordinates_to_polygon(item["coordinates"])
        if not polygon:
            continue
        zone = item["zone"]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "landscape_id": zone["id"],
                    "title": zone["label"],
                    "fill_color": zone["fill_color"],
                    "border_color": zone["border_color"],
                    "point_count": item["point_count"],
                    "description": zone["description"],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [polygon],
                },
            }
        )

    return features


def get_landscape_zone(landscape_label: str) -> dict:
    normalized = landscape_label.lower()
    if "прикам" in normalized:
        return landscape_zone("river", "Прикамская зона", "#cfe3ec", "#8db5c7", "Демонстрационная зона прикамского рельефа.")
    if "север" in normalized:
        return landscape_zone("north", "Северная лесная зона", "#d7e8d1", "#8db08a", "Северные и северо-восточные лесные районы.")
    if "централь" in normalized or "пригород" in normalized:
        return landscape_zone("central", "Центральная зона", "#e8e2c9", "#bba979", "Центральная часть республики и пригородные территории.")
    if "запад" in normalized:
        return landscape_zone("west", "Западная лесная зона", "#dce7d6", "#98aa8d", "Западные лесные и переходные территории.")
    if "юж" in normalized:
        return landscape_zone("south", "Южная зона", "#ecd8c8", "#c39a7c", "Южные и юго-западные территории демонстрационного набора.")
    return landscape_zone("mixed", "Переходная зона", "#dde5ea", "#95a8b5", "Смешанная демонстрационная ландшафтная зона.")


def landscape_zone(zone_id: str, label: str, fill_color: str, border_color: str, description: str) -> dict:
    return {
        "id": zone_id,
        "label": label,
        "fill_color": fill_color,
        "border_color": border_color,
        "description": description,
    }


def build_demo_points(districts_geojson: Optional[dict]) -> List[dict]:
    centroid_lookup = build_district_centroid_lookup(districts_geojson)
    specs = get_demo_point_specs()
    points: List[dict] = []

    for spec in specs:
        latitude = spec.get("latitude")
        longitude = spec.get("longitude")
        if latitude is None or longitude is None:
            centroid = centroid_lookup.get(spec["district"])
            if centroid:
                latitude, longitude = centroid
        latitude = latitude if latitude is not None else spec["fallback"][0]
        longitude = longitude if longitude is not None else spec["fallback"][1]
        points.append(
            normalize_point(
                {
                    "point_id": spec["point_id"],
                    "region": "Удмуртская Республика",
                    "district": spec["district"],
                    "settlement": spec["settlement"],
                    "latitude": str(latitude),
                    "longitude": str(longitude),
                    "landscape": spec["landscape"],
                    "source": "Учебный демо-набор",
                    "comment": spec["comment"],
                }
            )
        )

    return points


def get_demo_point_specs() -> List[dict]:
    return [
        spec("DP001", "Ижевск", "г. Ижевск", "Центральная часть", 56.8527, 53.2115),
        spec("DP002", "Завьяловский район", "с. Завьялово", "Пригородная зона", 56.7902, 53.3764),
        spec("DP003", "Глазов", "г. Глазов", "Север Удмуртии", 58.1395, 52.6580),
        spec("DP004", "Воткинск", "г. Воткинск", "Северо-восточная часть", 57.0518, 53.9872),
        spec("DP005", "Сарапул", "г. Сарапул", "Юго-восток", 56.4615, 53.8032),
        spec("DP006", "Можга", "г. Можга", "Юго-запад", 56.4447, 52.2277),
        spec("DP007", "Увинский район", "п. Ува", "Центральная часть", 56.9887, 52.1853),
        spec("DP008", "Дебёсский район", "с. Дебёсы", "Северо-восток", 57.6519, 53.8097),
        spec("DP009", "Балезинский район", "п. Балезино", "Северо-восток", 57.9781, 53.0135),
        spec("DP010", "Игринский район", "п. Игра", "Центрально-восточная часть", 57.5544, 53.0543),
        spec("DP011", "Якшур-Бодьинский район", "с. Якшур-Бодья", "Центрально-восточная часть", 57.1840, 53.0100),
        spec("DP012", "Вавожский район", "с. Вавож", "Западная часть", 56.7750, 51.9300),
        spec("DP013", "Малопургинский район", "с. Малая Пурга", "Южная часть", 56.5577, 53.0014),
        spec("DP014", "Кизнерский район", "п. Кизнер", "Юго-запад", 56.2741, 51.5148),
        spec("DP015", "Шарканский район", "с. Шаркан", "Северо-восточная часть", 57.2980, 53.8800),
        spec("DP016", "Сюмсинский район", "с. Сюмси", "Западная лесная зона", 57.1113, 51.6149),
        spec("DP017", "Кезский район", "п. Кез", "Северо-восток", 57.8950, 53.7130),
        spec("DP018", "Алнашский район", "с. Алнаши", "Южная часть", 56.1870, 52.4790),
        spec("DP019", "Граховский район", "с. Грахово", "Юго-запад", 56.0500, 51.9670),
        spec("DP020", "Камбарский район", "г. Камбарка", "Юго-восток", 56.2660, 54.2060),
        spec("DP021", "Каракулинский район", "с. Каракулино", "Прикамье", 56.0120, 53.7060),
        spec("DP022", "Киясовский район", "с. Киясово", "Южная часть", 56.3490, 53.1240),
        spec("DP023", "Красногорский район", "с. Красногорское", "Северная часть", 57.7040, 52.4990),
        spec("DP024", "Селтинский район", "с. Селты", "Западная часть", 57.3140, 51.8990),
        spec("DP025", "Юкаменский район", "с. Юкаменское", "Северо-запад", 57.8870, 52.2440),
        spec("DP026", "Ярский район", "п. Яр", "Северо-запад", 58.2450, 52.1030),
        spec("DP027", "Глазовский район", "с. Понино", "Северная часть", None, None, fallback=(58.0400, 52.7900)),
        spec("DP028", "Сарапульский район", "с. Сигаево", "Юго-восток", 56.4210, 53.7840),
        spec("DP029", "Можгинский район", "с. Большая Уча", "Юго-запад", None, None, fallback=(56.5750, 52.0400)),
        spec("DP030", "Воткинский район", "с. Перевозное", "Северо-восточная часть", 56.9080, 53.9010),
    ]


def spec(
    point_id: str,
    district: str,
    settlement: str,
    landscape: str,
    latitude: Optional[float],
    longitude: Optional[float],
    fallback: Tuple[float, float] | None = None,
) -> dict:
    return {
        "point_id": point_id,
        "district": district,
        "settlement": settlement,
        "landscape": landscape,
        "latitude": latitude,
        "longitude": longitude,
        "fallback": fallback or (56.95, 53.0),
        "comment": (
            "Учебная демонстрационная точка. Координаты и наблюдения предназначены "
            "для проверки интерфейса и логики карты."
        ),
    }


def build_demo_observations() -> List[dict]:
    north = ["DP003", "DP008", "DP009", "DP015", "DP017", "DP023", "DP025", "DP026", "DP027"]
    north_east = ["DP004", "DP010", "DP011", "DP015", "DP017", "DP020", "DP030"]
    center = ["DP001", "DP002", "DP007", "DP010", "DP011", "DP012", "DP024"]
    south = ["DP005", "DP006", "DP013", "DP014", "DP018", "DP019", "DP020", "DP021", "DP022", "DP028", "DP029"]
    west = ["DP006", "DP007", "DP012", "DP016", "DP018", "DP019", "DP024", "DP029"]
    east = ["DP004", "DP010", "DP011", "DP015", "DP020", "DP021", "DP028", "DP030"]

    pattern_definitions = [
        ("F001", [("е", north + center[:4]), ("и", south[:6]), ("ие", east[:4] + west[:2])]),
        ("F002", [("о", north + center[:3]), ("ô", south[:6]), ("уо", east[:4] + west[:3])]),
        ("F003", [("есть", center + north[:3]), ("нет", south[:6]), ("частично", east[:4] + west[:2])]),
        ("F004", [("’á", north[:4] + center[:4]), ("’é", south[:5]), ("смешанный тип", east[:4] + west[:2])]),
        ("F005", [("оканье", north + ["DP010", "DP011"]), ("неполное оканье", center), ("сверхоканье", ["DP020", "DP021", "DP028"])]),
        ("F006", [("сильное", south), ("диссимилятивное", west), ("ассимилятивно-диссимилятивное", east)]),
        ("F007", [("сильное", north), ("умеренное", center + ["DP024"]), ("ассимилятивное", ["DP005", "DP013", "DP018", "DP022"])]),
        ("F008", [("да", north + center[:3]), ("нет", south[:6])]),
        ("F009", [("да", north[:5] + east[:3]), ("нет", south[:6] + west[:3])]),
        ("F010", [("предударное", north[:4] + center[:4]), ("заударное", east[:4] + south[:3]), ("нет", west[:4] + south[3:6])]),
        ("F011", [("да", north[:4] + west[:4]), ("нет", south[:6] + center[:3])]),
        ("F012", [("взрывной [г]", north + center + ["DP024"]), ("фрикативный [ɣ]", south[:7])]),
        ("F013", [("только к", north[:4] + center[:4]), ("все заднеязычные", east[:4] + south[:4]), ("нет", west[:4] + south[4:8])]),
        ("F014", [("различение", north[:6] + ["DP024"]), ("цоканье", ["DP004", "DP010", "DP015", "DP020", "DP030"]), ("смешанный тип", ["DP001", "DP002", "DP011"])]),
        ("F015", [("нет", north[:5] + center[:4]), ("шоканье", ["DP004", "DP010", "DP015", "DP020"]), ("секанье", ["DP005", "DP013", "DP018", "DP021"])]),
        ("F016", [("краткие", north[:4] + center[:4]), ("мягкие", east[:4] + south[:4]), ("долгие", west[:4] + south[4:8])]),
        ("F017", [("[в]", center + north[:4]), ("[w]", ["DP005", "DP006", "DP013", "DP018", "DP019", "DP021"]), ("[ф]", ["DP004", "DP020", "DP028"])]),
        ("F018", [("[л]", center + west[:3]), ("[l]", north[:5]), ("[у]-образный рефлекс", ["DP005", "DP013", "DP014", "DP018", "DP019"])]),
        ("F019", [("сохранение нормы", center + north[:4]), ("изменение рода", south[:6]), ("смешанный тип", ["DP010", "DP011", "DP015", "DP028"])]),
        ("F020", [("формы на -а", north[:4] + west[:3]), ("формы с -ин-", south[:5] + east[:2]), ("смешанный тип", center[:4] + east[:3])]),
        ("F021", [("активно", north[:6] + center[:3]), ("ограниченно", east + west[:3]), ("нет", ["DP013", "DP014", "DP018", "DP019", "DP022"])]),
        ("F022", [("твердое т", ["DP005", "DP006", "DP013", "DP018", "DP019", "DP022", "DP028"]), ("мягкое т’", north[:6]), ("без конечного т", center + ["DP024"])]),
        ("F023", [("северный", north[:7]), ("южный", ["DP005", "DP013", "DP014", "DP018", "DP019", "DP022"]), ("смешанный тип", center + ["DP028"])]),
        ("F024", [("ся", north[:5] + center[:4]), ("са", ["DP005", "DP006", "DP013", "DP018", "DP019", "DP029"]), ("се", ["DP004", "DP010", "DP015", "DP020", "DP030"])]),
        ("F025", [("-учи", north[:5] + center[:4]), ("-ши", ["DP005", "DP013", "DP018", "DP021", "DP029"]), ("-вши", ["DP004", "DP010", "DP015", "DP020", "DP028"])]),
        ("F026", [("да", north[:5] + west[:4]), ("нет", ["DP001", "DP002", "DP005", "DP013", "DP018", "DP022", "DP028"])]),
    ]

    observations: List[dict] = []
    obs_index = 1
    for feature_id, value_groups in pattern_definitions:
        for value, point_ids in value_groups:
            for point_id in point_ids:
                observations.append(
                    normalize_observation(
                        {
                            "obs_id": f"DO{obs_index:03d}",
                            "point_id": point_id,
                            "feature_id": feature_id,
                            "attested_value": value,
                            "answer_type": "учебное наблюдение",
                            "source_year": str(2020 + (obs_index % 5)),
                            "collector": "Демонстрационная выборка",
                            "comment": "Учебное демонстрационное наблюдение для проверки фильтрации и карточек.",
                        }
                    )
                )
                obs_index += 1
    return observations


def build_demo_observations_v2(features: Sequence[dict]) -> List[dict]:
    region_points = {
        "north": ["DP003", "DP008", "DP009", "DP015", "DP017", "DP023", "DP025", "DP026", "DP027"],
        "north_east": ["DP004", "DP010", "DP011", "DP015", "DP017", "DP020", "DP030"],
        "center": ["DP001", "DP002", "DP007", "DP010", "DP011", "DP012", "DP024"],
        "south": ["DP005", "DP006", "DP013", "DP014", "DP018", "DP019", "DP020", "DP021", "DP022", "DP028", "DP029"],
        "west": ["DP006", "DP007", "DP012", "DP016", "DP018", "DP019", "DP024", "DP029"],
        "east": ["DP004", "DP010", "DP011", "DP015", "DP020", "DP021", "DP028", "DP030"],
    }
    ordered_regions = list(region_points.keys())
    observations: List[dict] = []
    obs_index = 1

    for feature in features:
        feature_id = feature.get("feature_id") or ""
        if not feature_id:
            continue

        region_index = abs(hash_string(feature_id)) % len(ordered_regions)
        primary_region = ordered_regions[region_index]
        secondary_region = ordered_regions[(region_index + 1) % len(ordered_regions)]
        primary_points = region_points[primary_region]
        secondary_points = region_points[secondary_region]
        subset_size = 6 + (abs(hash_string(feature_id + feature.get("subsection", ""))) % 3)
        selected_points = list(dict.fromkeys(primary_points[:subset_size] + secondary_points[:2]))
        attested_value = get_feature_demo_value(feature)

        for point_id in selected_points:
            observations.append(
                normalize_observation(
                    {
                        "obs_id": f"DO{obs_index:04d}",
                        "point_id": point_id,
                        "feature_id": feature_id,
                        "attested_value": attested_value,
                        "answer_type": "демо-наблюдение",
                        "source_year": str(2020 + (obs_index % 5)),
                        "collector": "Демонстрационная выборка",
                        "comment": (
                            "Учебное наблюдение для показа одного признака единым слоем "
                            "и построения предварительного ареала."
                        ),
                    }
                )
            )
            obs_index += 1
    return observations


def get_feature_demo_value(feature: dict) -> str:
    example_list = feature.get("example_list") or []
    if example_list:
        return example_list[0]
    return feature.get("feature_name") or "Признак зафиксирован"


def hash_string(value: str) -> int:
    result = 0
    for char in value:
        result = ((result * 33) + ord(char)) & 0xFFFFFFFF
    return result


def build_district_centroid_lookup(districts_geojson: Optional[dict]) -> Dict[str, Tuple[float, float]]:
    if not districts_geojson:
        return {}

    lookup: Dict[str, Tuple[float, float]] = {}
    for feature in districts_geojson.get("features", []):
        name = (feature.get("properties") or {}).get("name")
        geometry = feature.get("geometry")
        if not name or not geometry:
            continue
        centroid = geometry_centroid(geometry)
        if centroid:
            lookup[name] = centroid
    return lookup


def build_district_feature_lookup(districts_geojson: Optional[dict]) -> Dict[str, dict]:
    if not districts_geojson:
        return {}

    lookup: Dict[str, dict] = {}
    for feature in districts_geojson.get("features", []):
        name = (feature.get("properties") or {}).get("name")
        if name:
            lookup[name] = feature
    return lookup


def point_in_geometry(longitude: float, latitude: float, geometry: dict) -> bool:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []

    if geometry_type == "Polygon":
        return point_in_polygon(longitude, latitude, coordinates)
    if geometry_type == "MultiPolygon":
        return any(point_in_polygon(longitude, latitude, polygon) for polygon in coordinates)
    return False


def point_in_polygon(longitude: float, latitude: float, polygon: Sequence[Sequence[Sequence[float]]]) -> bool:
    if not polygon or not point_in_ring(longitude, latitude, polygon[0]):
        return False
    for hole in polygon[1:]:
        if point_in_ring(longitude, latitude, hole):
            return False
    return True


def point_in_ring(longitude: float, latitude: float, ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    previous_index = len(ring) - 1
    for index in range(len(ring)):
        x1, y1 = ring[index]
        x2, y2 = ring[previous_index]
        intersects = ((y1 > latitude) != (y2 > latitude)) and (
            longitude < (x2 - x1) * (latitude - y1) / ((y2 - y1) or 1e-12) + x1
        )
        if intersects:
            inside = not inside
        previous_index = index
    return inside


def geometry_bounds(geometry: dict) -> Optional[Tuple[float, float, float, float]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    points: List[Tuple[float, float]] = []

    if geometry_type == "Polygon":
        for ring in coordinates:
            points.extend((point[0], point[1]) for point in ring)
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                points.extend((point[0], point[1]) for point in ring)
    else:
        return None

    if not points:
        return None

    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return (min(longitudes), min(latitudes), max(longitudes), max(latitudes))


def geometry_representative_point(geometry: dict) -> Optional[Tuple[float, float]]:
    centroid = geometry_centroid(geometry)
    if centroid and point_in_geometry(centroid[1], centroid[0], geometry):
        return centroid

    bounds = geometry_bounds(geometry)
    if bounds is None:
        return centroid

    min_lon, min_lat, max_lon, max_lat = bounds
    fallback_lat = centroid[0] if centroid else (min_lat + max_lat) / 2
    fallback_lon = centroid[1] if centroid else (min_lon + max_lon) / 2
    best_point: Optional[Tuple[float, float]] = None
    best_score: Optional[float] = None
    steps = 9

    for row in range(steps):
        lat = min_lat + (max_lat - min_lat) * (row + 0.5) / steps
        for column in range(steps):
            lon = min_lon + (max_lon - min_lon) * (column + 0.5) / steps
            if not point_in_geometry(lon, lat, geometry):
                continue
            score = (lat - fallback_lat) ** 2 + (lon - fallback_lon) ** 2
            if best_score is None or score < best_score:
                best_score = score
                best_point = (lat, lon)

    return best_point or centroid


def geometry_centroid(geometry: dict) -> Optional[Tuple[float, float]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []

    polygons: List[List[List[float]]] = []
    if geometry_type == "Polygon":
        polygons = coordinates
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            polygons.extend(polygon)
    else:
        return None

    largest_ring: Optional[List[List[float]]] = None
    largest_area = 0.0
    for ring in polygons:
        area = abs(ring_signed_area(ring))
        if area > largest_area:
            largest_area = area
            largest_ring = ring

    if not largest_ring:
        return None

    centroid = ring_centroid(largest_ring)
    if centroid:
        return centroid

    latitudes = [point[1] for point in largest_ring]
    longitudes = [point[0] for point in largest_ring]
    return ((min(latitudes) + max(latitudes)) / 2, (min(longitudes) + max(longitudes)) / 2)


def ring_signed_area(ring: Sequence[Sequence[float]]) -> float:
    area = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def ring_centroid(ring: Sequence[Sequence[float]]) -> Optional[Tuple[float, float]]:
    area = ring_signed_area(ring)
    if area == 0:
        return None

    centroid_x = 0.0
    centroid_y = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        factor = x1 * y2 - x2 * y1
        centroid_x += (x1 + x2) * factor
        centroid_y += (y1 + y2) * factor

    centroid_x /= 6 * area
    centroid_y /= 6 * area
    return (centroid_y, centroid_x)
