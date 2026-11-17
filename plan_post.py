"""Put a finished Reel on the posting plan.

    python plan_post.py drafts/reels/<name> "2026-11-18 06:00"     -> offered for that slot (India time)
    python plan_post.py drafts/reels/<name> STANDBY                -> offered for the standby bank

Uploads reel.mp4 + cover.jpg to the public media host (GitHub Pages, so Instagram can fetch them) and writes
planned/<name>.json to the PRIVATE assets repo, which the cloud radar reads every run. The cloud then asks
for approval in Telegram at the right time. Nothing is posted without the owner's Approve.
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import autopost as A  # noqa: E402
import radar as R  # noqa: E402

WORK = BASE / ".asset_sync"


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    folder, slot = Path(sys.argv[1]), sys.argv[2].strip()
    if slot != A.STANDBY:
        try:
            A._hhmm(slot.split(" ")[1], "slot")
            assert len(slot.split(" ")[0]) == 10
        except (IndexError, AssertionError):
            sys.exit('slot must look like "2026-11-18 06:00" (India time) or STANDBY')
    reel, cover = folder / "reel.mp4", folder / "cover.jpg"
    if not reel.exists():
        sys.exit(f"{reel} not found - build it first with reel.py")
    spec = json.loads((folder / "spec.json").read_text(encoding="utf-8")) if (folder / "spec.json").exists() else {}
    caption = (folder / "caption.txt").read_text(encoding="utf-8").strip()

    token = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    host = A.GitHubHost("ZILLA2025/lobby-news-radar", token)
    name = folder.name
    print("Uploading the video (GitHub Pages takes a minute or two)...")
    video_url, _ = host.upload(reel.read_bytes(), f"{name}.mp4")
    cover_url, _ = host.upload(cover.read_bytes(), f"{name}-cover.jpg") if cover.exists() else ("", "")

    plan = {
        "id": name, "slot": slot, "media_type": "REELS", "video_url": video_url, "cover_url": cover_url,
        "caption": caption, "series": spec.get("series", "Reel"), "title": spec.get("title", spec.get("headline", name)),
        "game": spec.get("game", ""),
    }
    if not WORK.exists():
        subprocess.run(["gh", "repo", "clone", "ZILLA2025/lobby-assets", str(WORK)], check=True)
    subprocess.run(["git", "pull", "-q"], cwd=WORK, check=True)
    (WORK / "planned").mkdir(exist_ok=True)
    (WORK / "planned" / f"{name}.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["git", "add", "planned"], cwd=WORK, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Plan {name} for {slot}"], cwd=WORK, check=True)
    subprocess.run(["git", "push", "-q"], cwd=WORK, check=True)
    print(f"Planned: {name} -> {slot}\n  video: {video_url}")
    return 0


if __name__ == "__main__":
    R.setup_logging()
    sys.exit(main())
