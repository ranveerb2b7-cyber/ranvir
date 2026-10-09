"""DesiDiya Brand Store animation: a row of diyas lights up, then the wordmark appears.

Renders a seamless, silent, looping MP4 suitable for an Amazon Brand Store video tile.
Usage: python3 diya_lights.py [--size 1920x1080] [--out diya_lights.mp4]
"""
import argparse
import math
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FPS = 30
DURATION = 12.0
SERIF = "/usr/share/fonts/truetype/crosextra/Caladea-Bold.ttf"
SANS = "/usr/share/fonts/opentype/inter/Inter-Medium.otf"

GOLD = (246, 196, 92)
CREAM = (255, 240, 214)
CLAY = (176, 74, 34)
CLAY_DARK = (110, 40, 18)


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def glow_sprite(radius):
    y, x = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    d = np.sqrt(x * x + y * y) / radius
    g = np.clip(1 - d, 0, 1) ** 2.2
    return g[..., None] * np.array([1.0, 0.62, 0.22])  # warm orange light


def add_sprite(img, sprite, cx, cy, k):
    r = sprite.shape[0] // 2
    h, w = img.shape[:2]
    x0, y0 = int(cx) - r, int(cy) - r
    sx0, sy0 = max(0, -x0), max(0, -y0)
    x1, y1 = min(w, x0 + 2 * r + 1), min(h, y0 + 2 * r + 1)
    if x1 <= max(x0, 0) or y1 <= max(y0, 0):
        return
    img[max(y0, 0):y1, max(x0, 0):x1] += k * sprite[sy0:sy0 + y1 - max(y0, 0), sx0:sx0 + x1 - max(x0, 0)]


def background(w, h):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((x - w / 2) / w) ** 2 + ((y - h * 0.62) / h) ** 2)
    t = np.clip(d * 1.6, 0, 1)[..., None]
    center = np.array([92, 22, 38], np.float32)   # deep maroon
    edge = np.array([18, 6, 22], np.float32)      # near-black plum
    grain = np.random.default_rng(1).uniform(-1.5, 1.5, (h, w, 1)).astype(np.float32)  # hides banding
    return center * (1 - t) + edge * t + grain


def draw_diya(draw, cx, cy, s):
    """Clay diya: a shallow bowl with a pinched spout pointing up-right."""
    bowl = [(cx - 1.0 * s, cy - 0.15 * s), (cx + 0.75 * s, cy - 0.15 * s),
            (cx + 1.15 * s, cy - 0.45 * s), (cx + 0.9 * s, cy + 0.05 * s),
            (cx + 0.55 * s, cy + 0.45 * s), (cx - 0.55 * s, cy + 0.45 * s),
            (cx - 0.95 * s, cy + 0.1 * s)]
    draw.polygon(bowl, fill=CLAY)
    draw.ellipse([cx - 1.0 * s, cy - 0.32 * s, cx + 0.8 * s, cy + 0.02 * s], fill=CLAY_DARK)
    draw.ellipse([cx - 0.85 * s, cy - 0.24 * s, cx + 0.65 * s, cy - 0.04 * s], fill=(60, 22, 10))
    # decorative dots on the rim
    for i in range(7):
        px = cx - 0.75 * s + i * 0.24 * s
        draw.ellipse([px - 0.035 * s, cy + 0.17 * s, px + 0.035 * s, cy + 0.24 * s], fill=GOLD)
    return cx + 1.05 * s, cy - 0.45 * s  # wick position


def draw_flame(draw, x, y, s, t, seed, k):
    if k <= 0:
        return
    flick = 1 + 0.08 * math.sin(t * 13 + seed) + 0.05 * math.sin(t * 29 + seed * 2.3)
    sway = 0.06 * s * math.sin(t * 7 + seed * 1.7)
    hgt = 0.9 * s * flick * k
    wid = 0.22 * s * k

    def tear(scale, color):
        pts = []
        for i in range(24):
            a = i / 24 * 2 * math.pi
            px = math.sin(a) * wid * scale
            py = -(1 - math.cos(a)) / 2 * hgt * scale
            bend = (py / hgt) ** 2 * sway * 4 if hgt else 0
            pts.append((x + px * (1 + py / hgt * 0.9) + bend, y + py))
        draw.polygon(pts, fill=color)

    tear(1.0, (255, 140, 30))
    tear(0.75, (255, 200, 70))
    tear(0.45, (255, 248, 220))


def render(w, h, out):
    n = int(FPS * DURATION)
    s = h / 1080
    bg = background(w, h)
    big_glow = glow_sprite(int(260 * s))
    small_glow = glow_sprite(int(120 * s))

    # Seven diyas in a gentle arc; the centre one is larger.
    count = 7
    diyas = []
    for i in range(count):
        off = i - count // 2
        cx = w / 2 + off * min(230 * s, w / 7.6)  # keep the outer diyas in frame
        cy = h * 0.74 + (off ** 2) * 9 * s
        size = (95 if off == 0 else 62) * s
        light_at = 0.6 + (3 - abs(off)) * 0.45 if off != 0 else 2.2  # outside-in, centre last
        diyas.append((cx, cy, size, light_at, i * 1.37))

    # Static layer of unlit diyas, drawn once.
    body = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(body)
    wicks = [draw_diya(bd, cx, cy, sz) for cx, cy, sz, _, _ in diyas]

    rng = np.random.default_rng(7)
    parts = rng.random((70, 4))  # x, phase, speed, size

    title_font = ImageFont.truetype(SERIF, int(150 * s))
    tag_font = ImageFont.truetype(SANS, int(44 * s))
    title, tag = "DesiDiya", "Light up every celebration"

    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264",
         "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE)

    for f in range(n):
        t = f / FPS
        fade_out = 1 - smooth((t - (DURATION - 1.2)) / 1.0)  # back to dark for a seamless loop
        img = bg.copy()

        # Rising golden embers, wrapping so the loop is seamless.
        for px, ph, sp, sz in parts:
            yy = (ph - t / DURATION * (1 + int(sp * 2))) % 1.0
            xx = px * w + 25 * s * math.sin(t * 1.3 + ph * 9)
            k = 0.5 * (0.4 + 0.6 * sz) * math.sin(math.pi * yy)
            r = int((2 + 3 * sz) * s)
            cy = h * (1.05 - 1.1 * (1 - yy))
            img[max(int(cy) - r, 0):max(int(cy) + r, 0), max(int(xx) - r, 0):max(int(xx) + r, 0)] += \
                np.array([255, 190, 90]) * k

        lit = []
        for (cx, cy, sz, at, seed), (wx, wy) in zip(diyas, wicks):
            k = smooth((t - at) / 0.5) * fade_out
            lit.append(k)
            if k > 0:
                flick = 1 + 0.07 * math.sin(t * 11 + seed)
                sprite = big_glow if sz > 80 * s else small_glow
                add_sprite(img, sprite, wx, wy - 0.3 * sz, 210 * k * flick)

        frame = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
        frame.paste(body, (0, 0), body)
        d = ImageDraw.Draw(frame)
        for (cx, cy, sz, at, seed), (wx, wy), k in zip(diyas, wicks, lit):
            draw_flame(d, wx, wy, sz, t, seed, k)

        # Wordmark + tagline rise and fade in.
        tk = smooth((t - 3.2) / 1.0) * fade_out
        gk = smooth((t - 4.2) / 1.0) * fade_out
        if tk > 0:
            txt = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            td = ImageDraw.Draw(txt)
            ty = h * 0.30 + (1 - tk) * 30 * s
            td.text((w / 2, ty), title, font=title_font, fill=GOLD + (int(255 * tk),), anchor="mm")
            if gk > 0:
                gy = h * 0.30 + 115 * s + (1 - gk) * 20 * s
                td.text((w / 2, gy), tag, font=tag_font, fill=CREAM + (int(255 * gk),), anchor="mm")
                lw = 260 * s * gk
                td.line([(w / 2 - lw, gy + 50 * s), (w / 2 + lw, gy + 50 * s)],
                        fill=GOLD + (int(160 * gk),), width=max(1, int(2 * s)))
            halo = txt.filter(ImageFilter.GaussianBlur(18 * s))
            frame.paste(halo, (0, 0), halo)
            frame.paste(txt, (0, 0), txt)

        enc.stdin.write(frame.tobytes())
    enc.stdin.close()
    enc.wait()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--out", default="diya_lights.mp4")
    a = ap.parse_args()
    w, h = map(int, a.size.split("x"))
    render(w, h, a.out)
