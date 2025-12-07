import os
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import re
from http.server import BaseHTTPRequestHandler

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

import api.a2_check_note as note_checker
import api.a1_check_releace as pr_checker
from spreadsheet2json import load_spreadsheet_data


def _build_name_index(sheet: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Create lookup tables to resolve names by prtimes_id / note_id / x_id."""
    by_name = sheet.get("by_name") if isinstance(sheet, dict) else {}
    pr_by_id: Dict[str, str] = {}
    note_by_id: Dict[str, str] = {}
    x_by_id: Dict[str, str] = {}
    if not isinstance(by_name, dict):
        return {"pr": pr_by_id, "note": note_by_id, "x": x_by_id}

    for name, ids in by_name.items():
        if not isinstance(ids, dict):
            continue
        pr_id = str(ids.get("prtimes_id", "")).strip()
        if pr_id:
            pr_by_id[pr_id.lstrip("0") or "0"] = name

        note_id = str(ids.get("note_id", "")).strip()
        if note_id:
            note_by_id[note_id] = name

        x_id = str(ids.get("x_id", "")).strip()
        if x_id:
            x_by_id[x_id] = name

    return {"pr": pr_by_id, "note": note_by_id, "x": x_by_id}


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


def send_with_preview(url: str, *, name: str | None = None) -> requests.Response:
    """Send a Slack message with manual preview via blocks."""
    meta = fetch_preview(url)
    title = meta.get("title") or url
    description = meta.get("description") or ""
    image = meta.get("image") or ""

    if len(description) > 500:
        description = description[:500] + "…"

    label = _source_label(url)
    quoted_lines = []
    label_text = f"{label} - {name}" if name else label
    quoted_lines.append(f"> {label_text}")
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

    fallback_text = f"{name} | {label}: {title}" if name else f"{label}: {title}"
    return send_to_slack(fallback_text, enable_unfurl=False, blocks=blocks)


def run_notification(window_hours: int = 1, *, persist_cache: bool = True) -> dict:
    """
    Execute release/note checks and post results to Slack.
    Returns a summary dict for logging/HTTP responses.
    """
    sheet_data = load_spreadsheet_data(force_refresh=True, persist=persist_cache)
    name_index = _build_name_index(sheet_data)

    pr_data = pr_checker.check_releases(window_hours=window_hours)
    pr_checker.write_output(pr_data)

    note_data = note_checker.check_notes(window_hours=window_hours)
    note_checker.write_output(note_data)

    pr_entries = [
        (r.get("url", ""), name_index["pr"].get(r.get("company_id", "")))
        for r in pr_data.get("releases", [])
        if r.get("url")
    ]
    note_entries = [
        (a.get("url", ""), name_index["note"].get(a.get("note_id", "")))
        for a in note_data.get("articles", [])
        if a.get("url")
    ]

    responses = []
    for url, name in pr_entries:
        responses.append(send_with_preview(url, name=name))
    for url, name in note_entries:
        responses.append(send_with_preview(url, name=name))

    # When nothing new, don't post anything.

    summary = {
        "pr_count": len(pr_entries),
        "note_count": len(note_entries),
        "messages_sent": len(responses),
        "pr_ids": pr_data.get("target_ids", []),
        "note_ids": note_data.get("target_ids", []),
    }
    return summary


def main():
    summary = run_notification(window_hours=1)
    print(
        f"Slack posted: pr_count={summary['pr_count']}, "
        f"note_count={summary['note_count']}, "
        f"messages_sent={summary['messages_sent']}"
    )


def build_response() -> Dict[str, Any]:
    """Shared HTTP response builder for serverless/handler entrypoints."""
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


class Handler(BaseHTTPRequestHandler):
    """
    Fallback handler for environments that expect BaseHTTPRequestHandler subclass.
    Delegates to build_response above.
    """

    def _dispatch(self):
        result = build_response()
        status = result.get("statusCode", 200)
        headers = result.get("headers", {}) or {}
        body = result.get("body", "")
        if not isinstance(body, (str, bytes)):
            body = json.dumps(body, ensure_ascii=False)

        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        payload = body if isinstance(body, bytes) else body.encode("utf-8")
        self.wfile.write(payload)

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()


# Alias expected by older Vercel Python runtimes: treat `handler` as a Handler subclass.
handler = Handler


if __name__ == "__main__":
    main()
