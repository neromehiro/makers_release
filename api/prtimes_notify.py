from http.server import BaseHTTPRequestHandler
import os
import json
import requests
from pathlib import Path


def _load_env_file():
    """
    Minimal .env loader for local runs (KEY="value" lines only).
    Does nothing on Vercel; safe to call always.
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


# Try loading .env for local execution convenience
_load_env_file()

# Vercel の環境変数に設定しておく
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# id_list.txt のパス（リポジトリ直下を想定）
BASE_DIR = Path(__file__).resolve().parent.parent
ID_LIST_PATH = BASE_DIR / "id_list.txt"


def load_prtimes_ids():
    """
    id_list.txt から PR TIMES の company_id を読み込む。
    - 1行1ID
    - 空行と # で始まる行は無視
    """
    if not ID_LIST_PATH.exists():
        return []

    ids: list[str] = []
    with ID_LIST_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            ids.append(line)
    return ids


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not SLACK_WEBHOOK_URL:
            # 環境変数未設定の場合
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"SLACK_WEBHOOK_URL is not set")
            return

        prtimes_ids = load_prtimes_ids()

        # テスト用メッセージ
        text = (
            ":mega: *PRTIMES Bot テスト送信*\n"
            "このメッセージは Vercel の Python Function から送信されています。\n"
            f"現在登録されている PR TIMES ID 数: {len(prtimes_ids)} 件"
        )

        payload = {"text": text}

        try:
            resp = requests.post(
                SLACK_WEBHOOK_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            resp.raise_for_status()

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        except Exception as e:
            # Slack 送信失敗時
            self.send_response(500)
            self.end_headers()
            msg = f"Slack error: {e}"
            self.wfile.write(msg.encode("utf-8"))


def send_test_message():
    """Send a one-off test message (used when running this file directly)."""
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError("SLACK_WEBHOOK_URL is not set")

    prtimes_ids = load_prtimes_ids()
    text = (
        ":mega: *PRTIMES Bot テスト送信*\n"
        "このメッセージはローカル実行で送信されています。\n"
        f"現在登録されている PR TIMES ID 数: {len(prtimes_ids)} 件"
    )
    payload = {"text": text}
    resp = requests.post(
        SLACK_WEBHOOK_URL,
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    resp.raise_for_status()
    return resp


if __name__ == "__main__":
    try:
        resp = send_test_message()
        print(f"Sent to Slack: status={resp.status_code}")
    except Exception as e:
        # Print for local debugging
        print(f"Failed to send Slack message: {e}")
