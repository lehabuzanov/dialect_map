from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pandas as pd


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


def normalize_rows(rows: Iterable[dict]) -> List[dict]:
    normalized_rows: List[dict] = []
    for row in rows:
        normalized = {field: normalize_cell(row.get(field, "")) for field in EXPECTED_MAP_FIELDS}
        if any(normalized.values()):
            normalized_rows.append(normalized)
    return normalized_rows


def normalize_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_google_sheet_url(sheet_url: str) -> Tuple[str, Optional[int]]:
    parsed = urlparse(sheet_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    try:
        sheet_index = path_parts.index("d")
        spreadsheet_id = path_parts[sheet_index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("Не удалось определить идентификатор Google Sheets из ссылки.") from exc

    query = parse_qs(parsed.query)
    gid_values = query.get("gid")
    gid = int(gid_values[0]) if gid_values else None
    return spreadsheet_id, gid


def build_google_sheet_csv_url(sheet_url: str) -> str:
    spreadsheet_id, gid = parse_google_sheet_url(sheet_url)
    base_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv"
    if gid is not None:
        return f"{base_url}&gid={gid}"
    return base_url


def fetch_public_sheet_rows(sheet_url: str) -> List[dict]:
    csv_url = build_google_sheet_csv_url(sheet_url)
    with urlopen(csv_url, timeout=30) as response:
        raw_bytes = response.read()

    text = decode_remote_text(raw_bytes)
    reader = csv.DictReader(io.StringIO(text))
    return normalize_rows(reader)


def decode_remote_text(raw_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def rows_to_dataframe(rows: Sequence[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(normalize_rows(rows))
    for field in EXPECTED_MAP_FIELDS:
        if field not in frame.columns:
            frame[field] = ""
    return frame[EXPECTED_MAP_FIELDS].fillna("")


def dataframe_to_rows(frame: pd.DataFrame) -> List[dict]:
    subset = frame.copy()
    for field in EXPECTED_MAP_FIELDS:
        if field not in subset.columns:
            subset[field] = ""
    subset = subset[EXPECTED_MAP_FIELDS].fillna("")
    return normalize_rows(subset.to_dict(orient="records"))


def rows_to_csv_bytes(rows: Sequence[dict]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPECTED_MAP_FIELDS)
    writer.writeheader()
    for row in normalize_rows(rows):
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def make_rows_signature(rows: Sequence[dict]) -> str:
    payload = json.dumps(normalize_rows(rows), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def get_google_service_account_info() -> Optional[dict]:
    if "google_service_account" in os.environ:
        try:
            return json.loads(os.environ["google_service_account"])
        except json.JSONDecodeError:
            return None

    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw_json:
        return json.loads(raw_json)

    return None


def save_rows_to_google_sheet(sheet_url: str, rows: Sequence[dict], credentials_info: dict) -> None:
    import gspread
    from google.oauth2.service_account import Credentials

    spreadsheet_id, gid = parse_google_sheet_url(sheet_url)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(spreadsheet_id)

    worksheet = None
    if gid is not None:
        for candidate in spreadsheet.worksheets():
            if candidate.id == gid:
                worksheet = candidate
                break
    if worksheet is None:
        worksheet = spreadsheet.sheet1

    values = [EXPECTED_MAP_FIELDS]
    for row in normalize_rows(rows):
        values.append([row.get(field, "") for field in EXPECTED_MAP_FIELDS])

    worksheet.clear()
    worksheet.update("A1", values, value_input_option="USER_ENTERED")
