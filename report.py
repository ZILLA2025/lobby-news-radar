"""Daily Telegram report at 21:00 IST (CLAUDE.md section 9) and 24-hour results logging (section 7).

Runs in the cloud on every check (and in --loop on the PC); does nothing until there's something to do.
Uses only the Instagram Login API (graph.instagram.com). Data lives in radar.db:
  follower_history(day, followers)       - one row per India-time day (latest count of that day)
  results(media_id, ...)                 - each post's numbers 24 h after publishing
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

import radar as R

log = R.log
G = "https://graph.instagram.com"
REPORT_TIME = (21, 0)            # India time
START_DAY = "2026-11-17"         # day 0 of the 30-day goal (CLAUDE.md section 1)
MILESTONES = [(7, 250), (14, 1000), (21, 2500), (30, 5000)]
REEL_METRICS = "views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time,reels_skip_rate"
FEED_METRICS = "views,reach,likes,comments,shares,saved,follows"

SCHEMA = """
CREATE TABLE IF NOT EXISTS follower_history (day TEXT PRIMARY KEY, followers INTEGER, at TEXT);
CREATE TABLE IF NOT EXISTS results (
    media_id TEXT PRIMARY KEY, posted_at TEXT, slot_ist TEXT, format TEXT, hook TEXT, views INTEGER, reach INTEGER,
    avg_watch_s REAL, skip_pct REAL, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER, follows INTEGER,
    permalink TEXT, logged_at TEXT
);
"""


class Reporter:
    def __init__(self, radar: R.Radar, token: str) -> None:
        self.radar, self.db, self.tg, self.token = radar, radar.db, radar.tg, token
        self.db.executescript(SCHEMA)

    def get(self, path: str, **params) -> dict:
        r = requests.get(f"{G}/{path}", params=params, headers={"Authorization": f"Bearer {self.token}"}, timeout=40)
        body = r.json()
        if "error" in body:
            raise RuntimeError(body["error"].get("message", f"HTTP {r.status_code}"))
        return body

    def media(self, limit: int = 30) -> list[dict]:
        return self.get("me/media", fields="id,media_product_type,media_type,timestamp,caption,permalink",
                        limit=limit).get("data", [])

    def numbers(self, m: dict) -> dict:
        metrics = REEL_METRICS if m.get("media_product_type") == "REELS" else FEED_METRICS
        out = {}
        for metric in metrics.split(","):  # one by one so a missing metric doesn't lose the rest
            try:
                data = self.get(f"{m['id']}/insights", metric=metric).get("data") or []
                if data:
                    out[metric] = data[0]["values"][0]["value"]
            except RuntimeError:
                pass
        return out

    # ---- followers
    def snapshot_followers(self) -> int | None:
        try:
            n = int(self.get("me", fields="followers_count").get("followers_count"))
        except (RuntimeError, TypeError, ValueError):
            return None
        day = R.now_utc().astimezone(R.IST).strftime("%Y-%m-%d")
        self.db.execute("INSERT OR REPLACE INTO follower_history(day, followers, at) VALUES(?,?,?)",
                        (day, n, R.iso(R.now_utc())))
        return n

    # ---- 24-hour results (section 7)
    def log_24h(self) -> int:
        logged = 0
        now = R.now_utc()
        for m in self.media():
            ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            age = now - ts
            if not timedelta(hours=24) <= age <= timedelta(hours=48):
                continue
            if self.db.execute("SELECT 1 FROM results WHERE media_id=?", (m["id"],)).fetchone():
                continue
            v = self.numbers(m)
            hook = next((ln.strip() for ln in (m.get("caption") or "").splitlines() if ln.strip()), "")[:120]
            self.db.execute(
                "INSERT INTO results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m["id"], R.iso(ts), ts.astimezone(R.IST).strftime("%Y-%m-%d %H:%M"),
                 "Reel" if m.get("media_product_type") == "REELS" else m.get("media_type", "Post").title(), hook,
                 v.get("views"), v.get("reach"),
                 round(v["ig_reels_avg_watch_time"] / 1000, 1) if "ig_reels_avg_watch_time" in v else None,
                 v.get("reels_skip_rate"), v.get("likes"), v.get("comments"), v.get("shares"), v.get("saved"),
                 v.get("follows"), m.get("permalink", ""), R.iso(now)))
            logged += 1
        return logged

    # ---- the report (section 9)
    def report(self, ap) -> str:
        now_ist = R.now_utc().astimezone(R.IST)
        today, yday = now_ist.strftime("%Y-%m-%d"), (now_ist - timedelta(days=1)).strftime("%Y-%m-%d")
        n = self.snapshot_followers()
        prev = self.db.execute("SELECT followers FROM follower_history WHERE day<=? ORDER BY day DESC LIMIT 1",
                               (yday,)).fetchone()
        day_no = (now_ist.date() - datetime.strptime(START_DAY, "%Y-%m-%d").date()).days
        lines = [f"📊 Daily report · {now_ist:%d %b} · day {day_no} of 30"]
        if n is not None:
            change = f" ({n - prev[0]:+d} since yesterday)" if prev else ""
            lines.append(f"👥 Followers: {n}{change}")
            nxt = next(((d, g) for d, g in MILESTONES if d >= day_no and g > n), None)
            if nxt:
                d, g = nxt
                left = max(1, d - day_no)
                lines.append(f"🎯 Next milestone: {g} by day {d} - need +{g - n} (~{-(-(g - n) // left)}/day)")
            behind = [g for d, g in MILESTONES if d <= day_no and n < g]
            if behind:
                lines.append(f"⚠️ Behind the day-{max(d for d, g in MILESTONES if d <= day_no)} milestone: change the plan")

        posted = [m for m in self.media(15)
                  if datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z").astimezone(R.IST).strftime("%Y-%m-%d") == today]
        lines.append(f"\n📮 Posted today: {len(posted)}")
        for m in posted:
            v = self.numbers(m)
            hook = next((ln.strip() for ln in (m.get("caption") or "").splitlines() if ln.strip()), "")[:45]
            skip = f", skip {v['reels_skip_rate']}%" if "reels_skip_rate" in v else ""
            lines.append(f"• {hook} - {v.get('views', 0)} views, {v.get('shares', 0)} shares, "
                         f"{v.get('saved', 0)} saves{skip}")

        tomorrow = (now_ist + timedelta(days=1)).strftime("%Y-%m-%d")
        lines.append("\n🗓 Tomorrow:")
        gaps = 0
        for t in ap.cfg.times:
            key = f"{tomorrow} {t}"
            plan = next((p for p in ap._plans() if p.get("slot") == key), None)
            approved = self.db.execute("SELECT 1 FROM posts WHERE slot=? AND status='approved'", (key,)).fetchone()
            if plan:
                state = "✅ approved" if approved else "waiting for your ✅"
                lines.append(f"• {ap.label(key)}: {plan.get('series', 'Reel')} - {plan.get('title', '')[:40]} ({state})")
            else:
                gaps += 1
                lines.append(f"• {ap.label(key)}: nothing planned yet (news or standby will fill it)")
        bank = ap._standby_bank_size()
        lines.append(f"🗄 Standby bank: {bank} Reel(s) ready")

        needs = []
        waiting = self.db.execute("SELECT COUNT(*) FROM posts WHERE status='proposed' AND slot!='STANDBY'").fetchone()[0]
        if waiting:
            needs.append(f"{waiting} post(s) waiting for your ✅")
        if bank < 3:
            needs.append("standby bank is low - ask Claude Code to make more evergreen Reels")
        if gaps:
            needs.append(f"{gaps} of tomorrow's times have no planned Reel - ask Claude Code to plan them")
        exp = R.from_iso(R.meta_get(self.db, "ig_token_expires") or None)
        if exp and exp - R.now_utc() < timedelta(days=10):
            needs.append(f"Instagram token expires {exp.astimezone(R.IST):%d %b} (it should renew itself)")
        lines.append("\n🙋 Needs you: " + ("; ".join(needs) if needs else "nothing - all good"))
        return "\n".join(lines)


def tick(radar: R.Radar) -> None:
    """Never raises. 24 h logging every run; the report once a day after 21:00 IST."""
    try:
        import autopost
        ap = autopost._get(radar)
        token = ap.tokens.get()
        if not token.startswith("IG"):
            return
        rep = Reporter(radar, token)
        last = R.meta_get(radar.db, "results_checked")
        if not last or R.now_utc() - R.from_iso(last) >= timedelta(hours=1):
            R.meta_set(radar.db, "results_checked", R.iso(R.now_utc()))
            n = rep.log_24h()
            if n:
                log.info("Logged 24-hour results for %d post(s)", n)
        now_ist = R.now_utc().astimezone(R.IST)
        today = now_ist.strftime("%Y-%m-%d")
        if (now_ist.hour, now_ist.minute) >= REPORT_TIME and R.meta_get(radar.db, "report_sent") != today:
            R.meta_set(radar.db, "report_sent", today)
            radar.tg.text(rep.report(ap))
            log.info("Daily report sent")
    except Exception:
        log.exception("Daily report / results error (the radar keeps running)")
