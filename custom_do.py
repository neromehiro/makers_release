from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import api.a1_check_releace as pr_checker
import api.a2_check_note as note_checker
import api.b_send_slack as slack
from spreadsheet2json import load_spreadsheet_data

try:
    from zoneinfo import ZoneInfo

    JST = ZoneInfo("Asia/Tokyo")
except Exception:
    JST = timezone(timedelta(hours=9))

# ====== Edit these values ======
START_AT_JST = "2026-02-10 11:25"  # format: YYYY-MM-DD HH:MM (JST)
END_AT_JST = None  # e.g. "2026-02-20 00:00"; None uses current time
INCLUDE_CURRENT_HOUR = False  # False = match regular hourly window behavior
CONFIRM_BEFORE_SEND = True  # True = create custom_do.json, then ask before sending
DRY_RUN = False  # True = no Slack posts, just list output
SLEEP_SECONDS = 0.3  # throttle Slack posts 
# ===============================

OUTPUT_JSON = Path("custom_do.json")


def _parse_jst(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=JST)


def _floor_to_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _build_name_index(sheet: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    # reuse internal helper (kept small here in case it changes)
    return slack._build_name_index(sheet)  # type: ignore[attr-defined]


def _collect_pr_items(
    range_start_utc: datetime,
    range_end_utc: datetime,
    name_index: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    pr_ids = pr_checker.load_prtimes_ids()
    target_set = set(pr_ids)
    releases = pr_checker.parse_sitemap(pr_checker.fetch_sitemap())

    items: List[Dict[str, str]] = []
    for r in releases:
        company_id = r.get("company_id", "")
        if company_id not in target_set:
            continue

        pub_dt = r.get("published_at")
        if not isinstance(pub_dt, datetime):
            continue
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        pub_utc = pub_dt.astimezone(timezone.utc)

        if not (range_start_utc <= pub_utc < range_end_utc):
            continue

        items.append(
            {
                "source": "pr",
                "url": r.get("url", ""),
                "name": name_index["pr"].get(company_id, ""),
                "published_at": pub_utc.isoformat(),
            }
        )
    return items


def _collect_note_items(
    range_start_utc: datetime,
    range_end_utc: datetime,
    name_index: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    note_ids = note_checker.load_note_ids()
    items: List[Dict[str, str]] = []

    for note_id in note_ids:
        try:
            xml_bytes = note_checker.fetch_rss(note_id)
        except Exception as exc:
            print(f"[note] skip {note_id}: {exc}")
            continue

        articles = note_checker.parse_rss(xml_bytes, note_id)
        for a in articles:
            pub_dt = a.get("published_at")
            if not isinstance(pub_dt, datetime):
                continue
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            pub_utc = pub_dt.astimezone(timezone.utc)

            if not (range_start_utc <= pub_utc < range_end_utc):
                continue

            items.append(
                {
                    "source": "note",
                    "url": a.get("url", ""),
                    "name": name_index["note"].get(a.get("note_id", ""), ""),
                    "published_at": pub_utc.isoformat(),
                }
            )

    return items


def _dedupe_and_sort(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    unique: List[Dict[str, str]] = []
    for item in sorted(items, key=lambda x: x.get("published_at", "")):
        url = item.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(item)
    return unique


def _write_json(
    *,
    range_start_utc: datetime,
    range_end_utc: datetime,
    items: List[Dict[str, str]],
    pr_count: int,
    note_count: int,
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "range_start_utc": range_start_utc.isoformat(),
        "range_end_utc": range_end_utc.isoformat(),
        "range_start_jst": range_start_utc.astimezone(JST).isoformat(),
        "range_end_jst": range_end_utc.astimezone(JST).isoformat(),
        "counts": {"total": len(items), "pr": pr_count, "note": note_count},
        "items": items,
    }
    OUTPUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _confirm_send() -> bool:
    if not sys.stdin.isatty():
        print("Non-interactive mode: confirmation required. Set CONFIRM_BEFORE_SEND=False to override.")
        return False

    answer = input("実行しますか？ [y/N]: ").strip().lower()
    return answer in {"y", "yes", "はい"}


def main() -> None:
    start_jst = _parse_jst(START_AT_JST)
    end_jst = _parse_jst(END_AT_JST) if END_AT_JST else datetime.now(JST)

    start_utc = start_jst.astimezone(timezone.utc)
    end_utc = end_jst.astimezone(timezone.utc)

    range_start_utc = _floor_to_hour(start_utc)
    range_end_utc = end_utc if INCLUDE_CURRENT_HOUR else _floor_to_hour(end_utc)

    if range_end_utc <= range_start_utc:
        print("No window to process. Check START_AT_JST / END_AT_JST.")
        return

    print(
        "Backfill window (UTC): "
        f"{range_start_utc.isoformat()} -> {range_end_utc.isoformat()}"
    )
    print(
        "Backfill window (JST): "
        f"{range_start_utc.astimezone(JST).isoformat()} -> "
        f"{range_end_utc.astimezone(JST).isoformat()}"
    )

    sheet_data = load_spreadsheet_data(force_refresh=True, persist=True)
    name_index = _build_name_index(sheet_data)  # type: ignore[arg-type]

    pr_items = _collect_pr_items(range_start_utc, range_end_utc, name_index)
    note_items = _collect_note_items(range_start_utc, range_end_utc, name_index)
    items = _dedupe_and_sort(pr_items + note_items)

    print(f"Found {len(items)} items (pr={len(pr_items)}, note={len(note_items)}).")

    _write_json(
        range_start_utc=range_start_utc,
        range_end_utc=range_end_utc,
        items=items,
        pr_count=len(pr_items),
        note_count=len(note_items),
    )
    print(f"Saved: {OUTPUT_JSON}")

    if DRY_RUN:
        for item in items:
            print(f"{item['published_at']} | {item['source']} | {item['url']}")
        print("DRY_RUN enabled: no Slack posts sent.")
        return

    if CONFIRM_BEFORE_SEND and not _confirm_send():
        print("Canceled. No Slack posts sent.")
        return

    sent = 0
    for item in items:
        slack.send_with_preview(item["url"], name=item.get("name") or None)
        sent += 1
        if SLEEP_SECONDS > 0:
            time.sleep(SLEEP_SECONDS)

    print(f"Slack posts sent: {sent}")


if __name__ == "__main__":
    main()
