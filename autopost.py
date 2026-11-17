"""Scheduled Instagram posting for Lobby News Radar.

Uses Instagram's OFFICIAL publishing API (Instagram API with Instagram Login). It never logs in
to Instagram with a password and never posts anything you didn't approve in Telegram.

How it works (config.yaml -> autopost.times, in autopost.timezone = the audience's time zone):
  * ask_minutes_before each slot (or just before owner_sleep_ist if that would be at night in
    India), the bot sends you the best OFFICIAL/REPORTED news found since
    the previous slot or, if there's no news, the next item from your own queue, with
    ✅ Approve / ⏭ Skip buttons. Skip offers the next option.
  * Approved posts go out at the slot time. Approved after the slot time (up to
    late_approval_minutes later) = posted right away. Not approved = not posted.
  * Your own content: send the bot a photo with a caption. It joins the queue.
    Commands: /queue  /remove N  /caption N new text  /status  /help

Instagram needs a public link to the picture, so images are uploaded to the "media" branch of
the GitHub repository and removed again after posting.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from PIL import Image, ImageOps

import radar as R

log = R.log

IG_HOST = "https://graph.instagram.com"
FB_HOST = "https://graph.facebook.com"
MEDIA_BRANCH = "media"
PRIO_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
NEWS_STATUSES = ("alerted", "digest", "pending")
ACTIVE = ("proposed", "approved", "publishing", "posted")
STANDBY = "STANDBY"   # posts.slot for Reels in the standby bank (approved ahead, used if a slot has nothing)
MAX_PUBLISH_ATTEMPTS = 3
REFRESH_EVERY = timedelta(days=7)
AI_MARK = "\n\n----------------------------------------\nAI options"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, slot TEXT, kind TEXT, ref INTEGER,
    caption TEXT, image_name TEXT, image_url TEXT, image_sha TEXT, status TEXT,
    tg_msg INTEGER, ig_media TEXT, permalink TEXT, attempts INTEGER DEFAULT 0, error TEXT,
    created_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_slot ON posts(slot);
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT, caption TEXT, image_name TEXT, image_url TEXT,
    image_sha TEXT, status TEXT, added_at TEXT
);
"""
# posts.status: proposed | approved | skipped | publishing | posted | failed | expired | empty
# queue.status: queued | posted | removed

HELP = (
    "🤖 Lobby News Radar - auto-posting\n\n"
    "Before each posting time I send you a post to approve:\n"
    "  ✅ Approve = it goes on Instagram at that time\n"
    "  ⏭ Skip = I show you the next option\n"
    "  🚀 Post now = it goes on Instagram right away (breaking news)\n"
    "Nothing is ever posted without your ✅ or 🚀.\n\n"
    "Standby bank: Reels you approve ahead of time. If a posting time arrives with nothing approved, "
    "the oldest one goes out, so a posting time is never missed. You get a reminder 30 min before.\n\n"
    "Saturdays 13:00 New York: the week's most-talked-about rumor, labelled RUMOR HEARD.\n\n"
    "Add your own post: send me a photo with the caption written under it.\n"
    "(Tip: send it as a File to keep full quality.)\n\n"
    "Commands:\n"
    "/queue - your waiting posts\n"
    "/remove 3 - delete post #3 from the queue\n"
    "/caption 3 new caption text - change the caption of #3\n"
    "/status - today's posting times and what's planned\n"
    "/help - this message"
)


class IGError(Exception):
    pass


def _hhmm(value, where: str) -> str | None:
    try:
        hh, mm = (int(x) for x in str(value).split(":"))
        return f"{hh:02d}:{mm:02d}"
    except ValueError:
        log.warning("%s: '%s' is not a time like \"06:00\" - ignored", where, value)
        return None


def _redact(secret: str) -> None:
    """Never let a token reach the log file or the console."""
    if secret and secret not in R.REDACTOR.secrets:
        R.REDACTOR.secrets.append(secret)


# --------------------------------------------------------------------------- settings

class APConfig:
    def __init__(self, s: R.Settings) -> None:
        c = s.cfg.get("autopost") or {}
        self.enabled = bool(c.get("enabled", False))
        # Posting times are in the AUDIENCE's time zone, so they follow its daylight saving.
        tz_name = str(c.get("timezone") or "Asia/Kolkata")
        try:
            self.tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            log.warning("autopost.timezone '%s' is unknown (e.g. America/New_York) - using India time", tz_name)
            tz_name, self.tz = "Asia/Kolkata", R.IST
        self.tz_label = {"Asia/Kolkata": "IST"}.get(tz_name, tz_name.split("/")[-1].replace("_", " "))
        self.times = sorted({t for t in (_hhmm(x, "autopost.times") for x in c.get("times") or c.get("times_ist") or []) if t})
        self.ask_before = max(5, int(c.get("ask_minutes_before", 30)))
        self.late = max(0, int(c.get("late_approval_minutes", 90)))
        self.news_max_age = max(1, int(c.get("news_max_age_hours", 12)))
        sleep = c.get("owner_sleep_ist") or []
        self.sleep = tuple(_hhmm(x, "autopost.owner_sleep_ist") for x in sleep) if len(sleep) == 2 else None
        if self.sleep and None in self.sleep:
            self.sleep = None
        self.tiers = [str(x).upper() for x in (c.get("news_tiers") or ["OFFICIAL", "REPORTED"])]
        self.tiers = [t for t in self.tiers if t != "RUMOR"]  # rumors only via the weekly RUMOR HEARD post
        w = c.get("weekly_rumor") or {}
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        day = str(w.get("day", "")).strip().lower()
        self.rumor_day = days.index(day) if w.get("enabled") and day in days else None
        self.rumor_time = _hhmm(w.get("time", "13:00"), "autopost.weekly_rumor.time")
        if self.rumor_day is not None and self.rumor_time not in self.times:
            log.warning("autopost.weekly_rumor.time %s is not one of autopost.times - weekly rumor post off", self.rumor_time)
            self.rumor_day = None
        self.api_version = str(c.get("instagram_api_version") or "").strip()
        self.ig_user_id = str(c.get("instagram_user_id") or "").strip()
        self.repo = os.getenv("GITHUB_REPOSITORY", "").strip() or str(c.get("github_repo") or "").strip()
        self.gh_token = os.getenv("GITHUB_TOKEN", "").strip()
        self.ig_env_token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        _redact(self.gh_token)
        _redact(self.ig_env_token)


# --------------------------------------------------------------------------- Instagram token

class TokenStore:
    """The Instagram token lasts 60 days. It is refreshed every 7 days and the new one is kept in
    radar.db, encrypted with a key made from the Telegram bot token (radar.db sits in the Actions
    cache; without the secret it can't be read)."""

    def __init__(self, ap: "AutoPost") -> None:
        self.ap = ap
        self.db = ap.db

    def _fernet(self):
        from cryptography.fernet import Fernet

        key = hashlib.sha256(("lobby-radar-ig:" + self.ap.s.token).encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    def _save(self, token: str, expires_in: int | None = None) -> None:
        R.meta_set(self.db, "ig_token_enc", self._fernet().encrypt(token.encode()).decode())
        R.meta_set(self.db, "ig_token_refreshed", R.iso(R.now_utc()))
        if expires_in:
            R.meta_set(self.db, "ig_token_expires", R.iso(R.now_utc() + timedelta(seconds=int(expires_in))))
        _redact(token)

    def get(self) -> str:
        env = self.ap.cfg.ig_env_token
        if env:
            fp = hashlib.sha256(env.encode()).hexdigest()[:16]
            if R.meta_get(self.db, "ig_token_env_fp") != fp:  # a new token was put in .env / GitHub Secrets
                R.meta_set(self.db, "ig_token_env_fp", fp)
                R.meta_set(self.db, "ig_token_expires", "")
                self._save(env)
                return env
        enc = R.meta_get(self.db, "ig_token_enc")
        if enc:
            try:
                token = self._fernet().decrypt(enc.encode()).decode()
                _redact(token)
                return token
            except Exception:
                log.warning("Stored Instagram token can't be read (Telegram token changed?) - using the one from .env")
        return env

    def maybe_refresh(self) -> None:
        token = self.get()
        if not token.startswith("IG"):
            return  # only Instagram-login tokens expire; system-user (EAA...) tokens never do
        last = R.from_iso(R.meta_get(self.db, "ig_token_refreshed"))
        if last and R.now_utc() - last < REFRESH_EVERY:
            return
        try:
            resp = requests.get(f"{IG_HOST}/refresh_access_token",
                                params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=20)
            body = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("Instagram token refresh: network problem (%s), will try again later", type(e).__name__)
            return
        if resp.ok and body.get("access_token"):
            self._save(body["access_token"], body.get("expires_in"))
            log.info("Instagram token refreshed (valid for another %s days)", int(body.get("expires_in", 0)) // 86400)
            return
        msg = (body.get("error") or {}).get("message", f"HTTP {resp.status_code}")
        log.error("Instagram token refresh failed: %s", msg)
        R.meta_set(self.db, "ig_token_refreshed", R.iso(R.now_utc() - REFRESH_EVERY + timedelta(hours=12)))
        self.ap.warn_once("ig_refresh", "⚠️ Auto-posting: the Instagram token could not be renewed:\n"
                          f"{msg}\nMake a new token (README section 10) or posting will stop when it expires.")


# --------------------------------------------------------------------------- Instagram API

class Instagram:
    """Instagram publishing. Two kinds of token work:
    - IGAA... (Instagram login, 60 days, renewed automatically) -> graph.instagram.com
    - EAA...  (Unified / Facebook login, e.g. a system-user token that never expires) -> graph.facebook.com
    Both use the same steps: create a media container, wait until it's ready, publish it."""

    def __init__(self, token: str, version: str = "", ig_id: str = "") -> None:
        if not token.startswith("IG"):
            # CLAUDE.md rule 6: only the Instagram Login API (graph.instagram.com). An EAA... token would
            # go through graph.facebook.com, so it is refused.
            raise IGError("this token is not an Instagram-login token (IGAA...). CLAUDE.md rule 6 allows only "
                          "graph.instagram.com - get an Instagram-login token (README section 10)")
        self.token = token
        self.version = version
        self.ig_id = ig_id
        self.fb = False
        self.host = IG_HOST

    def _url(self, path: str) -> str:
        return f"{self.host}/{self.version + '/' if self.version else ''}{path}"

    def _req(self, method: str, path: str, **kw) -> dict:
        if self.fb:  # graph.facebook.com: token as a parameter
            kw["params"] = {**kw.get("params", {}), "access_token": self.token}
            headers = {}
        else:
            headers = {"Authorization": f"Bearer {self.token}"}
        try:
            resp = requests.request(method, self._url(path), headers=headers, timeout=40, **kw)
            body = resp.json()
        except (requests.RequestException, ValueError) as e:
            raise IGError(f"network problem ({type(e).__name__})") from e
        if not resp.ok or "error" in body:
            err = body.get("error") or {}
            msg = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
            if err.get("code") == 190:
                msg += " (the Instagram token is wrong or expired - see README section 10)"
            raise IGError(msg)
        return body

    def me(self) -> dict:
        if not self.fb:
            return self._req("GET", "me", params={"fields": "user_id,username,account_type"})
        if self.ig_id:  # system-user tokens have no Instagram "me": ask about the account directly
            acc = self._req("GET", self.ig_id, params={"fields": "id,username"})
            return {"user_id": acc.get("id"), "username": acc.get("username"), "account_type": "BUSINESS"}
        pages = self._req("GET", "me/accounts", params={"fields": "instagram_business_account{id,username}"})
        for p in pages.get("data", []):
            acc = p.get("instagram_business_account")
            if acc:
                return {"user_id": acc["id"], "username": acc.get("username"), "account_type": "BUSINESS"}
        raise IGError("couldn't find the Instagram account for this token - put its ID in "
                      "config.yaml > autopost > instagram_user_id")

    def create(self, ig_id: str, image_url: str, caption: str) -> str:
        return self._req("POST", f"{ig_id}/media", data={"image_url": image_url, "caption": caption})["id"]

    def create_reel(self, ig_id: str, video_url: str, caption: str, cover_url: str = "") -> str:
        data = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
        if cover_url:
            data["cover_url"] = cover_url  # the action frame with the headline, never a logo
        return self._req("POST", f"{ig_id}/media", data=data)["id"]

    def wait_ready(self, container: str, max_wait: int = 90) -> None:
        end = time.time() + max_wait
        while True:
            st = self._req("GET", container, params={"fields": "status_code,status"})
            code = st.get("status_code")
            if code in ("FINISHED", "PUBLISHED"):
                return
            if code in ("ERROR", "EXPIRED"):
                raise IGError(f"Instagram couldn't use the picture ({st.get('status') or code})")
            if time.time() > end:
                raise IGError(f"Instagram was still processing it after {max_wait} seconds")
            time.sleep(5)

    def publish(self, ig_id: str, container: str) -> str:
        return self._req("POST", f"{ig_id}/media_publish", data={"creation_id": container})["id"]

    def permalink(self, media_id: str) -> str:
        try:
            return self._req("GET", media_id, params={"fields": "permalink"}).get("permalink", "")
        except IGError:
            return ""


# --------------------------------------------------------------------------- picture hosting

class GitHubHost:
    """Puts pictures on the 'media' branch of the (public) GitHub repo so Instagram can fetch them."""

    def __init__(self, repo: str, token: str) -> None:
        self.repo, self.token = repo, token
        self._branch_ok = False

    @property
    def ready(self) -> bool:
        return bool(self.repo and self.token)

    def _api(self, method: str, path: str, **kw) -> requests.Response:
        url = f"https://api.github.com/repos/{self.repo}" + (f"/{path}" if path else "")
        return requests.request(method, url, timeout=30,
                                headers={"Authorization": f"Bearer {self.token}",
                                         "Accept": "application/vnd.github+json"}, **kw)

    def _ensure_branch(self) -> None:
        if self._branch_ok:
            return
        r = self._api("GET", f"branches/{MEDIA_BRANCH}")
        if r.status_code == 404:
            repo = self._api("GET", "").json()
            head = self._api("GET", f"git/ref/heads/{repo['default_branch']}").json()["object"]["sha"]
            c = self._api("POST", "git/refs", json={"ref": f"refs/heads/{MEDIA_BRANCH}", "sha": head})
            if c.status_code not in (201, 422):
                raise IGError(f"couldn't create the '{MEDIA_BRANCH}' branch on GitHub (HTTP {c.status_code})")
        elif not r.ok:
            raise IGError(f"GitHub said HTTP {r.status_code} - check GITHUB_TOKEN / github_repo")
        self._branch_ok = True

    def upload(self, data: bytes, name: str) -> tuple[str, str]:
        self._ensure_branch()
        r = self._api("PUT", f"contents/posts/{name}", json={
            "message": f"picture for a scheduled post ({name})", "branch": MEDIA_BRANCH,
            "content": base64.b64encode(data).decode(),
        })
        if not r.ok:
            raise IGError(f"couldn't upload the picture to GitHub (HTTP {r.status_code}: {r.text[:120]})")
        url = f"https://raw.githubusercontent.com/{self.repo}/{MEDIA_BRANCH}/posts/{name}"
        if name.lower().endswith(".mp4"):
            # Videos: raw.githubusercontent serves them as application/octet-stream, which Instagram rejects.
            # GitHub Pages (on the media branch) serves video/mp4; it needs ~1-2 min to publish each push.
            owner, repo = self.repo.split("/", 1)
            url = f"https://{owner.lower()}.github.io/{repo}/posts/{name}"
            for _ in range(36):
                try:
                    h = requests.head(url, timeout=15)
                    if h.status_code == 200 and h.headers.get("content-type", "").startswith("video/"):
                        break
                except requests.RequestException:
                    pass
                time.sleep(10)
            else:
                raise IGError("the video link on GitHub Pages didn't come online within 6 minutes")
            return url, r.json()["content"]["sha"]
        for _ in range(10):  # wait until the public link works
            try:
                if requests.head(url, timeout=10).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(3)
        return url, r.json()["content"]["sha"]

    def delete(self, name: str | None, sha: str | None) -> None:
        if not (name and sha and self.ready):
            return
        try:
            self._api("DELETE", f"contents/posts/{name}",
                      json={"message": f"remove posted picture ({name})", "sha": sha, "branch": MEDIA_BRANCH})
        except requests.RequestException:
            pass


def ig_ready_jpeg(data: bytes, bg: tuple[int, int, int]) -> bytes:
    """Instagram feed posts: JPEG, width 320-1440, aspect between 4:5 (tall) and 1.91:1 (wide).
    Pictures outside that are padded with the brand background, never cropped."""
    img = ImageOps.exif_transpose(Image.open(BytesIO(data)))
    img = img.convert("RGB")
    w, h = img.size
    if w / h < 0.8:
        canvas = Image.new("RGB", (math.ceil(h * 0.8), h), bg)
        canvas.paste(img, ((canvas.width - w) // 2, 0))
        img = canvas
    elif w / h > 1.91:
        canvas = Image.new("RGB", (w, math.ceil(w / 1.91)), bg)
        canvas.paste(img, (0, (canvas.height - h) // 2))
        img = canvas
    if img.width > 1440:
        img = img.resize((1440, round(img.height * 1440 / img.width)), Image.LANCZOS)
    elif img.width < 1080:
        img = img.resize((1080, round(img.height * 1080 / img.width)), Image.LANCZOS)
    out = BytesIO()
    img.save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue()


# --------------------------------------------------------------------------- the scheduler

class AutoPost:
    def __init__(self, radar: R.Radar) -> None:
        self.radar = radar
        self.s = radar.s
        self.db = radar.db
        self.tg = radar.tg
        self.db.executescript(SCHEMA)
        for sql in ("ALTER TABLE posts ADD COLUMN media_type TEXT", "ALTER TABLE posts ADD COLUMN cover_url TEXT",
                    "ALTER TABLE posts ADD COLUMN post_now INTEGER DEFAULT 0", "ALTER TABLE posts ADD COLUMN plan_id TEXT"):
            try:
                self.db.execute(sql)
            except Exception:
                pass  # already there
        self.cfg = APConfig(self.s)
        self.tokens = TokenStore(self)
        self.host = GitHubHost(self.cfg.repo, self.cfg.gh_token)
        self._ig_id: str | None = None

    # ---- helpers
    def warn_once(self, key: str, text: str) -> None:
        """Same warning at most once a day."""
        today = R.now_utc().astimezone(R.IST).strftime("%Y-%m-%d")
        if R.meta_get(self.db, f"warn:{key}") != today:
            R.meta_set(self.db, f"warn:{key}", today)
            self.tg.text(text)

    def problems(self) -> list[str]:
        p = []
        if not self.s.telegram_ready:
            p.append("Telegram is not set up")
        if not self.cfg.times:
            p.append("autopost.times_ist in config.yaml has no times")
        if not self.tokens.get():
            p.append("INSTAGRAM_ACCESS_TOKEN is missing (.env on the PC, GitHub Secrets in the cloud)")
        if not self.host.ready:
            p.append("picture hosting is not set up (GITHUB_TOKEN + autopost.github_repo)")
        return p

    def ig(self) -> Instagram:
        return Instagram(self.tokens.get(), self.cfg.api_version, self.cfg.ig_user_id)

    def ig_id(self, ig: Instagram) -> str:
        if not self._ig_id:
            self._ig_id = self.cfg.ig_user_id or R.meta_get(self.db, "ig_user_id") or ""
            if not self._ig_id:
                me = ig.me()
                self._ig_id = str(me.get("user_id") or me.get("id"))
                R.meta_set(self.db, "ig_user_id", self._ig_id)
                R.meta_set(self.db, "ig_username", me.get("username", ""))
        return self._ig_id

    def now(self) -> datetime:
        return R.now_utc()

    # Slot keys are "YYYY-MM-DD HH:MM" in the audience time zone (autopost.timezone).
    def slots(self) -> list[tuple[str, datetime]]:
        """(key, time in UTC) for yesterday, today and tomorrow."""
        today = self.now().astimezone(self.cfg.tz).date()
        keys = [f"{(today + timedelta(days=d)).isoformat()} {t}" for d in (-1, 0, 1) for t in self.cfg.times]
        return sorted(((k, self.slot_dt(k)) for k in keys), key=lambda x: x[1])

    def slot_dt(self, key: str) -> datetime:
        d, t = key.split(" ")
        y, m, dd = (int(x) for x in d.split("-"))
        hh, mm = (int(x) for x in t.split(":"))
        return datetime(y, m, dd, hh, mm, tzinfo=self.cfg.tz).astimezone(R.now_utc().tzinfo)

    def label(self, key: str) -> str:
        """'16:00 New York (02:30 IST)' - the posting time, and the same moment in India."""
        if key == STANDBY:
            return "the standby bank"
        dt = self.slot_dt(key)
        own = dt.astimezone(self.cfg.tz).strftime("%H:%M")
        if self.cfg.tz_label == "IST":
            return f"{own} IST"
        return f"{own} {self.cfg.tz_label} ({dt.astimezone(R.IST).strftime('%H:%M')} IST)"

    def _sleep_start_before(self, when: datetime) -> datetime | None:
        """If 'when' is in the owner's sleep hours (India time), the moment that sleep started."""
        if not self.cfg.sleep:
            return None
        (sh, sm), (eh, em) = ((int(x) for x in t.split(":")) for t in self.cfg.sleep)
        local = when.astimezone(R.IST)
        for back in (0, 1):
            day = (local - timedelta(days=back)).date()
            start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=R.IST)
            end = datetime(day.year, day.month, day.day, eh, em, tzinfo=R.IST)
            if end <= start:
                end += timedelta(days=1)
            if start <= local < end:
                return start
        return None

    def asleep(self) -> bool:
        return self._sleep_start_before(self.now()) is not None

    def ask_at(self, key: str) -> datetime:
        """ask_minutes_before the slot - or, if that's while the owner sleeps, 15 min before they go to sleep."""
        ask = self.slot_dt(key) - timedelta(minutes=self.cfg.ask_before)
        start = self._sleep_start_before(ask)
        return start - timedelta(minutes=15) if start else ask

    def in_window(self, key: str) -> bool:
        return self.ask_at(key) <= self.now() <= self.slot_dt(key) + timedelta(minutes=self.cfg.late)

    def _update_post(self, pid: int, **fields) -> None:
        fields["updated_at"] = R.iso(self.now())
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE posts SET {cols} WHERE id=?", (*fields.values(), pid))

    def _post(self, pid: int):
        return self.db.execute("SELECT * FROM posts WHERE id=?", (pid,)).fetchone()

    def _set_buttons(self, msg_id: int | None, label: str) -> None:
        if not msg_id:
            return
        self.tg.api("editMessageReplyMarkup", {
            "message_id": msg_id,
            "reply_markup": json.dumps({"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}),
        }, quiet=True)

    # ---- candidates
    def _news_candidates(self, key: str) -> list:
        """Best news from the last news_max_age_hours that was never offered before."""
        since = self.now() - timedelta(hours=self.cfg.news_max_age)
        q = ",".join("?" * len(self.cfg.tiers)) or "''"
        rows = self.db.execute(
            f"SELECT * FROM items WHERE tier IN ({q}) AND game IS NOT NULL AND status IN {NEWS_STATUSES}"
            " AND found_at > ? AND id NOT IN (SELECT ref FROM posts WHERE kind='news' AND ref IS NOT NULL)",
            (*self.cfg.tiers, R.iso(since)),
        ).fetchall()
        return sorted(rows, key=lambda r: (PRIO_RANK.get(r["priority"], 3), -(R.from_iso(r["found_at"]).timestamp())))

    def is_rumor_slot(self, key: str) -> bool:
        if self.cfg.rumor_day is None:
            return False
        d, t = key.split(" ")
        return t == self.cfg.rumor_time and datetime.fromisoformat(d).weekday() == self.cfg.rumor_day

    def _rumor_candidates(self, key: str) -> list:
        """The 3 rumors with the most traction in the last 7 days that were never offered before."""
        offered = self.db.execute("SELECT COUNT(*) FROM posts WHERE kind='rumor' AND slot=?", (key,)).fetchone()[0]
        if offered >= 3:  # after 3 skipped rumors: on to normal news / the queue
            return []
        return self.db.execute(
            "SELECT * FROM items WHERE tier='RUMOR' AND game IS NOT NULL AND COALESCE(traction, 0) > 0"
            " AND found_at > ? AND id NOT IN (SELECT ref FROM posts WHERE kind='rumor' AND ref IS NOT NULL)"
            " ORDER BY traction DESC, found_at DESC LIMIT 3",
            (R.iso(self.now() - timedelta(days=7)),),
        ).fetchall()

    def _queue_candidates(self, key: str) -> list:
        return self.db.execute(
            "SELECT * FROM queue WHERE status='queued' AND id NOT IN"
            " (SELECT ref FROM posts WHERE kind='queue' AND slot=?) ORDER BY id", (key,)
        ).fetchall()

    def _news_picture(self, row) -> tuple[bytes, str]:
        folder = Path(row["draft_dir"]) if row["draft_dir"] else None
        if not (folder and (folder / "card.png").exists() and (folder / "caption.txt").exists()):
            item = {
                "source": row["source"], "tier": row["tier"], "game": row["game"], "priority": row["priority"],
                "title": row["title"], "url": row["url"], "summary": row["summary"] or "",
                "published": R.from_iso(row["published"]), "found_at": R.from_iso(row["found_at"]),
            }
            # Rumors: text-only card. Never fetch the Reddit post's picture (could be leaked footage).
            meta = {"title": row["title"], "description": "", "image": "", "body": ""} if row["tier"] == "RUMOR" else None
            if meta:
                item["summary"] = ""
            d = R.make_draft(item, self.s, self.radar.fonts, meta=meta)
            folder = d["folder"]
            self.db.execute("UPDATE items SET draft_dir=? WHERE id=?", (str(folder), row["id"]))
        caption = (folder / "caption.txt").read_text(encoding="utf-8").split(AI_MARK)[0].strip()
        return ig_ready_jpeg((folder / "card.png").read_bytes(), R.hex_rgb(self.s.bg)), caption

    # ---- planned posts (Reels made ahead for a slot, or for the standby bank)
    def _plans(self) -> list[dict]:
        """planned/*.json from the private assets repo (cloud: assets/Official/planned; PC: .asset_sync/planned)."""
        plans, seen = [], set()
        for d in (R.ASSETS_DIR / "planned", R.BASE_DIR / ".asset_sync" / "planned"):
            for f in sorted(d.glob("*.json")) if d.exists() else []:
                if f.stem in seen:
                    continue
                try:
                    p = json.loads(f.read_text(encoding="utf-8"))
                    p.setdefault("id", f.stem)
                    plans.append(p)
                    seen.add(f.stem)
                except ValueError:
                    log.warning("planned post %s is not valid JSON - skipped", f.name)
        return plans

    def _planned_candidates(self, key: str) -> list[dict]:
        used = {r[0] for r in self.db.execute("SELECT plan_id FROM posts WHERE plan_id IS NOT NULL")}
        return [p for p in self._plans() if p.get("slot") == key and p["id"] not in used]

    def propose_standby(self) -> None:
        """Offer new standby-bank Reels for approval (a couple at a time, never while the owner sleeps)."""
        if self.asleep():
            return
        for p in self._planned_candidates(STANDBY)[:2]:
            self._propose_plan(STANDBY, p)

    def _propose_plan(self, key: str, p: dict) -> None:
        label = f"🎬 {p.get('series', 'PLANNED')}: {p.get('title', p['id'])}"
        cur = self.db.execute(
            "INSERT INTO posts(slot, kind, caption, image_name, image_url, status, created_at, updated_at,"
            " media_type, cover_url, plan_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (key, "planned", p.get("caption", ""), p["id"], p["video_url"] if p.get("media_type") == "REELS" else p["image_url"],
             "proposed", R.iso(self.now()), R.iso(self.now()), p.get("media_type", "IMAGE"), p.get("cover_url", ""), p["id"]))
        pid = cur.lastrowid
        msg_id = self._send_proposal(pid, key, label, p.get("caption", ""),
                                     p.get("video_url") or p.get("image_url"), p.get("media_type", "IMAGE"))
        self._update_post(pid, tg_msg=msg_id)
        log.info("Asked for approval: %s post = planned %s", key, p["id"])

    def propose(self, key: str) -> bool:
        """Send the next option for this slot. False when there is nothing (left) to offer."""
        planned = self._planned_candidates(key)
        if planned:  # the Reel made for this slot comes first; news/queue after a Skip
            self._propose_plan(key, planned[0])
            return True
        order = [("news", self._news_candidates(key)), ("queue", self._queue_candidates(key))]
        if self.is_rumor_slot(key):  # the weekly RUMOR HEARD post comes first, news/queue after a Skip
            order.insert(0, ("rumor", self._rumor_candidates(key)))
        for kind, rows in order:
            for row in rows:
                try:
                    if kind in ("news", "rumor"):
                        data, caption = self._news_picture(row)
                        name = f"{kind}-{row['id']}-{uuid.uuid4().hex[:8]}.jpg"
                        url, sha = self.host.upload(data, name)
                        if kind == "news":
                            label = f"NEWS · {row['tier']} · {R.GAME_LABEL.get(row['game'], '')} · {row['priority']}"
                        else:
                            label = (f"⚠️ WEEKLY {R.RUMOR_LABEL} · {R.GAME_LABEL.get(row['game'], '')} · "
                                     f"traction {row['traction']} (top on Reddit this week)\n"
                                     "Unconfirmed: labelled as a rumor on the card and in the caption")
                    else:
                        caption, name, url, sha = row["caption"] or "", row["image_name"], row["image_url"], row["image_sha"]
                        label = f"FROM YOUR QUEUE (#{row['id']})"
                except Exception as e:
                    log.exception("Could not prepare %s #%s for the %s post: %s", kind, row["id"], key, e)
                    if kind in ("news", "rumor"):  # don't try this one again
                        self.db.execute("INSERT INTO posts(slot, kind, ref, status, error, created_at) VALUES(?,?,?,?,?,?)",
                                        (key, kind, row["id"], "failed", str(e)[:300], R.iso(self.now())))
                    continue
                cur = self.db.execute(
                    "INSERT INTO posts(slot, kind, ref, caption, image_name, image_url, image_sha, status, created_at,"
                    " updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (key, kind, row["id"], caption, name, url, sha, "proposed", R.iso(self.now()), R.iso(self.now())),
                )
                pid = cur.lastrowid
                msg_id = self._send_proposal(pid, key, label, caption, url)
                self._update_post(pid, tg_msg=msg_id)
                log.info("Asked for approval: %s post = %s #%s", key, kind, row["id"])
                return True
        return False

    def _send_proposal(self, pid: int, key: str, label: str, caption: str, url: str,
                       media_type: str = "IMAGE") -> int | None:
        if key == STANDBY:
            head = f"🗄 For the STANDBY BANK\n{label}\n\n"
            foot = ("\n\n✅ = keep it ready: it goes out only if a posting time has nothing approved · "
                    "⏭ = don't use it · 🚀 = post it now")
        else:
            t = self.label(key)
            late = "" if self.now() < self.slot_dt(key) else " (the time has passed: ✅ posts right away)"
            head = f"🗓 Post for {t}{late}\n{label}\n\n"
            foot = f"\n\n✅ = post at {t} · ⏭ = show the next option · 🚀 = post it now"
        room = 1024 - len(head) - len(foot)
        body = caption if len(caption) <= room else caption[: room - 1] + "…"
        buttons = {"inline_keyboard": [[{"text": "✅ Approve", "callback_data": f"ok:{pid}"},
                                        {"text": "⏭ Skip", "callback_data": f"skip:{pid}"}],
                                       [{"text": "🚀 Post now", "callback_data": f"now:{pid}"}]]}
        method, field = ("sendVideo", "video") if media_type == "REELS" else ("sendPhoto", "photo")
        res = self.tg.api(method, {field: url, "caption": head + (body or "(no caption)") + foot,
                                   "reply_markup": json.dumps(buttons)})
        if res is None:  # Telegram couldn't fetch the link: send the text instead
            res = self.tg.api("sendMessage", {"text": head + url + "\n\n" + (body or "(no caption)") + foot,
                                              "reply_markup": json.dumps(buttons)})
        return (res or {}).get("message_id") if isinstance(res, dict) else None

    # ---- publishing
    def publish(self, row) -> None:
        pid = row["id"]
        self._update_post(pid, status="publishing", attempts=row["attempts"] + 1)
        try:
            ig = self.ig()
            ig_id = self.ig_id(ig)
            if row["media_type"] == "REELS":
                container = ig.create_reel(ig_id, row["image_url"], row["caption"] or "", row["cover_url"] or "")
                ig.wait_ready(container, max_wait=300)  # videos take a while to process
            else:
                container = ig.create(ig_id, row["image_url"], row["caption"] or "")
                ig.wait_ready(container)
            media = ig.publish(ig_id, container)
        except Exception as e:  # IGError, or anything unexpected: never retry blindly forever
            why = str(e) if isinstance(e, IGError) else f"{type(e).__name__}: {e}"
            log.error("Instagram post for %s failed (try %d): %s", row["slot"], row["attempts"] + 1, why)
            if row["attempts"] + 1 >= MAX_PUBLISH_ATTEMPTS:
                self._update_post(pid, status="failed", error=why[:300])
                self._set_buttons(row["tg_msg"], "❌ Not posted - see message")
                self.tg.text(f"❌ Couldn't post the {self.label(row['slot'])} post to Instagram:\n{why}\n\n"
                             "Post it by hand from the picture above if you still want it.", silent=self.asleep())
            else:
                self._update_post(pid, status="approved", error=why[:300])  # retried on the next check
            return
        self._update_post(pid, status="posted", ig_media=media)
        if row["kind"] == "queue":
            self.db.execute("UPDATE queue SET status='posted' WHERE id=?", (row["ref"],))
        link = self.ig().permalink(media)
        self._update_post(pid, permalink=link)
        log.info("Posted to Instagram: %s %s", row["slot"], link)
        self._set_buttons(row["tg_msg"], "✅ Posted on Instagram")
        self.tg.text(f"✅ Posted on Instagram · {self.label(row['slot'])}\n{link}\n"
                     "Reply to comments in the first 30 minutes if you can 💬", silent=self.asleep())
        self.host.delete(row["image_name"], row["image_sha"])

    def _drop_news_picture(self, row) -> None:
        if row["kind"] in ("news", "rumor"):
            self.host.delete(row["image_name"], row["image_sha"])

    # ---- one pass
    def run_slots(self) -> None:
        now = self.now()
        for key, dt in self.slots():
            ask_at, end = self.ask_at(key), dt + timedelta(minutes=self.cfg.late)
            rows = self.db.execute("SELECT * FROM posts WHERE slot=?", (key,)).fetchall()
            for r in rows:
                if r["status"] == "approved" and (now >= dt or r["post_now"]) and r["attempts"] < MAX_PUBLISH_ATTEMPTS:
                    self.publish(r)
                elif r["status"] == "proposed" and now > end:
                    self._update_post(r["id"], status="expired")
                    self._set_buttons(r["tg_msg"], "⌛ Not approved in time - not posted")
                    self._drop_news_picture(r)
                elif r["status"] == "publishing" and now > end + timedelta(minutes=30):
                    self._update_post(r["id"], status="failed", error="stopped while posting")
                    self.tg.text(f"⚠️ The {self.label(key)} post was interrupted while posting. "
                                 "Check Instagram: if it's not there, post it by hand.")
            if not (ask_at <= now <= end):
                continue
            if not rows:
                if not self.propose(key):
                    self.db.execute("INSERT INTO posts(slot, kind, status, created_at) VALUES(?,?,?,?)",
                                    (key, "none", "empty", R.iso(now)))
                    self.tg.text(f"🗓 {self.label(key)} post: nothing planned or new to offer yet. If news comes in "
                                 "before then I'll offer it; otherwise an approved standby Reel goes out.", silent=True)
            elif rows[-1]["status"] == "empty" and now < dt and not self.asleep():
                self.propose(key)  # fresh news since the "nothing to post" message: offer it

            rows = self.db.execute("SELECT * FROM posts WHERE slot=?", (key,)).fetchall()
            settled = any(r["status"] in ("approved", "publishing", "posted") for r in rows)
            # One reminder 30 minutes before a slot with nothing approved (CLAUDE.md 8.4) - not while asleep.
            if (not settled and dt - timedelta(minutes=30) <= now < dt and not self.asleep()
                    and R.meta_get(self.db, f"remind:{key}") is None):
                R.meta_set(self.db, f"remind:{key}", R.iso(now))
                bank = self._standby_bank_size()
                self.tg.text(f"⏰ The {self.label(key)} post isn't approved yet. Tap ✅ on it above"
                             + (f", or a standby Reel goes out ({bank} in the bank)." if bank else
                                " - the standby bank is empty, so the slot would stay empty."))
            # Never miss a posting time: nothing approved when the time comes -> the oldest approved standby Reel.
            # Only right at the posting time (checks run every 5 min); a standby going out an hour late would
            # break the 2-hours-between-posts rule, so a slot that's long past is left alone.
            if not settled and dt <= now <= dt + timedelta(minutes=15):
                self._use_standby(key, rows)

    def _standby_bank_size(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM posts WHERE slot=? AND status='approved'", (STANDBY,)).fetchone()[0]

    def _use_standby(self, key: str, rows) -> None:
        sb = self.db.execute("SELECT * FROM posts WHERE slot=? AND status='approved' ORDER BY id LIMIT 1",
                             (STANDBY,)).fetchone()
        if not sb:
            return
        for r in rows:  # whatever was still waiting for this slot can't be approved any more
            if r["status"] == "proposed":
                self._update_post(r["id"], status="expired")
                self._set_buttons(r["tg_msg"], "⌛ Not approved in time - a standby Reel went out")
                self._drop_news_picture(r)
        self._update_post(sb["id"], slot=key)
        log.info("Slot %s had nothing approved: using standby post %s", key, sb["plan_id"])
        self.tg.text(f"🗄 Nothing was approved for {self.label(key)}, so your approved standby Reel "
                     f"\"{sb['plan_id']}\" is going out now.", silent=self.asleep())
        self.publish(self._post(sb["id"]))

    def reopen_open_slots(self) -> None:
        """After something is added to the queue: offer it for a slot that currently has nothing planned."""
        for key, _ in self.slots():
            if self.in_window(key):
                active = self.db.execute(
                    f"SELECT 1 FROM posts WHERE slot=? AND status IN {ACTIVE} LIMIT 1", (key,)).fetchone()
                if not active:
                    self.propose(key)

    # ---- Telegram messages and buttons
    def process_updates(self) -> None:
        offset = int(R.meta_get(self.db, "tg_offset", "0") or 0)
        updates = self.tg.api("getUpdates", {"offset": offset, "timeout": 0,
                                             "allowed_updates": json.dumps(["message", "callback_query"])}, quiet=True)
        for upd in updates or []:
            R.meta_set(self.db, "tg_offset", upd["update_id"] + 1)
            try:
                if "callback_query" in upd:
                    self._on_button(upd["callback_query"])
                elif "message" in upd:
                    self._on_message(upd["message"])
            except Exception:
                log.exception("Could not handle a Telegram message")

    def _is_owner(self, chat: dict | None) -> bool:
        return chat is not None and str(chat.get("id")) == str(self.s.chat_id)

    def _on_button(self, cq: dict) -> None:
        msg = cq.get("message") or {}
        if not self._is_owner(msg.get("chat")):
            return
        data = cq.get("data") or ""
        action, _, pid = data.partition(":")
        row = self._post(int(pid)) if pid.isdigit() else None
        if not row or row["status"] != "proposed":
            self.tg.api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Already handled"}, quiet=True)
            return
        key, t = row["slot"], self.label(row["slot"])
        if key != STANDBY and self.now() > self.slot_dt(key) + timedelta(minutes=self.cfg.late):
            self._update_post(row["id"], status="expired")
            self._set_buttons(row["tg_msg"], "⌛ Too late - not posted")
            self._drop_news_picture(row)
            return
        if action == "now":  # breaking news / "post it now": approval + publish straight away
            self._update_post(row["id"], status="approved", post_now=1)
            self.tg.api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Posting now"}, quiet=True)
            self._set_buttons(row["tg_msg"], "🚀 Approved · posting now")
            log.info("Post now: %s post (%s)", key, row["plan_id"] or row["ref"])
            self.publish(self._post(row["id"]))
            return
        if action == "ok" and key == STANDBY:
            self._update_post(row["id"], status="approved")
            self.tg.api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "In the standby bank"}, quiet=True)
            self._set_buttons(row["tg_msg"], f"✅ In the standby bank ({self._standby_bank_size()} ready)")
            return
        if action == "skip" and key == STANDBY:
            self._update_post(row["id"], status="skipped")
            self.tg.api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Not used"}, quiet=True)
            self._set_buttons(row["tg_msg"], "⏭ Not used")
            return
        if action == "ok":
            self._update_post(row["id"], status="approved")
            when = "posting now" if self.now() >= self.slot_dt(key) else f"posts at {t}"
            self.tg.api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": f"Approved - {when}"}, quiet=True)
            self._set_buttons(row["tg_msg"], f"✅ Approved · {when}")
            log.info("Approved: %s post (%s #%s)", key, row["kind"], row["ref"])
        elif action == "skip":
            self._update_post(row["id"], status="skipped")
            self.tg.api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": "Skipped"}, quiet=True)
            self._set_buttons(row["tg_msg"], "⏭ Skipped")
            self._drop_news_picture(row)
            if not self.propose(key):
                self.tg.text(f"No more options for {t}, so nothing will be posted then.\n"
                             "Send me a photo with a caption and I'll offer it.", silent=True)

    def _on_message(self, msg: dict) -> None:
        if not self._is_owner(msg.get("chat")):
            return
        text = (msg.get("text") or "").strip()
        if msg.get("photo") or (msg.get("document") or {}).get("mime_type", "").startswith("image/"):
            self._add_to_queue(msg)
        elif text.startswith("/"):
            cmd, _, rest = text.partition(" ")
            cmd = cmd.split("@")[0].lower()
            if cmd in ("/start", "/help"):
                self.tg.text(HELP)
            elif cmd == "/queue":
                self._show_queue()
            elif cmd == "/remove":
                self._remove(rest.strip().lstrip("#"))
            elif cmd == "/caption":
                n, _, new = rest.strip().partition(" ")
                self._recaption(n.lstrip("#"), new.strip())
            elif cmd == "/status":
                self._status()
            else:
                self.tg.text("I don't know that command. Send /help for the list.")

    def _add_to_queue(self, msg: dict) -> None:
        if not self.host.ready:
            self.tg.text("Can't add it: picture hosting isn't set up yet (see README section 10).")
            return
        file_id = msg["photo"][-1]["file_id"] if msg.get("photo") else msg["document"]["file_id"]
        f = self.tg.api("getFile", {"file_id": file_id})
        if not f or not f.get("file_path"):
            self.tg.text("❌ Couldn't download that picture from Telegram (too big? max 20 MB). Try again.")
            return
        raw = requests.get(f"https://api.telegram.org/file/bot{self.s.token}/{f['file_path']}", timeout=60).content
        try:
            data = ig_ready_jpeg(raw, R.hex_rgb(self.s.bg))
        except Exception:
            self.tg.text("❌ That file isn't a picture I can read. Send a JPG or PNG.")
            return
        name = f"queue-{uuid.uuid4().hex[:12]}.jpg"
        url, sha = self.host.upload(data, name)
        caption = (msg.get("caption") or "").strip()
        cur = self.db.execute(
            "INSERT INTO queue(caption, image_name, image_url, image_sha, status, added_at) VALUES(?,?,?,?,?,?)",
            (caption, name, url, sha, "queued", R.iso(self.now())))
        pos = self.db.execute("SELECT COUNT(*) FROM queue WHERE status='queued'").fetchone()[0]
        note = "" if caption else "\n(No caption. Add one with /caption {n} your text)".format(n=cur.lastrowid)
        self.tg.text(f"✅ Added to your queue as #{cur.lastrowid} (number {pos} in line).\n"
                     f"I'll offer it at a posting time when there's no news.{note}")
        log.info("Queue: added #%s", cur.lastrowid)
        self.reopen_open_slots()

    def _show_queue(self) -> None:
        rows = self.db.execute("SELECT * FROM queue WHERE status='queued' ORDER BY id").fetchall()
        if not rows:
            self.tg.text("Your queue is empty. Send me a photo with a caption to add a post.")
            return
        lines = [f"📋 Your queue ({len(rows)}):"]
        for r in rows:
            cap = (r["caption"] or "(no caption)").replace("\n", " ")
            lines.append(f"#{r['id']} · {cap[:70]}{'…' if len(cap) > 70 else ''}")
        self.tg.text("\n".join(lines))

    def _remove(self, n: str) -> None:
        row = self.db.execute("SELECT * FROM queue WHERE id=? AND status='queued'", (n,)).fetchone() if n.isdigit() else None
        if not row:
            self.tg.text("No queued post with that number. Send /queue to see the numbers.")
            return
        self.db.execute("UPDATE queue SET status='removed' WHERE id=?", (row["id"],))
        for p in self.db.execute("SELECT * FROM posts WHERE kind='queue' AND ref=? AND status='proposed'", (row["id"],)):
            self._update_post(p["id"], status="skipped")
            self._set_buttons(p["tg_msg"], "🗑 Removed from queue")
        self.host.delete(row["image_name"], row["image_sha"])
        self.tg.text(f"🗑 Removed #{row['id']} from the queue.")

    def _recaption(self, n: str, new: str) -> None:
        if not n.isdigit() or not new:
            self.tg.text("Write it like this:  /caption 3 Your new caption")
            return
        row = self.db.execute("SELECT * FROM queue WHERE id=? AND status='queued'", (n,)).fetchone()
        if not row:
            self.tg.text("No queued post with that number. Send /queue to see the numbers.")
            return
        self.db.execute("UPDATE queue SET caption=? WHERE id=?", (new, row["id"]))
        changed = self.db.execute("UPDATE posts SET caption=? WHERE kind='queue' AND ref=? AND status IN ('proposed','approved')",
                                  (new, row["id"])).rowcount
        self.tg.text(f"✏️ Caption of #{row['id']} changed." + (" (Also for the post waiting for approval.)" if changed else ""))

    def _status(self) -> None:
        today = self.now().astimezone(self.cfg.tz).date().isoformat()
        lines = [f"🗓 Today's posting times for {self.s.handle}:"]
        for t in self.cfg.times:
            key = f"{today} {t}"
            t = self.label(key)
            rows = self.db.execute("SELECT status FROM posts WHERE slot=? ORDER BY id", (key,)).fetchall()
            st = rows[-1]["status"] if rows else "not asked yet"
            lines.append(f"  {t} - {st}")
        q = self.db.execute("SELECT COUNT(*) FROM queue WHERE status='queued'").fetchone()[0]
        lines.append(f"\nQueue: {q} post(s) waiting.")
        exp = R.from_iso(R.meta_get(self.db, "ig_token_expires") or None)
        if exp:
            lines.append(f"Instagram token valid until {exp.astimezone(R.IST).strftime('%d %b')} (renews itself).")
        self.tg.text("\n".join(lines))


# --------------------------------------------------------------------------- entry points

def _get(radar: R.Radar) -> AutoPost:
    if not hasattr(radar, "_autopost"):
        radar._autopost = AutoPost(radar)
    return radar._autopost


def tick(radar: R.Radar) -> None:
    """Called by --loop (every 20 s) and --once (each cloud run). Never raises."""
    try:
        ap = _get(radar)
        if not ap.cfg.enabled:
            return
        probs = ap.problems()
        if probs:
            log.warning("Auto-posting is on but not ready: %s", "; ".join(probs))
            ap.warn_once("ap_setup", "⚠️ Auto-posting is turned on but not ready:\n- " + "\n- ".join(probs))
            return
        ap.process_updates()
        ap.run_slots()
        ap.propose_standby()
        ap.tokens.maybe_refresh()
    except Exception:
        log.exception("Auto-posting error (the news radar keeps running)")


def check_setup(radar: R.Radar) -> int:
    """--ig-check: test every part of auto-posting WITHOUT posting anything."""
    ap = _get(radar)
    ok = True

    def line(name: str, good: bool, note: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"  {'OK  ' if good else 'FAIL'}  {name}{' - ' + note if note else ''}")

    print("\nAuto-posting check (nothing will be posted):")
    line("config.yaml autopost", bool(ap.cfg.times),
         f"enabled={ap.cfg.enabled}, times {', '.join(ap.cfg.times) or 'none'} {ap.cfg.tz_label}, "
         f"ask {ap.cfg.ask_before} min before, not between {'-'.join(ap.cfg.sleep or ()) or '(any time)'} IST")
    line("Telegram", ap.s.telegram_ready)
    token = ap.tokens.get()
    if not token:
        line("Instagram token", False, "INSTAGRAM_ACCESS_TOKEN missing")
        return 1
    ig = ap.ig()
    try:
        me = ig.me()
        line("Instagram account", bool(me.get("username")), f"@{me.get('username')} ({me.get('account_type')})")
        R.meta_set(ap.db, "ig_user_id", str(me.get("user_id") or me.get("id")))
        R.meta_set(ap.db, "ig_username", me.get("username", ""))
        ap._ig_id = None
    except IGError as e:
        line("Instagram account", False, str(e))
        return 1
    if not ap.host.ready:
        line("Picture hosting (GitHub)", False, "GITHUB_TOKEN / autopost.github_repo missing")
        return 1
    img = Image.new("RGB", (1080, 1350), R.hex_rgb(ap.s.bg))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=80)
    name = f"setup-check-{uuid.uuid4().hex[:8]}.jpg"
    try:
        url, sha = ap.host.upload(buf.getvalue(), name)
        ctype = requests.head(url, timeout=15).headers.get("content-type", "")
        line("Picture hosting (GitHub)", ctype.startswith("image/"), f"{url} ({ctype})")
    except Exception as e:
        line("Picture hosting (GitHub)", False, str(e))
        return 1
    try:
        container = ig.create(ap.ig_id(ig), url, "setup check - not published")
        ig.wait_ready(container)
        line("Instagram accepts the picture", True, "container made and ready; NOT published")
    except IGError as e:
        line("Instagram accepts the picture", False, str(e))
    finally:
        ap.host.delete(name, sha)
    print("\nAll good - auto-posting is ready." if ok else "\nSomething needs fixing - see FAIL above.")
    return 0 if ok else 1
