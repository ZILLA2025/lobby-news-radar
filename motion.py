"""Motion-design Reels for @thelobby.report - our OWN format (2026-11-19).

Why: Instagram flagged the account for unoriginal content after Reels re-cut from official trailers, so the page
can't be recommended to non-followers. These Reels are designed by us, frame by frame: kinetic headline and fact
scenes in the brand style, official STILLS only as framed pictures inside our layout (never full-screen trailer
video), and a music bed generated in code (no trailer audio, nothing anyone else owns).

    python motion.py reels/specs/<name>.json     -> drafts/reels/<name>/reel.mp4 + cover.jpg + caption.txt

Spec:
{
  "game": "gta6", "kicker": "GTA VI · OUT NOW", "source_line": "Source: Rockstar Games",
  "headline": "GTA VI is out now: the US unlocks at midnight",     (fact part white, hook part lime)
  "scenes": [ {"image": "GTA6/Pics/Places/Vice City/x.jpg"},                    <- headline scene
              {"image": "...", "big": "NOV 19", "text": "One short official fact"}, ... ],
  "question": "Lucia or Jason?",
  "choices": [ {"label": "LUCIA", "image": "..."}, {"label": "JASON", "image": "..."} ],      (optional)
  "caption": "Instagram caption", "series": "...", "title": "..."
}
Images: a path relative to assets/Official (or .asset_sync), or absolute.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import radar as R  # noqa: E402

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM, MARGIN = 230, 1480, 70
PX0, PY0, PX1, PY1 = 70, 420, 1010, 1080          # picture panel
PW, PH = PX1 - PX0, PY1 - PY0
TEXT_Y0, TEXT_Y1 = 1150, 1430                     # text block
HEAD_DUR, FACT_DUR, END_DUR, TRANS = 3.0, 2.5, 2.8, 0.38
OVERSCAN = 1.18                                   # picture prepared bigger than the panel, for the camera move
WHITE, GREY = (255, 255, 255), (170, 176, 184)


def ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def ease_io(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


# --------------------------------------------------------------------------- pictures

def resolve(rel: str) -> Path:
    p = Path(rel)
    if p.is_absolute() and p.exists():
        return p
    for root in (R.ASSETS_DIR, BASE / ".asset_sync"):
        if (root / rel).exists():
            return root / rel
    raise FileNotFoundError(rel)


def cover(img: Image.Image, w: int, h: int, focus_x: float = 0.5) -> Image.Image:
    """Scale to fill w x h and crop (horizontal focus at focus_x)."""
    s = max(w / img.width, h / img.height)
    im = img.resize((max(w, round(img.width * s)), max(h, round(img.height * s))), Image.LANCZOS)
    x = min(max(int(im.width * focus_x - w / 2), 0), im.width - w)
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def focus_of(img: Image.Image) -> float:
    """Where the detail is (the character / landmark): edge energy across the width, pulled to the centre."""
    g = img.convert("L")
    g.thumbnail((480, 480))
    e = np.asarray(g.filter(ImageFilter.FIND_EDGES), dtype=np.float32).sum(axis=0)
    if e.sum() == 0:
        return 0.5
    k = max(1, len(e) // 3)
    sm = np.convolve(e, np.ones(k), mode="same")
    c = np.arange(len(sm)) / len(sm)
    return float(c[int((sm * (1 - 0.5 * np.abs(c - 0.5))).argmax())])


class Pic:
    """One picture prepared for the panel (with room for the camera move) and as a blurred ambient background."""

    def __init__(self, path: Path, w: int = PW, h: int = PH, zoom_in: bool = True, focus: float | None = None) -> None:
        img = Image.open(path).convert("RGB")
        fx = focus_of(img) if focus is None else focus
        self.big = cover(img, round(w * OVERSCAN), round(h * OVERSCAN), fx)
        self.w, self.h, self.zoom_in = w, h, zoom_in
        amb = cover(img, W // 4, H // 4, fx).filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.BILINEAR)
        self.ambient = Image.blend(amb, Image.new("RGB", (W, H), R.hex_rgb("#0B0D10")), 0.80)

    def frame(self, p: float) -> Image.Image:
        """The panel picture at progress p (0..1): a slow push in (or pull out) with a slight drift."""
        p = ease_io(p) if self.zoom_in else 1 - ease_io(p)
        bw, bh = self.big.size
        z = 1 + 0.16 * p
        cw, ch = bw / z, bh / z
        cx = bw / 2 + (bw - cw) * 0.25 * (p - 0.5)
        box = (cx - cw / 2, (bh - ch) / 2, cx + cw / 2, (bh + ch) / 2)
        return self.big.resize((self.w, self.h), Image.BILINEAR, box=box)


def rounded_mask(w: int, h: int, r: int = 34) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), radius=r, fill=255)
    return m


# --------------------------------------------------------------------------- type

def word_img(word: str, font, fill) -> Image.Image:
    asc, desc = font.getmetrics()
    im = Image.new("RGBA", (int(font.getlength(word)) + 40, asc + desc + 20), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10 + asc), word, font=font, fill=fill, anchor="ls")
    return im


def layout(words: list[tuple[str, tuple]], fonts: R.Fonts, box: tuple[int, int, int, int], sizes: range,
           max_lines: int, line_h: float = 1.0) -> list[tuple[Image.Image, int, int, int]]:
    """Left-aligned words that fit the box: [(image, x, y, line_no)], biggest size that fits."""
    x0, y0, x1, y1 = box
    for size in sizes:
        f = fonts.get("headline", size)
        space = f.getlength(" ")
        lines, cur, cur_w = [], [], 0.0
        for w, c in words:
            ww = f.getlength(w)
            if cur and cur_w + space + ww > x1 - x0:
                lines.append(cur)
                cur, cur_w = [], 0.0
            cur.append((w, c, ww))
            cur_w += (space if len(cur) > 1 else 0) + ww
        if cur:
            lines.append(cur)
        lh = int(size * line_h)
        if len(lines) <= max_lines and len(lines) * lh <= y1 - y0:
            break
    out, y = [], y0
    for n, line in enumerate(lines):
        x = x0
        for w, c, ww in line:
            out.append((word_img(w, f, c), int(x) - 10, y - 10, n))
            x += ww + space
        y += lh
    return out


def faded(im: Image.Image, a: float) -> Image.Image:
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def pill(text: str, font, fg, bg, pad=(26, 14), radius=30) -> Image.Image:
    tw = int(font.getlength(text))
    asc, desc = font.getmetrics()
    im = Image.new("RGBA", (tw + 2 * pad[0], asc + desc // 2 + 2 * pad[1]), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=radius, fill=bg)
    d.text((im.width // 2, im.height // 2), text, font=font, fill=fg, anchor="mm")
    return im


def slab(text: str, font, fg, bg) -> Image.Image:
    """The big stat label: a slanted lime slab with dark type (sits on the panel's lower edge)."""
    tw = int(font.getlength(text))
    asc, desc = font.getmetrics()
    h = asc + desc // 2 + 34
    sk = int(h * 0.25)
    im = Image.new("RGBA", (tw + 70 + sk, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(sk, 0), (im.width, 0), (im.width - sk, h), (0, h)], fill=bg)
    d.text((im.width // 2, h // 2 + 2), text, font=font, fill=fg, anchor="mm")
    return im


# --------------------------------------------------------------------------- music (generated, ours)

def music(total: float, seed: str, cues: list[float], path: Path) -> None:
    """A synthwave/trap bed made from scratch: half-time drums, 808 bass on a minor progression, a soft pad and
    a plucked arp, with a whoosh into every scene change. Different songs per seed (key, tempo, pattern)."""
    sr = 44100
    rng = random.Random(seed)
    bpm = rng.choice([96, 100, 104, 110])
    beat = 60 / bpm
    n = int((total + 0.5) * sr)
    t = np.arange(n) / sr
    roots = {"A": 55.0, "B": 61.74, "C#": 69.30, "D": 73.42, "E": 82.41, "F#": 92.50, "G": 98.0}
    root = roots[rng.choice(list(roots))]
    prog = rng.choice([[0, 8, 3, 10], [0, 5, 8, 7], [0, 8, 5, 7], [0, 3, 8, 10]])  # semitones, minor-key moves
    bar = 4 * beat

    def env(start, dur, attack=0.004, rel=None):
        a = np.clip((t - start) / attack, 0, 1)
        d = np.exp(-np.clip(t - start, 0, None) / (rel or dur)) * (t >= start)
        return a * d * (t < start + dur * 6)

    def band(sig, lo, hi):
        f = np.fft.rfft(sig)
        fr = np.fft.rfftfreq(len(sig), 1 / sr)
        f *= ((fr >= lo) & (fr <= hi)).astype(float)
        return np.fft.irfft(f, len(sig))

    noise = np.random.default_rng(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)).standard_normal(n)
    drums, bass, pad, arp, fx = (np.zeros(n) for _ in range(5))
    kicks = []
    steps = int(total / (beat / 4)) + 2
    kick_pat = rng.choice(["x.........x.....", "x.......x..x....", "x.........x..x.."])
    hat_roll = rng.random() < 0.6
    for s in range(steps):
        st = s * beat / 4
        k = s % 16
        if kick_pat[k] == "x":
            kicks.append(st)
            ph = 2 * np.pi * np.cumsum(45 + 110 * np.exp(-np.clip(t - st, 0, None) / 0.03)) / sr
            drums += 0.95 * np.sin(ph) * env(st, 0.35, 0.002, 0.18)
        if k == 8:  # clap/snare on the half-time 3
            drums += 0.55 * band(noise * env(st, 0.2, 0.001, 0.07), 900, 7000)
        if k % 2 == 0 or (hat_roll and (s // 16) % 2 == 1 and k >= 12):
            drums += 0.16 * (1 if k % 4 else 0.6) * band(noise * env(st, 0.05, 0.001, 0.018), 7000, 16000)
    for b in range(int(total / bar) + 2):
        semis = prog[b % len(prog)]
        f0 = root * 2 ** (semis / 12)
        st = b * bar
        on = (t >= st) & (t < st + bar)
        # 808: long sine on the bar's root, a little drive
        bass += np.tanh(2.2 * np.sin(2 * np.pi * f0 * (t - st)) * np.exp(-np.clip(t - st, 0, None) / 1.4)) * on * 0.55
        # pad: minor triad, detuned saws, filtered later
        for iv, det in ((0, 1.0), (3, 1.003), (7, 0.997), (12, 1.002)):
            fr_ = f0 * 4 * 2 ** (iv / 12) * det
            pad += (2 * ((t * fr_) % 1) - 1) * on * 0.08
        # arp: 16th plucks over the triad, two octaves up
        notes = [0, 3, 7, 12, 7, 3]
        for j in range(16):
            ast = st + j * beat / 4
            fr_ = f0 * 8 * 2 ** (notes[j % len(notes)] / 12)
            arp += np.sign(np.sin(2 * np.pi * fr_ * (t - ast))) * env(ast, 0.12, 0.002, 0.07) * 0.06
    pad = band(pad, 120, 2600)
    arp = band(arp, 400, 5000)
    # sidechain: pad and bass duck under every kick
    duck = np.ones(n)
    for k in kicks:
        duck -= 0.55 * np.exp(-np.clip(t - k, 0, None) / 0.13) * (t >= k)
    duck = np.clip(duck, 0.3, 1)
    for c in cues:  # whoosh up into each scene change, small boom on it
        w = np.clip((t - (c - 0.45)) / 0.45, 0, 1) * (t < c)
        fx += band(noise * w ** 2, 1500, 9000) * 0.35
        fx += np.sin(2 * np.pi * 50 * (t - c)) * env(c, 0.5, 0.002, 0.25) * 0.5
    mix = drums + bass * duck + pad * duck + arp + fx
    fade = np.clip(t / 0.15, 0, 1) * np.clip((total - t) / 1.0, 0, 1)
    mix = np.tanh(1.3 * mix) * fade
    mix /= max(1e-6, np.abs(mix).max()) / 0.89
    left = mix + 0.15 * np.roll(arp + pad, 441)
    right = mix + 0.15 * np.roll(arp + pad, -441)
    st = np.stack([left, right], axis=1)
    st /= max(1e-6, np.abs(st).max()) / 0.89
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((st * 32767).astype("<i2").tobytes())


# --------------------------------------------------------------------------- render

def render(spec: dict, name: str) -> Path:
    s, fonts = R.Settings(), R.Fonts()
    lime, bg = R.hex_rgb(s.accent), R.hex_rgb(s.bg)
    out_dir = R.DRAFTS_DIR / "reels" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="motion_"))

    scenes = spec["scenes"]
    durs = [spec.get("head_dur", HEAD_DUR)] + [sc.get("dur", spec.get("fact_dur", FACT_DUR)) for sc in scenes[1:]]
    starts = [sum(durs[:i]) for i in range(len(durs))]
    end_start = sum(durs)
    total = end_start + END_DUR
    if not 12 <= total <= 20.5:
        print(f"warning: Reel is {total:.1f} s (brief: 12-20 s)")

    pics = [Pic(resolve(sc["image"]), zoom_in=sc.get("zoom", "in" if i % 2 == 0 else "out") == "in",
                focus=sc.get("focus")) for i, sc in enumerate(scenes)]
    mask = rounded_mask(PW, PH)

    # words: headline (fact white, hook lime), then each fact
    fact, hook = R.split_headline(spec["headline"])
    hw = [(w, WHITE) for w in fact.upper().split()] + [(w, lime) for w in hook.upper().split()]
    texts = [layout(hw, fonts, (MARGIN, TEXT_Y0 - 30, W - MARGIN, TEXT_Y1), range(104, 52, -4), 4, 1.02)]
    for sc in scenes[1:]:
        texts.append(layout([(w, WHITE) for w in sc.get("text", "").upper().split()], fonts,
                            (MARGIN, TEXT_Y0, W - MARGIN, TEXT_Y1), range(76, 40, -4), 4, 1.06))
    slabs = [slab(sc["big"].upper(), fonts.get("headline", 92), bg, lime) if sc.get("big") else None for sc in scenes]

    # fixed chrome: kicker pill, handle, source line
    chrome = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kick = pill(spec.get("kicker") or R.GAME_LABEL.get(spec["game"], ""), fonts.get("headline", 38), bg, lime)
    chrome.paste(kick, (MARGIN, SAFE_TOP + 20), kick)
    d = ImageDraw.Draw(chrome)
    d.text((W - MARGIN, SAFE_TOP + 20 + kick.height // 2), s.handle, font=fonts.get("bold", 32), fill=GREY, anchor="rm")
    chrome_end = chrome.copy()  # the question card has no source line (it would sit under the answer prompt)
    if spec.get("source_line"):
        d.text((MARGIN, TEXT_Y1 + 26), spec["source_line"], font=fonts.get("bold", 30), fill=GREY, anchor="lm")
    prog_y = PY0 - 34

    # end card: question + optional two choices
    q_words = [(w, lime) for w in spec["question"].upper().split()]
    choices = spec.get("choices") or []
    if choices:
        cw_, ch_ = 430, 620
        cpics = [Pic(resolve(c["image"]), cw_, ch_, focus=c.get("focus")) for c in choices[:2]]
        cmask = rounded_mask(cw_, ch_, 30)
        clabels = [pill(c["label"].upper(), fonts.get("headline", 46), bg, lime) for c in choices[:2]]
        q_lay = layout(q_words, fonts, (MARGIN, 1180, W - MARGIN, 1400), range(120, 60, -6), 2, 1.0)
    else:
        q_lay = layout(q_words, fonts, (MARGIN, TEXT_Y0 - 30, W - MARGIN, TEXT_Y1 - 40), range(130, 60, -6), 2, 1.0)
    sub = word_img("COMMENT YOUR ANSWER", fonts.get("headline", 44), WHITE)

    # music
    wav = tmp / "music.wav"
    music(total, spec.get("headline", name), starts[1:] + [end_start], wav)

    # stripes for the background (slow drift)
    stripes = Image.new("RGBA", (W + 240, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripes)
    for x in range(-H, W + 240, 120):
        sd.line([(x, H), (x + H * 0.55, 0)], fill=lime + (10,), width=28)

    reel = out_dir / "reel.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", str(wav), "-filter_complex", "[1:a]aresample=48000,loudnorm=I=-14:TP=-1.5:LRA=11[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "8M",
           "-bufsize", "16M", "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
           "-ar", "48000", "-movflags", "+faststart", "-t", f"{total:.3f}", str(reel)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    nframes = int(round(total * FPS))
    cover_img = None
    for fi in range(nframes):
        t = fi / FPS
        if t >= end_start:
            frame = _end_frame(t - end_start, pics[-1], stripes, chrome_end, choices, locals())
        else:
            i = max(k for k in range(len(starts)) if starts[k] <= t)
            frame = _scene_frame(t, i, starts, durs, pics, texts, slabs, mask, stripes, chrome, lime, prog_y, total)
        if fi == 12:
            cover_img = frame.convert("RGB")
        proc.stdin.write(frame.convert("RGB").tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while encoding the motion Reel")
    cover_img.save(out_dir / "cover.jpg", quality=92)
    (out_dir / "caption.txt").write_text(spec.get("caption", ""), encoding="utf-8")
    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Reel ready: {reel} ({total:.1f} s, {reel.stat().st_size // 1024} KB)")
    return reel


def _background(t: float, amb: Image.Image, stripes: Image.Image) -> Image.Image:
    frame = amb.convert("RGBA")
    off = int(t * 60) % 120
    frame.alpha_composite(stripes.crop((off, 0, off + W, H)))
    return frame


def _scene_frame(t, i, starts, durs, pics, texts, slabs, mask, stripes, chrome, lime, prog_y, total):
    u = t - starts[i]
    p = u / durs[i]
    tr = ease(u / TRANS) if i > 0 else 1.0
    amb = pics[i].ambient if tr >= 1 else Image.blend(pics[i - 1].ambient, pics[i].ambient, tr)
    frame = _background(t, amb, stripes)
    d = ImageDraw.Draw(frame)
    # panel(s): the new one slides in from the right while the old one leaves to the left
    panels = [(pics[i], p, PX0 + int((1 - tr) * (W + 40)))]
    if tr < 1:
        panels.insert(0, (pics[i - 1], 1.0, PX0 - int(tr * (W + 40))))
    for pic, pp, x in panels:
        d.rounded_rectangle((x + 16, PY0 + 16, x + PW + 16, PY1 + 16), radius=34, outline=lime, width=6)
        frame.paste(pic.frame(pp), (x, PY0), mask)
    if 0 < tr < 1:  # lime sweep across the change
        sx = int(W + 200 - tr * (W + 600))
        d.polygon([(sx, PY0 - 60), (sx + 120, PY0 - 60), (sx - 160, PY1 + 80), (sx - 280, PY1 + 80)], fill=lime)
    # big stat slab: slides in after the panel lands
    if slabs[i] is not None:
        a = ease((u - TRANS * 0.8) / 0.3)
        if a > 0:
            sl = slabs[i]
            frame.paste(faded(sl, a), (PX0 - 20 - int((1 - a) * 160), PY1 - sl.height // 2 - 10), faded(sl, a))
    # words: the headline is on screen from the first frame; facts pop in word by word
    for k, (im, x, y, line) in enumerate(texts[i]):
        if i == 0:
            a, dy = 1.0, 0
        else:
            a = ease((u - TRANS * 0.7 - k * 0.045) / 0.22)
            dy = int((1 - a) * 46)
        if a > 0:
            fim = faded(im, a)
            frame.paste(fim, (x, y + dy), fim)
    if i == 0:  # lime underline that grows under the headline
        bottom = max(y + im.height for im, _, y, _ in texts[0]) - 22 if texts[0] else TEXT_Y0
        bottom = min(bottom, TEXT_Y1 + 2)  # never into the source line
        d.rectangle((MARGIN, bottom, MARGIN + int(ease(u / 1.2) * 260), bottom + 9), fill=lime)
    frame.alpha_composite(chrome)
    # progress bar (story style) over the whole Reel
    d = ImageDraw.Draw(frame)
    d.rounded_rectangle((MARGIN, prog_y, W - MARGIN, prog_y + 8), radius=4, fill=(255, 255, 255, 45))
    d.rounded_rectangle((MARGIN, prog_y, MARGIN + int((W - 2 * MARGIN) * t / total), prog_y + 8), radius=4, fill=lime)
    return frame


def _end_frame(u, last_pic, stripes, chrome, choices, v):
    lime, bg = v["lime"], v["bg"]
    frame = _background(u + v["end_start"], last_pic.ambient, stripes)
    d = ImageDraw.Draw(frame)
    if choices:
        cw_, ch_ = 430, 620
        y0 = 450
        for j, (cp, lab) in enumerate(zip(v["cpics"], v["clabels"])):
            a = ease((u - j * 0.12) / 0.45)
            x = (MARGIN if j == 0 else W - MARGIN - cw_) + int((1 - a) * (-500 if j == 0 else 500))
            d.rounded_rectangle((x + 12, y0 + 12, x + cw_ + 12, y0 + ch_ + 12), radius=30, outline=lime, width=5)
            frame.paste(cp.frame(min(1.0, u / END_DUR)), (x, y0), v["cmask"])
            frame.paste(lab, (x + cw_ // 2 - lab.width // 2, y0 + ch_ - lab.height // 2), lab)
        a = ease((u - 0.3) / 0.3)
        r = int(58 * a)
        if r > 2:
            cx, cy = W // 2, y0 + ch_ // 2
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=bg, outline=lime, width=5)
            d.text((cx, cy + 2), "OR", font=v["fonts"].get("headline", int(44 * a) or 1), fill=lime, anchor="mm")
    else:  # the last picture stays in its panel, still moving, with the question under it
        d.rounded_rectangle((PX0 + 16, PY0 + 16, PX1 + 16, PY1 + 16), radius=34, outline=lime, width=6)
        frame.paste(last_pic.frame(1 - min(1.0, u / END_DUR)), (PX0, PY0), v["mask"])
    for k, (im, x, y, line) in enumerate(v["q_lay"]):
        a = ease((u - 0.15 - k * 0.06) / 0.25)
        if a > 0:
            fim = faded(im, a)
            frame.paste(fim, (x, y + int((1 - a) * 50)), fim)
    sub = v["sub"]
    ys =max(y + im.height for im, _, y, _ in v["q_lay"]) - 6
    a = ease((u - 0.7) / 0.3)
    if a > 0:
        frame.paste(faded(sub, a), (MARGIN - 10, ys), faded(sub, a))
    frame.alpha_composite(chrome)
    d = ImageDraw.Draw(frame)
    py = v["prog_y"]
    d.rounded_rectangle((MARGIN, py, W - MARGIN, py + 8), radius=4, fill=lime)
    return frame


# --------------------------------------------------------------------------- automatic news Reels (cloud)

_NUM = re.compile(r"(\$\d[\d,.]*|£\d[\d,.]*|\b\d[\d,.]*\s?(?:%|million|billion|GB|fps|hours?|minutes?|km|miles|"
                  r"players|copies|reviews|nominations)\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
                  r"\s\d{1,2}\b|\b\d{1,3}/(?:10|100)\b)", re.I)


def big_label(text: str) -> str | None:
    """A number or date from the fact itself for the big slab ('$69.99', 'NOV 19', '120 FPS'), else None."""
    m = _NUM.search(text or "")
    if not m:
        return None
    lab = re.sub(r"\s+", " ", m.group(1)).strip().upper()
    lab = re.sub(r"^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?", r"\1", lab)
    return lab if len(lab) <= 14 else None


def pick_images(item: dict, text: str, n: int, recent: dict) -> list[str]:
    """n different official stills for a story: topic matches first (Lucia story -> Lucia art), then the game's
    general art; least recently used first. Returns paths relative to the assets folder."""
    index = R._asset_index()
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", text.lower()) + " "
    game_words = {"gta6": ["gta6"], "mw4": ["cod"]}.get(item.get("game"), [])
    scored = []
    for p, name in index:
        if "benefit" in name or (game_words and not any(g in name for g in game_words)):
            continue
        score = sum(1 for key, targets in R.ASSET_KEYWORDS.items() if f" {key} " in t and any(x in name for x in targets))
        rel = p.relative_to(R.ASSETS_DIR).as_posix()
        h = hashlib.sha1((item.get("url", text) + rel).encode()).hexdigest()
        scored.append((-score, recent.get(rel, ""), h, rel))
    scored.sort()
    return [rel for *_, rel in scored[:n]]


QUESTIONS = {"gta6": ["Hyped or not?", "Day one or wait?", "Lucia or Jason?", "Buying it?"],
             "mw4": ["Solo or squad?", "Hyped or not?", "Rate it /10?", "PS5 or Xbox?"],
             "warzone": ["Solo or squad?", "Hyped or not?"], "dmz": ["Solo or squad?", "Hyped or not?"]}


def news_spec(item: dict, d: dict, recent: dict | None = None) -> dict | None:
    """A motion Reel plan from a story: the headline over the best-matching official still, then the article's own
    facts (never reworded) one per scene, each with a big number/date when the fact has one, then a question."""
    import reel as RL
    recent = {} if recent is None else recent
    facts = RL.fact_chunks(d.get("summary", ""), n=3, width=80)
    text = f"{item['title']} {d.get('summary', '')}"
    imgs = pick_images(item, text, 1 + max(2, len(facts)), recent)
    if len(imgs) < 2:
        return None
    fact_dur = max(FACT_DUR, min(3.4, (12.4 - HEAD_DUR - END_DUR) / max(1, len(facts))))
    scenes = [{"image": imgs[0]}]
    for k, f in enumerate(facts):
        scenes.append({"image": imgs[(k + 1) % len(imgs)], "text": f, "big": big_label(f)})
    if not facts:  # nothing to show but the headline: hold it longer
        scenes[0]["dur"] = 5.0
    now = R.iso(R.now_utc())
    recent.update({sc["image"]: now for sc in scenes})
    label = R.GAME_LABEL.get(item["game"], "")
    qs = QUESTIONS.get(item["game"], ["Hyped or not?"])
    q = qs[int(hashlib.sha1(item["title"].encode()).hexdigest(), 16) % len(qs)]
    spec = {
        "game": item["game"], "kicker": f"{label} · {'BREAKING' if item.get('priority') == 'HIGH' else 'NEWS'}",
        "headline": d.get("full_headline") or d["headline"],
        "source_line": f"Reported by {item['source']}" if item["tier"] == "REPORTED" else f"Source: {item['source']}",
        "scenes": scenes, "fact_dur": round(fact_dur, 2), "question": q,
        "caption": d.get("caption", ""), "series": "The Lobby Daily", "title": item["title"][:80],
    }
    if q == "Lucia or Jason?":
        lu = pick_images({"game": "gta6", "url": "lucia"}, "lucia", 1, {})
        ja = pick_images({"game": "gta6", "url": "jason"}, "jason", 1, {})
        if lu and ja:
            spec["choices"] = [{"label": "Lucia", "image": lu[0]}, {"label": "Jason", "image": ja[0]}]
    return spec


if __name__ == "__main__":
    R.setup_logging()
    if len(sys.argv) < 2:
        sys.exit("usage: python motion.py reels/specs/<name>.json")
    for arg in sys.argv[1:]:
        sp = Path(arg)
        render(json.loads(sp.read_text(encoding="utf-8")), sp.stem)
