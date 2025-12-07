import os
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import re

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

import api.a2_check_note as note_checker
import api.a1_check_releace as pr_checker
from spreadsheet2json import load_spreadsheet_data


def _load_env_file():
    """
    Minimal .env loader for local runs (KEY="value" lines only).
    Safe to call in any environment.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    with env_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_env_file()

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def send_to_slack(
    text: str,
    *,
    enable_unfurl: bool = True,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> requests.Response:
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")

    payload = {
        "text": text,
        "unfurl_links": enable_unfurl,
        "unfurl_media": enable_unfurl,
    }
    if blocks:
        payload["blocks"] = blocks

    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()
    return resp


def _extract_meta(content: str, pattern: str) -> str:
    """Return first capture from regex pattern (dotall)."""
    m = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
    return (m.group(1).strip() if m else "").replace("\n", " ").strip()


def fetch_preview(url: str) -> Dict[str, str]:
    """
    Fetch page and extract og:title / og:description / title.
    Best-effort; returns empty strings on failure.
    """
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
        html = resp.text
    except Exception:
        return {"title": "", "description": ""}

    og_title = _extract_meta(
        html, r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']'
    )
    og_desc = _extract_meta(
        html, r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']'
    )
    og_image = _extract_meta(
        html, r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']'
    )
    title_tag = _extract_meta(html, r"<title[^>]*>(.*?)</title>")

    title = og_title or title_tag
    description = og_desc
    return {"title": title, "description": description, "image": og_image}


def _source_label(url: str) -> str:
    if "note.com" in url:
        return "note（ノート）"
    if "prtimes.jp" in url:
        return "PR TIMES"
    return "update"


def _source_icon(url: str) -> str:
    if "note.com" in url:
        return "https://play-lh.googleusercontent.com/Jcdw4nXOdeg3pMPJldirClrj__oBd-UVZPehnb9Zn5MtWvWCQivgLqJ1mux0JjyxvA"
    if "prtimes.jp" in url:
        return "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTj6jiPk40UN8Vih6Vtaqv0DiIIF3ZUXWms1g&s"
    return ""


def send_with_preview(url: str) -> requests.Response:
    """Send a Slack message with manual preview via blocks."""
    meta = fetch_preview(url)
    title = meta.get("title") or url
    description = meta.get("description") or ""
    image = meta.get("image") or ""

    if len(description) > 500:
        description = description[:500] + "…"

    label = _source_label(url)
    quoted_lines = []
    quoted_lines.append(f"> {label}")
    quoted_lines.append(f"> {url}")
    quoted_lines.append(f"> *{title}*")
    if description:
        quoted_lines.append(f"> {description}")

    accessory = (
        {"type": "image", "image_url": image, "alt_text": title or "preview"} if image else None
    )

    blocks: List[Dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(quoted_lines)},
            **({"accessory": accessory} if accessory else {}),
        }
    ]

    fallback_text = f"{label}: {title}"
    return send_to_slack(fallback_text, enable_unfurl=False, blocks=blocks)


def run_notification(window_hours: int = 1) -> dict:
    """
    Execute release/note checks and post results to Slack.
    Returns a summary dict for logging/HTTP responses.
    """
    load_spreadsheet_data(force_refresh=True)

    pr_data = pr_checker.check_releases(window_hours=window_hours)
    pr_checker.write_output(pr_data)

    note_data = note_checker.check_notes(window_hours=window_hours)
    note_checker.write_output(note_data)

    pr_urls = [r.get("url", "") for r in pr_data.get("releases", []) if r.get("url")]
    note_urls = [a.get("url", "") for a in note_data.get("articles", []) if a.get("url")]

    responses = []
    for url in pr_urls:
        responses.append(send_with_preview(url))
    for url in note_urls:
        responses.append(send_with_preview(url))

    if not pr_urls and not note_urls:
        responses.append(send_to_slack("今回はありません"))

    summary = {
        "pr_count": len(pr_urls),
        "note_count": len(note_urls),
        "messages_sent": len(responses),
    }
    return summary


def main():
    summary = run_notification(window_hours=1)
    print(
        f"Slack posted: pr_count={summary['pr_count']}, "
        f"note_count={summary['note_count']}, "
        f"messages_sent={summary['messages_sent']}"
    )


def handler(request) -> Dict[str, Any]:
    """
    Vercel Python entrypoint to trigger the notification run via HTTP.
    """
    try:
        summary = run_notification(window_hours=1)
        body = {"ok": True, **summary}
        status_code = 200
    except requests.HTTPError as exc:
        body = {"ok": False, "error": f"Slack HTTP error: {exc}"}
        status_code = 502
    except Exception as exc:
        body = {"ok": False, "error": str(exc)}
        status_code = 500

    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


if __name__ == "__main__":
    main()
