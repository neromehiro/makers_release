import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import api.a2_check_note as note_checker
import api.a_check_releace as pr_checker


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
JST = timezone(timedelta(hours=9))


def format_pr_message(data: dict) -> str:
    """Build a human-friendly Slack message for PR TIMES payload."""
    count = data.get("count", 0)
    window_hours = data.get("window_hours", 1)
    target_ids = data.get("target_ids", [])
    releases = data.get("releases", [])

    checked_at = data.get("checked_at")
    try:
        checked_dt = datetime.fromisoformat(checked_at).astimezone(JST)
    except Exception:
        checked_dt = datetime.now(JST)
    window_start = checked_dt - timedelta(hours=window_hours)

    header = (
        f":mega: PR TIMES 新着 (直近{window_hours}時間)\n"
        f"対象ID: {', '.join(target_ids) if target_ids else '未設定'}\n"
        f"チェック時刻: {checked_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"集計期間: {window_start.strftime('%Y-%m-%d %H:%M:%S')} - "
        f"{checked_dt.strftime('%Y-%m-%d %H:%M:%S')} ({JST.tzname(None)})\n"
    )

    if count == 0:
        return header + ":zzz: 直近で新着リリースはありません。"

    lines = [header, f"件数: {count}件\n"]
    for idx, release in enumerate(releases, start=1):
        pub_dt = datetime.fromisoformat(release["published_at"]).astimezone(JST)
        title = release["title"] or "(タイトル無し)"
        lines.append(
            f"{idx}. {title}\n"
            f"   company_id: {release['company_id']} | 公開: {pub_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"   {release['url']}"
        )
    return "\n".join(lines)


def format_note_message(data: dict) -> str:
    """Build a Slack message for note RSS payload."""
    count = data.get("count", 0)
    window_hours = data.get("window_hours", 1)
    target_ids = data.get("target_ids", [])
    articles = data.get("articles", [])

    checked_at = data.get("checked_at")
    try:
        checked_dt = datetime.fromisoformat(checked_at).astimezone(JST)
    except Exception:
        checked_dt = datetime.now(JST)
    window_start = checked_dt - timedelta(hours=window_hours)

    header = (
        f":memo: note 新着 (直近{window_hours}時間)\n"
        f"対象ID: {', '.join(target_ids) if target_ids else '未設定'}\n"
        f"チェック時刻: {checked_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"集計期間: {window_start.strftime('%Y-%m-%d %H:%M:%S')} - "
        f"{checked_dt.strftime('%Y-%m-%d %H:%M:%S')} ({JST.tzname(None)})\n"
    )

    if count == 0:
        return header + ":zzz: 直近で新着記事はありません。"

    lines = [header, f"件数: {count}件\n"]
    for idx, article in enumerate(articles, start=1):
        pub_dt = datetime.fromisoformat(article["published_at"]).astimezone(JST)
        title = article["title"] or "(タイトル無し)"
        lines.append(
            f"{idx}. {title}\n"
            f"   note_id: {article['note_id']} | 公開: {pub_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"   {article['url']}"
        )
    return "\n".join(lines)


def send_to_slack(text: str) -> requests.Response:
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")

    resp = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    resp.raise_for_status()
    return resp


def main():
    pr_data = pr_checker.check_releases(window_hours=1)
    pr_checker.write_output(pr_data)

    note_data = note_checker.check_notes(window_hours=1)
    note_checker.write_output(note_data)

    message = "\n\n".join([format_pr_message(pr_data), format_note_message(note_data)])
    resp = send_to_slack(message)
    print(
        f"Slack posted: status={resp.status_code}, "
        f"pr_count={pr_data.get('count', 0)}, note_count={note_data.get('count', 0)}"
    )


if __name__ == "__main__":
    main()
