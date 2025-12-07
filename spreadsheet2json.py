"""
Fetches public Google Sheet data and writes prtimes_id / note_id lists to JSON.

The target sheet is shared read-only, so we can download it as CSV via the
`export?format=csv` endpoint. IDs marked as 'なし' or left blank are skipped.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List, Mapping
from urllib.parse import urlparse

import requests


SHEET_ID = "16zcRbmvBEdkWDARh-OZ_r8b-ucnKoFKQNLp9nF3EV4k"
SHEET_GID = "0"
CSV_URL = (
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"
)
OUTPUT_PATH = Path("spreadsheet2json.json")


def _dedupe_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    unique = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _is_missing(value: str) -> bool:
    normalized = value.replace("　", "").strip()
    return bool(
        not normalized
        or normalized in {"なし", "ナシ", "無し"}
        or normalized.startswith(("なし", "ナシ", "無し"))
    )


def _normalize_note_id(value: str) -> str:
    """Return just the note username/slug from a URL or raw value."""
    raw = value.strip()
    if not raw:
        return ""

    # Accept URLs such as https://note.com/username or note.com/@username
    if "note.com" in raw or "://" in raw:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        path = parsed.path.strip("/")
        if not path:
            return ""
        raw = path.split("/")[0]

    # Strip leading @ if present (note profile pages sometimes include it)
    return raw.lstrip("@")


def fetch_sheet_csv() -> str:
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def parse_ids(csv_text: str) -> dict:
    prtimes_ids = []
    note_ids = []
    x_ids = []

    reader = csv.DictReader(csv_text.splitlines())
    for row in reader:
        prtimes_value = (row.get("prtimes_id") or "").strip()
        note_value = (row.get("note_id") or "").strip()
        x_value = (row.get("x_id") or "").strip()

        if not _is_missing(prtimes_value):
            prtimes_ids.append(prtimes_value)
        if not _is_missing(note_value):
            normalized = _normalize_note_id(note_value)
            if normalized:
                note_ids.append(normalized)
        if not _is_missing(x_value):
            x_ids.append(x_value)

    return {
        "prtimes_id": _dedupe_preserve_order(prtimes_ids),
        "note_id": _dedupe_preserve_order(note_ids),
        "x_id": _dedupe_preserve_order(x_ids),
    }


def write_json(data: dict) -> None:
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def load_spreadsheet_data(
    force_refresh: bool = False, *, persist: bool = True
) -> Mapping[str, List[str]]:
    """
    Return parsed sheet data, optionally re-fetching the latest CSV.

    Falls back to re-fetching if the on-disk JSON is missing or invalid.
    When persist=False (e.g., API on read-only FS), skip writing the JSON cache.
    """
    if not force_refresh and OUTPUT_PATH.exists():
        try:
            return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    csv_text = fetch_sheet_csv()
    data = parse_ids(csv_text)
    if persist:
        write_json(data)
    return data


def main() -> None:
    csv_text = fetch_sheet_csv()
    data = parse_ids(csv_text)
    write_json(data)


if __name__ == "__main__":
    main()
