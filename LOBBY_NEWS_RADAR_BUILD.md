# Lobby Report News Radar — Build Spec for Claude Code

> **How to use this file:** put it in an empty folder (e.g. `lobby-news-radar`), open the
> folder in VS Code, open Claude Code and type:
> `Read LOBBY_NEWS_RADAR_BUILD.md and build the whole project exactly as specified. Ask me for my Telegram bot token and chat ID when you need them. Test everything before you finish.`

---

## 1. Goal

Make **@thelobby.report** (Instagram gaming page, US/UK audience) the **first page to post**
when anything new happens with **GTA VI** or **Call of Duty: Modern Warfare 4 / Warzone**.

The radar must:
1. **Watch official sources** (and a few trusted community sources) every few minutes.
2. **Alert the owner's phone instantly** via Telegram when something new appears.
3. **Auto-prepare a ready-to-post draft**: a branded 1080×1350 news card, a 1080×1920 story,
   and a caption, so the owner can post from the phone within ~2 minutes.
4. **Never present rumours as facts.** Every item is labelled by source reliability.

The owner is on **Windows**, is not a developer, and posts from his phone or laptop.
It must be simple to start (double-click), and clear when something is wrong.

---

## 2. Tech stack

- Python 3.10+
- Libraries: `requests`, `feedparser`, `beautifulsoup4`, `Pillow`, `python-dotenv`, `pyyaml`
  (install with `pip install -r requirements.txt`)
- Storage: SQLite (`radar.db`) for seen items
- Alerts: Telegram Bot API (free)
- Optional: Anthropic API for better captions (only if `ANTHROPIC_API_KEY` is set)
- No auto-posting to Instagram (against Instagram rules and risky for the account).

---

## 3. Folder structure

```
lobby-news-radar/
├── radar.py               # main program
├── sources.yaml           # all sources + keywords (owner can edit)
├── config.yaml            # timing, priorities, brand settings
├── .env                   # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, (optional) ANTHROPIC_API_KEY
├── .env.example
├── requirements.txt
├── run_radar.bat          # double-click: runs the radar in a loop
├── test_radar.bat         # double-click: one check + a test Telegram message
├── assets/fonts/          # put a bold font here (fallback to system fonts)
├── drafts/                # one folder per news item with card.png, story.png, caption.txt
├── radar.db
├── radar.log
└── README.txt             # step-by-step guide (section 11)
```

---

## 4. Sources (`sources.yaml`)

**Important for Claude Code:** verify every URL works at build time. Where a site offers
an RSS/Atom feed, use it; otherwise poll the page and parse article links. For YouTube,
look up the real channel IDs and use
`https://www.youtube.com/feeds/videos.xml?channel_id=<ID>`. If a source can't be fetched
reliably, disable it in `sources.yaml` with a comment instead of guessing.

Each source has: `name`, `url`, `type` (rss | page | youtube | reddit), `game` (gta6 | mw4 | both),
`tier` (OFFICIAL | REPORTED | RUMOR), `keywords` filter (optional), `enabled`.

### Tier OFFICIAL (publish-ready)
| Source | Game | Notes |
|---|---|---|
| Rockstar Newswire `https://www.rockstargames.com/newswire` | gta6 | filter by GTA VI keywords |
| Rockstar Games YouTube channel (RSS) | gta6 | trailers |
| Take-Two investor news `https://ir.take2games.com/news-releases` | gta6 | release-date / earnings confirmations |
| Call of Duty blog `https://www.callofduty.com/blog` | mw4 | seasons, maps, events, patch notes |
| Call of Duty YouTube channel (RSS) | mw4 | trailers |
| PlayStation Blog RSS `https://blog.playstation.com/feed/` | both | keyword filter |
| Xbox Wire RSS `https://news.xbox.com/en-us/feed/` | both | keyword filter |

### Tier REPORTED (reliable outlets: post with "Reported by …" credit)
| Source | Game |
|---|---|
| Charlie Intel (RSS if available) | mw4 |
| IGN / GameSpot news RSS (keyword-filtered) | both |

### Tier RUMOR (alert only, NEVER auto-draft as fact)
| Source | Game | Notes |
|---|---|---|
| Reddit `https://www.reddit.com/r/GTA6/new.json` | gta6 | only posts with score ≥ 300 or "Official"/"News" flair |
| Reddit `https://www.reddit.com/r/CallOfDuty/new.json` | mw4 | same rule |

Reddit: send a descriptive `User-Agent`, respect rate limits, poll no more than every 10 minutes.

**Do not** scrape Instagram or X/Twitter (blocked/against their rules). The README tells the
owner to turn on post notifications for @rockstargames, @callofduty and @charlieintel instead.

### Keywords
- **gta6:** "GTA 6", "GTA VI", "Grand Theft Auto VI", "Leonida", "Vice City", "Lucia", "Jason",
  "trailer", "pre-order", "release date"
- **mw4:** "Modern Warfare 4", "MW4", "Warzone", "DMZ", "Season 1", "Season 2", "Reloaded",
  "patch notes", "Double XP", "playlist", "Battle Pass"

Matching is case-insensitive on title + summary.

---

## 5. How a check works (`radar.py`)

For each enabled source:
1. Fetch with a timeout (15 s), a normal browser-like `User-Agent`, and retries (2).
2. Parse items: `title`, `url`, `published`, `summary`.
3. Keyword filter (if the source has one).
4. **Dedupe:** skip if the URL (normalised, without tracking params) or the
   title (lowercased, punctuation removed) is already in `radar.db`.
5. **Priority:**
   - **HIGH:** trailer, release date, delay, pre-order, new season/season launch, reveal,
     price, new map/mode announcement
   - **MEDIUM:** patch notes, events, playlists, Double XP, Battle Pass
   - **LOW:** everything else
6. Save to `radar.db` (`id, source, tier, game, priority, title, url, published, found_at, status`).
7. For OFFICIAL and REPORTED items: build a **draft** (section 6).
8. Send the **Telegram alert** (section 7).

On the very first run, mark everything currently on the sources as "seen" **without alerting**
(so the owner doesn't get 200 old alerts). Log it.

Run modes:
- `python radar.py --once`: one check, then exit
- `python radar.py --loop`: checks forever; interval from `config.yaml` (default **5 minutes**;
  Reddit sources every 10 minutes)
- `python radar.py --test`: send a test Telegram message + render a sample draft from a fake item
- `python radar.py --digest`: send a summary of today's LOW items

All errors go to `radar.log`; one failing source must never stop the others.

---

## 6. Draft generation (`drafts/<YYYY-MM-DD_HHMM>_<slug>/`)

For each OFFICIAL/REPORTED item:
1. Fetch the article page and read `og:title`, `og:description`, `og:image`.
   Download `og:image` (official press image) → `source_image.jpg`.
2. **Headline:** a short, punchy, TRUE headline from the title (≤ 60 characters), e.g.
   "GTA VI TRAILER 3 IS OUT" only if the source says so. Never invent details.
3. **Summary:** the first 1–2 sentences of the source description, trimmed to ~200 characters.
4. **`card.png` (1080×1350, Instagram post)**, in the page's brand style:
   - background `#0B0D10`, accent lime `#C6FF3D`, white text, bold heavy italic headline
   - top bar: game tag ("GTA VI" or "MW4") in lime, left; time-ago or date, right
   - image: `og:image` fitted to 1080×608 under the top bar, lime 8 px line below it
   - label pill: **OFFICIAL** (lime) or **REPORTED** (white outline)
   - headline (wrapped, max 3 lines), summary in grey
   - footer: `Source: <source name>` + `@thelobby.report`
   - if there is no image: big headline on a dark card with a lime frame
5. **`story.png` (1080×1920):** same content stacked vertically; keep the top 250 px and the
   bottom 300 px free for Instagram's buttons.
6. **`caption.txt`:**
   ```
   <Headline in sentence case>. <Summary>

   Source: <Source name>
   What do you think? 👇

   <3 hashtags>
   ```
   Hashtags: gta6 → `#GTA6 #GTAVI #RockstarGames`; mw4 → `#MW4 #CallofDuty #ModernWarfare4`.
   For REPORTED items, start with "Reported by <outlet>:".
   **No #ad and no @callofduty tag**: these are news posts, not campaign clips.
7. **Optional, if `ANTHROPIC_API_KEY` is set:** ask Claude to write 3 caption options and
   1 on-screen headline **using only facts in the fetched source text**, and append them to
   `caption.txt` under "AI options (check before posting)". If the call fails, skip silently.
8. `source.txt`: URL, tier, published time, found time.

Fonts: use the first `.ttf/.otf` in `assets/fonts/`, else common bold system fonts
(Windows Arial Bold / Segoe UI Bold, macOS Arial Bold, Linux DejaVu Sans Bold).

---

## 7. Telegram alerts

Setup (in README): owner creates a bot with **@BotFather** → gets the token; sends any message
to the bot; Claude Code helps him get the chat ID from
`https://api.telegram.org/bot<TOKEN>/getUpdates`. Both go into `.env` (never printed in logs,
never committed).

Alert format:
```
🚨 HIGH · OFFICIAL · GTA VI
<Title>
<Source> · <time found>
<URL>
```
- For OFFICIAL/REPORTED: send `card.png` as a photo with the text as its caption, then the
  caption text as a separate message (easy copy).
- For RUMOR: text only, prefixed `⚠️ RUMOR, don't post as fact`.
- HIGH = normal notification, MEDIUM = normal, LOW = silent (`disable_notification=true`)
  and also included in the daily digest.

---

## 8. Config (`config.yaml`)

```yaml
check_every_minutes: 5
reddit_every_minutes: 10
quiet_hours_ist: null          # e.g. ["01:00","05:30"] to make LOW/MEDIUM silent at night
send_low_priority: false       # LOW only in the daily digest
digest_time_ist: "21:30"
brand:
  handle: "@thelobby.report"
  bg: "#0B0D10"
  accent: "#C6FF3D"
```
HIGH alerts are **never** silenced. Big news drops at night in India.

---

## 9. Running it

- `run_radar.bat`: activates the folder, runs `python radar.py --loop`, restarts after a
  crash (loop in the .bat with a 30-second pause), keeps the window open.
- `test_radar.bat`: `python radar.py --test` then `--once`.
- README explains how to make it start with Windows (Task Scheduler → "At log on" →
  run `run_radar.bat`) and that the **PC must be on and online**.
- **Optional (section in README): run in the cloud** with GitHub Actions on a 5-minute cron so
  it works while the PC is off: store secrets in GitHub Secrets and keep `radar.db` as an
  Actions cache or commit it. Note that GitHub cron can be delayed a few minutes.

---

## 10. Rules built into the tool

- Only OFFICIAL/REPORTED items get drafts. RUMOR is alert-only and clearly labelled.
- Headlines and captions must only state what the source says. No invented dates, prices or features.
- Always credit the source on the card and in the caption.
- Use only official press images (`og:image` from the source article). Never leaked footage.
- No auto-posting to Instagram.

---

## 11. `README.txt` (plain English, CRLF line endings)

1. **Install** (Python with "Add to PATH", `pip install -r requirements.txt`)
2. **Create the Telegram bot** (BotFather → token → message the bot → chat ID → `.env`)
3. **Test:** double-click `test_radar.bat`. You should get a test alert + sample card.
4. **Start:** double-click `run_radar.bat` and leave it running
5. **When an alert arrives (speed playbook):**
   - HIGH + OFFICIAL → within 5 minutes: post `story.png` to your story, then post
     `card.png` as a post with the caption from `caption.txt`
   - REPORTED → same, keep the "Reported by …" line
   - RUMOR → don't post as fact; at most a story poll: "Real or fake? 👀"
   - Reply to comments for the first 30 minutes
6. **Turn on Instagram post notifications** for @rockstargames, @callofduty, @charlieintel
7. **Editing sources/keywords:** `sources.yaml` (one line per source; `enabled: false` to turn off)
8. **Troubleshooting:** no alerts (check `radar.log`, test bat), a source failing,
   Telegram not sending (token/chat ID), PC asleep (power settings: never sleep while plugged in)

---

## 12. Testing — do this before saying it's finished

1. `pip install -r requirements.txt` succeeds.
2. Each enabled source fetches and parses at least one item (print a table: source, items, OK/FAIL).
   Disable any that fail, with a comment explaining why.
3. First run marks existing items as seen and sends **no** alerts.
4. Insert a fake new OFFICIAL GTA VI item and a fake MW4 item → drafts are created → open
   `card.png` and `story.png` and **look at them**: text readable, nothing cut off, image
   fitted, brand colours right.
5. Run `--once` twice: the second run must not re-alert (dedupe works).
6. A fake RUMOR item → alert text has the ⚠️ RUMOR prefix and no draft folder.
7. With the owner's token and chat ID: `--test` delivers the message and the card photo.
8. A source returning an error doesn't crash the run (simulate with a bad URL).
9. Clean up test drafts and reset `radar.db` (then re-run the "first run" seen-marking).

Finish with a short summary: which sources are active, how to start it, and how alerts look.

---

## 13. Don'ts
- Don't post to Instagram automatically or log in to Instagram.
- Don't scrape Instagram or X.
- Don't put tokens or keys in code, logs, or anything committed.
- Don't draft RUMOR items as news.
- Don't hardcode URLs or YouTube channel IDs you haven't verified.
