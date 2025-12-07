import json
import os
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict

import requests

# Vercel will handle SLACK_WEBHOOK_URL via env vars. For local runs, optional .env.
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"


def _load_env_file():
    if not ENV_PATH.exists():
        return
    with ENV_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_env_file()

# Import after env load so webhook is available if .env is present locally.
from api import b_send_slack  # noqa: E402


def handler(request) -> Dict[str, Any]:
    """
    Vercel Python entrypoint.
    Triggers PR TIMES + note checks and posts results to Slack.
    """
    try:
        summary = b_send_slack.run_notification(window_hours=1)
        body = {"ok": True, **summary}
        status = HTTPStatus.OK
    except requests.HTTPError as exc:
        body = {"ok": False, "error": f"Slack HTTP error: {exc}"}
        status = HTTPStatus.BAD_GATEWAY
    except Exception as exc:
        body = {"ok": False, "error": str(exc)}
        status = HTTPStatus.INTERNAL_SERVER_ERROR

    return {
        "statusCode": status.value,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


if __name__ == "__main__":
    # Local manual trigger
    result = handler({})
    print(result)
