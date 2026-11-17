LOBBY NEWS RADAR - for @thelobby.report
========================================

What it does
------------
Every few minutes the radar checks official sources (Rockstar, Take-Two, Call of Duty,
PlayStation, Xbox) and trusted outlets (IGN, GameSpot) for anything new about GTA VI and
Call of Duty: Modern Warfare 4 / Warzone. It also watches Reddit for big rumours.

When something new appears, your phone gets a Telegram alert within minutes. For OFFICIAL and
REPORTED news it also makes a ready-to-post draft in the "drafts" folder:
  card.png      1080x1350 post image
  story.png     1080x1920 story image
  caption.txt   caption with source credit and hashtags
  source.txt    the link and times (for you to check)

Every alert is labelled:
  OFFICIAL  = from the game company itself. Safe to post.
  REPORTED  = from a news site. Post it, but keep the "Reported by ..." line.
  RUMOR     = Reddit. NEVER post as fact. No draft is made.

It never posts to Instagram for you (that's against Instagram's rules and risky for the page).


1. INSTALL (one time)
---------------------
a) Install Python from https://www.python.org/downloads/
   IMPORTANT: on the first installer screen tick "Add python.exe to PATH".
b) Open this folder in File Explorer. Click the address bar, type  cmd  and press Enter.
c) In the black window type this and press Enter:
       pip install -r requirements.txt
   Wait until it finishes.


2. CREATE THE TELEGRAM BOT (one time)
-------------------------------------
a) In Telegram, search for  @BotFather  (blue tick) and open it.
b) Send:  /newbot   Give it any name (e.g. "Lobby Radar") and a username ending in "bot".
c) BotFather replies with a TOKEN that looks like  1234567890:AAH...  Copy it.
d) Open your new bot in Telegram and send it any message (e.g. "hi"). This step is needed.
e) Get your CHAT ID: open this address in a browser (put your token after "bot"):
       https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   Look for  "chat":{"id":123456789  - that number is your chat ID.
f) In this folder, copy ".env.example" and rename the copy to ".env"
   (if Windows hides the name, open it with Notepad and use File > Save As > ".env").
   Open .env with Notepad and fill in:
       TELEGRAM_BOT_TOKEN=your token
       TELEGRAM_CHAT_ID=your chat ID
   Save. Never share the .env file with anyone.


3. TEST
-------
Double-click  test_radar.bat
You should get on your phone:
  - "Test message from Lobby News Radar..."
  - a sample card (it says TEST CARD - don't post it)
Then the window shows a table of all sources. Each one should say OK.
The sample draft is in the "drafts" folder (name starts with TEST_). You can delete it.


4. START
--------
Double-click  run_radar.bat  and leave the window open (you can minimise it).
Your phone gets a quiet "Radar started" message.
If the radar ever crashes, the window restarts it by itself after 30 seconds.
To stop it, close the window.

The first time it runs it marks everything already on the sources as "seen", so you
don't get 200 old alerts. After that you only get NEW items.

Start it automatically with Windows:
  a) Press the Windows key, type  Task Scheduler  and open it.
  b) Click "Create Basic Task...". Name: Lobby News Radar. Next.
  c) Trigger: "When I log on". Next.
  d) Action: "Start a program". Next.
  e) Program/script: click Browse and pick  run_radar.bat  in this folder.
     "Start in": paste this folder's path (e.g. C:\Users\you\lobby-news-radar). Next, Finish.

IMPORTANT: the radar only works while the PC is ON and ONLINE.
  Settings > System > Power > Screen and sleep > "When plugged in, put my device to sleep
  after": Never.
(Want it to work while the PC is off? See section 9, "Run in the cloud".)


5. WHEN AN ALERT ARRIVES (speed playbook)
-----------------------------------------
You get the card as a photo with the alert text, then a second message with the caption
(press and hold to copy it).

  HIGH + OFFICIAL  -> within 5 minutes:
       1. Post story.png to your story.
       2. Post card.png as a post, with the caption from caption.txt (or the Telegram message).
  REPORTED         -> same, but keep the "Reported by ..." line.
  RUMOR (⚠️)       -> DON'T post as fact. At most a story poll: "Real or fake? 👀"
  Then reply to comments for the first 30 minutes.

Alert levels:
  🚨 HIGH    trailer, release date, delay, pre-orders, new season, reveal, price, new map/mode
             (always makes a sound, even at night)
  🔔 MEDIUM  patch notes, events, playlists, Double XP, Battle Pass
  📰 LOW     everything else - sent once a day in the digest (21:30 IST)

The drafts are also saved on the PC in the "drafts" folder (one folder per news item).
Always glance at the headline before posting: it only uses the source's own words, but
you are the editor.

Optional - AI captions: if you have an Anthropic API key, put it in .env as
ANTHROPIC_API_KEY=... and each draft also gets 3 extra caption ideas written only from the
source text (sent as a separate Telegram message, and added to caption.txt under
"AI options (check before posting)"). Leave it empty to turn this off.


6. TURN ON INSTAGRAM POST NOTIFICATIONS
---------------------------------------
The radar can't watch Instagram or X/Twitter (they block it). So on your phone, open each of
these profiles, tap the bell icon and turn on Posts (and Stories/Reels if you like):
  @rockstargames    @callofduty    @charlieintel


7. EDITING SOURCES AND KEYWORDS
-------------------------------
Open  sources.yaml  with Notepad.
  - Each source is a block starting with "- name:". To turn one off, change
        enabled: true    to    enabled: false
  - Keywords are at the top under "keywords:". "names" are words that always mean the
    game (like "GTA VI"); "topics" are only used on Call of Duty-only sources.
Open  config.yaml  for timing, quiet hours, digest time and priority words.
  - quiet_hours_ist: ["01:00","05:30"]  makes MEDIUM/LOW silent at night. HIGH always rings.
Keep the spacing at the start of lines exactly as it is (spaces, not tabs).
After any change, close run_radar.bat and start it again.

Sources currently turned off (and why) - see the comments in sources.yaml:
  - Rockstar Newswire: the page is built by JavaScript and can't be read reliably.
    Rockstar trailers still come in through the Rockstar YouTube feed.
  - Charlie Intel: its feed and website have not had a new article since January 2025.
  - Reddit "News/Official flair" searches: Reddit now blocks these without a login.
    Reddit rumours still come in through the "top today" feeds.


8. TROUBLESHOOTING
------------------
No alerts at all?
  - Is the run_radar.bat window open? Is the PC awake and online?
  - Double-click test_radar.bat. If the test message doesn't arrive, see "Telegram" below.
  - Open radar.log (in this folder) with Notepad and read the last lines.
  - Quiet news day? LOW items only come in the 21:30 digest.

A source is failing?
  - The table from test_radar.bat shows FAIL and the reason. radar.log has details.
  - One failing source never stops the others. If a source fails for about 30 minutes in a
    row you get a quiet Telegram warning, and another message when it works again.
  - If a site changed for good, set  enabled: false  for it in sources.yaml.

Telegram not sending?
  - radar.log says what's wrong:
      "token in .env is wrong"   -> copy the token from BotFather again.
      "chat ID ... is wrong"     -> redo step 2e, and make sure you sent your bot a message.
  - Check .env has no spaces or quotes around the values.
  - Alerts that couldn't be sent (e.g. internet dropped) are retried for 6 hours.

"The radar is already running in another window"?
  - Only one radar can run at a time (otherwise every alert comes twice). Close the other
    window first.

PC went to sleep?
  - Power settings: never sleep while plugged in (see section 4).

Start fresh (forget everything seen so far)?
  - Close the radar, delete radar.db, start again. The first run marks everything as seen.


9. RUN IN THE CLOUD (works while the PC is off)
-----------------------------------------------
This is already set up. GitHub Actions runs one check about every 5 minutes on GitHub's
computers, for free (the repository is public; your token and chat ID are kept secret in
GitHub Secrets and are NOT in the code).

  - GitHub's timer is often a few minutes late, so the PC is still a bit faster when it's on.
  - Don't run run_radar.bat on the PC while the cloud is on: you'd get every alert twice.
    To use the PC instead: GitHub > your repository > Actions > Lobby News Radar >
    "..." (top right) > Disable workflow. Click "Enable workflow" to switch back.
  - In the cloud there is no drafts folder, so the story image is also sent to Telegram
    (save both pictures from Telegram to your phone). Full-quality files are on the run's
    page in the Actions tab under "Artifacts" for 3 days.
  - The daily digest (21:30 IST) is sent by the first check after 21:30.
  - The workflow file is .github/workflows/radar.yml. Seen items are kept between runs in
    the Actions cache (Actions > Caches). Deleting those caches = start fresh.
  - Changed sources.yaml or config.yaml? Upload the new file to the repository (or ask
    Claude Code to push it). The next run uses it.
  - Run a check now: Actions > Lobby News Radar > Run workflow.
