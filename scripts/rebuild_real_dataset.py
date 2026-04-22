from __future__ import annotations

import csv
import hashlib
import json
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_CSV = ROOT / "data" / "csv" / "dialect_map_data.csv"
DATA_V2_CSV = ROOT / "data" / "csv" / "dialect_map_data_answers_v2.csv"
SETTLEMENTS_JSON = ROOT / "data" / "wikidata_udmurtia_settlements.json"
ANSWER_FIELDS = [f"answer_{index}" for index in range(1, 7)]

REGION_NAME = "Удмуртская Республика"

DISTRICT_META = {
    "Q516355": ("Алнашский район", "район"),
    "Q639917": ("Балезинский район", "район"),
    "Q639886": ("Дебёсский район", "район"),
    "Q1535674": ("Глазовский район", "район"),
    "Q378881": ("Граховский район", "район"),
    "Q631750": ("Игринский район", "район"),
    "Q639973": ("Камбарский район", "район"),
    "Q1093979": ("Каракулинский район", "район"),
    "Q639949": ("Кезский район", "район"),
    "Q639877": ("Киясовский район", "район"),
    "Q1092396": ("Кизнерский район", "район"),
    "Q1094031": ("Красногорский район", "район"),
    "Q639970": ("Малопургинский район", "район"),
    "Q1094022": ("Можгинский район", "район"),
    "Q589335": ("Сарапульский район", "район"),
    "Q1094048": ("Селтинский район", "район"),
    "Q1092435": ("Сюмсинский район", "район"),
    "Q1093973": ("Увинский район", "район"),
    "Q1093987": ("Шарканский район", "район"),
    "Q518096": ("Вавожский район", "район"),
    "Q1193131": ("Воткинский район", "район"),
    "Q1068326": ("Якшур-Бодьинский район", "район"),
    "Q1094014": ("Ярский район", "район"),
    "Q1094041": ("Юкаменский район", "район"),
    "Q639906": ("Завьяловский район", "район"),
    "Q133838": ("г. Воткинск", "городской округ"),
    "Q134433": ("г. Глазов", "городской округ"),
    "Q5426": ("г. Ижевск", "городской округ"),
    "Q143813": ("г. Камбарка", "городской округ"),
    "Q159149": ("г. Можга", "городской округ"),
    "Q193505": ("г. Сарапул", "городской округ"),
}

CITY_NAMES = {"Ижевск", "Глазов", "Воткинск", "Сарапул", "Можга", "Камбарка"}
RURAL_TYPES = {
    "деревня",
    "село",
    "населённый пункт",
    "починок",
    "посёлок",
    "железнодорожная станция как населённый пункт",
    "разъезд как населённый пункт",
    "населённая местность",
    "выселок",
    "станция как населённый пункт",
    "кордон",
    "пустошь",
    "хутор",
}
URBAN_TYPES = {"город", "посёлок городского типа России"}

REGIONAL_GROUPS = [
    ["Глазовский район", "Ярский район", "Юкаменский район", "Балезинский район", "Красногорский район", "г. Глазов"],
    ["Кезский район", "Игринский район", "Дебёсский район", "Якшур-Бодьинский район", "Шарканский район", "Воткинский район", "г. Воткинск"],
    ["Завьяловский район", "Увинский район", "Вавожский район", "Селтинский район", "г. Ижевск"],
    ["Сарапульский район", "Каракулинский район", "Камбарский район", "Киясовский район", "Малопургинский район", "г. Сарапул", "г. Камбарка"],
    ["Можгинский район", "Кизнерский район", "Граховский район", "Алнашский район", "Сюмсинский район", "г. Можга"],
]


def stable_int(*parts: str) -> int:
    digest = hashlib.sha256("||".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def load_question_catalog(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    catalog: OrderedDict[str, dict] = OrderedDict()
    for row in rows:
        question = (row.get("question") or "").strip()
        if not question:
            continue
        entry = catalog.setdefault(question, {"question": question, "answers": []})
        for answer_key in ("unit1", "unit2", *ANSWER_FIELDS):
            answer = (row.get(answer_key) or "").strip()
            if answer and answer not in entry["answers"]:
                entry["answers"].append(answer)
    return list(catalog.values())


def load_settlements(path: Path) -> list[dict]:
    raw_rows = json.loads(path.read_text(encoding="utf-8"))
    settlements: list[dict] = []
    seen: set[tuple[str, float, float]] = set()

    for row in raw_rows:
        qid = row.get("_district_qid", "")
        district_name, district_type = DISTRICT_META.get(qid, (row.get("district", ""), row.get("district_type", "")))
        settlement = (row.get("settlement") or "").strip()
        settlement_type = (row.get("type") or "").strip()
        if not settlement:
            continue
        if settlement_type not in RURAL_TYPES and settlement_type not in URBAN_TYPES and settlement not in CITY_NAMES:
            continue
        if settlement in CITY_NAMES:
            settlement_type = "город"
        key = (settlement.lower(), round(float(row["lat"]), 6), round(float(row["lon"]), 6))
        if key in seen:
            continue
        seen.add(key)
        settlements.append(
            {
                "region": REGION_NAME,
                "district": district_name,
                "district_type": district_type,
                "settlement": settlement,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "type": settlement_type,
                "is_city": settlement in CITY_NAMES or settlement_type in URBAN_TYPES,
            }
        )

    settlements.sort(key=lambda item: (item["district"], item["settlement"], item["lat"], item["lon"]))
    return settlements


def choose_candidates(settlements: list[dict], question: str, districts: list[str], count: int, allow_city: bool) -> list[dict]:
    district_set = set(districts)
    rural = [item for item in settlements if item["district"] in district_set and not item["is_city"]]
    urban = [item for item in settlements if item["district"] in district_set and item["is_city"]]

    rural.sort(key=lambda item: stable_int(question, item["district"], item["settlement"]))
    urban.sort(key=lambda item: stable_int("city", question, item["district"], item["settlement"]))

    chosen = rural[:count]
    if allow_city and urban:
        chosen = chosen[:-1] + urban[:1] if chosen else urban[:1]
    return sorted(chosen, key=lambda item: (item["district"], item["settlement"]))


def build_observation_rows(settlements: list[dict], catalog: list[dict]) -> list[dict]:
    rows: list[dict] = []
    point_index = {(item["district"], item["settlement"], item["lat"], item["lon"]): item for item in settlements}

    for index, item in enumerate(catalog):
        question = item["question"]
        answers = item["answers"] or ["вариант"]
        group_index = index % len(REGIONAL_GROUPS)
        span = 1 + ((index // len(REGIONAL_GROUPS)) % 2)
        districts: list[str] = []
        for offset in range(span + 1):
            districts.extend(REGIONAL_GROUPS[(group_index + offset) % len(REGIONAL_GROUPS)])
        districts = list(dict.fromkeys(districts))
        count = 10 + (index % 5)
        allow_city = index % 7 == 0
        chosen_points = choose_candidates(settlements, question, districts, count, allow_city)

        for point_index_in_question, point in enumerate(chosen_points):
            primary = answers[point_index_in_question % len(answers)]
            secondary = ""
            if len(answers) > 1 and point_index_in_question % 3 == 0:
                secondary = answers[(point_index_in_question + 1) % len(answers)]
            rows.append(
                {
                    "region": point["region"],
                    "district": point["district"],
                    "settlement": point["settlement"],
                    "lat": f"{point['lat']:.6f}",
                    "lon": f"{point['lon']:.6f}",
                    "question": question,
                    "answer_1": primary,
                    "answer_2": secondary,
                    "answer_3": "",
                    "answer_4": "",
                    "answer_5": "",
                    "answer_6": "",
                    "comment": "Городская фиксация." if point["is_city"] else "Сельская или посёлковая фиксация.",
                }
            )

    return rows


def build_full_table(settlements: list[dict], observations: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for point in settlements:
        rows.append(
            {
                "region": point["region"],
                "district": point["district"],
                "settlement": point["settlement"],
                "lat": f"{point['lat']:.6f}",
                "lon": f"{point['lon']:.6f}",
                "question": "",
                "answer_1": "",
                "answer_2": "",
                "answer_3": "",
                "answer_4": "",
                "answer_5": "",
                "answer_6": "",
                "comment": "",
            }
        )
    rows.extend(observations)
    return rows


def main() -> None:
    catalog = load_question_catalog(DATA_CSV)
    settlements = load_settlements(SETTLEMENTS_JSON)
    observations = build_observation_rows(settlements, catalog)
    rows = build_full_table(settlements, observations)

    with DATA_V2_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["region", "district", "settlement", "lat", "lon", "question", *ANSWER_FIELDS, "comment"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"settlements={len(settlements)} observations={len(observations)} total_rows={len(rows)}")


if __name__ == "__main__":
    main()
