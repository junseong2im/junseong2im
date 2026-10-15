#!/usr/bin/env python3
"""SVG generator for the profile README.

    python scripts/build.py                  # static assets -> assets/*-{dark,light}.svg
    python scripts/build.py live OUT_DIR     # data-driven cards (daily workflow)
    python scripts/build.py activity README  # rewrite the activity block in README.md
    python scripts/build.py play OUT_DIR     # add a note to the blend demo (issue workflow;
                                             # reads SCENT_TITLE / SCENT_PLAYER / REPLY_FILE)

Every image is built twice, for GitHub's dark and light themes. Text is drawn as glyph
outlines (Pretendard, JetBrains Mono; both SIL OFL 1.1) so it renders the same everywhere.
"""
import datetime as dt
import html
import json
import math
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
FONT_URLS = {
    "Pretendard-Regular.otf": "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-Regular.otf",
    "Pretendard-Medium.otf": "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-Medium.otf",
    "Pretendard-SemiBold.otf": "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/public/static/Pretendard-SemiBold.otf",
    "JetBrainsMono-Regular.ttf": "https://cdn.jsdelivr.net/gh/JetBrains/JetBrainsMono@v2.304/fonts/ttf/JetBrainsMono-Regular.ttf",
    "JetBrainsMono-Medium.ttf": "https://cdn.jsdelivr.net/gh/JetBrains/JetBrainsMono@v2.304/fonts/ttf/JetBrainsMono-Medium.ttf",
}
USER = "junseong2im"
KST = dt.timezone(dt.timedelta(hours=9))
DOI = "10.1021/acs.jcim.6c01297"

# GitHub Primer neutrals with two restrained accents (cool = blue, warm = amber).
THEMES = {
    "dark": dict(surface="#0f141a", surface2="#161b22", border="#262c36", grid="#1c222b",
                 text="#e6edf3", muted="#8d96a0", faint="#5c6570", cool="#79c0ff", warm="#f0b072",
                 violet="#b9a6ff", green="#56d364", heat=["#161b22", "#123a5c", "#1c5d94", "#3a8ad6", "#79c0ff"]),
    "light": dict(surface="#ffffff", surface2="#f6f8fa", border="#d8dee4", grid="#eef1f4",
                  text="#1f2328", muted="#59636e", faint="#8c959f", cool="#0969da", warm="#bc4c00",
                  violet="#8250df", green="#1a7f37", heat=["#eff2f5", "#c8def7", "#8cbcf0", "#4a90e2", "#0969da"]),
}

BASE_CSS = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


# ---------------------------------------------------------------- text as glyph outlines

class Font:
    def __init__(self, name, key, fallback=None):
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):
            os.makedirs(FONT_DIR, exist_ok=True)
            urllib.request.urlretrieve(FONT_URLS[name], path)
        self.tt = TTFont(path)
        self.gs = self.tt.getGlyphSet()
        self.cmap = self.tt.getBestCmap()
        self.hm = self.tt["hmtx"]
        self.upm = self.tt["head"].unitsPerEm
        self.key, self.fallback = key, fallback

    def resolve(self, ch):
        if ord(ch) in self.cmap:
            return self, self.cmap[ord(ch)]
        if self.fallback:
            return self.fallback.resolve(ch)
        return self, self.cmap[ord("?")]


SANS = MED = SEMI = MONO = MONO_M = None
GLYPHS = {}  # glyph id -> outline, collected per SVG and emitted once as <defs>


def load_fonts():
    global SANS, MED, SEMI, MONO, MONO_M
    SANS = Font("Pretendard-Regular.otf", "r")
    MED = Font("Pretendard-Medium.otf", "m")
    SEMI = Font("Pretendard-SemiBold.otf", "b")
    MONO = Font("JetBrainsMono-Regular.ttf", "j", fallback=SANS)
    MONO_M = Font("JetBrainsMono-Medium.ttf", "k", fallback=MED)


def _glyph(font, name):
    gid = f"{font.key}{font.tt.getGlyphID(name)}"
    if gid not in GLYPHS:
        pen = SVGPathPen(font.gs, ntos=lambda v: str(round(v)))
        font.gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, 0)))
        GLYPHS[gid] = pen.getCommands()
    return gid


def measure(s, size, font, ls=0.0):
    w = 0.0
    for ch in s:
        f, g = font.resolve(ch)
        w += f.hm[g][0] * size / f.upm + ls
    return w - (ls if s else 0)


def text(s, x, y, fill, size, font, anchor="start", ls=0.0):
    w = measure(s, size, font, ls)
    if anchor == "middle":
        x -= w / 2
    elif anchor == "end":
        x -= w
    uses, cx = [], 0.0
    for ch in s:
        f, g = font.resolve(ch)
        k = size / f.upm
        if not ch.isspace():
            uses.append(f'<use href="#{_glyph(f, g)}" transform="matrix({k:.5f} 0 0 {k:.5f} {cx:.2f} 0)"/>')
        cx += f.hm[g][0] * k + ls
    return f'<g fill="{fill}" transform="translate({x:.2f} {y:.2f})">{"".join(uses)}</g>'


# ---------------------------------------------------------------- primitives

def esc(s):
    return html.escape(s, quote=True)


def rect(x, y, w, h, r, fill, stroke=None, extra=""):
    st = f' stroke="{stroke}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"{st} fill="{fill}"{extra}/>'


def card(P, w, h, r=12):
    return rect(0.5, 0.5, w - 1, h - 1, r, P["surface"], P["border"])


def label(s, x, y, P, color=None):
    return text(s.upper(), x, y, color or P["muted"], 11, MONO_M, ls=1.1)


def dot(x, y, r, fill, extra=""):
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}"{extra}/>'


def poly(pts):
    return "M" + "L".join(f"{a:.1f} {b:.1f}" for a, b in pts) + "Z"


def icon(slug, x, y, size, fill):
    # brand glyphs from simple-icons (CC0), vendored in scripts/icons
    with open(os.path.join(ROOT, "scripts", "icons", slug + ".svg"), encoding="utf-8") as f:
        d = re.search(r' d="([^"]+)"', f.read()).group(1)
    return f'<path fill="{fill}" transform="translate({x} {y}) scale({size / 24:.4f})" d="{d}"/>'


def svg(w, h, body, css="", title=""):
    defs = "".join(f'<path id="{k}" d="{v}"/>' for k, v in GLYPHS.items())
    GLYPHS.clear()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>'
            f'<style>{BASE_CSS}{css}</style><defs>{defs}</defs>{body}</svg>')


def ago(when, now):
    days = (now.date() - when.date()).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days}d ago"
    if days < 60:
        return f"{days // 7}w ago"
    return f"{days // 30}mo ago"


# ---------------------------------------------------------------- hero

def build_hero(P, theme):
    W, H = 1000, 340
    rng = random.Random(11)
    body = [card(P, W, H, 16)]
    # identity
    body.append(label("Physics-inspired AI  ·  Computational olfaction", 48, 72, P, P["cool"]))
    body.append(text("김준성", 46, 138, P["text"], 58, SEMI))
    body.append(text("Junseong Kim", 48, 180, P["muted"], 26, MED))
    body.append(rect(48, 204, 36, 2, 1, P["warm"]))
    body.append(text("혼합 향의 지각적 유사도를 연구하고,", 48, 244, P["text"], 18, SANS))
    body.append(text("시뮬레이션과 웹 서비스를 만듭니다.", 48, 272, P["text"], 18, SANS))
    body.append(text("J. Chem. Inf. Model. 2026  ·  ORCID 0009-0009-1468-9375", 48, 306, P["faint"], 12, MONO))
    # latent-space schematic: molecules drift from scattered states into two mixtures
    x0, y0, x1, y1 = 556, 44, 956, 296
    body.append(f'<path fill="{P["grid"]}" d="' + "".join(
        f"M{x} {y}h1.6v1.6h-1.6z" for x in range(x0 + 20, x1, 20) for y in range(y0 + 12, y1, 20)) + '"/>')
    body.append(f'<path d="M{x0} {y0}V{y1}H{x1}" fill="none" stroke="{P["border"]}"/>')
    for i in range(1, 5):
        tx, ty = x0 + i * (x1 - x0) / 5, y0 + i * (y1 - y0) / 5
        body.append(f'<path d="M{tx:.0f} {y1}v5M{x0} {ty:.0f}h-5" stroke="{P["border"]}"/>')
    body.append(text("z₁", x1 - 4, y1 + 22, P["faint"], 12, MONO, "end"))
    body.append(text("z₂", x0 - 12, y0 + 10, P["faint"], 12, MONO, "end"))
    body.append(text("latent dynamics · schematic", x0 + 14, y0 + 18, P["faint"], 11, MONO))
    clusters = [((735, 132), P["cool"], 5, "A"), ((862, 218), P["warm"], 4, "B")]
    for (cx, cy), col, n, name in clusters:
        for k in range(n):
            a = 2 * math.pi * k / n + rng.uniform(-.3, .3)
            ax, ay = cx + math.cos(a) * rng.uniform(16, 26), cy + math.sin(a) * rng.uniform(12, 22)
            sx, sy = rng.uniform(x0 + 30, x1 - 30), rng.uniform(y0 + 30, y1 - 30)
            mx, my = (sx + ax) / 2 + rng.uniform(-50, 50), (sy + ay) / 2 + rng.uniform(-40, 40)
            trail = f"M{sx:.1f} {sy:.1f}Q{mx:.1f} {my:.1f} {ax:.1f} {ay:.1f}"
            body.append(f'<path class="trail" d="{trail}" fill="none" stroke="{col}" stroke-opacity=".35" '
                        f'stroke-width="1.2" stroke-dasharray="2 4"/>')
            body.append(dot(sx, sy, 2, col, ' fill-opacity=".45"'))
            body.append(f'<circle r="2.6" fill="{col}"><animateMotion dur="{rng.uniform(4, 6.5):.1f}s" '
                        f'begin="{rng.uniform(0, 3):.1f}s" repeatCount="indefinite" path="{trail}"/></circle>')
            r = rng.uniform(4, 8)
            orbit = f"M{ax + r:.1f} {ay:.1f}a{r:.1f} {r:.1f} 0 1 1 {-2 * r:.1f} 0a{r:.1f} {r:.1f} 0 1 1 {2 * r:.1f} 0"
            mv = f'<animateMotion dur="{rng.uniform(7, 12):.1f}s" repeatCount="indefinite" path="{orbit}"/>'
            body.append(f'<circle r="11" fill="{col}" fill-opacity=".12">{mv}</circle><circle r="5" fill="{col}">{mv}</circle>')
        body.append(f'<path d="M{cx - 6} {cy}h12M{cx} {cy - 6}v12" stroke="{P["text"]}" stroke-width="1.2"/>')
        body.append(text(f"mixture {name}", cx + (-14 if name == "A" else 14), cy + (-34 if name == "A" else 44),
                         col, 12, MONO_M, "end" if name == "A" else "start"))
    (ax, ay), (bx, by) = clusters[0][0], clusters[1][0]
    body.append(f'<path d="M{ax} {ay}L{bx} {by}" stroke="{P["muted"]}" stroke-dasharray="3 4"/>')
    body.append(text("sim(A, B)", (ax + bx) / 2 + 12, (ay + by) / 2 - 6, P["muted"], 12, MONO))
    css = "@keyframes flow{to{stroke-dashoffset:-24}}.trail{animation:flow 2.4s linear infinite}"
    return svg(W, H, "".join(body), css,
               "김준성 · Junseong Kim — 물리 기반 AI · 계산 후각. 혼합 향의 지각적 유사도를 연구하고, "
               "시뮬레이션과 웹 서비스를 만듭니다.")


# ---------------------------------------------------------------- link badges

def build_badge(P, theme, label_text, icon_slug=None, glyph=None):
    h, pad = 34, 14
    lead = 22 if (icon_slug or glyph) else 0
    w = pad + lead + measure(label_text, 13, MED) + pad + 14
    body = [rect(0.5, 0.5, round(w) - 1, h - 1, 17, P["surface2"], P["border"])]
    if icon_slug:
        body.append(icon(icon_slug, pad, 9, 16, P["text"]))
    elif glyph:
        body.append(text(glyph, pad + 1, 23, P["text"], 15, MONO_M))
    body.append(text(label_text, pad + lead, 22, P["text"], 13, MED))
    body.append(f'<path d="M{w - 21:.1f} 21l5-5m-3.5 0h3.5v3.5" fill="none" stroke="{P["muted"]}" stroke-width="1.3"/>')
    return svg(round(w), h, "".join(body), "", label_text)


def build_cite(P, theme, cites):
    return build_badge(P, theme, f"Cited by {cites} · OpenAlex" if cites else "JCIM · Published 2026")


# ---------------------------------------------------------------- research figure

def molecule(x, y, s, col):
    """Line-art ring with a side chain."""
    pts = [(x + s * math.cos(math.pi / 6 + k * math.pi / 3), y + s * math.sin(math.pi / 6 + k * math.pi / 3))
           for k in range(6)]
    tail = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}l{s * .9:.1f} {s * .5:.1f}l{s * .9:.1f} {-s * .5:.1f}"
    out = f'<path d="{poly(pts)}{tail}" fill="none" stroke="{col}" stroke-width="1.4" stroke-linejoin="round"/>'
    return out + "".join(dot(a, b, 1.8, col) for a, b in pts[::2])


def arrow(x1, y, x2, P):
    return (f'<path class="pulse" d="M{x1} {y}H{x2 - 6}" stroke="{P["muted"]}" stroke-width="1.2" stroke-dasharray="3 5"/>'
            f'<path d="M{x2 - 7} {y - 4}l6 4-6 4" fill="none" stroke="{P["muted"]}" stroke-width="1.2"/>')


def build_figure(P, theme):
    W, H = 1000, 268
    rng = random.Random(5)
    body = [card(P, W, H, 16)]
    for x, num, title in ((40, "01", "Odorant mixtures"), (262, "02", "Representations"),
                          (484, "03", "Latent dynamics"), (754, "04", "Perceptual similarity")):
        body.append(text(num, x, 46, P["faint"], 11, MONO_M))
        body.append(text(title, x + 24, 46, P["text"], 15, MED))
    # 01 two mixtures of molecules
    body.append(molecule(78, 104, 15, P["cool"]) + molecule(140, 118, 12, P["cool"]))
    body.append(molecule(84, 178, 12, P["warm"]) + molecule(146, 192, 15, P["warm"]))
    body.append(text("A", 46, 112, P["cool"], 12, MONO_M) + text("B", 46, 192, P["warm"], 12, MONO_M))
    body.append(arrow(196, 146, 256, P))
    # 02 embeddings
    for row, col in ((0, P["cool"]), (1, P["warm"])):
        for k in range(12):
            h = rng.uniform(8, 30)
            body.append(rect(268 + k * 12, round(118 + row * 52 - h, 1), 7, round(h, 1), 1.5, col, extra=' fill-opacity=".85"'))
        body.append(f'<path d="M264 {120 + row * 52}H416" stroke="{P["border"]}"/>')
    body.append(text("molecular embeddings", 268, 220, P["faint"], 11, MONO))
    body.append(arrow(426, 146, 478, P))
    # 03 latent dynamics
    px, py, pw, ph = 488, 72, 236, 148
    body.append(rect(px, py, pw, ph, 10, P["surface2"], P["border"]))
    body.append(f'<path fill="{P["grid"]}" d="' + "".join(
        f"M{x} {y}h1.5v1.5h-1.5z" for x in range(px + 14, px + pw - 6, 16) for y in range(py + 12, py + ph - 6, 16)) + '"/>')
    cx, cy = px + pw / 2, py + ph / 2
    for k, (col, rx, ry, dur) in enumerate(((P["cool"], 70, 34, 9), (P["warm"], 46, 52, 7), (P["cool"], 28, 20, 5),
                                            (P["warm"], 92, 44, 12))):
        rx, ry = min(rx, pw / 2 - 10), min(ry, ph / 2 - 10)
        orbit = f"M{cx + rx} {cy}a{rx} {ry} 0 1 1 {-2 * rx} 0a{rx} {ry} 0 1 1 {2 * rx} 0"
        body.append(f'<path d="{orbit}" fill="none" stroke="{col}" stroke-opacity=".25"/>')
        for j in range(2):
            mv = (f'<animateMotion dur="{dur}s" begin="-{dur * j / 2 + k:.1f}s" repeatCount="indefinite" '
                  f'path="{orbit}"/>')
            body.append(f'<circle r="8" fill="{col}" fill-opacity=".14">{mv}</circle><circle r="3.6" fill="{col}">{mv}</circle>')
    body.append(dot(cx, cy, 2.5, P["text"]))
    body.append(text("physics-inspired interactions", px, 240, P["faint"], 11, MONO))
    body.append(arrow(734, 146, 788, P))
    # 04 similarity gauge
    gx, gy, gr = 868, 166, 62
    end = math.pi * .28

    def arc(a0, a1):
        return (f"M{gx + gr * math.cos(a0):.1f} {gy - gr * math.sin(a0):.1f}"
                f"A{gr} {gr} 0 0 1 {gx + gr * math.cos(a1):.1f} {gy - gr * math.sin(a1):.1f}")
    body.append(f'<path d="{arc(math.pi, 0)}" fill="none" stroke="{P["border"]}" stroke-width="6" stroke-linecap="round"/>')
    body.append(f'<path class="gauge" d="{arc(math.pi, end)}" fill="none" stroke="url(#g)" stroke-width="6" '
                f'stroke-linecap="round" pathLength="100" stroke-dasharray="100"/>')
    body.append(f'<g class="needle"><path d="M{gx} {gy}L{gx + gr * .72 * math.cos(end):.1f} '
                f'{gy - gr * .72 * math.sin(end):.1f}" stroke="{P["text"]}" stroke-width="1.6"/></g>')
    body.append(dot(gx, gy, 3.5, P["text"]))
    body.append(text("0", gx - gr, gy + 22, P["faint"], 11, MONO, "middle"))
    body.append(text("1", gx + gr, gy + 22, P["faint"], 11, MONO, "middle"))
    body.append(text("sim(A, B)", gx, gy + 46, P["muted"], 12, MONO, "middle"))
    body.append(text("Fig. 1  Schematic of the approach (simplified)", 40, H - 22, P["faint"], 11, MONO))
    defs = (f'<linearGradient id="g"><stop offset="0" stop-color="{P["cool"]}"/>'
            f'<stop offset="1" stop-color="{P["warm"]}"/></linearGradient>')
    sweep = 180 - math.degrees(end)
    css = ("@keyframes pulse{to{stroke-dashoffset:-16}}.pulse{animation:pulse 1.2s linear infinite}"
           "@keyframes gauge{0%{stroke-dashoffset:100}35%,100%{stroke-dashoffset:0}}"
           ".gauge{animation:gauge 6s ease-out infinite}"
           f"@keyframes needle{{0%{{transform:rotate(-{sweep:.0f}deg)}}35%,100%{{transform:rotate(0)}}}}"
           f".needle{{transform-origin:{gx}px {gy}px;animation:needle 6s ease-out infinite}}")
    return svg(W, H, f"<defs>{defs}</defs>" + "".join(body), css,
               "연구 방법 개요: 혼합물의 분자 표현을 물리에서 착안한 잠재 동역학으로 변화시켜 지각적 유사도를 예측")


# ---------------------------------------------------------------- project cards

def fig_physsim(x, y, P):
    out = []
    for k, (col, cx, cy) in enumerate(((P["cool"], x + 18, y + 26), (P["warm"], x + 46, y + 38))):
        for j in range(3):
            a = 2 * math.pi * j / 3 + k
            px, py = cx + 9 * math.cos(a), cy + 9 * math.sin(a)
            out.append(f'<path d="M{cx} {cy}L{px:.1f} {py:.1f}" stroke="{col}" stroke-opacity=".5"/>')
            out.append(dot(px, py, 2.6, col))
        out.append(dot(cx, cy, 3.4, col))
    out.append(f'<path d="M{x + 18} {y + 26}L{x + 46} {y + 38}" stroke="{P["muted"]}" stroke-dasharray="2 3"/>')
    return f'<g class="breathe">{"".join(out)}</g>'


def fig_umn(x, y, P):
    cx, cy = x + 32, y + 32
    out = [dot(cx, cy, 3.5, P["warm"])]
    for rx, ry, dur, col in ((14, 9, 4, P["cool"]), (24, 15, 7, P["violet"]), (30, 22, 11, P["cool"])):
        orbit = f"M{cx + rx} {cy}a{rx} {ry} 0 1 1 {-2 * rx} 0a{rx} {ry} 0 1 1 {2 * rx} 0"
        out.append(f'<path d="{orbit}" fill="none" stroke="{P["border"]}"/>')
        out.append(f'<circle r="2.8" fill="{col}"><animateMotion dur="{dur}s" repeatCount="indefinite" path="{orbit}"/></circle>')
    return "".join(out)


def fig_fluid(x, y, P):
    out = []
    for k in range(5):
        yy = y + 12 + k * 10
        bend = 7 if 1 <= k <= 3 else 3
        sgn = -1 if k < 2 else 1
        out.append(f'<path class="stream" d="M{x} {yy}C{x + 20} {yy} {x + 24} {yy + sgn * bend} {x + 34} {yy + sgn * bend}'
                   f'S{x + 52} {yy} {x + 64} {yy}" fill="none" stroke="{P["cool"]}" stroke-opacity=".75" '
                   f'stroke-dasharray="6 5"/>')
    out.append(f'<path d="M{x + 20} {y + 30}h28l-6 9h-18z" fill="{P["warm"]}"/>')
    return "".join(out)


def fig_spot(x, y, P):
    out, k = [], 0
    for r in range(4):
        for c in range(7):
            cx, cy = round(x + c * 9.5, 1), y + 10 + r * 11
            out.append(rect(cx, cy, 7, 7, 1.5, P["grid"]))
            if (r * 7 + c) % 3 != 1:
                out.append(rect(cx, cy, 7, 7, 1.5, P["green"], extra=f' class="fill" style="animation-delay:{k * .18:.2f}s"'))
                k += 1
    return "".join(out)


FIG_CSS = (
    "@keyframes breathe{0%,100%{transform:translateX(0)}50%{transform:translateX(2px)}}"
    ".breathe{animation:breathe 3s ease-in-out infinite}"
    "@keyframes stream{to{stroke-dashoffset:-22}}.stream{animation:stream 1.6s linear infinite}"
    "@keyframes fill{0%,5%{opacity:0}12%,85%{opacity:1}100%{opacity:0}}.fill{animation:fill 8s infinite;opacity:0}"
    "@keyframes beat{0%,100%{opacity:1}50%{opacity:.35}}.beat{animation:beat 2s ease-in-out infinite}"
)

PROJECTS = [
    dict(key="physsim", repo="PhysSim-Olfactory-Mixture-Similarity", name="PhysSim", tag="Research", accent="warm",
         sub="JCIM 2026 논문의 구현", desc=["물리 기반 잠재 동역학으로", "혼합 향의 유사도를 예측합니다."],
         tech=["Python", "PyTorch", "RDKit"], fig=fig_physsim,
         alt="PhysSim — 물리 기반 잠재 동역학으로 혼합 향 유사도 예측"),
    dict(key="umn", repo="Universe-Multi-NeuralNetwork", name="UMN", tag="Research", accent="cool",
         sub="ChemRxiv 프리프린트", desc=["분자 지문과 미분 가능한 N체", "시뮬레이션을 연결합니다."],
         tech=["Python", "PyTorch", "RDKit"], fig=fig_umn,
         alt="UMN — 분자 지문과 미분 가능한 N체 시뮬레이션의 연결"),
    dict(key="gravityfluid", repo="GravityFluid", name="GravityFluid", tag="Simulation", accent="cool",
         sub="선박 초기 설계 검토 도구", desc=["선박 초기 설계의 물리 검토와", "CFD·FEA 계획을 세웁니다."],
         tech=["Python", "Taichi", "FastAPI"], fig=fig_fluid,
         alt="GravityFluid — 선박 초기 설계의 물리 검토와 CFD·FEA 계획"),
    dict(key="spot", repo="SPOT", name="SPOT.", tag="Web app", accent="green",
         sub="크루 운동 관리 서비스", desc=["운동 일정을 공유하고 크루별", "맞춤 루틴을 관리합니다."],
         tech=["Next.js", "TypeScript", "PostgreSQL"], fig=fig_spot,
         alt="SPOT. — 운동 일정 공유와 크루별 맞춤 루틴 관리"),
]


def build_card(P, theme, p, live=None, now=None):
    W, H = 400, 236
    body = [card(P, W, H)]
    body.append(dot(28, 32, 3.5, P[p["accent"]]))
    body.append(label(p["tag"], 40, 36, P))
    body.append(p["fig"](W - 88, 18, P))
    body.append(text(p["name"], 24, 76, P["text"], 22, SEMI))
    body.append(text(p["sub"], 24, 99, P["muted"], 13, SANS))
    for i, line in enumerate(p["desc"]):
        body.append(text(line, 24, 132 + i * 21, P["text"], 14, SANS))
    x = 24
    for t in p["tech"]:
        w = round(measure(t, 11, MONO) + 16, 1)
        body.append(rect(x, 168, w, 22, 11, P["surface2"], P["border"]))
        body.append(text(t, x + 8, 183, P["muted"], 11, MONO))
        x += w + 6
    body.append(f'<path d="M24 {H - 34}H{W - 24}" stroke="{P["border"]}"/>')
    if live:
        fresh = (now - live["pushed"]).days < 14
        body.append(dot(30, H - 17, 3.5, P["green"] if fresh else P["faint"], ' class="beat"' if fresh else ""))
        body.append(text(f"updated {ago(live['pushed'], now)}", 40, H - 13, P["muted"], 11, MONO))
    else:
        body.append(text(f"github.com/{USER}", 24, H - 13, P["faint"], 11, MONO))
    if live and live["stars"]:
        body.append(text(f"★ {live['stars']}", W - 24, H - 13, P["muted"], 11, MONO, "end"))
    else:
        body.append(f'<path d="M{W - 34} {H - 13}l7-7m-5 0h5v5" fill="none" stroke="{P["faint"]}" stroke-width="1.3"/>')
    return svg(W, H, "".join(body), FIG_CSS, p["alt"])


# ---------------------------------------------------------------- stack

STACK = [
    ("Research & data", [("Python", "python", ("#ffd43b", "#3776ab"), "연구 코드와 데이터 파이프라인"),
                         ("PyTorch", "pytorch", ("#ee4c2c", "#ee4c2c"), "신경망과 미분 가능한 시뮬레이션"),
                         ("RDKit", None, ("#56d364", "#1a7f37"), "분자 구조와 분자 지문"),
                         ("NumPy", "numpy", ("#4dabcf", "#013243"), "수치 계산과 배열 연산")]),
    ("Web", [("TypeScript", "typescript", ("#3178c6", "#3178c6"), "타입이 있는 웹 개발"),
             ("React", "react", ("#61dafb", "#087ea4"), "인터랙티브 UI"),
             ("Next.js", "nextdotjs", (None, None), "풀스택 웹 서비스"),
             ("PostgreSQL", "postgresql", ("#699eca", "#336791"), "관계형 데이터베이스")]),
    ("Writing & tools", [("LaTeX", "latex", ("#3fb6a8", "#008080"), "논문 조판과 수식"),
                         ("Git", "git", ("#f05032", "#f05032"), "버전 관리와 협업"),
                         ("Google Colab", "googlecolab", ("#f9ab00", "#e8710a"), "GPU 실험 환경"),
                         ("VS Code", "visualstudiocode", ("#3ea6ff", "#007acc"), "주 편집기")]),
]


def build_stack(P, theme):
    W, H = 1000, 292
    body = [card(P, W, H, 16)]
    for gi, (group, items) in enumerate(STACK):
        gx = 32 + gi * 324
        body.append(label(group, gx, 44, P))
        if gi:
            body.append(f'<path d="M{gx - 18} 32V{H - 32}" stroke="{P["border"]}"/>')
        for ii, (name, slug, colors, desc) in enumerate(items):
            y = 66 + ii * 54
            body.append(rect(gx, y, 40, 40, 10, P["surface2"], P["border"]))
            col = colors[0 if theme == "dark" else 1] or P["text"]
            if slug:
                body.append(icon(slug, gx + 10, y + 10, 20, col))
            else:
                ring = [(gx + 20 + 10 * math.cos(math.pi / 6 + k * math.pi / 3),
                         y + 20 + 10 * math.sin(math.pi / 6 + k * math.pi / 3)) for k in range(6)]
                body.append(f'<path d="{poly(ring)}" fill="none" stroke="{col}" stroke-width="2"/>')
                body.append(dot(gx + 20, y + 20, 3, col))
            body.append(text(name, gx + 54, y + 18, P["text"], 15, MED))
            body.append(text(desc, gx + 54, y + 36, P["muted"], 12, SANS))
    return svg(W, H, "".join(body), "", "사용하는 기술: " + ", ".join(i[0] for _, items in STACK for i in items))


# ---------------------------------------------------------------- blend demo (issue-driven)

FAMILIES = ["Floral", "Citrus", "Woody", "Sweet", "Fresh", "Musky", "Aquatic"]
FAMILIES_KO = ["플로럴", "시트러스", "우디", "스위트", "프레시", "머스키", "아쿠아틱"]
NOTES = {  # id: (English, Korean, (dark, light) colour, family vector)
    "lavender": ("Lavender", "라벤더", ("#b9a6ff", "#8250df"), (.6, 0, 0, 0, .5, 0, 0)),
    "citrus": ("Citrus", "시트러스", ("#e3b341", "#9a6700"), (0, 1, 0, 0, .3, 0, 0)),
    "rose": ("Rose", "장미", ("#ff7b9c", "#bf3989"), (1, 0, 0, .2, 0, 0, 0)),
    "vanilla": ("Vanilla", "바닐라", ("#f0c987", "#a0700b"), (0, 0, 0, 1, 0, .2, 0)),
    "sandalwood": ("Sandalwood", "샌달우드", ("#d29a6a", "#953800"), (0, 0, 1, .1, 0, .3, 0)),
    "musk": ("Musk", "머스크", ("#c9c4d6", "#6e7781"), (0, 0, .1, .2, 0, 1, 0)),
    "mint": ("Mint", "민트", ("#56d4a0", "#1a7f37"), (0, .2, 0, 0, 1, 0, 0)),
    "marine": ("Marine", "바다", ("#79c0ff", "#0969da"), (0, 0, 0, 0, .4, 0, 1)),
}
MIX_SIZE = 5


def mix_vector(mix):
    v = [0.0] * len(FAMILIES)
    for k, m in enumerate(mix):
        w = 1 + k * .25  # the newest note weighs the most
        for i, x in enumerate(NOTES[m["note"]][3]):
            v[i] += w * x
    return v


def cosine(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else None


def mix_name(mix, ko=False):
    if not mix:
        return "빈 블렌드" if ko else "Empty"
    names = FAMILIES_KO if ko else FAMILIES
    v = mix_vector(mix)
    top = sorted(range(len(v)), key=lambda i: -v[i])
    if v[top[1]] < v[top[0]] * .45:
        return names[top[0]]
    return f"{names[top[1]]} {names[top[0]]}"


def load_state(out):
    path = os.path.join(out, "scent.json")
    state = {"mix": [], "previous": [], "total": 0, "players": {}, "similarity": None}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            state.update(json.load(f))
    return state


def josa(word, a, b):
    ch = word[-1]
    if "가" <= ch <= "힣":
        return a if (ord(ch) - 0xAC00) % 28 else b
    return a


def play(out, title, player):
    state = load_state(out)
    note = title.split("|", 1)[1].strip().lower() if "|" in title else ""
    if note not in NOTES or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", player):
        names = ", ".join(f"`{k}`" for k in NOTES)
        return state, f"알 수 없는 향료입니다. 제목을 `scent|lavender` 형식으로 입력해 주세요.\n\n사용 가능한 향료: {names}"
    prev = mix_vector(state["mix"])
    state["previous"] = state["mix"]
    state["mix"] = (state["mix"] + [{"note": note, "by": player,
                                      "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}])[-MIX_SIZE:]
    sim = cosine(prev, mix_vector(state["mix"]))
    state["similarity"] = None if sim is None else round(sim, 4)
    state["total"] += 1
    state["players"][player] = state["players"].get(player, 0) + 1
    en, ko = NOTES[note][0], NOTES[note][1]
    reply = (f"@{player} 님이 **{ko} ({en})**{josa(ko, '을', '를')} 추가했습니다.\n\n"
             f"| | |\n|---|---|\n| 현재 블렌드 | **{mix_name(state['mix'])}** ({mix_name(state['mix'], True)}) |\n"
             + (f"| 직전 블렌드와의 코사인 유사도 | **{sim:.2f}** |\n" if sim is not None else "")
             + f"| 누적 조합 | {state['total']}회 |\n\n"
             f"[프로필에서 보기](https://github.com/{USER}#blend-demo) · 이미지는 1~2분 안에 갱신됩니다.")
    return state, reply


def radar_points(v, cx, cy, r, vmax):
    pts = []
    for i, x in enumerate(v):
        a = -math.pi / 2 + 2 * math.pi * i / len(v)
        rr = r * (x / vmax if vmax else 0)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def build_blend_profile(P, theme, state):
    W, H = 400, 320
    cx, cy, r = 200, 170, 92
    n = len(FAMILIES)
    body = [card(P, W, H), dot(28, 32, 3.5, P["warm"]), label("Blend profile", 40, 36, P)]
    for ring in (.25, .5, .75, 1):
        body.append(f'<path d="{poly(radar_points([1] * n, cx, cy, r * ring, 1))}" fill="none" stroke="{P["border"]}"/>')
    outer, labels = radar_points([1] * n, cx, cy, r, 1), radar_points([1] * n, cx, cy, r + 18, 1)
    for i in range(n):
        body.append(f'<path d="M{cx} {cy}L{outer[i][0]:.1f} {outer[i][1]:.1f}" stroke="{P["border"]}"/>')
        la, lb = labels[i]
        anchor = "middle" if abs(la - cx) < 10 else ("start" if la > cx else "end")
        body.append(text(FAMILIES[i], la, lb + 4, P["muted"], 11, MONO, anchor))
    cur, prev = mix_vector(state["mix"]), mix_vector(state["previous"])
    vmax = max(cur + prev) or 1
    if any(prev):
        body.append(f'<path d="{poly(radar_points(prev, cx, cy, r, vmax))}" fill="none" stroke="{P["cool"]}" '
                    f'stroke-dasharray="4 4" stroke-width="1.4"/>')
    if any(cur):
        pts = radar_points(cur, cx, cy, r, vmax)
        body.append(f'<g class="grow"><path d="{poly(pts)}" fill="{P["warm"]}" fill-opacity=".18" stroke="{P["warm"]}" '
                    f'stroke-width="1.8"/>{"".join(dot(a, b, 2.6, P["warm"]) for a, b in pts)}</g>')
    else:
        body.append(text("no notes yet", cx, cy + 4, P["faint"], 12, MONO, "middle"))
    body.append(f'<path d="M24 {H - 26}h16" stroke="{P["warm"]}" stroke-width="2"/>')
    body.append(text("current", 46, H - 22, P["muted"], 11, MONO))
    body.append(f'<path d="M116 {H - 26}h16" stroke="{P["cool"]}" stroke-width="1.4" stroke-dasharray="4 3"/>')
    body.append(text("previous", 138, H - 22, P["muted"], 11, MONO))
    css = ("@keyframes grow{0%{transform:scale(.6);opacity:0}100%{transform:scale(1);opacity:1}}"
           f".grow{{transform-origin:{cx}px {cy}px;animation:grow 1.4s cubic-bezier(.2,.8,.2,1) both}}")
    return svg(W, H, "".join(body), css, f"블렌드 프로필 레이더 차트: {mix_name(state['mix'], True)}")


def build_blend_info(P, theme, state):
    W, H = 400, 320
    mix = state["mix"]
    t = 0 if theme == "dark" else 1
    body = [card(P, W, H), dot(28, 32, 3.5, P["cool"]), label("Current blend", 40, 36, P)]
    body.append(text(mix_name(mix), 24, 76, P["text"], 22, SEMI))
    body.append(text(mix_name(mix, True), 24, 98, P["muted"], 13, SANS))
    y = 134
    if mix:
        for m in reversed(mix):
            en, ko, cols, _ = NOTES[m["note"]]
            body.append(dot(30, y - 4, 4, cols[t]))
            body.append(text(en, 42, y, P["text"], 14, MED))
            body.append(text(ko, 42 + measure(en, 14, MED) + 8, y, P["muted"], 13, SANS))
            body.append(text("@" + m["by"], W - 24, y, P["faint"], 11, MONO, "end"))
            y += 26
    else:
        body.append(text("아직 아무 향료도 없습니다.", 24, y, P["text"], 14, SANS))
        body.append(text("아래에서 첫 향료를 추가해 보세요.", 24, y + 22, P["muted"], 13, SANS))
    sim = state["similarity"]
    body.append(f'<path d="M24 {H - 70}H{W - 24}" stroke="{P["border"]}"/>')
    body.append(text(f"cos(previous, current) = {sim:.2f}" if sim is not None else "cos(previous, current) = —",
                     24, H - 46, P["text"] if sim is not None else P["muted"], 12, MONO))
    body.append(rect(24, H - 36, W - 48, 4, 2, P["grid"]))
    if sim is not None:
        body.append(rect(24, H - 36, round((W - 48) * sim, 1), 4, 2, P["cool"]))
    body.append(text(f"{state['total']} blends · {len(state['players'])} contributors", 24, H - 14, P["faint"], 11, MONO))
    return svg(W, H, "".join(body), "", f"현재 블렌드: {mix_name(mix, True)}, 누적 {state['total']}회")


def build_note_chip(P, theme, note):
    en, ko, cols, _ = NOTES[note]
    h = 34
    w = round(32 + measure(en, 13, MED) + 6 + measure(ko, 12, SANS) + 16)
    body = [rect(0.5, 0.5, w - 1, h - 1, 17, P["surface2"], P["border"]),
            dot(19, 17, 4.5, cols[0 if theme == "dark" else 1]),
            text(en, 32, 22, P["text"], 13, MED),
            text(ko, 32 + measure(en, 13, MED) + 6, 22, P["muted"], 12, SANS)]
    return svg(w, h, "".join(body), "", f"{ko} 추가")


# ---------------------------------------------------------------- GitHub stats

LANG_COLORS = {"Python": "#3572A5", "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "HTML": "#e34c26",
               "CSS": "#663399", "TeX": "#3D6117", "Shell": "#89e051", "Java": "#b07219"}


def streaks(days):
    longest = run = 0
    for _, n, _ in days:
        run = run + 1 if n else 0
        longest = max(longest, run)
    seq = [n for _, n, _ in days]
    if seq and seq[-1] == 0:
        seq = seq[:-1]  # today may simply not have started yet
    cur = 0
    for n in reversed(seq):
        if not n:
            break
        cur += 1
    return cur, longest


def build_contrib(P, theme, d):
    W, H = 400, 236
    body = [card(P, W, H), dot(28, 32, 3.5, P["cool"]), label("Contributions · last 12 months", 40, 36, P)]
    total = f"{d['total']:,}"
    body.append(text(total, 24, 88, P["text"], 40, SEMI))
    cur, longest = streaks(d["days"])
    sx = 24 + measure(total, 40, SEMI) + 20
    body.append(text(f"current streak  {cur}d", sx, 70, P["muted"], 11, MONO))
    body.append(text(f"longest streak  {longest}d", sx, 88, P["muted"], 11, MONO))
    days = d["days"][-53 * 7:]
    offset = (dt.date.fromisoformat(days[0][0]).weekday() + 1) % 7  # GitHub weeks start on Sunday
    pitch, cell = 6.6, 5.2
    cells = []
    for i, (_, _, lvl) in enumerate(days):
        k = i + offset
        cells.append(f'<rect class="hm" style="animation-delay:{k // 7 * .02:.2f}s" x="{24 + k // 7 * pitch:.1f}" '
                     f'y="{112 + k % 7 * pitch:.1f}" width="{cell}" height="{cell}" rx="1" fill="{P["heat"][lvl]}"/>')
    body.append("".join(cells))
    body.append(text("less", 24, 182, P["faint"], 10, MONO))
    for i, c in enumerate(P["heat"]):
        body.append(rect(52 + i * 8, 175, 6, 6, 1, c))
    body.append(text("more", 96, 182, P["faint"], 10, MONO))
    body.append(f'<path d="M24 {H - 34}H{W - 24}" stroke="{P["border"]}"/>')
    body.append(text(f"{d['repos']} public repositories · since {d['created'].replace('-', '.')}", 24, H - 13,
                     P["muted"], 11, MONO))
    css = "@keyframes hm{from{opacity:0}to{opacity:1}}.hm{animation:hm .5s both}"
    return svg(W, H, "".join(body), css, f"지난 1년 기여 {d['total']}회, 공개 저장소 {d['repos']}개")


def build_langs(P, theme, d):
    W, H = 400, 236
    body = [card(P, W, H), dot(28, 32, 3.5, P["warm"]), label("Languages · by bytes", 40, 36, P)]
    langs = d["langs"][:5]
    tot = sum(v for _, v in d["langs"]) or 1
    x, bw = 24.0, W - 48
    body.append(f'<clipPath id="bar"><rect x="24" y="58" width="{bw}" height="8" rx="4"/></clipPath><g clip-path="url(#bar)">')
    body.append(rect(24, 58, bw, 8, 0, P["grid"]))
    for name, v in langs:
        w = bw * v / tot
        body.append(rect(round(x, 2), 58, round(w + .5, 2), 8, 0, LANG_COLORS.get(name, P["muted"])))
        x += w
    body.append("</g>")
    for i, (name, v) in enumerate(langs):
        y = 98 + i * 20
        body.append(dot(30, y - 4, 4, LANG_COLORS.get(name, P["muted"])))
        body.append(text(name, 42, y, P["text"], 13, SANS))
        body.append(text(f"{v / tot * 100:.1f}%", W - 24, y, P["muted"], 11, MONO, "end"))
    body.append(f'<path d="M24 {H - 34}H{W - 24}" stroke="{P["border"]}"/>')
    stamp = dt.datetime.now(KST).strftime("%Y.%m.%d")
    body.append(text(f"excludes notebooks · updated {stamp}", 24, H - 13, P["muted"], 11, MONO))
    return svg(W, H, "".join(body), "", "주요 언어: " + ", ".join(f"{n} {v / tot * 100:.0f}%" for n, v in langs))


# ---------------------------------------------------------------- live data

def fetch(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER + "-profile"})
    if token and "api.github.com" in url:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def fetch_json(url, token=None):
    return json.loads(fetch(url, token))


def parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(KST)


def gather():
    token = os.environ.get("GITHUB_TOKEN")
    page = fetch(f"https://github.com/users/{USER}/contributions").decode()
    flat = re.sub(r"\s+", " ", page)
    total = int(re.search(r"([\d,]+) contributions? in the last year", flat).group(1).replace(",", ""))
    tips = {m.group(1): m.group(2) for m in re.finditer(r'<tool-tip [^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', page)}
    days = []
    for m in re.finditer(r"<td [^>]*data-date=[^>]*>", page):
        tag = m.group(0)
        cid = re.search(r'id="([^"]+)"', tag).group(1)
        cm = re.match(r"(\d+) contribution", tips.get(cid, ""))
        days.append((re.search(r'data-date="([^"]+)"', tag).group(1), int(cm.group(1)) if cm else 0,
                     int(re.search(r'data-level="(\d)"', tag).group(1))))
    days.sort()
    user = fetch_json(f"https://api.github.com/users/{USER}", token)
    repos = fetch_json(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner", token)
    langs = {}
    for r in repos:
        if r["fork"]:
            continue
        for k, v in fetch_json(r["languages_url"], token).items():
            if k != "Jupyter Notebook":  # notebook outputs would drown everything else
                langs[k] = langs.get(k, 0) + v
    by_name = {r["name"]: r for r in repos}
    cards = {p["repo"]: {"pushed": parse_time(by_name[p["repo"]]["pushed_at"]),
                         "stars": by_name[p["repo"]]["stargazers_count"]}
             for p in PROJECTS if p["repo"] in by_name}
    return dict(total=total, days=days, repos=sum(not r["fork"] for r in repos), created=user["created_at"][:7],
                langs=sorted(langs.items(), key=lambda kv: -kv[1]), cards=cards, cites=gather_citations())


def gather_citations():
    try:
        return int(fetch_json(f"https://api.openalex.org/works/doi:{DOI}").get("cited_by_count") or 0)
    except Exception:
        try:
            return int(fetch_json(f"https://api.crossref.org/works/{DOI}")["message"].get("is-referenced-by-count", 0))
        except Exception:
            return 0


def gather_activity(token, limit=8):
    events = fetch_json(f"https://api.github.com/users/{USER}/events/public?per_page=100", token)
    rows = []
    for e in events:
        repo = e["repo"]["name"]
        if repo == f"{USER}/{USER}":
            continue  # profile edits are not news
        when, pl, short = parse_time(e["created_at"]), e["payload"], repo.split("/")[1]
        if e["type"] == "PushEvent":
            # a streak of pushes to one repo becomes a single line
            if not (rows and rows[-1]["kind"] == "push" and rows[-1]["full"] == repo):
                rows.append({"kind": "push", "repo": short, "full": repo, "when": when, "pushes": []})
            rows[-1]["since"] = when
            rows[-1]["pushes"].append((repo, pl.get("before"), pl.get("head")))
        elif e["type"] == "CreateEvent" and pl.get("ref_type") == "repository":
            rows.append({"kind": "create", "repo": short, "when": when})
        elif e["type"] == "PullRequestEvent" and pl.get("action") in ("opened", "closed"):
            merged = pl.get("action") == "closed" and (pl.get("pull_request") or {}).get("merged")
            if pl.get("action") == "opened" or merged:
                rows.append({"kind": "merged" if merged else "pr", "repo": short, "when": when, "num": pl.get("number")})
        elif e["type"] == "ReleaseEvent":
            rows.append({"kind": "release", "repo": short, "when": when,
                         "tag": (pl.get("release") or {}).get("tag_name", "")})
        elif e["type"] == "MemberEvent":
            rows.append({"kind": "member", "repo": short, "when": when})
    rows = rows[:limit]
    for r in rows:
        if r["kind"] == "push":
            n = 0
            for repo, before, head in r["pushes"]:
                try:
                    if not before or set(before) == {"0"}:
                        raise ValueError
                    n += fetch_json(f"https://api.github.com/repos/{repo}/compare/{before}...{head}", token)["total_commits"]
                except Exception:
                    n += 1
            r["commits"] = n
    return rows


def activity_block(rows):
    lines = []
    for r in rows:
        if r["kind"] == "push":
            what = f"+{r['commits']} commit{'s' if r['commits'] != 1 else ''}"
            if r["since"].date() != r["when"].date():
                what += f" since {r['since'].strftime('%m-%d')}"
        else:
            what = {"create": "new repository", "pr": f"opened PR #{r.get('num')}",
                    "merged": f"merged PR #{r.get('num')}", "release": f"released {r.get('tag')}",
                    "member": "joined as collaborator"}[r["kind"]]
        lines.append(f"{r['when'].strftime('%Y-%m-%d')}  {r['kind']:<8}{r['repo']:<30}{what}")
    return "```text\n" + ("\n".join(lines) or "no recent public activity") + "\n```"


# ---------------------------------------------------------------- main

def themed(out, name, fn, *args):
    os.makedirs(out, exist_ok=True)
    for theme, P in THEMES.items():
        content = fn(P, theme, *args)
        path = os.path.join(out, f"{name}-{theme}.svg")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        print(f"  {os.path.relpath(path, ROOT):42s} {len(content) / 1024:7.1f} KB")


def write_blend(out, state):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "scent.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    themed(out, "blend-profile", build_blend_profile, state)
    themed(out, "blend-info", build_blend_info, state)


def main():
    load_fonts()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "static"
    if cmd == "live":
        out = sys.argv[2]
        d = gather()
        now = dt.datetime.now(KST)
        themed(out, "contrib", build_contrib, d)
        themed(out, "langs", build_langs, d)
        themed(out, "cite", build_cite, d["cites"])
        for p in PROJECTS:
            themed(out, f"card-{p['key']}", build_card, p, d["cards"].get(p["repo"]), now)
        write_blend(out, load_state(out))
        return
    if cmd == "activity":
        path = sys.argv[2]
        with open(path, encoding="utf-8") as f:
            readme = f.read()
        block = activity_block(gather_activity(os.environ.get("GITHUB_TOKEN")))
        readme = re.sub(r"(<!-- activity:start -->\n).*?(\n<!-- activity:end -->)",
                        lambda m: m.group(1) + block + m.group(2), readme, flags=re.S)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(readme)
        return
    if cmd == "play":
        out, title, player = sys.argv[2], os.environ["SCENT_TITLE"], os.environ["SCENT_PLAYER"]
        state, reply = play(out, title, player)
        write_blend(out, state)
        with open(os.environ.get("REPLY_FILE", os.path.join(out, "..", "reply.md")), "w", encoding="utf-8") as f:
            f.write(reply)
        return
    print("building assets/")
    themed(ASSETS, "hero", build_hero)
    themed(ASSETS, "figure", build_figure)
    themed(ASSETS, "stack", build_stack)
    themed(ASSETS, "badge-orcid", build_badge, "ORCID", "orcid")
    themed(ASSETS, "badge-paper", build_badge, "Paper · JCIM 2026", None, "¶")
    themed(ASSETS, "badge-repos", build_badge, "Repositories", "github")
    themed(ASSETS, "badge-code", build_badge, "Code", "github")
    for note in NOTES:
        themed(ASSETS, f"note-{note}", build_note_chip, note)


if __name__ == "__main__":
    main()
