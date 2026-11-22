#!/usr/bin/env python3
"""One perfect strawberry, rendered in pure Python stdlib.

Entry for make.fun's "The picture that tastes of one ingredient":
a single strawberry, glossy with water droplets and seeds, on a warm
cream backdrop. No network, no third-party packages: a hand-written
rasterizer (spans, gradients, soft shadows, specular highlights) plus
a minimal PNG encoder (zlib).

Writes /output/entry.png (1024x1024).
"""

import math
import os
import struct
import zlib

W = H = 1024
OUT = "/output/entry.png"

CX = 512
Y0, Y1 = 315, 895          # body top, tip
WMAX = 252                 # max half-width of the berry

# ---- palette -------------------------------------------------------
BG_C = (253, 246, 231)     # warm cream, centre
BG_M = (247, 232, 200)     # warm cream, mid
BG_E = (232, 206, 158)     # warm cream, edge
RED_HI = (255, 118, 92)    # highlight tint
RED_MID = (233, 34, 40)    # ripe red
RED_DEEP = (158, 12, 28)   # deep red edge
GREEN_D = (34, 88, 28)
GREEN_M = (74, 148, 52)
GREEN_L = (122, 190, 78)
SEED_TOP = (255, 226, 152)
SEED_BOT = (238, 186, 88)
SEED_EDGE = (198, 146, 58)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def mix3(a, b, t):
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def half_width(y):
    """Half-width of the strawberry body at row y (rounded shoulders,
    tapering to a soft point)."""
    t = (y - Y0) / (Y1 - Y0)
    if t <= 0.0:
        return WMAX * 0.62
    if t >= 1.0:
        return 0.0
    s = t / 0.18
    if s > 1.0:
        s = 1.0
    shoulder = 0.55 + 0.45 * (s * s * (3.0 - 2.0 * s))
    return WMAX * shoulder * (1.0 - t ** 2.35) ** 0.58


def body_rgb(x, y, w):
    """Ripe-red shading for a body pixel: bright centre-left, deep red
    edges, darker tip, warm rim light on the right."""
    nx = (x - CX) / w
    ny = (y - Y0) / (Y1 - Y0)
    r = math.sqrt(nx * nx + ny * ny * 0.9)
    te = r * r * (3.0 - 2.0 * r) if r < 1.0 else 1.0
    cr, cg, cb = mix3(RED_MID, RED_DEEP, te)
    # soft highlight, upper-left
    dhx = (nx + 0.38) / 0.62
    dhy = (ny - 0.28) / 0.42
    hl = math.exp(-(dhx * dhx + dhy * dhy))
    a = hl * 0.72
    cr += (255 - cr) * a
    cg += (118 - cg) * a
    cb += (92 - cb) * a
    # darken toward the tip
    dark = 1.0 - 0.16 * ny * ny
    cr *= dark
    cg *= dark
    cb *= dark
    # warm rim light on the right edge
    rim = math.exp(-((nx - 0.97) * 6.0) ** 2) * (1.0 - 0.45 * ny)
    cr += (255 - cr) * rim * 0.30
    cg += (150 - cg) * rim * 0.30
    cb += (100 - cb) * rim * 0.30
    return (int(clamp(cr, 0, 255)),
            int(clamp(cg, 0, 255)),
            int(clamp(cb, 0, 255)))


# ---- primitive fills -----------------------------------------------

def fill_circle(rows, cx, cy, r, rgb, alpha=1.0):
    cx = int(round(cx))
    cy = int(round(cy))
    r = int(round(r))
    if r <= 0:
        return
    R, G, B = int(rgb[0]), int(rgb[1]), int(rgb[2])
    for dy in range(-r, r + 1):
        y = cy + dy
        if y < 0 or y >= H:
            continue
        dx = int(math.sqrt(r * r - dy * dy))
        row = rows[y]
        for x in range(cx - dx, cx + dx + 1):
            if x < 0 or x >= W:
                continue
            i3 = x * 3
            if alpha >= 1.0:
                row[i3] = R
                row[i3 + 1] = G
                row[i3 + 2] = B
            else:
                row[i3] = int(row[i3] + (R - row[i3]) * alpha)
                row[i3 + 1] = int(row[i3 + 1] + (G - row[i3 + 1]) * alpha)
                row[i3 + 2] = int(row[i3 + 2] + (B - row[i3 + 2]) * alpha)


def fill_ellipse(rows, cx, cy, rx, ry, rgb, alpha=1.0):
    cx = int(round(cx))
    cy = int(round(cy))
    rx = int(round(rx))
    ry = int(round(ry))
    if rx <= 0 or ry <= 0:
        return
    R, G, B = int(rgb[0]), int(rgb[1]), int(rgb[2])
    for dy in range(-ry, ry + 1):
        y = cy + dy
        if y < 0 or y >= H:
            continue
        f = 1.0 - (dy / ry) ** 2
        if f <= 0.0:
            continue
        dx = int(rx * math.sqrt(f))
        row = rows[y]
        for x in range(cx - dx, cx + dx + 1):
            if x < 0 or x >= W:
                continue
            i3 = x * 3
            if alpha >= 1.0:
                row[i3] = R
                row[i3 + 1] = G
                row[i3 + 2] = B
            else:
                row[i3] = int(row[i3] + (R - row[i3]) * alpha)
                row[i3 + 1] = int(row[i3 + 1] + (G - row[i3 + 1]) * alpha)
                row[i3 + 2] = int(row[i3 + 2] + (B - row[i3 + 2]) * alpha)


def soft_ellipse(rows, cx, cy, rx, ry, rgb, max_alpha):
    """Radial-falloff ellipse (soft shadow)."""
    R, G, B = rgb
    for dy in range(-ry, ry + 1):
        y = cy + dy
        if y < 0 or y >= H:
            continue
        f = 1.0 - (dy / ry) ** 2
        if f <= 0.0:
            continue
        dx = int(rx * math.sqrt(f))
        row = rows[y]
        for x in range(cx - dx, cx + dx + 1):
            if x < 0 or x >= W:
                continue
            q = 1.0 - ((x - cx) / rx) ** 2 - (dy / ry) ** 2
            if q <= 0.0:
                continue
            a = max_alpha * q
            i3 = x * 3
            row[i3] = int(row[i3] + (R - row[i3]) * a)
            row[i3 + 1] = int(row[i3 + 1] + (G - row[i3 + 1]) * a)
            row[i3 + 2] = int(row[i3 + 2] + (B - row[i3 + 2]) * a)


# ---- strawberry parts ----------------------------------------------

LEAVES = [(-62, 150), (-32, 188), (0, 208), (32, 188), (62, 150)]


def draw_leaf(rows, ang_deg, length):
    a = math.radians(ang_deg)
    dx_dir = math.sin(a)
    dy_dir = -math.cos(a)
    bx, by = 512.0, 342.0
    cos_a = max(0.45, abs(math.cos(a)))
    n = int(length)
    for i in range(n + 1):
        s = i / n
        px = bx + dx_dir * s * length
        py = by + dy_dir * s * length
        half = 25.0 * math.sin(math.pi * (s ** 0.8)) * (1.0 - 0.25 * s) / cos_a
        if half < 0.6:
            continue
        y = int(round(py))
        if y < 0 or y >= H:
            continue
        c = mix3(GREEN_D, GREEN_L, s)
        row = rows[y]
        x0 = int(px - half - 2)
        x1 = int(px + half + 2)
        for x in range(max(0, x0), min(W, x1 + 1)):
            i3 = x * 3
            row[i3] = GREEN_D[0]
            row[i3 + 1] = GREEN_D[1]
            row[i3 + 2] = GREEN_D[2]
        x0 = int(px - half)
        x1 = int(px + half)
        for x in range(max(0, x0), min(W, x1 + 1)):
            i3 = x * 3
            row[i3] = int(c[0])
            row[i3 + 1] = int(c[1])
            row[i3 + 2] = int(c[2])


def draw_leaf_veins(rows):
    for ang_deg, length in LEAVES:
        a = math.radians(ang_deg)
        dx_dir = math.sin(a)
        dy_dir = -math.cos(a)
        for i in range(int(length * 0.15), int(length * 0.9)):
            s = i / length
            px = 512.0 + dx_dir * s * length
            py = 342.0 + dy_dir * s * length
            x = int(round(px))
            y = int(round(py))
            if 0 <= x < W and 0 <= y < H:
                row = rows[y]
                for xx in (x - 1, x):
                    if 0 <= xx < W:
                        i3 = xx * 3
                        row[i3] = int(row[i3] * 0.35 + 150 * 0.65)
                        row[i3 + 1] = int(row[i3 + 1] * 0.35 + 210 * 0.65)
                        row[i3 + 2] = int(row[i3 + 2] * 0.35 + 110 * 0.65)


def draw_stem(rows):
    for k in range(41):
        t = k / 40.0
        x = 512 + 34 * t + 26 * t * t
        y = 340 - 104 * t
        r = 7.0 - 2.5 * t
        fill_circle(rows, x, y, r, (96, 122, 46))
        fill_circle(rows, x - 2, y, max(1, r * 0.45), (150, 175, 90), 0.7)


def draw_seed(rows, sx, sy, w, nx):
    rx = max(4.5, min(10.0, 0.035 * w))
    ry = rx * 1.5
    rot = nx * 0.45
    shear = math.sin(rot)
    # soft shadow under the seed
    fill_ellipse(rows, sx + 2, sy + 3, rx, ry, (120, 18, 24), 0.45)
    # seed body: pale gold, lighter on top, darker rim
    ry_i = int(ry) + 1
    for dy in range(-ry_i, ry_i + 1):
        y = sy + dy
        if y < 0 or y >= H:
            continue
        f = 1.0 - (dy / ry) ** 2
        if f <= 0.0:
            continue
        dx = rx * math.sqrt(f)
        ccx = sx + dy * shear
        t = (dy / ry + 1.0) / 2.0
        cr, cg, cb = mix3(SEED_TOP, SEED_BOT, t)
        row = rows[y]
        x0 = int(ccx - dx)
        x1 = int(ccx + dx)
        for x in range(max(0, x0), min(W, x1 + 1)):
            edge = abs(x - ccx) / dx if dx > 0 else 0.0
            if edge > 0.82:
                r2, g2, b2 = SEED_EDGE
            else:
                r2, g2, b2 = cr, cg, cb
            i3 = x * 3
            row[i3] = int(r2)
            row[i3 + 1] = int(g2)
            row[i3 + 2] = int(b2)
    # tiny highlight
    fill_circle(rows, sx - rx * 0.35, sy - ry * 0.35, 1.8, (255, 255, 255), 0.85)


def draw_seeds(rows):
    rows_ny = [0.10, 0.22, 0.34, 0.46, 0.58, 0.70, 0.82, 0.92]
    for ri, ny in enumerate(rows_ny):
        y = int(Y0 + ny * (Y1 - Y0))
        w = half_width(y)
        off = 0.13 if ri % 2 else 0.0
        nx = -0.78 + off
        while nx <= 0.78:
            # deterministic jitter so the rows don't look machine-gridded
            h1 = math.sin(ri * 127.1 + nx * 311.7) * 43758.5453
            h2 = math.sin(ri * 269.5 + nx * 183.3) * 28001.8384
            jx = (h1 - math.floor(h1) - 0.5) * 10.0
            jy = (h2 - math.floor(h2) - 0.5) * 7.0
            sx = int(CX + nx * w + jx)
            draw_seed(rows, sx, int(y + jy), w, nx)
            nx += 0.26


DROPS = [(430, 470, 13), (600, 500, 16), (505, 615, 11), (645, 430, 9),
         (375, 590, 10), (560, 705, 12), (465, 545, 8), (625, 640, 9),
         (395, 470, 7)]


def draw_droplets(rows):
    for (x, y, r) in DROPS:
        w = half_width(y)
        if abs(x - CX) > w * 0.88:
            continue
        base = body_rgb(x, y, w)
        fill_circle(rows, x, y, r + 1, (150, 20, 30), 0.25)
        fill_circle(rows, x, y, r, mix3(base, (255, 255, 255), 0.18))
        fill_circle(rows, x - r * 0.25, y - r * 0.30, r * 0.55,
                    mix3(base, (255, 255, 255), 0.35), 0.8)
        fill_circle(rows, x - r * 0.35, y - r * 0.42, r * 0.22,
                    (255, 255, 255), 0.95)


# ---- render ----------------------------------------------------------

def render():
    rows = [bytearray(W * 3) for _ in range(H)]

    # warm cream radial background (lookup table by radius)
    bg = []
    for i in range(1024):
        t = i / 1023.0
        if t < 0.55:
            c = mix3(BG_C, BG_M, t / 0.55)
        else:
            c = mix3(BG_M, BG_E, (t - 0.55) / 0.45)
        bg.append((int(c[0]), int(c[1]), int(c[2])))
    isqrt = math.isqrt
    for y in range(H):
        dy = y - 470
        dy2 = dy * dy
        row = rows[y]
        for x in range(W):
            dx = x - 512
            idx = isqrt(dx * dx + dy2) * 1023 // 760
            if idx > 1023:
                idx = 1023
            c = bg[idx]
            i3 = x * 3
            row[i3] = c[0]
            row[i3 + 1] = c[1]
            row[i3 + 2] = c[2]

    # soft drop shadow under the berry
    soft_ellipse(rows, 512, 905, 275, 50, (88, 44, 20), 0.30)

    # strawberry body (domed top edge so the shoulders curve, not flat)
    w_top = half_width(Y0)
    x_lo = int(CX - WMAX)
    ystart = []
    for x in range(x_lo, int(CX + WMAX) + 1):
        u = (x - CX) / w_top
        ystart.append(Y0 + 34 * u * u if abs(u) <= 1.0 else Y0 + 34)
    for y in range(Y0, Y1):
        w = half_width(y)
        x0 = int(CX - w)
        x1 = int(CX + w)
        row = rows[y]
        for x in range(x0, x1 + 1):
            if y < ystart[x - x_lo]:
                continue
            r, g, b = body_rgb(x, y, w)
            i3 = x * 3
            row[i3] = r
            row[i3 + 1] = g
            row[i3 + 2] = b

    # soft specular sheen, upper-left of the body
    for dy in range(-210, 211):
        y = 435 + dy
        if y < 0 or y >= H:
            continue
        for dx in range(-210, 211):
            x = 425 + dx
            if x < 0 or x >= W:
                continue
            d = math.sqrt(dx * dx + dy * dy)
            if d >= 210:
                continue
            w = half_width(y)
            if abs(x - CX) > w:
                continue
            a = 0.28 * (1.0 - d / 210.0) ** 2
            row = rows[y]
            i3 = x * 3
            row[i3] = int(row[i3] + (255 - row[i3]) * a)
            row[i3 + 1] = int(row[i3 + 1] + (240 - row[i3 + 1]) * a)
            row[i3 + 2] = int(row[i3 + 2] + (225 - row[i3 + 2]) * a)

    # stem, calyx crown, leaves
    draw_stem(rows)
    fill_ellipse(rows, 512, 344, 58, 26, (46, 104, 36))
    fill_ellipse(rows, 512, 336, 34, 15, GREEN_M)
    for ang, ln in LEAVES:
        draw_leaf(rows, ang, ln)
    draw_leaf_veins(rows)

    # seeds and water droplets
    draw_seeds(rows)
    draw_droplets(rows)
    return rows


# ---- PNG encoder -----------------------------------------------------

def encode_png(rows):
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter: None
        raw += row
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        c = tag + data
        return (struct.pack(">I", len(data)) + c +
                struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    out += chunk(b"IDAT", comp)
    out += chunk(b"IEND", b"")
    return bytes(out)


def main():
    rows = render()
    png = encode_png(rows)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(png)
    print("wrote %s: %dx%d, %d bytes" % (OUT, W, H, len(png)))


if __name__ == "__main__":
    main()
