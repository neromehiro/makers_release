import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from spreadsheet2json import load_spreadsheet_data

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_PATH = OUTPUT_DIR / "a3_check_x.json"
FEED_URL_TEMPLATE = "https://nitter.net/{x_id}/rss"
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def load_x_ids() -> List[str]:
    """Load X(Twitter) user IDs from spreadsheet2json output."""
    data = load_spreadsheet_data(persist=False)
    raw_ids = data.get("x_id", []) if isinstance(data, dict) else []
    ids: List[str] = []
    for x_id in raw_ids:
        x_str = str(x_id).strip()
        if x_str:
            ids.append(x_str)
    return ids


def fetch_rss(x_id: str) -> bytes:
    """Fetch RSS feed bytes for a given X user via Nitter."""
    url = FEED_URL_TEMPLATE.format(x_id=x_id)
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.content


def parse_rss(xml_bytes: bytes, x_id: str) -> List[Dict[str, Any]]:
    """Parse RSS XML and return tweets for the specified x_id."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    tweets: List[Dict[str, Any]] = []
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

        tweets.append(
            {
                "x_id": x_id,
                "url": link,
                "title": title,
                "published_at": pub_dt,
            }
        )
    return tweets


def filter_recent(tweets: List[Dict[str, Any]], window_hours: int = 1) -> List[Dict[str, Any]]:
    """Return tweets published within the last window_hours."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)

    filtered: List[Dict[str, Any]] = []
    for tweet in tweets:
        pub_dt: datetime = tweet["published_at"]
        pub_dt_utc = pub_dt.astimezone(timezone.utc)
        if pub_dt_utc < window_start:
            continue

        filtered.append(
            {
                "x_id": tweet["x_id"],
                "url": tweet["url"],
                "title": tweet["title"],
                "published_at": pub_dt_utc.isoformat(),
            }
        )

    filtered.sort(key=lambda x: x["published_at"], reverse=True)
    return filtered


def check_x(window_hours: int = 1) -> Dict[str, Any]:
    """High-level entry: fetch Nitter feeds, filter recent, and return structured data."""
    x_ids = load_x_ids()
    all_tweets: List[Dict[str, Any]] = []

    for x_id in x_ids:
        try:
            xml_bytes = fetch_rss(x_id)
            all_tweets.extend(parse_rss(xml_bytes, x_id))
        except Exception:
            continue

    recent = filter_recent(all_tweets, window_hours=window_hours)
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "checked_at": now.isoformat(),
        "window_hours": window_hours,
        "target_ids": x_ids,
        "count": len(recent),
        "tweets": recent,
    }
    return payload


def write_output(data: Dict[str, Any]) -> None:
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # Skip persist on read-only filesystems (e.g., serverless)
        pass


def main():
    data = check_x(window_hours=1)
    write_output(data)
    print(f"Saved {data['count']} tweets to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
