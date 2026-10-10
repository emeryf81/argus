"""ARGUS brand kit generator: icon, logo (light/dark), banner, social preview.

Design system
- Night   #0A1029 / #141D45  (background, text on light)
- Gold    #E9B949  light #F8DC8C  dark #B98A22  (the eyes)
- Teal    #27B7A8  (the peacock feather)  · Green #3DDC84 (the lowest price)
- Cream   #FFF3D6  (the whites of the eyes, text on dark)
- Slate   #5D6680 / #9AA6C2  (secondary text)
Mark: Argus Panoptes, the giant with a hundred eyes. After he died Hera set his eyes on the peacock's tail: the mark is
his eye in front of a fan of peacock-feather eyes. Banner: the same, with a falling price line and its lowest point. Type: Inter ExtraBold / SemiBold (OFL), converted to paths so the SVGs need no font.

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

NIGHT, NIGHT2, NIGHT3 = "#0A1029", "#141D45", "#1C2756"
GOLD, GOLD_L, GOLD_D = "#E9B949", "#F8DC8C", "#B98A22"
TEAL, TEAL_D = "#27B7A8", "#127A78"
CREAM, SLATE, SLATE_L = "#FFF4DA", "#5D6680", "#A3ADC8"
GREEN = "#3DDC84"


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


def ocellus(cx: float, cy: float, r: float, rot: float = 0.0) -> str:
    """One 'eye' of a peacock feather (the eyes Hera set on the peacock's tail after Argus died): a gold drop with a
    teal ring and a dark pupil, slightly pointed towards the feather's tip."""
    drop = lambda k: (f"M0,{-r * k * 1.25:.2f} C{r * k * .95:.2f},{-r * k * .55:.2f} {r * k:.2f},{r * k * .55:.2f} 0,{r * k:.2f}"  # noqa: E731
                      f" C{-r * k:.2f},{r * k * .55:.2f} {-r * k * .95:.2f},{-r * k * .55:.2f} 0,{-r * k * 1.25:.2f}Z")
    return (f'<g transform="translate({cx:.2f} {cy:.2f}) rotate({rot:.1f})"><path d="{drop(1)}" fill="url(#gold)"/>'
            f'<path d="{drop(.72)}" fill="{TEAL}"/><path d="{drop(.48)}" fill="{NIGHT}"/>'
            f'<circle cx="{-r * .14:.2f}" cy="{-r * .18:.2f}" r="{r * .12:.2f}" fill="{CREAM}" fill-opacity=".9"/></g>')


def mark(size: float = 512, tile: bool = True) -> str:
    """The emblem on a 512×512 canvas: Argus' eye in front of a fan of peacock-feather eyes (his hundred eyes)."""
    s = []
    if tile:
        s.append('<rect width="512" height="512" rx="116" fill="url(#bg)"/>')
        s.append('<rect width="512" height="512" rx="116" fill="url(#glow)"/>')
    cx, cy = 256, 318                                       # the fan grows from behind the big eye
    n = 11
    for i in range(n):                                      # the feathers: a thin shaft and an eye at the tip
        a = math.radians(-180 + 14 + i * (152 / (n - 1)))
        L = 196 if i % 2 == 0 else 168
        tx, ty = cx + math.cos(a) * L, cy + math.sin(a) * L
        s.append(f'<path d="M{cx},{cy} L{tx:.1f},{ty:.1f}" stroke="{GOLD_D}" stroke-opacity=".55" stroke-width="3" stroke-linecap="round"/>')
        r = 25 if i % 2 == 0 else 19
        s.append(ocellus(tx, ty, r, math.degrees(a) + 90))
    # the big eye
    w, h = 132, 76
    almond = f"M{cx - w},{cy} C{cx - w * .5},{cy - h * 1.15} {cx + w * .5},{cy - h * 1.15} {cx + w},{cy} C{cx + w * .5},{cy + h * 1.15} {cx - w * .5},{cy + h * 1.15} {cx - w},{cy}Z"
    s.append(f'<path d="{almond}" fill="{CREAM}"/>')
    s.append(f'<clipPath id="eyeclip"><path d="{almond}"/></clipPath><g clip-path="url(#eyeclip)">'
             f'<circle cx="{cx}" cy="{cy}" r="62" fill="url(#iris)"/>'
             f'<circle cx="{cx}" cy="{cy}" r="62" fill="none" stroke="{NIGHT}" stroke-opacity=".35" stroke-width="4"/>'
             f'<circle cx="{cx}" cy="{cy}" r="27" fill="{NIGHT}"/>'
             f'<circle cx="{cx - 19}" cy="{cy - 22}" r="11" fill="#fff" fill-opacity=".95"/>'
             f'<circle cx="{cx + 16}" cy="{cy + 17}" r="5" fill="#fff" fill-opacity=".6"/></g>')
    s.append(f'<path d="{almond}" fill="none" stroke="url(#gold)" stroke-width="10" stroke-linejoin="round"/>')
    return "".join(s)


def defs() -> str:
    return (f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{NIGHT2}"/><stop offset="1" stop-color="{NIGHT}"/></linearGradient>'
            f'<radialGradient id="glow" cx=".5" cy=".62" r=".55"><stop offset="0" stop-color="{GOLD}" stop-opacity=".22"/><stop offset="1" stop-color="{GOLD}" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="iris" cx=".42" cy=".38" r=".7"><stop offset="0" stop-color="{GOLD_L}"/><stop offset=".55" stop-color="{GOLD}"/><stop offset="1" stop-color="{TEAL_D}"/></radialGradient>'
            f'<linearGradient id="gold" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{GOLD_L}"/><stop offset="1" stop-color="{GOLD}"/></linearGradient>'
            f'<linearGradient id="fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{GOLD}" stop-opacity="0"/><stop offset=".25" stop-color="{GOLD}" stop-opacity=".55"/><stop offset="1" stop-color="{GOLD}" stop-opacity=".9"/></linearGradient></defs>')


def price_line(x0: float, y0: float, w: float, h: float) -> str:
    """A falling price line with its lowest point marked: what ARGUS watches for."""
    pts = [(0, .25), (.08, .2), (.16, .34), (.25, .3), (.34, .48), (.43, .42), (.52, .6), (.6, .55), (.7, .78), (.78, .7),
           (.87, .92), (.95, .84), (1, .88)]
    d = " ".join(f"{'M' if i == 0 else 'L'}{x0 + x * w:.1f},{y0 + y * h:.1f}" for i, (x, y) in enumerate(pts))
    lx, ly = x0 + .87 * w, y0 + .92 * h
    return (f'<path d="{d}" fill="none" stroke="url(#fade)" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="14" fill="{GREEN}" fill-opacity=".18"/><circle cx="{lx:.1f}" cy="{ly:.1f}" r="7" fill="{GREEN}"/>')


def dots(w: int, h: int, step: int = 34) -> str:
    """A quiet field of tiny eyes in the background."""
    out = []
    for y in range(step // 2, h, step):
        for x in range(step // 2 + (step // 2 if (y // step) % 2 else 0), w, step):
            out.append(f'<circle cx="{x}" cy="{y}" r="1.6" fill="{GOLD}" fill-opacity=".10"/>')
    return "".join(out)


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
        body = (f'<g transform="translate(0 0)">{m}</g><g transform="translate(552 270)"><path d="{word}" fill="{"url(#gold)" if fg == CREAM else NIGHT2}"/></g>'
                f'<g transform="translate(556 330)"><path d="{line}" fill="{sub}"/></g>')
        (out / f"{name}.svg").write_text(svg(int(W), 512, body))
    # README banner 1600×480 and social preview 1280×640 (dark)
    word, ww = text_path(xb, "ARGUS", 0, 0, 168, 0.08)
    line, lw = text_path(sb, "Altijd Rondkijken, Goedkoopste Uitzoeken, Snel melden", 0, 0, 30, 0.0)
    tag, tw = text_path(sb, "Watches prices across every shop · alerts you at the right moment", 0, 0, 26, 0.0)
    tag_nl, _ = text_path(sb, "Houdt prijzen in het oog bij elke winkel · meldt het juiste moment", 0, 0, 24, 0.0)
    banner = (f'{dots(1600, 480)}<rect width="1600" height="480" fill="url(#glow)" opacity=".7"/>{price_line(548, 412, 1010, 44)}'
              f'<g transform="translate(70 34) scale(.80)">{mark(tile=False)}</g>'
              f'<g transform="translate(540 236)"><path d="{word}" fill="url(#gold)"/></g>'
              f'<g transform="translate(546 290)"><path d="{line}" fill="{SLATE_L}"/></g>'
              f'<g transform="translate(546 346)"><path d="{tag}" fill="{CREAM}" fill-opacity=".85"/></g>'
              f'<g transform="translate(546 384)"><path d="{tag_nl}" fill="{CREAM}" fill-opacity=".55"/></g>')
    (out / "banner.svg").write_text(svg(1600, 480, banner, NIGHT))
    word2, _ = text_path(xb, "ARGUS", 0, 0, 150, 0.08)
    tag_s, _ = text_path(sb, "Houdt prijzen in het oog bij elke winkel", 0, 0, 24, 0.0)
    line2a, _ = text_path(sb, "Altijd Rondkijken, Goedkoopste Uitzoeken,", 0, 0, 30, 0.0)
    line2b, _ = text_path(sb, "Snel melden", 0, 0, 30, 0.0)
    social = (f'{dots(1280, 640)}<rect width="1280" height="640" fill="url(#glow)" opacity=".8"/>{price_line(700, 470, 500, 110)}'
              f'<g transform="translate(70 96) scale(.88)">{mark(tile=False)}</g>'
              f'<g transform="translate(560 270)"><path d="{word2}" fill="url(#gold)"/></g>'
              f'<g transform="translate(566 326)"><path d="{line2a}" fill="{SLATE_L}"/></g><g transform="translate(566 366)"><path d="{line2b}" fill="{SLATE_L}"/></g>'
              f'<g transform="translate(566 420)"><path d="{tag_s}" fill="{CREAM}" fill-opacity=".7"/></g>')
    (out / "social.svg").write_text(svg(1280, 640, social, NIGHT))

if __name__ == "__main__":
    here = Path(__file__).parent
    build(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else here / "out")
