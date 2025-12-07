import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
ID_LIST_PATH = BASE_DIR / "note_id_list.txt"
OUTPUT_PATH = Path(__file__).resolve().parent / "a2_check_note.py.json"
FEED_URL_TEMPLATE = "https://note.com/{note_id}/rss"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def load_note_ids() -> List[str]:
    """Load note user IDs from note_id_list.txt, ignoring blanks/comments."""
    if not ID_LIST_PATH.exists():
        return []

    ids: List[str] = []
    with ID_LIST_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line)
    return ids


def fetch_rss(note_id: str) -> bytes:
    """Fetch RSS feed bytes for a given note user."""
    url = FEED_URL_TEMPLATE.format(note_id=note_id)
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.content


def parse_rss(xml_bytes: bytes, note_id: str) -> List[Dict[str, Any]]:
    """Parse RSS XML and return articles for the specified note_id."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    items: List[Dict[str, Any]] = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        if not link or not pub_raw:
            continue

        try:
            pub_dt = parsedate_to_datetime(pub_raw)
        except (TypeError, ValueError):
            continue

        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)

        items.append(
            {
                "note_id": note_id,
                "url": link,
                "title": title,
                "published_at": pub_dt,
            }
        )
    return items


def filter_recent(articles: List[Dict[str, Any]], window_hours: int = 1) -> List[Dict[str, Any]]:
    """Return articles published within the last window_hours."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    filtered: List[Dict[str, Any]] = []
    for article in articles:
        pub_dt: datetime = article["published_at"]
        pub_dt_utc = pub_dt.astimezone(timezone.utc)
        if pub_dt_utc < window_start:
            continue

        filtered.append(
            {
                "note_id": article["note_id"],
                "url": article["url"],
                "title": article["title"],
                "published_at": pub_dt_utc.isoformat(),
            }
        )

    filtered.sort(key=lambda x: x["published_at"], reverse=True)
    return filtered


def check_notes(window_hours: int = 1) -> Dict[str, Any]:
    """High-level entry: fetch RSS feeds, filter recent, and return structured data."""
    note_ids = load_note_ids()
    all_articles: List[Dict[str, Any]] = []

    for note_id in note_ids:
        try:
            xml_bytes = fetch_rss(note_id)
            all_articles.extend(parse_rss(xml_bytes, note_id))
        except Exception:
            continue

    recent = filter_recent(all_articles, window_hours=window_hours)
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "checked_at": now.isoformat(),
        "window_hours": window_hours,
        "target_ids": note_ids,
        "count": len(recent),
        "articles": recent,
    }
    return payload


def write_output(data: Dict[str, Any]) -> None:
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    data = check_notes(window_hours=1)
    write_output(data)
    print(f"Saved {data['count']} articles to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
