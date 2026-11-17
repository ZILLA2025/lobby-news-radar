"""Prepare the shot library for cloud-made news Reels.

    python prep_library.py

For every curated shot in reels/library_src.json: cut it from the ORIGINAL official video, remove the
letterbox bars, crop to vertical 1080x1920 (30 fps, no audio) and save it as a small clip; plus one audio
section per video (the trailer's own audio). Writes everything + library.json into the private assets repo
(.asset_sync), then pushes. The cloud only joins these clips and adds text - no 4K files needed there.
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import radar as R  # noqa: E402
import reel  # noqa: E402

WORK = BASE / ".asset_sync"
AUDIO_SECONDS = 24


def main() -> int:
    src = json.loads((BASE / "reels" / "library_src.json").read_text(encoding="utf-8"))
    out_lib = {"videos": {}}
    (WORK / "clips").mkdir(parents=True, exist_ok=True)
    for key, v in src["videos"].items():
        path = R.ASSETS_DIR / v["src"]
        sw, sh_, _ = reel._probe(path)
        top, hf = reel._active_area(path)
        ah, ay = int(sh_ * hf) // 2 * 2, int(sh_ * top) // 2 * 2
        scaled_w = round(sw * reel.H / ah / 2) * 2
        shots = []
        for i, s in enumerate(v["shots"]):
            rel = f"clips/{key}_{i:02d}.mp4"
            dest = WORK / rel
            cx = min(max(int(scaled_w * s.get("crop_x", 0.5)) - reel.W // 2, 0), scaled_w - reel.W)
            if not dest.exists():
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s['start']:.3f}", "-t", f"{s['dur']:.3f}",
                                "-i", str(path), "-vf",
                                f"crop={sw}:{ah}:0:{ay},scale={scaled_w}:{reel.H}:flags=lanczos,"
                                f"crop={reel.W}:{reel.H}:{cx}:0,setsar=1,fps={reel.FPS}",
                                "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "21", "-pix_fmt", "yuv420p",
                                str(dest)], check=True)
            shots.append({"clip": rel, "dur": s["dur"], "tags": s["tags"]})
        arel = f"clips/{key}_audio.m4a"
        if not (WORK / arel).exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{v['audio_start']:.3f}", "-t", str(AUDIO_SECONDS),
                            "-i", str(path), "-vn", "-c:a", "aac", "-b:a", "160k", str(WORK / arel)], check=True)
        out_lib["videos"][key] = {"game": v["game"], "audio": arel, "shots": shots}
        print(f"{key}: {len(shots)} shots")
    (WORK / "reels").mkdir(exist_ok=True)
    (WORK / "reels" / "library.json").write_text(json.dumps(out_lib, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in (WORK / "clips").glob("*")) / 1e6
    print(f"clips total: {size:.0f} MB")
    for cmd in (["git", "add", "clips", "reels"], ["git", "commit", "-q", "-m", "Shot library for cloud news Reels"],
                ["git", "push", "-q"]):
        subprocess.run(cmd, cwd=WORK, check=True)
    print("pushed to the private repo")
    return 0


if __name__ == "__main__":
    R.setup_logging()
    sys.exit(main())
