"""Instagram insights for @thelobby.report -> results.csv (CLAUDE.md section 7).

    python insights.py            rebuild results.csv from every post on the account

Uses ONLY the Instagram Login API (graph.instagram.com, CLAUDE.md rule 6) with the IGAA token in .env
(INSTAGRAM_ACCESS_TOKEN). Never prints the token.
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
G = "https://graph.instagram.com"
IST = timezone(timedelta(hours=5, minutes=30))
OUT = BASE / "results.csv"

REEL_METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
                "ig_reels_avg_watch_time", "reels_skip_rate"]
FEED_METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions",
                "follows", "profile_visits"]
COLUMNS = ["date_ist", "slot_ist", "format", "topic", "hook_line", "length_s", "views", "reach",
           "avg_watch_time_s", "skip_rate_pct", "likes", "comments", "shares", "saves", "follows",
           "profile_visits", "age_hours", "permalink", "media_id"]


def token() -> str:
    load_dotenv(BASE / ".env")
    t = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not t.startswith("IG"):
        sys.exit("INSTAGRAM_ACCESS_TOKEN in .env must be an Instagram-login token (IGAA...) - CLAUDE.md rule 6")
    return t


def get(path: str, tok: str, **params) -> dict:
    r = requests.get(f"{G}/{path}", params=params, headers={"Authorization": f"Bearer {tok}"}, timeout=40)
    body = r.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", f"HTTP {r.status_code}"))
    return body


def all_media(tok: str) -> list[dict]:
    out, params = [], {"fields": "id,media_type,media_product_type,timestamp,caption,permalink,media_url", "limit": 50}
    page = get("me/media", tok, **params)
    while True:
        out += page.get("data", [])
        nxt = (page.get("paging") or {}).get("next")
        if not nxt:
            return out
        page = requests.get(nxt, timeout=40).json()


def insights(media: dict, tok: str) -> dict:
    metrics = REEL_METRICS if media.get("media_product_type") == "REELS" else FEED_METRICS
    vals = {}
    for m in metrics:  # one by one: a metric Instagram doesn't have for a post must not lose the others
        try:
            data = get(f"{media['id']}/insights", tok, metric=m).get("data") or []
            if data:
                vals[m] = data[0]["values"][0]["value"]
        except RuntimeError:
            pass
    return vals


def video_length(url: str | None) -> str:
    if not url:
        return ""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url],
                           capture_output=True, text=True, timeout=30)
        return f"{float(r.stdout.strip()):.1f}" if r.stdout.strip() else ""
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""


def classify(caption: str) -> tuple[str, str]:
    """(format extra, topic) from the caption."""
    c = caption.lower()
    campaign = "#ad" in c
    if "gta" in c or "leonida" in c or "rockstar" in c:
        topic = "GTA VI"
    elif "dmz" in c:
        topic = "DMZ"
    elif "warzone" in c:
        topic = "Warzone"
    elif "mw4" in c or "modern warfare" in c or "call of duty" in c or "callofduty" in c:
        topic = "MW4"
    else:
        topic = "other"
    return ("campaign " if campaign else ""), topic


def row_for(media: dict, tok: str) -> dict:
    ts = datetime.strptime(media["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    caption = media.get("caption") or ""
    extra, topic = classify(caption)
    kind = {"REELS": "Reel", "FEED": {"IMAGE": "Photo", "CAROUSEL_ALBUM": "Carousel", "VIDEO": "Video"}.get(
        media.get("media_type"), "Post"), "STORY": "Story"}.get(media.get("media_product_type"), "Post")
    v = insights(media, tok)
    hook = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    return {
        "date_ist": ts.astimezone(IST).strftime("%Y-%m-%d"),
        "slot_ist": ts.astimezone(IST).strftime("%H:%M"),
        "format": (extra + kind).strip(),
        "topic": topic,
        "hook_line": re.sub(r"\s+", " ", hook)[:120],
        "length_s": video_length(media.get("media_url")) if kind == "Reel" else "",
        "views": v.get("views", ""), "reach": v.get("reach", ""),
        "avg_watch_time_s": f"{v['ig_reels_avg_watch_time'] / 1000:.1f}" if "ig_reels_avg_watch_time" in v else "",
        "skip_rate_pct": v.get("reels_skip_rate", ""),
        "likes": v.get("likes", ""), "comments": v.get("comments", ""), "shares": v.get("shares", ""),
        "saves": v.get("saved", ""), "follows": v.get("follows", ""), "profile_visits": v.get("profile_visits", ""),
        "age_hours": int((datetime.now(timezone.utc) - ts).total_seconds() // 3600),
        "permalink": media.get("permalink", ""), "media_id": media["id"],
    }


def account(tok: str) -> dict:
    return get("me", tok, fields="username,followers_count,media_count")


def main() -> int:
    tok = token()
    acc = account(tok)
    media = all_media(tok)
    print(f"@{acc.get('username')}: {acc.get('followers_count')} followers, {len(media)} posts. Reading insights...")
    rows = [row_for(m, tok) for m in media]
    rows.sort(key=lambda r: (r["date_ist"], r["slot_ist"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (BASE / "account_snapshot.json").write_text(json.dumps(
        {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **acc}, indent=2), encoding="utf-8")
    print(f"results.csv: {len(rows)} posts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
