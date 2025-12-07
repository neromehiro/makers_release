import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import requests
 

SITEMAP_URL = "https://prtimes.jp/sitemap-news.xml"
BASE_DIR = Path(__file__).resolve().parent.parent
ID_LIST_PATH = BASE_DIR / "id_list.txt"
OUTPUT_PATH = Path(__file__).resolve().parent / "a1_check_releace.json"


def load_prtimes_ids() -> List[str]:
    """Load company_id list from id_list.txt (ignores comments/blank lines)."""
    if not ID_LIST_PATH.exists():
        return []

    ids: List[str] = []
    with ID_LIST_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line.lstrip("0") or "0")
    return ids


def fetch_sitemap() -> bytes:
    """Fetch the news sitemap (contains latest press releases across PR TIMES)."""
    resp = requests.get(SITEMAP_URL, timeout=15)
    resp.raise_for_status()
    return resp.content


def parse_sitemap(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse sitemap XML and return list of releases with company_id."""
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    root = ET.fromstring(xml_bytes)
    releases: List[Dict[str, Any]] = []
    pattern = re.compile(r"/p/(\d+)\.(\d+)\.html")

    for url_node in root.findall("sm:url", ns):
        loc_el = url_node.find("sm:loc", ns)
        news_el = url_node.find("news:news", ns)
        if loc_el is None or news_el is None:
            continue

        loc = (loc_el.text or "").strip()
        m = pattern.search(loc)
        if not m:
            continue

        company_id = m.group(2).lstrip("0") or "0"
        pub_date_el = news_el.find("news:publication_date", ns)
        title_el = news_el.find("news:title", ns)
        if pub_date_el is None:
            continue

        pub_raw = (pub_date_el.text or "").strip()
        try:
            published_at = datetime.fromisoformat(pub_raw)
        except ValueError:
            continue

        releases.append(
            {
                "company_id": company_id,
                "url": loc,
                "title": (title_el.text or "").strip() if title_el is not None else "",
                "published_at": published_at,
            }
        )
    return releases


def filter_recent_releases(
    releases: List[Dict[str, Any]],
    target_ids: List[str],
    window_hours: int = 1,
) -> List[Dict[str, Any]]:
    """Filter releases to target company IDs within the last window_hours."""
    target_set = set(target_ids)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    filtered: List[Dict[str, Any]] = []

    for r in releases:
        cid = r["company_id"]
        pub_dt: datetime = r["published_at"]
        pub_dt_utc = pub_dt.astimezone(timezone.utc)

        if cid not in target_set:
            continue
        if pub_dt_utc < window_start:
            continue

        filtered.append(
            {
                "company_id": cid,
                "url": r["url"],
                "title": r["title"],
                "published_at": pub_dt_utc.isoformat(),
            }
        )

    filtered.sort(key=lambda x: x["published_at"], reverse=True)
    return filtered


def check_releases(window_hours: int = 1) -> Dict[str, Any]:
    """High-level entry: fetch sitemap, filter, and return structured data."""
    ids = load_prtimes_ids()
    xml_bytes = fetch_sitemap()
    releases = parse_sitemap(xml_bytes)
    recent = filter_recent_releases(releases, ids, window_hours=window_hours)

    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "checked_at": now.isoformat(),
        "window_hours": window_hours,
        "target_ids": ids,
        "count": len(recent),
        "releases": recent,
    }
    return payload


def write_output(data: Dict[str, Any]) -> None:
    OUTPUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    data = check_releases(window_hours=1)
    write_output(data)
    print(f"Saved {data['count']} releases to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
