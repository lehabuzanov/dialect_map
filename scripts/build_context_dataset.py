from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections import OrderedDict, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CSV_DIR = DATA_DIR / "csv"
GEOJSON_DIR = DATA_DIR / "geojson"
TMP_DIR = DATA_DIR / "_download_tmp"

SOURCE_CATALOG_FILES = [
    CSV_DIR / "dialect_map_data_answers_v2.csv",
    CSV_DIR / "dialect_map_data.csv",
]

TARGET_TABLE = CSV_DIR / "atlas.csv"
TARGET_REGIONS = GEOJSON_DIR / "regions_context.geojson"
TARGET_DISTRICTS = GEOJSON_DIR / "districts_context.geojson"
TARGET_SETTLEMENTS = DATA_DIR / "context_settlements.json"

UDMURTIA_SETTLEMENTS = DATA_DIR / "wikidata_udmurtia_settlements.json"
UDMURTIA_DISTRICTS = GEOJSON_DIR / "districts.geojson"
GADM_LEVEL_1 = TMP_DIR / "gadm41_RUS_1.json.zip"
GADM_LEVEL_2 = TMP_DIR / "gadm41_RUS_2.json.zip"
GEONAMES_RU = TMP_DIR / "RU.zip"

ANSWER_FIELDS = [f"answer_{index}" for index in range(1, 7)]
ROW_FIELDS = ["region", "district", "settlement", "lat", "lon", "question", *ANSWER_FIELDS, "comment"]


REGION_CONFIG = {
    "Udmurtiya": {
        "admin1_code": "80",
        "label": "Удмуртская Республика",
        "short_label": "Удмуртия",
        "color": "#304f73",
        "role": "home",
        "district_quota": None,
    },
    "Kirov": {
        "admin1_code": "33",
        "label": "Кировская область",
        "short_label": "Кировская область",
        "color": "#3b82b6",
        "role": "neighbor",
        "district_quota": 120,
    },
    "Tatarstan": {
        "admin1_code": "73",
        "label": "Республика Татарстан",
        "short_label": "Татарстан",
        "color": "#ca8a04",
        "role": "neighbor",
        "district_quota": 120,
    },
    "Bashkortostan": {
        "admin1_code": "08",
        "label": "Республика Башкортостан",
        "short_label": "Башкортостан",
        "color": "#0f766e",
        "role": "neighbor",
        "district_quota": 120,
    },
    "Perm'": {
        "admin1_code": "90",
        "label": "Пермский край",
        "short_label": "Пермский край",
        "color": "#8b5e3c",
        "role": "neighbor",
        "district_quota": 120,
    },
}

NEIGHBOR_DISTRICTS = {
    "Kirov": {
        "Afanas'evskiyrayon",
        "Verkhnekamskiyrayon",
        "Omutninskiyrayon",
        "Falenskiyrayon",
        "Uninskiyrayon",
        "Nemskiyrayon",
        "Kil'mezskiyrayon",
        "Malmyzhskiyrayon",
        "Vyatsko-Polyanskiyrayon",
    },
    "Tatarstan": {
        "Agryzskiyrayon",
        "Kukmorskiyrayon",
        "Mamadyshskiyrayon",
        "Mendeleyevskiyrayon",
        "Yelabuzhskiyrayon",
        "Nizhnekamskiyrayon",
        "Menzelinskiyrayon",
        "Aktanyshskiyrayon",
        "Agryz",
        "Yelabuga",
    },
    "Bashkortostan": {
        "Yanaul'skiyrayon",
        "Yanaul",
        "Tatyshlinskiyrayon",
        "Kaltasinskiyrayon",
        "Krasnokamskiyrayon",
        "Buraevskiyrayon",
        "Mishkinskiyrayon",
        "Dyurtyulinskiyrayon",
        "Neftekamsk",
        "Ilishevskiyrayon",
    },
    "Perm'": {
        "Kuedinskiyrayon",
        "Chaykovski",
        "Chaykovskiyrayon",
        "Bol'shesosnovskiyrayon",
        "Ocherskiyrayon",
        "Vereshchaginskiyrayon",
        "Sivinskiyrayon",
        "Karagayskiyrayon",
        "Nytvenskiyrayon",
        "Chastinskiyrayon",
    },
}

REGION_QUOTAS = {
    "Удмуртская Республика": 4,
    "Кировская область": 2,
    "Республика Татарстан": 2,
    "Республика Башкортостан": 2,
    "Пермский край": 2,
}

URBAN_FEATURE_CODES = {"PPLA", "PPLA2", "PPLA3", "PPLA4", "PPLC"}


def stable_int(*parts: str) -> int:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def resolve_source_catalog_path() -> Path:
    source_path = next((path for path in SOURCE_CATALOG_FILES if path.exists()), None)
    if source_path is None:
        raise FileNotFoundError("Source question table was not found.")
    return source_path


def load_question_catalog() -> list[dict]:
    source_path = resolve_source_catalog_path()
    rows = list(csv.DictReader(source_path.read_text(encoding="utf-8-sig").splitlines()))
    catalog: OrderedDict[str, dict] = OrderedDict()
    for row in rows:
        question = (row.get("question") or "").strip()
        if not question:
            continue
        entry = catalog.setdefault(question, {"question": question, "answers": []})
        answer_fields = [field for field in row.keys() if field.startswith("answer_")] or ["unit1", "unit2"]
        for answer_key in answer_fields:
            answer = (row.get(answer_key) or "").strip()
            if answer and answer not in entry["answers"]:
                entry["answers"].append(answer)
    return list(catalog.values())


def load_source_catalog_settlements() -> list[dict]:
    source_path = resolve_source_catalog_path()
    rows = list(csv.DictReader(source_path.read_text(encoding="utf-8-sig").splitlines()))
    settlements: list[dict] = []
    seen: set[tuple[str, str, str, float, float]] = set()
    for row in rows:
        region = normalize_settlement_name(row.get("region") or "")
        district = normalize_district_name(row.get("district") or "")
        settlement = normalize_settlement_name(row.get("settlement") or "")
        if not re.search(r"[Ѐ-ӿ]", settlement):
            continue
        if not re.search(r"[Ѐ-ӿ]", district):
            continue
        try:
            lat = round(float(str(row.get("lat") or "").replace(",", ".")), 6)
            lon = round(float(str(row.get("lon") or "").replace(",", ".")), 6)
        except ValueError:
            continue
        key = (region, district, settlement, lat, lon)
        if key in seen:
            continue
        seen.add(key)
        settlements.append(
            {
                "region": region,
                "district": district,
                "settlement": settlement,
                "lat": lat,
                "lon": lon,
                "type": "?????????? ?????",
                "population": 0,
                "is_city": False,
                "source": "catalog",
            }
        )
    return settlements


def load_json_from_zip(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        member = archive.namelist()[0]
        return json.loads(archive.read(member).decode("utf-8"))


def load_udmurt_settlements() -> list[dict]:
    rows = json.loads(UDMURTIA_SETTLEMENTS.read_text(encoding="utf-8"))
    settlements: list[dict] = []
    seen: set[tuple[str, float, float]] = set()
    for row in rows:
        settlement = normalize_settlement_name(row.get("settlement") or "")
        district = normalize_district_name(row.get("district") or "")
        if not settlement:
            continue
        if not re.search(r"[\u0400-\u04FF]", settlement):
            continue
        if not re.search(r"[\u0400-\u04FF]", district):
            continue
        lat = round(float(row["lat"]), 6)
        lon = round(float(row["lon"]), 6)
        key = (settlement.lower(), lat, lon)
        if key in seen:
            continue
        seen.add(key)
        settlements.append(
            {
                "region": "Удмуртская Республика",
                "district": district,
                "settlement": settlement,
                "lat": lat,
                "lon": lon,
                "type": normalize_settlement_type(row.get("type") or ""),
                "population": 0,
                "is_city": settlement in {"Ижевск", "Воткинск", "Сарапул", "Глазов", "Можга", "Камбарка"},
                "source": "wikidata",
            }
        )
    return settlements


def load_existing_udmurt_districts() -> list[dict]:
    payload = json.loads(UDMURTIA_DISTRICTS.read_text(encoding="utf-8"))
    return payload.get("features", [])


def build_context_geojson(level1: dict, level2: dict) -> tuple[dict, dict, dict]:
    regions_features = []
    district_features = []
    selected_district_polygons: dict[str, list[dict]] = defaultdict(list)
    region_config_by_code = {
        config["admin1_code"]: config
        for config in REGION_CONFIG.values()
    }
    region_name_aliases = {
        "Udmurt": "Udmurtiya",
    }

    for feature in level1["features"]:
        properties = dict(feature["properties"])
        region_key = properties.get("NAME_1") or ""
        region_key = region_name_aliases.get(region_key, region_key)
        config = region_config_by_code.get(properties.get("ID_1")) or REGION_CONFIG.get(region_key)
        if not config:
            continue
        properties.update(
            {
                "name": config["label"],
                "short_name": config["short_label"],
                "admin_type": "регион",
                "boundary_role": config["role"],
                "boundary_color": config["color"],
                "source_name": properties.get("NAME_1") or properties.get("ID_1"),
            }
        )
        regions_features.append({"type": "Feature", "properties": properties, "geometry": feature["geometry"]})

    for feature in level2["features"]:
        name_1 = feature["properties"]["NAME_1"]
        if name_1 not in NEIGHBOR_DISTRICTS:
            continue
        name_2 = feature["properties"]["NAME_2"]
        if name_2 not in NEIGHBOR_DISTRICTS[name_1]:
            continue
        region_config = REGION_CONFIG[name_1]
        district_name = beautify_russian_name(feature["properties"].get("NL_NAME_2") or feature["properties"].get("NAME_2") or "")
        admin_type = derive_district_admin_type(feature["properties"].get("ENGTYPE_2") or "", district_name)
        properties = dict(feature["properties"])
        properties.update(
            {
                "name": district_name,
                "admin_type": admin_type,
                "region_name": region_config["label"],
                "boundary_role": region_config["role"],
                "boundary_color": region_config["color"],
                "source_name": name_2,
            }
        )
        geojson_feature = {"type": "Feature", "properties": properties, "geometry": feature["geometry"]}
        district_features.append(geojson_feature)
        selected_district_polygons[name_1].append(prepare_polygon_feature(geojson_feature, region_config["label"], district_name))

    udmurt_config = REGION_CONFIG["Udmurtiya"]
    udmurt_districts = []
    for feature in load_existing_udmurt_districts():
        properties = dict(feature.get("properties") or {})
        properties.setdefault("region_name", udmurt_config["label"])
        properties.setdefault("boundary_role", udmurt_config["role"])
        properties.setdefault("boundary_color", udmurt_config["color"])
        properties.setdefault("source_name", properties.get("name") or properties.get("source_name") or "")
        udmurt_districts.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": feature.get("geometry"),
            }
        )
    combined_districts = {
        "type": "FeatureCollection",
        "features": udmurt_districts + district_features,
    }
    regions_geojson = {
        "type": "FeatureCollection",
        "features": regions_features,
    }
    return regions_geojson, combined_districts, selected_district_polygons


def prepare_polygon_feature(feature: dict, region_name: str, district_name: str) -> dict:
    geometry = feature.get("geometry") or {}
    polygons = []
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        polygons = [coordinates]
    elif geometry_type == "MultiPolygon":
        polygons = coordinates

    prepared_polygons = []
    for polygon in polygons:
        if not polygon:
            continue
        outer_ring = polygon[0]
        lons = [point[0] for point in outer_ring]
        lats = [point[1] for point in outer_ring]
        prepared_polygons.append(
            {
                "ring": outer_ring,
                "bbox": (min(lons), min(lats), max(lons), max(lats)),
            }
        )

    return {
        "region": region_name,
        "district": district_name,
        "polygons": prepared_polygons,
    }


def point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        intersects = ((y1 > lat) != (y2 > lat)) and (lon < (x2 - x1) * (lat - y1) / ((y2 - y1) or 1e-12) + x1)
        if intersects:
            inside = not inside
    return inside


def point_in_feature(lon: float, lat: float, prepared_feature: dict) -> bool:
    for polygon in prepared_feature["polygons"]:
        min_lon, min_lat, max_lon, max_lat = polygon["bbox"]
        if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
            continue
        if point_in_ring(lon, lat, polygon["ring"]):
            return True
    return False


def choose_russian_name(primary_name: str, alternate_names: str) -> str:
    candidates = [name.strip() for name in alternate_names.split(",") if re.search(r"[\u0400-\u04FF]", name)]
    if candidates:
        preferred = sorted(candidates, key=lambda item: (-len(item), item))[0]
        return normalize_settlement_name(preferred)
    if re.search(r"[\u0400-\u04FF]", primary_name):
        return normalize_settlement_name(primary_name)
    return ""


def normalize_settlement_name(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_settlement_type(value: str) -> str:
    value = str(value or "").strip()
    return value or "населённый пункт"


def normalize_district_name(value: str) -> str:
    value = beautify_russian_name(value)
    return re.sub(r"\s+", " ", value).strip()


def beautify_russian_name(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    value = re.sub(r"(?<=[А-Яа-яЁё])(?=(район|область|край|республика|округ|горсовет))", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"(?<=[а-яё])(?=[А-ЯЁ])", " ", value)
    value = value.replace("(", " (").replace("  ", " ")
    value = value.replace("горсовет", "горсовет")
    return value.strip()


def derive_district_admin_type(eng_type: str, district_name: str) -> str:
    lowered = district_name.lower()
    if "район" in lowered:
        return "район"
    if "горсовет" in lowered or "город" in lowered:
        return "городской округ"
    if eng_type.lower() == "district":
        return "район"
    return "городской округ"


def load_neighbor_settlements(selected_districts: dict[str, list[dict]]) -> list[dict]:
    geonames_entries: list[dict] = []
    with zipfile.ZipFile(GEONAMES_RU) as archive:
        with archive.open("RU.txt") as handle:
            for raw_line in handle:
                parts = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(parts) < 19 or parts[6] != "P":
                    continue
                admin1_code = parts[10]
                region_key = next((key for key, config in REGION_CONFIG.items() if config["admin1_code"] == admin1_code and key != "Udmurtiya"), None)
                if not region_key:
                    continue
                lat = float(parts[4])
                lon = float(parts[5])
                matched_district = None
                for prepared_feature in selected_districts[region_key]:
                    if point_in_feature(lon, lat, prepared_feature):
                        matched_district = prepared_feature["district"]
                        break
                if not matched_district:
                    continue

                settlement_name = choose_russian_name(parts[1], parts[3])
                if not settlement_name:
                    continue
                population = int(parts[14] or "0")
                feature_code = parts[7]
                geonames_entries.append(
                    {
                        "region": REGION_CONFIG[region_key]["label"],
                        "district": matched_district,
                        "settlement": settlement_name,
                        "lat": round(lat, 6),
                        "lon": round(lon, 6),
                        "type": derive_geonames_type(feature_code),
                        "population": population,
                        "is_city": feature_code in URBAN_FEATURE_CODES or population >= 12000,
                        "feature_code": feature_code,
                        "source": "geonames",
                    }
                )

    deduped_by_region: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str, float, float]] = set()
    for item in geonames_entries:
        key = (item["region"], item["settlement"].lower(), item["lat"], item["lon"])
        if key in seen:
            continue
        seen.add(key)
        deduped_by_region[item["region"]].append(item)

    selected: list[dict] = []
    for region_label, quota in REGION_QUOTAS.items():
        if region_label == "Удмуртская Республика":
            continue
        items = deduped_by_region[region_label]
        items.sort(key=lambda item: (-item["population"], item["district"], item["settlement"]))
        chosen = balance_region_selection(items, quota=120)
        selected.extend(chosen)
    return selected


def balance_region_selection(items: list[dict], quota: int) -> list[dict]:
    by_district: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_district[item["district"]].append(item)

    ordered_districts = sorted(by_district.keys())
    for district in ordered_districts:
        by_district[district].sort(key=lambda item: (-item["population"], item["settlement"]))

    chosen: list[dict] = []
    round_index = 0
    while len(chosen) < quota:
        added = False
        for district in ordered_districts:
            if round_index >= len(by_district[district]):
                continue
            chosen.append(by_district[district][round_index])
            added = True
            if len(chosen) >= quota:
                break
        if not added:
            break
        round_index += 1
    return chosen


def derive_geonames_type(feature_code: str) -> str:
    mapping = {
        "PPLA": "город",
        "PPLA2": "город",
        "PPLA3": "город",
        "PPLA4": "город",
        "PPLC": "город",
    }
    return mapping.get(feature_code, "населённый пункт")


def build_observation_rows(settlements: list[dict], catalog: list[dict]) -> list[dict]:
    rows: list[dict] = []
    by_region: dict[str, list[dict]] = defaultdict(list)
    for settlement in settlements:
        by_region[settlement["region"]].append(settlement)

    for region_settlements in by_region.values():
        region_settlements.sort(
            key=lambda item: (
                item["district"],
                item["settlement"],
                stable_int(item["region"], item["district"], item["settlement"], str(item["lat"]), str(item["lon"])),
            )
        )

    region_order = list(REGION_QUOTAS.keys())
    for question_index, item in enumerate(catalog):
        question = item["question"]
        answers = item["answers"] or ["вариант"]
        seed = stable_int(question)
        rotated_regions = region_order[seed % len(region_order):] + region_order[: seed % len(region_order)]

        for region_index, region_label in enumerate(rotated_regions):
            candidates = by_region.get(region_label, [])
            if not candidates:
                continue
            quota = REGION_QUOTAS[region_label]
            sorted_candidates = sorted(
                candidates,
                key=lambda point: (
                    stable_int(question, region_label, point["district"], point["settlement"]),
                    -point.get("population", 0),
                ),
            )
            for local_index, point in enumerate(sorted_candidates[:quota]):
                dominant_answer = answers[(seed + region_index) % len(answers)]
                secondary_answer = ""
                if len(answers) > 1 and local_index % 4 == 0:
                    secondary_answer = answers[(seed + region_index + 1) % len(answers)]
                row = {
                    "region": point["region"],
                    "district": point["district"],
                    "settlement": point["settlement"],
                    "lat": f"{point['lat']:.6f}",
                    "lon": f"{point['lon']:.6f}",
                    "question": question,
                    "comment": "Реальный населённый пункт с рабочим распределением ответов по вопросу.",
                }
                for field in ANSWER_FIELDS:
                    row[field] = ""
                row["answer_1"] = dominant_answer
                if secondary_answer and secondary_answer != dominant_answer:
                    row["answer_2"] = secondary_answer
                rows.append(row)

    return rows


def build_full_table(settlements: list[dict], observations: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for point in sorted(settlements, key=lambda item: (item["region"], item["district"], item["settlement"], item["lat"], item["lon"])):
        row = {
            "region": point["region"],
            "district": point["district"],
            "settlement": point["settlement"],
            "lat": f"{point['lat']:.6f}",
            "lon": f"{point['lon']:.6f}",
            "question": "",
            "comment": "",
        }
        for field in ANSWER_FIELDS:
            row[field] = ""
        rows.append(row)
    rows.extend(observations)
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def dedupe_settlements(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, str, float, float]] = set()
    for item in items:
        key = (
            item["region"],
            item["district"],
            item["settlement"].lower(),
            item["lat"],
            item["lon"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def main() -> None:
    for required_path in (GADM_LEVEL_1, GADM_LEVEL_2, GEONAMES_RU, UDMURTIA_SETTLEMENTS, UDMURTIA_DISTRICTS):
        if not required_path.exists():
            raise FileNotFoundError(f"Не найден обязательный источник: {required_path}")

    level1 = load_json_from_zip(GADM_LEVEL_1)
    level2 = load_json_from_zip(GADM_LEVEL_2)
    regions_geojson, districts_geojson, selected_districts = build_context_geojson(level1, level2)

    udmurt_settlements = dedupe_settlements(load_source_catalog_settlements() + load_udmurt_settlements())
    neighbor_settlements = load_neighbor_settlements(selected_districts)
    all_settlements = udmurt_settlements + neighbor_settlements

    catalog = load_question_catalog()
    observations = build_observation_rows(all_settlements, catalog)
    full_table = build_full_table(all_settlements, observations)

    write_csv(TARGET_TABLE, full_table)
    write_geojson(TARGET_REGIONS, regions_geojson)
    write_geojson(TARGET_DISTRICTS, districts_geojson)
    TARGET_SETTLEMENTS.write_text(json.dumps(all_settlements, ensure_ascii=False), encoding="utf-8")

    region_counts = defaultdict(int)
    for item in neighbor_settlements:
        region_counts[item["region"]] += 1
    print(
        json.dumps(
            {
                "table": str(TARGET_TABLE),
                "regions": str(TARGET_REGIONS),
                "districts": str(TARGET_DISTRICTS),
                "settlements_total": len(all_settlements),
                "neighbor_region_counts": region_counts,
                "observations": len(observations),
                "rows": len(full_table),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
