#!/usr/bin/env python3
"""One perfect strawberry, rendered in code.

Pure Python 3.13 stdlib, no network, no third-party packages. A
hand-written rasterizer draws a single glossy strawberry -- ripe red
body, pale gold seeds, green calyx leaves, a leaning stem, water
droplets and a soft drop shadow -- on a warm cream background, and a
minimal PNG encoder (zlib) writes it out.

Run:  python3 main.py
Out:  /output/entry.png  (1024 x 1024, <= 1 MiB)
"""

import math
import os
import random
import struct
import zlib

W = H = 1024
OUT = "/output/entry.png"

# ---------------------------------------------------------------- canvas

def new_canvas():
    return [bytearray(W * 3) for _ in range(H)]


def lerp(a, b, t):
    return a + (b - a) * t


def clamp01(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def mix3(c1, c2, t):
    return (int(lerp(c1[0], c2[0], t)),
            int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


def set_px(buf, x, y, color):
    if 0 <= x < W and 0 <= y < H:
        row = buf[y]
        i = x * 3
        row[i], row[i + 1], row[i + 2] = color


def blend_px(buf, x, y, color, alpha):
    """Blend color over the pixel at (x, y); alpha 0..1."""
    if 0 <= x < W and 0 <= y < H:
        row = buf[y]
        i = x * 3
        row[i] = int(lerp(row[i], color[0], alpha))
        row[i + 1] = int(lerp(row[i + 1], color[1], alpha))
        row[i + 2] = int(lerp(row[i + 2], color[2], alpha))


def stamp_disc(buf, cx, cy, r, color):
    """Filled circle, integer centre/radius."""
    r = int(r)
    if r <= 0:
        return
    x0 = max(0, cx - r)
    x1 = min(W - 1, cx + r)
    y0 = max(0, cy - r)
    y1 = min(H - 1, cy + r)
    rr = r * r
    for yy in range(y0, y1 + 1):
        dy = yy - cy
        dx = int(math.sqrt(max(0, rr - dy * dy)))
        row = buf[yy]
        xa = max(0, cx - dx)
        xb = min(W - 1, cx + dx)
        for xx in range(xa, xb + 1):
            i = xx * 3
            row[i], row[i + 1], row[i + 2] = color


def stamp_ellipse(buf, cx, cy, rx, ry, color):
    """Filled axis-aligned ellipse (float radii)."""
    x0 = max(0, int(cx - rx))
    x1 = min(W - 1, int(cx + rx) + 1)
    y0 = max(0, int(cy - ry))
    y1 = min(H - 1, int(cy + ry) + 1)
    for yy in range(y0, y1 + 1):
        dy = (yy - cy) / ry
        t = 1.0 - dy * dy
        if t <= 0:
            continue
        dx = rx * math.sqrt(t)
        row = buf[yy]
        xa = max(0, int(cx - dx))
        xb = min(W - 1, int(cx + dx))
        for xx in range(xa, xb + 1):
            i = xx * 3
            row[i], row[i + 1], row[i + 2] = color


def stamp_ellipse_blend(buf, cx, cy, rx, ry, color, alpha):
    x0 = max(0, int(cx - rx))
    x1 = min(W - 1, int(cx + rx) + 1)
    y0 = max(0, int(cy - ry))
    y1 = min(H - 1, int(cy + ry) + 1)
    for yy in range(y0, y1 + 1):
        dy = (yy - cy) / ry
        t = 1.0 - dy * dy
        if t <= 0:
            continue
        dx = rx * math.sqrt(t)
        row = buf[yy]
        xa = max(0, int(cx - dx))
        xb = min(W - 1, int(cx + dx))
        for xx in range(xa, xb + 1):
            i = xx * 3
            row[i] = int(lerp(row[i], color[0], alpha))
            row[i + 1] = int(lerp(row[i + 1], color[1], alpha))
            row[i + 2] = int(lerp(row[i + 2], color[2], alpha))


# ---------------------------------------------------------------- background

CREAM_CENTRE = (251, 239, 212)
CREAM_EDGE = (231, 212, 172)


def paint_background(buf):
    for y in range(H):
        dy = y - 470
        row = buf[y]
        for x in range(W):
            dx = x - 512
            t = (dx * dx + dy * dy) / 720.0 ** 2
            if t > 1.0:
                t = 1.0
            # ease the falloff so the centre stays bright and clean
            t = t * (0.55 + 0.45 * t)
            i = x * 3
            row[i] = int(lerp(CREAM_CENTRE[0], CREAM_EDGE[0], t))
            row[i + 1] = int(lerp(CREAM_CENTRE[1], CREAM_EDGE[1], t))
            row[i + 2] = int(lerp(CREAM_CENTRE[2], CREAM_EDGE[2], t))


def paint_shadow(buf):
    # Soft elliptical drop shadow under the berry.
    cx, cy, rx, ry = 512, 932, 305, 40
    for y in range(cy - ry, cy + ry + 1):
        dy = (y - cy) / ry
        for x in range(cx - rx, cx + rx + 1):
            dx = (x - cx) / rx
            q = 1.0 - dx * dx - dy * dy
            if q <= 0:
                continue
            a = 0.30 * q * q
            blend_px(buf, x, y, (96, 62, 32), a)


# ---------------------------------------------------------------- strawberry body

BODY_CX = 512
BODY_TOP = 330
BODY_BOT = 912
BODY_W = 288

DEEP_RED = (146, 16, 26)
MID_RED = (213, 41, 40)
BRIGHT_RED = (247, 98, 66)


def body_half_width(y):
    """Half-width of the berry at row y (0 outside the berry)."""
    if y < BODY_TOP or y > BODY_BOT:
        return 0.0
    t = (y - BODY_TOP) / (BODY_BOT - BODY_TOP)
    # Domed shoulders: rise from a narrow rounded crown to full width,
    # then taper to a rounded point.
    s = t / 0.22
    if s > 1.0:
        s = 1.0
    shoulder = 0.32 + 0.68 * (s * s * (3.0 - 2.0 * s))
    taper = math.sqrt(max(0.0, 1.0 - t ** 2.6))
    return BODY_W * shoulder * taper


def paint_body(buf):
    for y in range(BODY_TOP, BODY_BOT + 1):
        w = body_half_width(y)
        if w < 1.0:
            continue
        vy = (y - BODY_TOP) / (BODY_BOT - BODY_TOP)
        row = buf[y]
        x0 = int(BODY_CX - w)
        x1 = int(BODY_CX + w)
        for x in range(x0, x1 + 1):
            nx = (x - BODY_CX) / w
            edge = 1.0 - nx * nx            # 1 centre, 0 at the rim
            # Warm light from the upper left.
            hx = (x - 428) / 165.0
            hy = (y - 455) / 185.0
            hl = 1.0 - (hx * hx + hy * hy)
            if hl < 0.0:
                hl = 0.0
            hl2 = hl * hl
            t = 0.22 + 0.62 * edge + 0.55 * hl2 - 0.30 * vy
            t = clamp01(t)
            if t < 0.5:
                r, g, b = mix3(DEEP_RED, MID_RED, t * 2.0)
            else:
                r, g, b = mix3(MID_RED, BRIGHT_RED, (t - 0.5) * 2.0)
            # Broad soft specular sheen, upper left.
            sheen = hl2 * hl2 * 55.0
            r = min(255, int(r + sheen))
            g = min(255, int(g + sheen * 0.55))
            b = min(255, int(b + sheen * 0.35))
            i = x * 3
            row[i], row[i + 1], row[i + 2] = r, g, b


# ---------------------------------------------------------------- seeds

SEED_GOLD = (247, 220, 146)
SEED_RIM = (178, 128, 56)
SEED_LITE = (255, 243, 196)
SEED_SHADOW = (118, 18, 24)


def paint_seeds(buf):
    rng = random.Random(20261123)
    y = 388
    row_idx = 0
    while y < 862:
        w = body_half_width(y)
        vy = (y - BODY_TOP) / (BODY_BOT - BODY_TOP)
        scale = 1.06 - 0.52 * vy
        step = 46.0 * scale
        n = int(w * 1.62 / step)
        offset = (step * 0.5) if (row_idx % 2) else 0.0
        for k in range(-n, n + 1):
            cx = BODY_CX + k * step + offset + rng.uniform(-7, 7)
            cy = y + rng.uniform(-5, 5)
            if abs(cx - BODY_CX) > w * 0.86:
                continue
            rx = 4.6 * scale
            ry = 7.6 * scale
            # Tiny dark pocket under the seed, then rim, then gold.
            stamp_ellipse(buf, cx + 1.5, cy + 2.0, rx + 1.0, ry + 1.0, SEED_SHADOW)
            stamp_ellipse(buf, cx, cy, rx, ry, SEED_RIM)
            stamp_ellipse(buf, cx, cy - 0.5, rx - 1.2, ry - 1.6, SEED_GOLD)
            stamp_disc(buf, int(cx - 1.5), int(cy - 2.5), max(1, int(1.6 * scale)), SEED_LITE)
        y += int(47 * scale)
        row_idx += 1


# ---------------------------------------------------------------- droplets

def paint_droplets(buf):
    rng = random.Random(77)
    spots = []
    tries = 0
    while len(spots) < 9 and tries < 300:
        tries += 1
        x = rng.uniform(300, 724)
        y = rng.uniform(390, 830)
        w = body_half_width(int(y))
        if w < 10 or abs(x - BODY_CX) > w * 0.78:
            continue
        if any((x - sx) ** 2 + (y - sy) ** 2 < 2600 for sx, sy, _ in spots):
            continue
        spots.append((x, y, rng.uniform(6.5, 13.0)))
    for cx, cy, r in spots:
        # Glassy bead: pale cool tint over the red, bright sparkle.
        stamp_ellipse_blend(buf, cx, cy, r, r, (226, 236, 246), 0.42)
        stamp_ellipse_blend(buf, cx, cy + r * 0.45, r * 0.85, r * 0.4,
                            (120, 36, 44), 0.30)
        stamp_disc(buf, int(cx - r * 0.34), int(cy - r * 0.38),
                   max(1, int(r * 0.30)), (255, 255, 255))


# ---------------------------------------------------------------- calyx, stem, leaves

LEAF_DARK = (30, 100, 36)
LEAF_MID = (58, 148, 62)
LEAF_LITE = (150, 206, 118)
CAP_GREEN = (26, 92, 32)
STEM_GREEN = (104, 126, 54)


def paint_stem(buf):
    # Leaning stem, drawn first so the leaves cover its base.
    x0, y0, x1, y1 = 512, 348, 550, 206
    steps = 26
    for i in range(steps + 1):
        t = i / steps
        cx = int(lerp(x0, x1, t))
        cy = int(lerp(y0, y1, t))
        r = lerp(9.5, 5.0, t)
        stamp_disc(buf, cx, cy, r, STEM_GREEN)
    # Lighter edge on the sun side.
    for i in range(steps + 1):
        t = i / steps
        cx = int(lerp(x0, x1, t)) - 2
        cy = int(lerp(y0, y1, t))
        stamp_disc(buf, cx, cy, max(1, int(lerp(3.0, 1.5, t))), (150, 168, 96))


def paint_leaf(buf, angle_deg, length):
    """One pointed leaf fanning from the calyx centre."""
    base_x, base_y = 512, 352
    ang = math.radians(angle_deg - 90.0)  # 0 deg = straight up
    dx = math.cos(ang)
    dy = math.sin(ang)
    # Perpendicular for the slight outward curl.
    px, py = -dy, dx
    steps = 42
    for i in range(steps + 1):
        s = i / steps
        curl = 14.0 * s * s
        cx = base_x + dx * length * s + px * curl
        cy = base_y + dy * length * s + py * curl
        half = 23.0 * math.sin(math.pi * (s ** 0.75)) ** 0.9
        if half < 1.0:
            half = 1.0
        col = mix3(LEAF_DARK, LEAF_MID, s)
        stamp_disc(buf, int(cx), int(cy), half, col)
    # Centre vein, lighter green, along the spine.
    for i in range(2, steps):
        s = i / steps
        curl = 14.0 * s * s
        cx = base_x + dx * length * s + px * curl
        cy = base_y + dy * length * s + py * curl
        stamp_disc(buf, int(cx), int(cy), 2, LEAF_LITE)


def paint_calyx(buf):
    # Five leaves: outer pair low and wide, inner trio upright.
    for angle, length in ((-64, 148), (-33, 182), (0, 198),
                         (33, 182), (64, 148)):
        paint_leaf(buf, angle, length)
    # Cap disc where the leaves meet the berry.
    stamp_ellipse(buf, 512, 350, 56, 17, CAP_GREEN)
    stamp_ellipse(buf, 512, 347, 44, 11, (38, 118, 44))


# ---------------------------------------------------------------- PNG encoder

def chunk(tag, data):
    out = struct.pack(">I", len(data)) + tag + data
    out += struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return out


def write_png(buf, path):
    raw = bytearray()
    for row in buf:
        raw.append(0)  # filter: none
        raw += row
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    buf = new_canvas()
    paint_background(buf)
    paint_shadow(buf)
    paint_stem(buf)
    paint_body(buf)
    paint_seeds(buf)
    paint_droplets(buf)
    paint_calyx(buf)
    size = write_png(buf, OUT)
    print(f"wrote {OUT}: {W}x{H}, {size} bytes")


if __name__ == "__main__":
    main()
