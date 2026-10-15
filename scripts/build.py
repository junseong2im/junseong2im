#!/usr/bin/env python3
"""Pixel-art SVG generator for the profile README.

    python scripts/build.py                  # static assets -> assets/*.svg
    python scripts/build.py stats OUT.svg    # live stats card (run daily by the workflow)

Text is rendered to paths with the Galmuri pixel fonts (SIL OFL 1.1, by Lee Minseo),
so the SVGs look identical everywhere without any font loading.
"""
import base64
import datetime as dt
import html
import io
import json
import os
import random
import re
import sys
import urllib.request

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
FONT_DIR = os.path.join(ROOT, ".fonts")
FONT_URL = "https://cdn.jsdelivr.net/npm/galmuri@2.40.3/dist/"
USER = "junseong2im"

C = dict(
    ink="#07081a", night="#0d0f2b", panel="#14173a", panel2="#1d2150", line="#2b3070", line2="#3e4499",
    cream="#f6eedb", text="#e9e7ff", muted="#a3a8dc", dim="#6268ad",
    amber="#ffb547", amber2="#ff8f3f", coral="#ff6f7d", teal="#5ee7d8", lav="#a99bff", leaf="#8be07f",
    sky="#6fb5ff", brown="#8a5a3c", brown2="#5a3520",
)

BASE_CSS = (
    "@keyframes tw{0%,100%{opacity:.15}50%{opacity:1}}"
    ".t1{animation:tw 2.6s infinite}.t2{animation:tw 3.4s 1.1s infinite}.t3{animation:tw 4.6s 2.2s infinite}"
    "@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}.blink{animation:blink 1s steps(1) infinite}"
    "@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}"
    ".bob{animation:bob 1.2s steps(2) infinite}"
    "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
)


# ---------------------------------------------------------------- primitives

class Font:
    def __init__(self, name):
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):
            os.makedirs(FONT_DIR, exist_ok=True)
            urllib.request.urlretrieve(FONT_URL + name, path)
        self.tt = TTFont(path)
        self.gs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.hm = self.tt["hmtx"]
        self.upm = self.tt["head"].unitsPerEm

    def _g(self, ch):
        return self.cmap.get(ord(ch)) or self.cmap[ord("?")]

    def advances(self, text, size):
        return [self.hm[self._g(ch)][0] * size / self.upm for ch in text]

    def width(self, text, size):
        return sum(self.advances(text, size))

    def path(self, text, size, x, y):
        s = size / self.upm
        pen = SVGPathPen(self.gs, ntos=lambda v: ("%.2f" % v).rstrip("0").rstrip("."))
        cx = x
        for ch in text:
            g = self._g(ch)
            self.gs[g].draw(TransformPen(pen, (s, 0, 0, -s, cx, y)))
            cx += self.hm[g][0] * s
        return pen.getCommands()


REG = BOLD = SMALL = None


def load_fonts():
    global REG, BOLD, SMALL
    REG, BOLD, SMALL = Font("Galmuri11.ttf"), Font("Galmuri11-Bold.ttf"), Font("Galmuri9.ttf")


def esc(s):
    return html.escape(s, quote=True)


def text(s, x, y, fill, size=20, font=None, anchor="start", cls=""):
    font = font or SMALL
    w = font.width(s, size)
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    c = f' class="{cls}"' if cls else ""
    return f'<path{c} fill="{fill}" d="{font.path(s, size, x, y)}"/>'


def notch(x, y, w, h, c=4):
    """Rectangle with two-step pixel corners."""
    p = [(x + 2 * c, y), (x + w - 2 * c, y), (x + w - 2 * c, y + c), (x + w - c, y + c), (x + w - c, y + 2 * c),
         (x + w, y + 2 * c), (x + w, y + h - 2 * c), (x + w - c, y + h - 2 * c), (x + w - c, y + h - c),
         (x + w - 2 * c, y + h - c), (x + w - 2 * c, y + h), (x + 2 * c, y + h), (x + 2 * c, y + h - c),
         (x + c, y + h - c), (x + c, y + h - 2 * c), (x, y + h - 2 * c), (x, y + 2 * c), (x + c, y + 2 * c),
         (x + c, y + c), (x + 2 * c, y + c)]
    return "M" + "L".join(f"{a:g} {b:g}" for a, b in p) + "Z"


def panel(x, y, w, h, fill=None, border=None, accent=None, shadow=True):
    fill, border = fill or C["panel"], border or C["ink"]
    out = []
    if shadow:
        out.append(f'<path fill="#000" fill-opacity=".35" d="{notch(x + 6, y + 6, w, h)}"/>')
    out.append(f'<path fill="{border}" d="{notch(x, y, w, h)}"/>')
    if accent:
        out.append(f'<path fill="{accent}" d="{notch(x + 4, y + 4, w - 8, h - 8)}"/>')
        out.append(f'<path fill="{fill}" d="{notch(x + 8, y + 8, w - 16, h - 16)}"/>')
    else:
        out.append(f'<path fill="{fill}" d="{notch(x + 4, y + 4, w - 8, h - 8)}"/>')
        out.append(f'<rect x="{x + 12}" y="{y + 4}" width="{w - 24}" height="2" fill="#fff" fill-opacity=".08"/>')
    return "".join(out)


def sprite(rows, pal, x, y, p):
    """ASCII pixel art -> one <path> per colour, horizontal runs merged."""
    runs = {}
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            ch = row[c]
            if ch == "." or ch == " ":
                c += 1
                continue
            s = c
            while c < len(row) and row[c] == ch:
                c += 1
            runs.setdefault(ch, []).append(f"M{x + s * p:g} {y + r * p:g}h{(c - s) * p:g}v{p:g}h{-(c - s) * p:g}z")
    return "".join(f'<path fill="{pal[k]}" d="{"".join(v)}"/>' for k, v in runs.items())


def stars(seed, n, box, colors=("#ffffff",), sizes=(2, 2, 4)):
    rng = random.Random(seed)
    x0, y0, x1, y1 = box
    out = []
    for _ in range(n):
        x, y = rng.randrange(x0, x1, 2), rng.randrange(y0, y1, 2)
        s = rng.choice(sizes)
        out.append(f'<rect class="t{rng.randint(1, 3)}" x="{x}" y="{y}" width="{s}" height="{s}" '
                   f'fill="{rng.choice(colors)}"/>')
    return "".join(out)


def sparkle(x, y, color, cls, p=4):
    return sprite([".a.", "aba", ".a."], {"a": color, "b": "#fff"}, x, y, p).replace("<path", f'<path class="{cls}"')


def svg(w, h, body, css="", title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'shape-rendering="crispEdges" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>'
            f'<style>{BASE_CSS}{css}</style>{body}</svg>')


def save(name, content):
    with open(os.path.join(ASSETS, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"  {name:28s} {len(content) / 1024:7.1f} KB")


def wrap(s, font, size, max_w):
    lines, cur = [], ""
    for word in s.split(" "):
        trial = (cur + " " + word).strip()
        if cur and font.width(trial, size) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur]


# ---------------------------------------------------------------- sprites

SWORD = ["..........ww", ".........wsw", "........wsw.", ".......wsw..", "......wsw...", "..y..wsw....",
         "..yywsw.....", "...yyw......", "...byy......", "..bb..y.....", ".bb.........", "bb.........."]
TROPHY = ["..yyyyyyyy..", "yyywyyyyyoyy", "y.ywyyyyyo.y", "y.ywyyyyyo.y", ".yywyyyyyoy.", "...ywyyyo...",
          "....yyyo....", ".....yo.....", ".....yo.....", "....yyoo....", "...bbbbbb...", "...bbbbbb..."]
CHEST = ["............", ".dddddddddd.", "dooooooooood", "dowoooooooodd"[:12], "dddddyyddddd", "dooooyyooood",
         "dooooooooood", "dooooooooood", "dddddddddddd", "............", "............", "............"]
HEART = [".rr..rr.", "rwrrrrrr", "rwrrrrrr", "rrrrrrrr", ".rrrrrr.", "..rrrr..", "...rr..."]
MAP = ["pppppppppppp", "pggggpgggggp", "pgxggpggxggp", "pggxgpgxgggp", "pgggxxxggggp", "pggggpggxxgp",
       "pgggggpgggxp", "pgggggpggggp", "pppppppppppp"]

ICON_PAL = {"w": "#e6ecff", "s": "#9aa7d6", "y": C["amber"], "o": C["amber2"], "b": C["brown"], "d": C["brown2"],
            "r": C["coral"], "p": C["brown"], "g": "#e9d9a8", "x": C["coral"]}


# ---------------------------------------------------------------- hero (animated banner)

def build_hero():
    from PIL import Image
    im = Image.open(os.path.join(ASSETS, "banner.png")).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=90, method=6)
    b64 = base64.b64encode(buf.getvalue()).decode()
    W, H = 2000, 667
    rng = random.Random(7)
    body = [f'<image href="data:image/webp;base64,{b64}" width="{W}" height="{H}" preserveAspectRatio="none" '
            f'style="image-rendering:pixelated"/>']
    # twinkling stars in the two windows
    pts = [(668, 22), (712, 64), (790, 18), (835, 92), (742, 112), (905, 30), (958, 84), (1012, 18), (1066, 58),
           (1118, 22), (1158, 96), (1330, 18), (1382, 70), (1446, 30), (1520, 52), (1576, 16), (1622, 74),
           (1098, 128), (930, 140), (1262, 104), (1490, 98), (875, 52)]
    for x, y in pts:
        s = rng.choice((3, 3, 5))
        body.append(f'<rect class="t{rng.randint(1, 3)}" x="{x}" y="{y}" width="{s}" height="{s}" fill="#fff"/>')
    # shooting star
    body.append('<g class="shoot"><rect x="0" y="0" width="70" height="3" fill="url(#trail)"/>'
                '<rect x="66" y="-1" width="6" height="5" fill="#fff"/></g>')
    # lamp glow
    body.append('<ellipse class="glow" cx="482" cy="318" rx="150" ry="110" fill="url(#lamp)"/>')
    # point travelling along the plot on the right monitor
    curve = "M1106 405 C1140 380 1165 352 1205 338 S1240 330 1252 331"
    body.append(f'<circle r="9" fill="{C["amber"]}" fill-opacity=".35"><animateMotion dur="3.2s" '
                f'repeatCount="indefinite" path="{curve}"/></circle>'
                f'<circle r="4" fill="#fff6dd"><animateMotion dur="3.2s" repeatCount="indefinite" path="{curve}"/></circle>')
    # caret in the left monitor
    body.append(f'<rect class="blink" x="797" y="415" width="8" height="12" fill="{C["teal"]}"/>')
    # steam over both mugs
    for i, (x, y) in enumerate([(392, 478), (1335, 462)]):
        for j in range(3):
            body.append(f'<rect class="steam" style="animation-delay:{i * .7 + j * .9:.1f}s" x="{x + j * 8 - 8}" '
                        f'y="{y}" width="5" height="5" fill="#fff"/>')
    # shimmering reflections on the lake
    for _ in range(18):
        x, y = (rng.randrange(1300, 1630), rng.randrange(248, 330)) if rng.random() < .6 else             (rng.randrange(960, 1260), rng.randrange(248, 276))
        body.append(f'<rect class="t{rng.randint(1, 3)}" x="{x}" y="{y}" width="{rng.choice((10, 16, 24))}" '
                    f'height="2" fill="{rng.choice(("#ffd58a", "#ffe9bd", "#9fc4ff"))}"/>')
    # fireflies around the plants
    for i, (x, y) in enumerate([(120, 160), (250, 300), (60, 420), (300, 120), (1700, 330), (1840, 280),
                                (1760, 420), (1600, 360)]):
        body.append(f'<rect class="ff f{i % 3}" style="animation-delay:{i * .6:.1f}s" x="{x}" y="{y}" '
                    f'width="5" height="5" fill="#e9ff9a"/>')
    defs = (f'<defs><radialGradient id="lamp"><stop offset="0" stop-color="#ffcf7a" stop-opacity=".55"/>'
            f'<stop offset="1" stop-color="#ffb547" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="trail"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            f'<stop offset="1" stop-color="#fff"/></linearGradient></defs>')
    css = ("@keyframes shoot{0%{transform:translate(1560px,20px) rotate(162deg);opacity:0}"
           "2%{opacity:1}10%{transform:translate(1250px,120px) rotate(162deg);opacity:0}100%{opacity:0}}"
           ".shoot{animation:shoot 9s 2s linear infinite;opacity:0}"
           "@keyframes glow{0%,100%{opacity:.75}45%{opacity:1}50%{opacity:.82}55%{opacity:1}}"
           ".glow{animation:glow 4s infinite;mix-blend-mode:screen}"
           "@keyframes steam{0%{transform:translate(0,0);opacity:0}20%{opacity:.55}"
           "100%{transform:translate(6px,-46px);opacity:0}}.steam{animation:steam 2.7s steps(9) infinite;opacity:0}"
           "@keyframes ff0{0%,100%{transform:translate(0,0);opacity:.1}50%{transform:translate(18px,-22px);opacity:1}}"
           "@keyframes ff1{0%,100%{transform:translate(0,0);opacity:1}50%{transform:translate(-20px,-12px);opacity:.1}}"
           "@keyframes ff2{0%,100%{transform:translate(0,0);opacity:.2}50%{transform:translate(10px,24px);opacity:1}}"
           ".ff{filter:drop-shadow(0 0 6px #e9ff9a)}.f0{animation:ff0 5s infinite}.f1{animation:ff1 6.5s infinite}"
           ".f2{animation:ff2 4.5s infinite}")
    return svg(W, H, defs + "".join(body), css,
               "저녁 도시가 보이는 창가의 연구·개발 작업실을 담은 픽셀 아트").replace(
        'shape-rendering="crispEdges" ', "")


# ---------------------------------------------------------------- dialog box

def build_dialog():
    W, H = 1000, 214
    T = 14.0
    lines = [("물리 기반 AI · 계산 후각 · 소프트웨어", C["teal"]),
             ("혼합 향의 유사도를 연구하고,", C["cream"]),
             ("시뮬레이션과 웹 서비스를 만듭니다.", C["cream"])]
    x0, ys, size = 52, [104, 144, 184], 24
    body = [panel(4, 36, W - 14, H - 44, fill=C["night"], border=C["ink"], accent=C["cream"])]
    body.append(f'<rect x="16" y="48" width="{W - 38}" height="2" fill="{C["line2"]}"/>')
    body.append(stars(3, 26, (620, 60, 960, 190), ("#ffffff", C["lav"]), (2, 2, 2, 4)))
    # name tag
    name = "김준성 · JUNSEONG KIM"
    nw = BOLD.width(name, 24) + 40
    body.append(panel(30, 2, nw, 50, fill=C["amber"], border=C["ink"], shadow=False))
    body.append(text(name, 50, 36, "#2b1606", 24, BOLD))
    # typed lines: a discrete clip width per line
    keyed, caret = [], [(0.0, x0, ys[0])]
    t = 0.5
    defs = []
    for i, (s, color) in enumerate(lines):
        adv = REG.advances(s, size)
        ev = [(0.0, 0)]
        acc = 0
        for a in adv:
            acc += a
            t += 0.085
            ev.append((t, acc))
            caret.append((t, x0 + acc + 4, ys[i]))
        ev.append((11.6, 0))
        keyed.append(ev)
        t += 0.45
        defs.append(f'<clipPath id="c{i}"><rect x="{x0}" y="{ys[i] - 30}" height="40" width="{acc + 4:.0f}">'
                    f'{discrete("width", ev, T)}</rect></clipPath>')
        body.append(f'<g clip-path="url(#c{i})">{text(s, x0, ys[i], color, size, REG)}</g>')
    caret.append((11.6, x0, ys[0]))
    body.append(f'<g class="blink"><rect y="0" width="12" height="4" fill="{C["amber"]}">'
                f'{discrete("x", [(a, b) for a, b, _ in caret], T)}'
                f'{discrete("y", [(a, c + 2) for a, _, c in caret], T)}</rect></g>')
    body.append(f'<g class="bob">{text("▼", W - 52, H - 22, C["amber"], 24, REG)}</g>')
    return svg(W, H, f'<defs>{"".join(defs)}</defs>' + "".join(body), "",
               "김준성 · Junseong Kim — 물리 기반 AI · 계산 후각 · 소프트웨어. "
               "혼합 향의 유사도를 연구하고, 시뮬레이션과 웹 서비스를 만듭니다.")


def discrete(attr, events, T):
    events = sorted(events)
    kt = ";".join(f"{e[0] / T:.4f}" for e in events)
    vals = ";".join(f"{e[1]:.2f}" for e in events)
    return f'<animate attributeName="{attr}" calcMode="discrete" dur="{T}s" repeatCount="indefinite" keyTimes="{kt}" values="{vals}"/>'


# ---------------------------------------------------------------- buttons & headers

BTN_ICONS = {
    "id": [".xxxxx.", "x.x..xx", "xxx.x.x", "x.x.x.x", "x.x.x.x", "x.x..xx", ".xxxxx."],
    "doc": ["xxxxx.", "x...xx", "x.xx.x", "x....x", "x.xx.x", "x....x", "xxxxxx"],
    "box": ["xxx...", "xxxxxx", "x....x", "x....x", "x....x", "xxxxxx"],
    "code": ["..x....x..", ".x......x.", "x........x", ".x......x.", "..x....x.."],
}


def build_button(label, icon, color, delay):
    W, H = 232, 64
    body = [f'<path fill="{C["ink"]}" d="{notch(0, 4, W - 4, H - 8)}"/>',
            f'<path fill="{shade(color, .55)}" d="{notch(4, 12, W - 12, H - 20)}"/>',
            f'<path fill="{color}" d="{notch(4, 8, W - 12, H - 22)}"/>',
            f'<rect x="16" y="12" width="{W - 36}" height="3" fill="#fff" fill-opacity=".45"/>']
    ic = BTN_ICONS[icon]
    body.append(sprite(ic, {"x": "#1c1406"}, 22, 34 - len(ic) * 2, 4))
    body.append(text(label, 22 + len(ic[0]) * 4 + 12, 42, "#1c1406", 24, BOLD))
    body.append(f'<clipPath id="b"><path d="{notch(4, 8, W - 12, H - 22)}"/></clipPath>'
                f'<g clip-path="url(#b)"><path class="shine" fill="#fff" fill-opacity=".55" '
                f'd="M-40 0h18l-30 64h-18zM-14 0h6l-30 64h-6z"/></g>')
    css = (f"@keyframes sh{{0%,70%{{transform:translateX(0)}}100%{{transform:translateX({W + 90}px)}}}}"
           f".shine{{animation:sh 3.6s {delay}s infinite}}")
    return svg(W, H, "".join(body), css, label)


def shade(hex_color, k):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * k), int(g * k), int(b * k))


def build_header(title, sub, icon_rows, icon_px, seed):
    W, H = 1000, 76
    body = [panel(0, 0, W - 8, H - 8, fill=C["panel"])]
    iw, ih = len(icon_rows[0]) * icon_px, len(icon_rows) * icon_px
    body.append(f'<g class="bob">{sprite(icon_rows, ICON_PAL, 26 + (48 - iw) // 2, 10 + (48 - ih) // 2, icon_px)}</g>')
    body.append(text(title, 92, 46, C["amber"], 24, BOLD))
    tw = BOLD.width(title, 24)
    body.append(text(sub, 92 + tw + 18, 45, C["cream"], 20, SMALL))
    sx = int(92 + tw + 18 + SMALL.width(sub, 20) + 28)
    sx += (4 - sx % 4)
    ex = W - 64
    n = (ex - sx) // 12
    dots = "".join(f"M{sx + i * 12} 32h4v4h-4z" for i in range(n))
    body.append(f'<path fill="{C["line2"]}" d="{dots}"/>')
    body.append(f'<rect class="run" x="{sx}" y="30" width="8" height="8" fill="{C["teal"]}"/>')
    body.append(sparkle(ex + 8, 22, C["amber"], "t1"))
    css = (f"@keyframes run{{0%{{transform:translateX(0)}}100%{{transform:translateX({(n - 1) * 12}px)}}}}"
           f".run{{animation:run {max(2.5, n / 12):.1f}s steps({n - 1}) infinite}}")
    return svg(W, H, "".join(body), css, f"{title} · {sub}")


# ---------------------------------------------------------------- project cards

def scene_physsim(x, y):
    """Perfume bottle with scent particles drifting up."""
    rows = ["........yyyy........", "........yyyy........", ".........gg.........", ".........gg.........",
            "....gggggggggggg....", "...gwlllllllllllg...", "...gwlllllllllllg...", "...glllllllllllllg.."[:20],
            "...gpppppppppppg....", "...gpqpppppppppg....", "...gppppppppqppg....", "...gpppqpppppppg....",
            "...gppppppppppppg..."[:20], "....gggggggggggg...."]
    rows = [r.ljust(20, ".")[:20] for r in rows]
    rows[7] = "...gllllllllllllg..."
    rows[12] = "...gppppppppppppg..."
    out = [sprite(rows, {"y": C["amber"], "g": "#cfd8ff", "w": "#ffffff", "l": "#2a2f6e", "p": C["lav"],
                         "q": "#d8d0ff"}, x + 8, y + 38, 4)]
    cols = [C["teal"], C["lav"], C["amber"], C["coral"], C["teal"], C["lav"]]
    for i in range(6):
        out.append(f'<rect class="rise" style="animation-delay:{i * .55:.2f}s" x="{x + 36 + (i * 11) % 28}" '
                   f'y="{y + 34}" width="4" height="4" fill="{cols[i]}"/>')
    return "".join(out)


def scene_umn(x, y):
    cx, cy = x + 48, y + 48
    out = []
    for r, n in ((18, 14), (30, 22), (41, 30)):
        import math
        d = "".join(f"M{round(cx + r * math.cos(2 * math.pi * k / n)) - 1} "
                    f"{round(cy + r * math.sin(2 * math.pi * k / n)) - 1}h2v2h-2z" for k in range(n))
        out.append(f'<path fill="{C["line2"]}" d="{d}"/>')
    out.append(sprite([".a.", "aaa", ".a."], {"a": C["amber"]}, cx - 6, cy - 6, 4))
    out.append(f'<rect class="t1" x="{cx - 2}" y="{cy - 2}" width="4" height="4" fill="#fff"/>')
    for r, col, dur, s in ((18, C["teal"], 2.4, 6), (30, C["coral"], 4.2, 8), (41, C["lav"], 7.0, 6)):
        out.append(f'<g><animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" '
                   f'to="360 {cx} {cy}" dur="{dur}s" repeatCount="indefinite"/>'
                   f'<rect x="{cx + r - s // 2}" y="{cy - s // 2}" width="{s}" height="{s}" fill="{col}"/></g>')
    return "".join(out)


def scene_fluid(x, y):
    out = [sprite([".mmm", "mm..", "m...", "mm..", ".mmm"], {"m": C["cream"]}, x + 66, y + 10, 3),
           stars(11, 6, (x + 8, y + 8, x + 60, y + 40))]
    ship = ["......w.....", "......wc....", "......wcc...", "......w.....", "rrrrrrrrrrrr", ".rrrrrrrrrr.",
            "..rrrrrrrr.."]
    out.append(f'<g class="sail">{sprite(ship, {"w": C["cream"], "c": C["teal"], "r": C["coral"]}, x + 24, y + 34, 4)}</g>')
    wave = "".join(f"M{i * 16} 0h8v4h-8zM{i * 16 + 8} 4h8v4h-8z" for i in range(14))
    out.append(f'<clipPath id="wv"><rect x="{x}" y="{y + 58}" width="96" height="38"/></clipPath>'
               f'<g clip-path="url(#wv)"><rect x="{x}" y="{y + 62}" width="96" height="34" fill="#1f3a7a"/>'
               f'<g class="wave"><path transform="translate({x - 16} {y + 62})" fill="{C["sky"]}" d="{wave}"/></g>'
               f'<g class="wave2"><path transform="translate({x - 16} {y + 76})" fill="#3a63b8" d="{wave}"/></g></g>')
    return "".join(out)


def scene_spot(x, y):
    out = [f'<rect x="{x + 12}" y="{y + 16}" width="72" height="68" fill="{C["cream"]}"/>',
           f'<rect x="{x + 12}" y="{y + 16}" width="72" height="14" fill="{C["coral"]}"/>',
           f'<rect x="{x + 24}" y="{y + 10}" width="4" height="10" fill="{C["ink"]}"/>',
           f'<rect x="{x + 68}" y="{y + 10}" width="4" height="10" fill="{C["ink"]}"/>']
    k = 0
    for r in range(4):
        for c in range(5):
            cx, cy = x + 16 + c * 13 + 1, y + 34 + r * 12 + 1
            out.append(f'<rect x="{cx}" y="{cy}" width="10" height="9" fill="#d9cfb5"/>')
            if (r * 5 + c) % 3 != 2:
                out.append(f'<rect class="fill" style="animation-delay:{k * .22:.2f}s" x="{cx}" y="{cy}" '
                           f'width="10" height="9" fill="{C["leaf"]}"/>')
                k += 1
    return "".join(out)


SCENE_CSS = (
    "@keyframes rise{0%{transform:translate(0,0);opacity:0}15%{opacity:1}100%{transform:translate(4px,-30px);opacity:0}}"
    ".rise{animation:rise 3.3s steps(10) infinite;opacity:0}"
    "@keyframes sail{0%,100%{transform:translateY(0)}50%{transform:translateY(3px)}}.sail{animation:sail 1.6s steps(2) infinite}"
    "@keyframes wave{0%{transform:translateX(0)}100%{transform:translateX(16px)}}"
    ".wave{animation:wave 1.2s steps(4) infinite}.wave2{animation:wave 1.8s steps(4) infinite reverse}"
    "@keyframes fill{0%,8%{opacity:0}12%,85%{opacity:1}100%{opacity:0}}.fill{animation:fill 7s steps(1) infinite;opacity:0}"
)


def build_card(p):
    W, H = 490, 268
    body = [panel(0, 0, W - 8, H - 8, fill=C["panel"])]
    body.append(f'<path fill="{C["ink"]}" d="{notch(20, 20, 104, 104)}"/>')
    body.append(f'<path fill="{C["night"]}" d="{notch(24, 24, 96, 96)}"/>')
    body.append(p["scene"](24, 24))
    # tag chip
    tw = BOLD.width(p["tag"], 12) + 20
    body.append(f'<path fill="{p["color"]}" d="{notch(142, 24, tw, 24, 2)}"/>')
    body.append(text(p["tag"], 152, 41, C["ink"], 12, BOLD))
    body.append(text(p["name"], 142, 84, C["text"], 24, BOLD))
    body.append(text(p["sub"], 142, 114, p["color"], 20, SMALL))
    body.append(f'<g class="bob">{text("↗", W - 52, 46, C["muted"], 24, REG)}</g>')
    for i, line in enumerate(p["desc"]):
        body.append(text(line, 26, 162 + i * 28, C["cream"], 20, SMALL))
    x = 24
    for t in p["tech"]:
        w = SMALL.width(t, 20) + 22
        body.append(f'<path fill="{C["line"]}" d="{notch(x, 212, w, 30, 2)}"/>')
        body.append(text(t, x + 11, 233, C["text"], 20, SMALL))
        x += w + 8
    return svg(W, H, "".join(body), SCENE_CSS, f'{p["name"]} — {" ".join(p["desc"])}')


PROJECTS = [
    dict(file="card-physsim.svg", name="PhysSim", tag="MAIN QUEST", color=C["amber"], sub="★ JCIM 2026 게재",
         desc=["물리 기반 잠재 동역학으로", "혼합 향의 유사도를 예측합니다"], tech=["Python", "PyTorch", "RDKit"],
         scene=scene_physsim),
    dict(file="card-umn.svg", name="UMN", tag="RESEARCH", color=C["teal"], sub="◆ ChemRxiv 프리프린트",
         desc=["분자 지문과 미분 가능한", "N체 시뮬레이션을 연결합니다"], tech=["Python", "PyTorch", "RDKit"],
         scene=scene_umn),
    dict(file="card-gravityfluid.svg", name="GravityFluid", tag="SIMULATION", color=C["coral"], sub="◆ 선박 설계 물리 검토",
         desc=["선박 초기 설계의 물리 검토와", "CFD·FEA 계획을 세웁니다"], tech=["Python", "Taichi", "FastAPI"],
         scene=scene_fluid),
    dict(file="card-spot.svg", name="SPOT.", tag="WEB APP", color=C["lav"], sub="◆ 크루 운동 기록",
         desc=["운동 일정을 공유하고", "크루별 맞춤 루틴을 관리합니다"], tech=["Next.js", "TypeScript", "PostgreSQL"],
         scene=scene_spot),
]


# ---------------------------------------------------------------- research card

def build_research():
    W, H = 1000, 268
    body = [panel(0, 0, W - 8, H - 8, fill=C["panel"], accent=C["amber"])]
    body.append(f'<path fill="{C["ink"]}" d="{notch(28, 28, 136, 136)}"/>')
    body.append(f'<path fill="{C["night"]}" d="{notch(32, 32, 128, 128)}"/>')
    body.append(f'<g class="bob">{sprite(TROPHY, ICON_PAL, 48, 50, 8)}</g>')
    for i, (sx, sy) in enumerate([(40, 40), (140, 58), (132, 136), (46, 124)]):
        body.append(sparkle(sx, sy, C["amber"] if i % 2 else C["teal"], f"t{i % 3 + 1}"))
    body.append(text("2026", 96, 200, C["amber"], 24, BOLD, "middle"))
    body.append(text("PUBLISHED", 96, 226, C["muted"], 12, BOLD, "middle"))
    x = 192
    for label, fill, fg in (("ACHIEVEMENT UNLOCKED", C["amber"], C["ink"]), ("PEER-REVIEWED", C["teal"], C["ink"]),
                            ("J. Chem. Inf. Model.", C["line"], C["text"])):
        w = BOLD.width(label, 12) + 20
        body.append(f'<path fill="{fill}" d="{notch(x, 32, w, 24, 2)}"/>')
        body.append(text(label, x + 10, 49, fg, 12, BOLD))
        x += w + 8
    body.append(text("물리 기반 잠재 동역학을 활용한 혼합 향 유사도 예측", 192, 102, C["text"], 24, BOLD))
    body.append(text("김준성 · Journal of Chemical Information and Modeling", 192, 138, C["cream"], 20, SMALL))
    body.append(text("2026, 66(17), 10584–10592 · doi:10.1021/acs.jcim.6c01297", 192, 166, C["muted"], 20, SMALL))
    desc = ("여러 분자의 표현을 학습된 잠재 공간에서 변화시켜 혼합 향의 지각적 유사도를 예측합니다. "
            "물리적 상호작용에서 가져온 형태를 학습에 활용합니다.")
    for i, line in enumerate(wrap(desc, SMALL, 20, W - 192 - 40)):
        body.append(text(line, 192, 206 + i * 28, C["dim"] if False else C["muted"], 20, SMALL))
    body.append(f'<clipPath id="pc"><path d="{notch(8, 8, W - 24, H - 24)}"/></clipPath>'
                f'<g clip-path="url(#pc)"><path class="shine" fill="#fff" fill-opacity=".07" '
                f'd="M-200 0h90l-120 270h-90zM-90 0h24l-120 270h-24z"/></g>')
    css = ("@keyframes sh{0%,60%{transform:translateX(0)}100%{transform:translateX(1400px)}}"
           ".shine{animation:sh 6s 1s infinite}")
    return svg(W, H, "".join(body), css, "발표한 연구: 물리 기반 잠재 동역학을 활용한 혼합 향 유사도 예측 (JCIM 2026)")


# ---------------------------------------------------------------- inventory

INVENTORY = [
    ("연구 · 데이터", [("Python", "python", "#ffd43b", "연구 코드와 데이터 파이프라인"),
                     ("PyTorch", "pytorch", "#ee4c2c", "신경망과 미분 가능한 시뮬레이션"),
                     ("RDKit", None, C["leaf"], "분자 구조와 분자 지문 계산"),
                     ("NumPy", "numpy", "#4dabcf", "수치 계산과 배열 연산")]),
    ("웹 개발", [("TypeScript", "typescript", "#4a90e2", "타입이 있는 웹 개발"),
               ("React", "react", "#61dafb", "인터랙티브 UI 구성"),
               ("Next.js", "nextdotjs", "#ffffff", "풀스택 웹 서비스"),
               ("PostgreSQL", "postgresql", "#7c9cff", "관계형 데이터 저장")]),
    ("기록 · 도구", [("LaTeX", "latex", C["teal"], "논문 조판과 수식"),
                  ("Git", "git", "#f05032", "버전 관리와 협업"),
                  ("Colab", "googlecolab", "#f9ab00", "GPU 실험 환경"),
                  ("VS Code", "visualstudiocode", "#3ea6ff", "매일 쓰는 편집기")]),
]
HEX = ["....gggg....", "..gg....gg..", "gg........gg", "g...gggg...g", "g..g....g..g", "g..g....g..g",
       "g..g....g..g", "g...gggg...g", "gg........gg", "..gg....gg..", "....gggg...."]


def icon_path(slug):
    # brand glyphs from simple-icons (CC0), vendored in scripts/icons
    with open(os.path.join(ROOT, "scripts", "icons", slug + ".svg"), encoding="utf-8") as f:
        return re.search(r' d="([^"]+)"', f.read()).group(1)


def build_inventory():
    W, H = 1000, 268
    T = 2.0 * 12
    body = [panel(0, 0, W - 8, H - 8, fill=C["panel"])]
    slots, gx = [], 28
    for gi, (group, items) in enumerate(INVENTORY):
        body.append(text(group, gx, 46, C["amber"], 20, SMALL))
        for ii, (name, slug, color, _) in enumerate(items):
            sx, sy = gx + ii * 76, 60
            body.append(f'<path fill="{C["ink"]}" d="{notch(sx, sy, 68, 68, 4)}"/>')
            body.append(f'<path fill="{C["night"]}" d="{notch(sx + 4, sy + 4, 60, 60, 4)}"/>')
            body.append(f'<rect x="{sx + 8}" y="{sy + 58}" width="52" height="2" fill="{C["line"]}"/>')
            if slug:
                body.append(f'<path fill="{color}" transform="translate({sx + 16} {sy + 16}) scale(1.5)" '
                            f'shape-rendering="geometricPrecision" d="{icon_path(slug)}"/>')
            else:
                body.append(sprite(HEX, {"g": color}, sx + 10, sy + 12, 4))
            body.append(text(name, sx + 34, sy + 88, C["muted"], 12, REG, "middle"))
            slots.append((sx, sy, name, color, _))
        gx += 4 * 76 + 18
    # status bar
    body.append(f'<path fill="{C["ink"]}" d="{notch(24, 172, W - 56, 64, 4)}"/>')
    body.append(f'<path fill="{C["night"]}" d="{notch(28, 176, W - 64, 56, 4)}"/>')
    body.append(text("▶", 48, 212, C["amber"], 20, SMALL, cls="blink"))
    n = len(slots)
    for i, (sx, sy, name, color, desc) in enumerate(slots):
        ev = [(0.0, 0)] + ([(i * T / n, 1)] if i else [(0.0, 1)]) + ([((i + 1) * T / n, 0)] if i < n - 1 else [])
        vis = discrete("opacity", sorted({e[0]: e for e in ev}.values()), T)
        body.append(f'<g opacity="0">{vis}{text(name, 76, 213, color, 24, BOLD)}'
                    f'{text("— " + desc, 76 + BOLD.width(name, 24) + 14, 212, C["cream"], 20, SMALL)}</g>')
    cur = sprite(["aaa......aaa", "a..........a", "a..........a", "", "", "", "", "", "", "a..........a",
                  "a..........a", "aaa......aaa"], {"a": C["amber"]}, 0, 0, 6)
    body.append(f'<g>{discrete_translate([(i * T / n, s[0] - 2, s[1] - 2) for i, s in enumerate(slots)], T)}{cur}</g>')
    body.append(stars(5, 10, (700, 18, 960, 44), (C["lav"], "#fff")))
    return svg(W, H, "".join(body), "", "사용하는 기술: Python, PyTorch, RDKit, NumPy, TypeScript, React, Next.js, "
                                        "PostgreSQL, LaTeX, Git, Google Colab, VS Code")


def discrete_translate(events, T):
    kt = ";".join(f"{t / T:.4f}" for t, _, _ in events)
    vals = ";".join(f"{x} {y}" for _, x, y in events)
    return (f'<animateTransform attributeName="transform" type="translate" calcMode="discrete" dur="{T}s" '
            f'repeatCount="indefinite" keyTimes="{kt}" values="{vals}"/>')


# ---------------------------------------------------------------- footer

def build_footer():
    W, H = 1000, 230
    rng = random.Random(21)
    body = [panel(0, 0, W - 8, H - 8, fill="#0b0d26")]
    body.append(f'<clipPath id="fc"><path d="{notch(4, 4, W - 16, H - 16)}"/></clipPath><g clip-path="url(#fc)">')
    body.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#sky)"/>')
    body.append(stars(9, 60, (10, 10, 990, 130), ("#ffffff", "#ffe6b0", C["lav"])))
    body.append(sprite(["..mmmm..", ".mmmmmmm", "mmmmm...", "mmmm....", "mmmm....", "mmmmm...", ".mmmmmmm", "..mmmm.."],
                       {"m": "#ffe9b8"}, 880, 26, 4))
    body.append('<g class="shoot"><rect width="60" height="3" fill="url(#trail)"/><rect x="58" y="-1" width="5" height="5" fill="#fff"/></g>')
    # skyline
    x, sky, wins = 0, [], []
    while x < W:
        w = rng.choice((32, 40, 48, 56, 64))
        h = rng.choice((36, 48, 56, 64, 72, 88, 104))
        sky.append(f"M{x} {H - h}h{w}v{h}h{-w}z")
        for wy in range(H - h + 8, H - 12, 12):
            for wx in range(x + 6, x + w - 6, 10):
                if rng.random() < .28:
                    wins.append((wx, wy))
        x += w
    body.append(f'<path fill="#05061a" d="{"".join(sky)}"/>')
    for wx, wy in wins:
        cls = f' class="t{rng.randint(1, 3)}"' if rng.random() < .3 else ""
        body.append(f'<rect{cls} x="{wx}" y="{wy}" width="4" height="4" fill="{rng.choice(("#ffcf7a", "#ffb547", "#ffe9b8"))}"/>')
    body.append("</g>")
    body.append(text("THANKS FOR VISITING", W / 2 - 4, 74, C["amber"], 36, BOLD, "middle"))
    body.append(text("방문해 주셔서 감사합니다", W / 2 - 4, 112, C["cream"], 20, SMALL, "middle"))
    body.append(text("▶ CONTINUE?", W / 2 - 4, 146, C["teal"], 12, BOLD, "middle", "blink"))
    defs = ('<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0b0d26"/>'
            '<stop offset=".7" stop-color="#2a2160"/><stop offset="1" stop-color="#6b3a6e"/></linearGradient>'
            '<linearGradient id="trail"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            '<stop offset="1" stop-color="#fff"/></linearGradient></defs>')
    css = ("@keyframes shoot{0%{transform:translate(160px,20px) rotate(20deg);opacity:0}2%{opacity:1}"
           "9%{transform:translate(420px,110px) rotate(20deg);opacity:0}100%{opacity:0}}"
           ".shoot{animation:shoot 7s 1.5s linear infinite;opacity:0}")
    return svg(W, H, defs + "".join(body), css, "방문해 주셔서 감사합니다")


# ---------------------------------------------------------------- live stats

def fetch(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER + "-profile"})
    if token and "api.github.com" in url:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def gather():
    token = os.environ.get("GITHUB_TOKEN")
    page = fetch(f"https://github.com/users/{USER}/contributions").decode()
    flat = re.sub(r"\s+", " ", page)
    total = int(re.search(r"([\d,]+) contributions? in the last year", flat).group(1).replace(",", ""))
    tips = {m.group(1): m.group(2) for m in re.finditer(r'<tool-tip [^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', page)}
    days = []
    for m in re.finditer(r"<td [^>]*data-date=[^>]*>", page):
        tag = m.group(0)
        date = re.search(r'data-date="([^"]+)"', tag).group(1)
        level = int(re.search(r'data-level="(\d)"', tag).group(1))
        cid = re.search(r'id="([^"]+)"', tag).group(1)
        cm = re.match(r"(\d+) contribution", tips.get(cid, ""))
        days.append((date, int(cm.group(1)) if cm else 0, level))
    days.sort()
    user = json.loads(fetch(f"https://api.github.com/users/{USER}", token))
    repos = json.loads(fetch(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner", token))
    langs = {}
    for r in repos:
        if r["fork"]:
            continue
        for k, v in json.loads(fetch(r["languages_url"], token)).items():
            if k != "Jupyter Notebook":  # notebook outputs would drown everything else
                langs[k] = langs.get(k, 0) + v
    avatar = fetch(user["avatar_url"] + "&s=120")
    return dict(total=total, days=days, repos=sum(not r["fork"] for r in repos), created=user["created_at"][:7],
                langs=sorted(langs.items(), key=lambda kv: -kv[1]), avatar=avatar)


LANG_COLORS = {"Python": "#6fb5ff", "TypeScript": "#5ee7d8", "JavaScript": "#f1e05a", "HTML": "#ff7a59",
               "CSS": "#a99bff", "TeX": "#8be07f", "Shell": "#c7f28a", "Java": "#e0a96d"}


def streaks(days):
    longest = run = 0
    for _, n, _ in days:
        run = run + 1 if n else 0
        longest = max(longest, run)
    cur = 0
    seq = [n for _, n, _ in days]
    if seq and seq[-1] == 0:
        seq = seq[:-1]  # today may simply not have started yet
    for n in reversed(seq):
        if not n:
            break
        cur += 1
    return cur, longest


def build_stats(d):
    from PIL import Image
    W, H = 1000, 368
    body = [panel(0, 0, W - 8, H - 8, fill=C["panel"])]
    # emblem from the avatar, sampled to 12x12
    im = Image.open(io.BytesIO(d["avatar"])).convert("RGB").resize((12, 12), Image.NEAREST)
    body.append(f'<path fill="{C["ink"]}" d="{notch(24, 24, 136, 136)}"/>')
    body.append(f'<path fill="{C["night"]}" d="{notch(28, 28, 128, 128)}"/>')
    px = []
    for yy in range(12):
        for xx in range(12):
            r, g, b = im.getpixel((xx, yy))
            if min(r, g, b) > 225:
                continue
            px.append(f'<rect x="{44 + xx * 8}" y="{44 + yy * 8}" width="8" height="8" fill="#{r:02x}{g:02x}{b:02x}"/>')
    body.append(f'<g class="bob">{"".join(px)}</g>')
    body.append(text("PLAYER", 92, 182, C["muted"], 12, BOLD, "middle"))
    body.append(text(f"since {d['created'].replace('-', '.')}", 92, 204, C["cream"], 20, SMALL, "middle"))
    # name + stat tiles
    body.append(text("Kim Junseong", 188, 58, C["text"], 24, BOLD))
    body.append(text("@" + USER, 188 + BOLD.width("Kim Junseong", 24) + 14, 57, C["muted"], 20, SMALL))
    cur, longest = streaks(d["days"])
    tiles = [("올해 기여", f"{d['total']:,}", C["amber"]), ("현재 연속", f"{cur}일", C["coral"]),
             ("최장 연속", f"{longest}일", C["teal"]), ("공개 저장소", str(d["repos"]), C["lav"])]
    for i, (label, val, col) in enumerate(tiles):
        tx = 188 + i * 196
        body.append(f'<path fill="{C["ink"]}" d="{notch(tx, 78, 184, 82, 4)}"/>')
        body.append(f'<path fill="{C["night"]}" d="{notch(tx + 4, 82, 176, 74, 4)}"/>')
        body.append(f'<rect x="{tx + 4}" y="82" width="4" height="74" fill="{col}"/>')
        body.append(text(val, tx + 22, 124, col, 36, BOLD))
        body.append(text(label, tx + 22, 146, C["muted"], 12, REG))
    # heatmap
    days = d["days"][-53 * 7:]
    first = dt.date.fromisoformat(days[0][0])
    offset = (first.weekday() + 1) % 7  # GitHub weeks start on Sunday
    ramp = ["#1d2150", "#4a3b8f", "#8a4f9e", "#d9706a", "#ffbf5a"]
    body.append(text("ADVENTURE MAP · 지난 1년의 기여", 24, 236, C["amber"], 20, SMALL))
    cells = []
    for i, (date, n, lvl) in enumerate(days):
        k = i + offset
        wk, wd = k // 7, k % 7
        cells.append(f'<rect class="hm" style="animation-delay:{wk * .03:.2f}s" x="{24 + wk * 11}" y="{248 + wd * 11}" '
                     f'width="9" height="9" fill="{ramp[lvl]}"/>')
    body.append("".join(cells))
    lk = len(days) - 1 + offset
    body.append(f'<rect class="blink" x="{22 + lk // 7 * 11}" y="{246 + lk % 7 * 11}" width="13" height="13" '
                f'fill="none" stroke="#fff" stroke-width="2"/>')
    # languages
    lx = 640
    body.append(text("TOP LANGUAGES", lx, 236, C["amber"], 20, SMALL))
    tot = sum(v for _, v in d["langs"]) or 1
    for i, (name, v) in enumerate(d["langs"][:5]):
        y = 254 + i * 18
        pct = v / tot * 100
        col = LANG_COLORS.get(name, C["muted"])
        body.append(text(name, lx, y + 11, C["text"], 12, REG))
        segs = 20
        on = max(1, round(pct / 100 * segs))
        bar = "".join(f"M{lx + 92 + s * 9} {y + 2}h7v10h-7z" for s in range(segs))
        body.append(f'<path fill="{C["line"]}" d="{bar}"/>')
        on_bar = "".join(f"M{lx + 92 + s * 9} {y + 2}h7v10h-7z" for s in range(on))
        body.append(f'<path class="bar" style="animation-delay:{i * .15:.2f}s" fill="{col}" d="{on_bar}"/>')
        body.append(text(f"{pct:.1f}%", W - 30, y + 11, C["muted"], 12, REG, "end"))
    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y.%m.%d")
    body.append(text(f"UPDATED {stamp} · 매일 자동 갱신", W - 30, 58, C["dim"], 12, REG, "end"))
    css = ("@keyframes hm{0%{opacity:0}100%{opacity:1}}.hm{animation:hm .4s steps(2) both}"
           "@keyframes bar{0%{transform:scaleX(0)}100%{transform:scaleX(1)}}"
           f".bar{{transform-origin:{lx + 92}px 0;animation:bar .9s steps(8) both}}")
    return svg(W, H, "".join(body), css, f"활동 기록: 지난 1년 기여 {d['total']}회, 공개 저장소 {d['repos']}개")


# ---------------------------------------------------------------- main

def main():
    load_fonts()
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ASSETS, "stats.svg")
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        content = build_stats(gather())
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print(f"wrote {out} ({len(content) / 1024:.1f} KB)")
        return
    print("building assets/")
    save("hero.svg", build_hero())
    save("dialog.svg", build_dialog())
    save("btn-orcid.svg", build_button("ORCID", "id", C["leaf"], 0))
    save("btn-paper.svg", build_button("JCIM 논문", "doc", C["amber"], .5))
    save("btn-repos.svg", build_button("전체 저장소", "box", C["lav"], 1))
    save("btn-read.svg", build_button("논문 읽기", "doc", C["amber"], 0))
    save("btn-code.svg", build_button("연구 코드", "code", C["teal"], .6))
    save("h-quest.svg", build_header("QUEST LOG", "만들고 있는 것들", SWORD, 4, 1))
    save("h-research.svg", build_header("ACHIEVEMENT", "발표한 연구", TROPHY, 4, 2))
    save("h-inventory.svg", build_header("INVENTORY", "사용하는 기술", CHEST, 4, 3))
    save("h-stats.svg", build_header("PLAYER STATUS", "활동 기록", HEART, 6, 4))
    for p in PROJECTS:
        save(p["file"], build_card(p))
    save("research.svg", build_research())
    save("inventory.svg", build_inventory())
    save("footer.svg", build_footer())


if __name__ == "__main__":
    main()
