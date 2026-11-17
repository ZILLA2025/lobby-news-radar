"""Copy the owner's official stills to the PRIVATE repo the cloud radar reads (ZILLA2025/lobby-assets).

    python sync_assets.py

Takes every still that the card maker can use (same rules as radar._asset_index: no videos, no logos,
only the landscape copy of each wallpaper), resizes it to max 1600 px as JPEG, mirrors the folder layout,
and pushes only what changed. Run it after adding files to assets/Official.
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import radar as R  # noqa: E402

REPO = "ZILLA2025/lobby-assets"
WORK = BASE / ".asset_sync"          # local clone of the private repo (gitignored)
MAX_SIDE = 1600


def git(*args, cwd=WORK) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def main() -> int:
    if not WORK.exists():
        subprocess.run(["gh", "repo", "clone", REPO, str(WORK)], check=True)
    git("pull", "-q")
    wanted = set()
    added = 0
    for src, _ in R._asset_index():
        rel = src.relative_to(R.ASSETS_DIR).with_suffix(".jpg")
        dest = WORK / rel
        wanted.add(dest.resolve())
        stamp = dest.with_suffix(".src")
        sig = hashlib.sha1(f"{src.stat().st_size}:{src.stat().st_mtime_ns}".encode()).hexdigest()
        if dest.exists() and stamp.exists() and stamp.read_text() == sig:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        img = Image.open(src).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        img.save(dest, "JPEG", quality=85, optimize=True)
        stamp.write_text(sig)
        added += 1
    removed = 0
    for f in WORK.rglob("*.jpg"):
        if f.resolve() not in wanted:
            f.unlink()
            f.with_suffix(".src").unlink(missing_ok=True)
            removed += 1
    git("add", "-A")
    if not git("status", "--porcelain").strip():
        print("Cloud assets already up to date.")
        return 0
    git("commit", "-q", "-m", f"Sync official stills (+{added} / -{removed})")
    git("push", "-q")
    print(f"Cloud assets updated: {added} new/changed, {removed} removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
