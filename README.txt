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

It never logs in to Instagram with your password (that's against Instagram's rules and risky
for the page). Optional: scheduled posts at fixed times through Instagram's OFFICIAL API, only
after you tap Approve in Telegram - see section 10.


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


10. SCHEDULED INSTAGRAM POSTS (13:00, 16:00, 20:00 New York time)
-------------------------------------------------------------------
Times are set in New York time because the page is for a US/UK audience:
  13:00 New York = 18:00 London  (UK evening, US lunch)
  16:00 New York = 21:00 London  (UK prime time, US after school/work)
  20:00 New York = 01:00 London  (US prime time)
They follow US daylight saving by themselves. In India that is 23:30, 02:30, 06:30 in winter
(22:30, 01:30, 05:30 in summer).

How it works
  - Before each time the Telegram bot sends you a post: the best OFFICIAL or REPORTED news
    from the last 12 hours that wasn't offered yet or, if there's none, the next post from
    YOUR queue.
  - Normally that's 30 minutes before. But you're never asked between 00:00 and 06:00 India
    time: posts that go out while you sleep are asked about at 23:45, before bed.
  - Tap  ✅ Approve  -> it goes on @thelobby.report at that time (even while you sleep).
    Tap  ⏭ Skip     -> the bot shows you the next option.
    No tap          -> nothing is posted. NOTHING is ever posted without your Approve.
  - Approved late (up to 90 minutes after the time)? It's posted right away.
  - "Nothing to post" message, then news comes in before the time? It's offered then
    (but never while you sleep).
  - RUMOR items are never offered.
  - Each message shows both times, e.g. "16:00 New York (02:30 IST)".
  - In the cloud a tap is picked up at the next check, so give it up to ~10 minutes.
    GitHub's timer can also make a post go out a few minutes after the exact time.
  - Messages that arrive while you sleep (like "Posted") are silent.
  - Who sees the posts is NOT affected by any of this setup: posts made through Instagram's
    official API look exactly like posts made in the app.

Your own posts (the queue)
  - Send the bot a photo with the caption written underneath. It replies "Added to your queue".
    Send it as a File (paperclip > File) to keep full quality.
  - Pictures that are too tall/wide for Instagram get dark bars added, never cropped.
  - /queue  list   ·  /remove 3  delete #3  ·  /caption 3 new text  change a caption
    /status  today's times  ·  /help
  - Note: the repository is public, so a queued picture can be seen on GitHub (in the
    "media" branch) until it's posted. Don't queue anything secret.

Setting it up (one time)
  a) Instagram app > your profile > menu > Settings > "Account type and tools" >
     "Switch to professional account" (Creator or Business, both free). Keep the account public.
  b) On a computer go to https://developers.facebook.com and log in with FACEBOOK
     (not Instagram). Register as a developer if asked.
  c) My Apps > Create app. Name: Lobby Radar. Use case: "Manage messaging & content on
     Instagram". Business portfolio: The Lobby Report.
  d) Use cases > Customize > Permissions and features: Add  instagram_business_basic  and
     instagram_business_content_publish.
  e) App roles > Roles > add  thelobby.report  as an Instagram Tester. Accept the invite at
     https://www.instagram.com/accounts/manage_access/ (Tester invites tab).
  f) Use cases > Customize > API setup with Unified login > "2. Generate access tokens" >
     Add account (log in as @thelobby.report) > Generate token. Copy the token.
  g) Paste it into .env:   INSTAGRAM_ACCESS_TOKEN=the token
     Then ask Claude Code to "finish the Instagram setup". It tests everything WITHOUT
     posting (python radar.py --ig-check), stores the token in GitHub Secrets and switches
     auto-posting on (config.yaml > autopost > enabled: true).

  If the token can expire, the radar renews it by itself. If renewing ever fails you get a
  Telegram warning: repeat step f) and g).

Change the times or time zone: config.yaml > autopost > timezone / times / owner_sleep_ist.
  Then push it to GitHub (or ask Claude Code to).
Turn it off: config.yaml > autopost > enabled: false.
