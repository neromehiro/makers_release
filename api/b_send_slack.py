import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


def send_to_slack(text: str, *, enable_unfurl: bool = False) -> requests.Response:
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")

    payload = {
        "text": text,
        "unfurl_links": enable_unfurl,
        "unfurl_media": enable_unfurl,
    }
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    resp.raise_for_status()
    return resp


def main():
    # Always refresh spreadsheet data before checking feeds
    load_spreadsheet_data(force_refresh=True)

    pr_data = pr_checker.check_releases(window_hours=1)
    pr_checker.write_output(pr_data)

    note_data = note_checker.check_notes(window_hours=1)
    note_checker.write_output(note_data)

    pr_urls = [r.get("url", "") for r in pr_data.get("releases", []) if r.get("url")]
    note_urls = [a.get("url", "") for a in note_data.get("articles", []) if a.get("url")]

    responses = []
    # Unfurl for both PR TIMES and note so previews show up.
    for url in pr_urls:
        responses.append(send_to_slack(url, enable_unfurl=True))
    for url in note_urls:
        responses.append(send_to_slack(url, enable_unfurl=True))

    if not pr_urls and not note_urls:
        responses.append(send_to_slack("今回はありません"))

    print(
        f"Slack posted: pr_count={len(pr_urls)}, note_count={len(note_urls)}, "
        f"messages_sent={len(responses)}"
    )


if __name__ == "__main__":
    main()
