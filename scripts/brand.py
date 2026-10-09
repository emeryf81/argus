"""ARGUS brand kit generator: icon, logo (light/dark), banner, social preview.

Design system
- Night   #0B1020 / #141B33  (background, text on light)
- Gold    #E8B84A  light #F6D77E  dark #B8862B  (the eyes)
- Cream   #FFF3D6  (the whites of the eyes, text on dark)
- Slate   #5D6680 / #9AA6C2  (secondary text)
Mark: Argus Panoptes, the giant with a hundred eyes — a face whose forehead, temples and cheeks are covered with eyes, two big
ones in the middle. Type: Inter ExtraBold / SemiBold (OFL), converted to paths so the SVGs need no font.

Usage: `python scripts/brand.py <inter-extrabold.otf> <inter-semibold.otf> [outdir]` (needs fonttools) writes the SVGs;
render the PNGs from them with any browser (see the commented block at the bottom).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

NIGHT, NIGHT2, NIGHT3 = "#0B1020", "#141B33", "#1E2747"
GOLD, GOLD_L, GOLD_D = "#E8B84A", "#F6D77E", "#B8862B"
CREAM, SLATE, SLATE_L = "#FFF3D6", "#5D6680", "#9AA6C2"


def text_path(font: TTFont, s: str, x: float, y: float, size: float, tracking: float = 0.0, anchor: str = "start") -> tuple[str, float]:
    """The text as one SVG path (d attribute) and its width."""
    upm = font["head"].unitsPerEm
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    k = size / upm
    width = sum(hmtx[cmap[ord(c)]][0] * k for c in s) + tracking * size * (len(s) - 1)
    if anchor == "middle":
        x -= width / 2
    elif anchor == "end":
        x -= width
    d, cx = [], x
    for c in s:
        g = cmap[ord(c)]
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (k, 0, 0, -k, cx, y)))
        d.append(pen.getCommands())
        cx += hmtx[g][0] * k + tracking * size
    return " ".join(d), width


def eye(cx: float, cy: float, w: float, rot: float = 0.0, look: tuple[float, float] = (0.0, 0.0), ring: bool = True) -> str:
    """One almond-shaped eye of half-width w, centred on (cx, cy), rotated by rot degrees."""
    h = w * 0.62
    almond = f"M{-w:.2f},0 Q0,{-h * 1.7:.2f} {w:.2f},0 Q0,{h * 1.7:.2f} {-w:.2f},0Z"
    r = h * 0.98
    ix, iy = look[0] * w * 0.28, look[1] * h * 0.2
    clip = f"e{abs(hash((round(cx), round(cy), round(w)))):x}"
    return (f'<g transform="translate({cx:.2f} {cy:.2f}) rotate({rot:.1f})"><clipPath id="{clip}"><path d="{almond}"/></clipPath>'
            f'<path d="{almond}" fill="{CREAM}"/><g clip-path="url(#{clip})">'
            f'<circle cx="{ix:.2f}" cy="{iy:.2f}" r="{r:.2f}" fill="{GOLD}"/><circle cx="{ix:.2f}" cy="{iy:.2f}" r="{r * 0.62:.2f}" fill="{GOLD_D}"/>'
            f'<circle cx="{ix:.2f}" cy="{iy:.2f}" r="{r * 0.36:.2f}" fill="{NIGHT}"/>'
            f'<circle cx="{ix - r * 0.22:.2f}" cy="{iy - r * 0.26:.2f}" r="{r * 0.14:.2f}" fill="{CREAM}"/></g>'
            + (f'<path d="{almond}" fill="none" stroke="{GOLD_L}" stroke-width="{max(w * 0.07, 0.6):.2f}" stroke-linejoin="round"/>' if ring else "")
            + "</g>")


def mark(size: float = 512, tile: bool = True) -> str:
    """The emblem on a 512×512 canvas: a face with eyes everywhere; tile=True puts it on a dark rounded square."""
    s = []
    if tile:
        s.append(f'<rect width="512" height="512" rx="112" fill="url(#bg)"/>')
        s.append(f'<circle cx="256" cy="262" r="214" fill="none" stroke="{GOLD}" stroke-opacity=".18" stroke-width="3"/>')
    # radiating halo of small eyes behind the head (the peacock fan of the myth)
    for i in range(15):
        a = math.radians(-180 + 12 + i * (156 / 14))
        cx, cy = 256 + math.cos(a) * 196, 268 + math.sin(a) * 178
        s.append(eye(cx, cy, 17, math.degrees(a) + 90, (math.cos(a) * 0.6, math.sin(a) * 0.6)))
    # the head
    s.append(f'<path d="M256 96 C170 96 126 160 126 238 C126 300 148 346 184 380 C206 400 228 412 256 412 C284 412 306 400 328 380'
             f' C364 346 386 300 386 238 C386 160 342 96 256 96Z" fill="{NIGHT3}" stroke="{GOLD}" stroke-width="5"/>')
    # brow band, nose, mouth, beard hint
    s.append(f'<path d="M150 214 Q256 176 362 214" fill="none" stroke="{GOLD_D}" stroke-width="5" stroke-linecap="round"/>')
    s.append(f'<path d="M256 258 L242 318 Q256 330 270 318Z" fill="none" stroke="{GOLD}" stroke-width="5" stroke-linejoin="round"/>')
    s.append(f'<path d="M222 358 Q256 376 290 358" fill="none" stroke="{GOLD}" stroke-width="6" stroke-linecap="round"/>')
    # forehead row, temples and cheeks
    for cx, cy, w, r in [(196, 150, 15, -14), (226, 130, 14, -6), (256, 124, 14, 0), (286, 130, 14, 6), (316, 150, 15, 14),
                         (160, 192, 12, -24), (352, 192, 12, 24),
                         (142, 262, 13, -18), (370, 262, 13, 18), (162, 318, 12, -26), (350, 318, 12, 26),
                         (200, 384, 11, -20), (312, 384, 11, 20)]:
        s.append(eye(cx, cy, w, r, ((cx - 256) / 120, 0.2)))
    # the two big eyes
    s.append(eye(204, 236, 38, -4, (0.5, 0.15)))
    s.append(eye(308, 236, 38, 4, (-0.5, 0.15)))
    return "".join(s)


def defs() -> str:
    return (f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NIGHT2}"/><stop offset="1" stop-color="{NIGHT}"/></linearGradient>'
            f'<linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{GOLD_L}"/><stop offset="1" stop-color="{GOLD}"/></linearGradient></defs>')


def svg(w: int, h: int, body: str, bg: str | None = None) -> str:
    rect = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{defs()}{rect}{body}</svg>'


def build(extrabold: Path, semibold: Path, out: Path) -> None:
    xb, sb = TTFont(extrabold), TTFont(semibold)
    out.mkdir(parents=True, exist_ok=True)
    m = mark()
    (out / "icon.svg").write_text(svg(512, 512, m))
    # logo: mark + wordmark + acronym line, transparent background (dark text for light UIs, cream for dark UIs)
    for name, fg, sub, sub2 in (("logo", NIGHT, SLATE, SLATE), ("dark_logo", CREAM, SLATE_L, SLATE_L)):
        word, ww = text_path(xb, "ARGUS", 0, 0, 120, 0.06)
        line, lw = text_path(sb, "Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden", 0, 0, 25, 0.0)
        W = 512 + 40 + max(ww, lw) + 40
        body = (f'<g transform="translate(0 0)">{m}</g><g transform="translate(552 270)"><path d="{word}" fill="url(#gold)"/></g>'
                f'<g transform="translate(556 330)"><path d="{line}" fill="{sub}"/></g>')
        (out / f"{name}.svg").write_text(svg(int(W), 512, body))
    # banner 1280×320 (README) and social preview 1280×640, dark
    word, ww = text_path(xb, "ARGUS", 0, 0, 150, 0.06)
    line, lw = text_path(sb, "Altijd Rondkijken, Goedkoopste Uitzoeken,", 0, 0, 30, 0.0)
    line2, _ = text_path(sb, "Snel melden", 0, 0, 30, 0.0)
    tag, tw = text_path(sb, "Price watcher for Home Assistant", 0, 0, 26, 0.0)
    banner = (f'<g transform="translate(60 24) scale(.5625)">{m}</g><g transform="translate(400 170)"><path d="{word}" fill="url(#gold)"/></g>'
              f'<g transform="translate(404 214)"><path d="{line}" fill="{SLATE_L}"/></g><g transform="translate(404 252)"><path d="{line2}" fill="{SLATE_L}"/></g>'
              f'<g transform="translate(404 296)"><path d="{tag}" fill="{CREAM}" fill-opacity=".7"/></g>')
    (out / "banner.svg").write_text(svg(1280, 320, banner, NIGHT))
    social = (f'<g transform="translate(110 112) scale(.82)">{m}</g><g transform="translate(570 292)"><path d="{word}" fill="url(#gold)"/></g>'
              f'<g transform="translate(574 352)"><path d="{line}" fill="{SLATE_L}"/></g><g transform="translate(574 394)"><path d="{line2}" fill="{SLATE_L}"/></g>'
              f'<g transform="translate(574 456)"><path d="{tag}" fill="{CREAM}" fill-opacity=".7"/></g>')
    (out / "social.svg").write_text(svg(1280, 640, social, NIGHT))


if __name__ == "__main__":
    here = Path(__file__).parent
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else here / "out")
