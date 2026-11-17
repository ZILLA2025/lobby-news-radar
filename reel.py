"""Reel maker for @thelobby.report (CLAUDE.md sections 3 and 5).

    python reel.py reels/specs/<name>.json        -> drafts/reels/<name>/reel.mp4 + cover.jpg + caption.txt

A spec (JSON) says which official clips to use and what to write. The Reel follows the brief:
  - 9:16, 1080x1920, 12-20 s, 30 fps
  - opens on the most dramatic moving shot WITH the headline already on screen (no logo/title card)
  - a new shot every ~1.5 s (fast montage); one short fact caption per shot (official facts only)
  - ends on a one-word-answer question
  - audio: the official trailer's own audio (a continuous section), or a royalty-free track from assets/Music

Spec example (times in seconds, crop_x = where to centre the vertical crop, 0 = left edge, 1 = right edge):
{
  "game": "gta6", "tier": "OFFICIAL", "source": "Rockstar Games",
  "headline": "GTA VI is out Thursday: what Rockstar has confirmed",
  "banner": "GTA VI · LAUNCH WEEK",
  "question": "DAY 1 OR WAIT?",
  "audio": {"file": "GTA6/Videos/GTAVI_Launch_Trailer.mp4", "start": 56.0},     (or {"music": "track.mp3"})
  "shots": [ {"file": "GTA6/Videos/GTAVI_Launch_Trailer.mp4", "start": 73.0, "dur": 1.5, "crop_x": 0.4,
              "caption": "OUT NOVEMBER 19"} , ... ],
  "caption": "Instagram caption text ..."
}
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import radar as R  # noqa: E402

W, H, FPS = 1080, 1920, 30
END_CARD = 2.2          # seconds
HEADLINE_SECONDS = 2.8  # big headline at the start, then a small banner
# Reels UI: keep text out of the top ~220 px and the bottom ~430 px; right-side buttons start at x~960 low down.
SAFE_TOP, SAFE_BOTTOM, MARGIN = 230, 1480, 70


def _probe(path: Path) -> tuple[int, int, float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


CROP_CACHE = BASE / "reels" / "letterbox.json"


def _active_area(path: Path) -> tuple[float, float]:
    """(top, height) of the picture inside the frame, as fractions - trailers often have black bars baked in.
    Measured once per file with ffmpeg cropdetect and remembered."""
    cache = json.loads(CROP_CACHE.read_text(encoding="utf-8")) if CROP_CACHE.exists() else {}
    key = path.relative_to(R.ASSETS_DIR).as_posix() if R.ASSETS_DIR in path.parents else path.name
    if key not in cache:
        _, _, dur = _probe(path)
        out = subprocess.run(["ffmpeg", "-v", "info", "-ss", f"{min(20.0, dur / 3):.1f}", "-t", "6", "-i", str(path),
                              "-vf", "scale=960:-2,cropdetect=limit=24:round=2:reset=0", "-an", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        crops = [c for c in out.split() if c.startswith("crop=")]
        top, hf = 0.0, 1.0
        if crops:
            cw, ch, cx, cy = (int(v) for v in crops[-1][5:].split(":"))
            full_h = 960 * _probe(path)[1] / _probe(path)[0]
            if ch < full_h * 0.97:  # real bars (not just a dark shot)
                top, hf = cy / full_h, ch / full_h
        cache[key] = [round(top, 4), round(hf, 4)]
        CROP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CROP_CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return tuple(cache[key])


# --------------------------------------------------------------------------- overlays (Pillow, transparent PNG)

def _text(draw, xy, text, font, fill, anchor="ma"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=max(2, font.size // 22),
              stroke_fill=(0, 0, 0))


def headline_overlay(spec: dict, s: R.Settings, fonts: R.Fonts, path: Path) -> None:
    """The first-frame headline: two colours (fact white, hook lime) over a soft dark band, like the cards."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent = R.hex_rgb(s.accent)
    fact, hook = R.split_headline(spec["headline"])
    fact, hook = fact.upper(), hook.upper()
    max_w = W - 2 * MARGIN
    for size in range(100, 50, -4):
        f = fonts.get("headline", size)
        a, b = R.wrap(draw, fact, f, max_w), (R.wrap(draw, hook, f, max_w) if hook else [])
        if len(a) + len(b) <= 5:
            break
    lh = int(f.size * 1.04)
    block = (len(a) + len(b)) * lh
    y = SAFE_BOTTOM - 40 - block
    # dark fade from above the text down to the bottom of the frame (no hard edge) so it reads on any shot
    top = max(0, y - 260)
    band = Image.new("RGBA", (W, H - top), (0, 0, 0, 0))
    grad = Image.linear_gradient("L").resize((W, H - top)).point(lambda v: int(min(255, v * 2.2) * 0.80))
    band.putalpha(grad)
    img.alpha_composite(band, (0, top))
    draw = ImageDraw.Draw(img)
    _text(draw, (W // 2, y - 58), s.handle, fonts.get("bold", 30), accent)
    for lines, color in ((a, (255, 255, 255)), (b, accent)):
        for line in lines:
            _text(draw, (W // 2, y), line, f, color)
            y += lh
    img.save(path)


def banner_overlay(spec: dict, s: R.Settings, fonts: R.Fonts, path: Path) -> None:
    """Small lime label at the top for the rest of the Reel (keeps the topic on screen)."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    f = fonts.get("headline", 40)
    text = spec.get("banner") or R.GAME_LABEL.get(spec["game"], "")
    tw = R.text_w(draw, text, f)
    x0, y0 = (W - tw) // 2 - 26, SAFE_TOP + 10
    draw.rounded_rectangle((x0, y0, x0 + tw + 52, y0 + 66), radius=33, fill=R.hex_rgb(s.accent) + (255,))
    draw.text((W // 2, y0 + 33), text, font=f, fill=R.hex_rgb(s.bg), anchor="mm")
    img.save(path)


def caption_overlay(text: str, s: R.Settings, fonts: R.Fonts, path: Path) -> None:
    """One short official fact per shot, big and centred in the lower-middle."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for size in range(84, 44, -4):
        f = fonts.get("headline", size)
        lines = R.wrap(draw, text.upper(), f, W - 2 * MARGIN)
        if len(lines) <= 2:
            break
    lh = int(f.size * 1.06)
    y = SAFE_BOTTOM - 120 - len(lines) * lh
    for line in lines:
        _text(draw, (W // 2, y), line, f, (255, 255, 255))
        y += lh
    img.save(path)


def end_card(spec: dict, s: R.Settings, fonts: R.Fonts, still: Image.Image, path: Path) -> None:
    """The question card: last shot blurred and darkened, question in big lime type, handle under it."""
    bg = still.convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), R.hex_rgb(s.bg)), 0.62)
    draw = ImageDraw.Draw(bg)
    accent = R.hex_rgb(s.accent)
    for size in range(150, 60, -6):
        f = fonts.get("headline", size)
        lines = R.wrap(draw, spec["question"].upper(), f, W - 2 * MARGIN)
        if len(lines) <= 3:
            break
    lh = int(f.size * 1.05)
    y = (H - len(lines) * lh) // 2 - 80
    for line in lines:
        _text(draw, (W // 2, y), line, f, accent)
        y += lh
    _text(draw, (W // 2, y + 50), "Tell us in the comments", fonts.get("bold", 40), (255, 255, 255))
    _text(draw, (W // 2, y + 130), s.handle, fonts.get("bold", 34), accent)
    bg.save(path)


# --------------------------------------------------------------------------- build

def build(spec_path: Path) -> Path:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    s, fonts = R.Settings(), R.Fonts()
    name = spec_path.stem
    out_dir = R.DRAFTS_DIR / "reels" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="reel_"))

    shots = spec["shots"]
    total_shots = sum(sh["dur"] for sh in shots)
    total = total_shots + END_CARD
    if not 12 <= total <= 20.5:
        print(f"warning: Reel is {total:.1f} s (brief: 12-20 s)")

    # overlays
    headline_overlay(spec, s, fonts, tmp / "headline.png")
    banner_overlay(spec, s, fonts, tmp / "banner.png")
    for i, sh in enumerate(shots):
        if sh.get("caption"):
            caption_overlay(sh["caption"], s, fonts, tmp / f"cap{i}.png")
    last = shots[-1]
    last_src = R.ASSETS_DIR / last["file"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{last['start'] + last['dur'] / 2:.2f}", "-i", str(last_src),
                    "-frames:v", "1", str(tmp / "last.png")], check=True)
    end_card(spec, s, fonts, Image.open(tmp / "last.png"), tmp / "end.png")

    # ffmpeg graph: each shot trimmed + vertical crop, then the end card, concatenated; overlays timed on top
    cmd = ["ffmpeg", "-v", "error", "-y"]
    filters, labels = [], []
    for i, sh in enumerate(shots):
        src = R.ASSETS_DIR / sh["file"]
        sw, shh, _ = _probe(src)
        top, hf = _active_area(src)
        ah, ay = int(shh * hf) // 2 * 2, int(shh * top) // 2 * 2       # picture area without black bars
        cmd += ["-ss", f"{sh['start']:.3f}", "-t", f"{sh['dur']:.3f}", "-i", str(src)]
        scaled_w = round(sw * H / ah / 2) * 2
        cx = min(max(int(scaled_w * sh.get("crop_x", 0.5)) - W // 2, 0), scaled_w - W)
        filters.append(f"[{i}:v]crop={sw}:{ah}:0:{ay},scale={scaled_w}:{H}:flags=lanczos,crop={W}:{H}:{cx}:0,setsar=1,fps={FPS},"
                       f"trim=duration={sh['dur']:.3f},setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
        labels.append(f"[v{i}]")
    n = len(shots)
    cmd += ["-loop", "1", "-t", f"{END_CARD}", "-i", str(tmp / "end.png")]
    filters.append(f"[{n}:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p[vend]")
    labels.append("[vend]")
    filters.append("".join(labels) + f"concat=n={n + 1}:v=1:a=0[base]")

    ov_inputs = [("headline.png", 0.0, HEADLINE_SECONDS), ("banner.png", HEADLINE_SECONDS, total_shots)]
    t = 0.0
    for i, sh in enumerate(shots):
        if sh.get("caption") and t + 0.01 >= HEADLINE_SECONDS - 0.01:
            ov_inputs.append((f"cap{i}.png", t, t + sh["dur"]))
        t += sh["dur"]
    cur = "[base]"
    for k, (png, a, b) in enumerate(ov_inputs):
        idx = n + 1 + k
        cmd += ["-loop", "1", "-t", f"{total:.3f}", "-i", str(tmp / png)]
        nxt = f"[o{k}]"
        filters.append(f"{cur}[{idx}:v]overlay=0:0:enable='between(t,{a:.3f},{b - 0.001:.3f})'{nxt}")
        cur = nxt

    # audio: a continuous section of the trailer's own audio, or a royalty-free track
    a_idx = n + 1 + len(ov_inputs)
    audio = spec.get("audio") or {}
    if audio.get("music"):
        cmd += ["-ss", f"{audio.get('start', 0):.3f}", "-t", f"{total:.3f}", "-i", str(BASE / "assets" / "Music" / audio["music"])]
    else:
        cmd += ["-ss", f"{audio.get('start', shots[0]['start']):.3f}", "-t", f"{total:.3f}",
                "-i", str(R.ASSETS_DIR / audio.get("file", shots[0]["file"]))]
    filters.append(f"[{a_idx}:a]afade=t=in:d=0.25,afade=t=out:st={total - 1.2:.3f}:d=1.2,"
                   f"aresample=48000,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    reel = out_dir / "reel.mp4"
    cmd += ["-filter_complex", ";".join(filters), "-map", cur, "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart",
            "-t", f"{total:.3f}", str(reel)]
    subprocess.run(cmd, check=True)

    # cover = the first frame (action shot + headline), never a logo
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.4", "-i", str(reel), "-frames:v", "1", "-q:v", "2",
                    str(out_dir / "cover.jpg")], check=True)
    (out_dir / "caption.txt").write_text(spec.get("caption", ""), encoding="utf-8")
    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reel ready: {reel} ({total:.1f} s, {reel.stat().st_size // 1024} KB)")
    return reel


if __name__ == "__main__":
    R.setup_logging()
    for arg in sys.argv[1:] or [None]:
        if not arg:
            sys.exit("usage: python reel.py reels/specs/<name>.json")
        build(Path(arg))
