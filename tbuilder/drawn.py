"""What Desktop drew (decisions/076, 078): the numbers of KPIs, registries, tables; the marks of bars, lines, areas.

  python -m tbuilder check-drawn <book.twbx> <spec.json> [-d out/drawn_<book>]

The gate and reconcile check the XML and the numbers it computes; neither sees what Desktop draws. a case's Top Closed
Won / Lost passed both with every value missing on screen (decisions/072, 075). Here:
1. each dashboard is opened in Desktop (a copy of the book with it as the open window, desktop_check) and captured
   without clicks (screenshot.capture_dashboard: found by its zone in UI Automation; one taller than the window
   scrolled through its scroll bar and stitched, decisions/078);
2. every zone of a number sheet is cut out and read by Windows' OCR as drawn and doubled (tbuilder/ocr.py);
3. the numbers read (words of a line joined into '1 059 080', 'o' read for '0' fixed, parsed as reconcile reads an
   HTML page: match.parse_number, by the marks of the book's <workbook locale>, decisions/085) are matched against
   expected.compute: a value is drawn when a number read is within half its displayed step ('$27.6M' holds
   27 550 000 .. 27 650 000; the sign by ▲ / ▼ / parentheses aside).
Groups: a registry's column, read in its own strip (the column's title zone stands right on it, decisions/064), so a
blank column cannot borrow its neighbour's equal numbers; a table's column and a KPI's tile, read in the sheet's zones.
A tick's base and a track have no label: not checked. Verdict per group:
- OK: every value read; PARTIAL: some (a registry that scrolls, an OCR miss);
- FAIL: none read and nothing drawn in its strip - no ink (luminance < INK_LUMA) on INK_MIN of it: the empty cells of
  a registry (white bars on white);
- UNREAD: none read but ink there (white labels on accent bars, a 26pt '25,1%' Windows' OCR drops): a warning;
- UNCHECKED: not wholly on screen, or hidden (a switch's other view).
Bars, lines, areas (decisions/078), the dots of a strip / beeswarm (decisions/176): their marks in the colors the book
gives them (mark_colors), laid over the zone's background at half opacity or more, in 2 x 2 blocks; FAIL when there
are none (or the color is the background's) though expected.compute has data; PARTIAL when the bars counted are not
about the categories, or a line covers less than LINE_COVER of its span (dots are not counted).
"""
import argparse
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import screenshot as shots
from .match import SCALES, parse_number

NUMBER_SHEETS = ("kpi", "registry", "table")
MARK_SHEETS = ("bar", "line", "area")  # their marks are looked for in the mark colors of the book (decisions/078)
DOT_SHEETS = ("strip", "beeswarm")  # dots: drawn or not, no count (a strip with a tooltip drew none, decisions/176)
MARK_TOL = 12  # a pixel is of a mark color when each channel is within this of it, laid over the background
MARK_ALPHA = 0.5  # ... at this opacity or more (an area is drawn at ~62%, a sloped line anti-aliased)
SEEN_MIN = 24  # a mark color within this of the zone's background (each channel) cannot be seen: white bars on white
MARK_MIN = 30  # fewer solid mark pixels (2 x 2 blocks of a mark color) than this: nothing drawn
BAR_MIN = 4  # solid pixels across a bar for its row / column to count: a 2-3 px line of the same color does not
LINE_COVER = 0.9  # share of a line's columns, from its first to its last, that must hold its color
DEFAULT_MARK = "#4e79a7"  # Desktop's mark color without one set (Tableau 10 blue)
TABLEAU10 = ("#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f",
             "#bab0ac")  # a color dimension without a palette of its own
ZOOMS = (1, 2)  # each zone is read as drawn and at twice its size: 9pt labels read clean doubled, 26pt KPI values
# only as drawn (a case: '25,1%' doubled is not read at all)
OK, PARTIAL, FAIL, UNREAD, UNCHECKED = "OK", "PARTIAL", "FAIL", "UNREAD", "UNCHECKED"
INK_LUMA, INK_MIN = 160, 0.003  # text (#333, muted #898989) and accent bars are ink; white / #e6e6e6 bars not
_SIGNS = "▲▼+-−–"
_NUMERIC = re.compile(r"^\(?[" + _SIGNS + r"]?[$€£₽]?\d[\d.,]*(?:%|[KMB])?\)?$")
_GROUP = re.compile(r"^\d{3}(?:[.,]\d+)?(?:%|[KMB])?\)?$")  # the next thousands group of a number: '000', '080)'
_TAIL = re.compile(r"^\d+(?:%|[KMB])?\)?$")  # the decimals after a word ending in its point: '($3,' '0M)'
_RU_PCT = re.compile(r"^(\d{1,3}(?:[.,]\d+)?)(?:96|0/6|0,6|0/0)$")  # the ru engine's '%': '1096', '390/6', '120,6'
# cells (decisions/098): a strip's lines of text, normalized dark on white, laid out side by side and read again
BAR_SAT, BAR_RUN = 40, 4  # a colored bar: a run of BAR_RUN+ pixels with channels apart by more than BAR_SAT
CELL_STROKE = 32  # px: a column dark down longer than this is a line drawn (a tick), not a glyph's stroke
CELL_MIN_H, CELL_TALL = 5, 48  # px: a line of text is this high (9pt .. a 26pt KPI value)
CELL_ZOOM = 2  # cells are read twice their size, smoothed: nearest-neighbour blocks read worse
CELL_MIN = 8  # a mosaic of fewer cells is laid forwards and backwards up to this many
CELL_ROW_W = 2400  # px of a mosaic line; more cells wrap


# ---- numbers on a picture ------------------------------------------------------------------------------------------
def _fix(text):
    """OCR's 'o' / 'O' for a zero in a word of digits ('$25 ooo' -> '$25 000'), its '0/0' for '%' ('25,10/0',
    a case); trailing ':' / ';' dropped."""
    t = re.sub(r"(?<=\d)[0oO]/[0oO](?=\)?$)", "%", text.strip(":;"))
    if any(c.isdigit() for c in t) or (t and set(t) <= set("oO")):
        t = t.replace("o", "0").replace("O", "0")
    return t


def tokens(words):
    """The number texts of OCR words: a word that is a number, joined with the next words of its line that continue
    it as thousands groups ('$1059' '080' -> '$1059 080') when the gap is under the word's height."""
    out, by_line = [], {}
    for w in words:
        by_line.setdefault(w.line, []).append(w)
    for line in by_line.values():
        line.sort(key=lambda w: w.x)
        i = 0
        while i < len(line):
            text = _fix(line[i].text)
            if not _NUMERIC.match(text):
                i += 1
                continue
            right, j = line[i].x + line[i].w, i + 1
            while j < len(line) and not text.endswith((")", "%", "K", "M", "B")):
                nxt = _fix(line[j].text)
                joins = _TAIL.match(nxt) if text.endswith((",", ".")) else _GROUP.match(nxt)
                if not joins or line[j].x - right > max(line[i].h, line[j].h):
                    break
                text = text + nxt if text.endswith((",", ".")) else f"{text} {nxt}"
                right, j = line[j].x + line[j].w, j + 1
            out.append(text)
            i = j
    return out


def numbers(texts, locale=None):
    """[(value, half step)] of number texts: '($5.8M)' -> (-5 800 000, 50 000); '25.1%' -> (0.251, 0.0005).
    locale: the workbook's (decisions/085), whose marks they are read by: en_US '2,742' is 2742 and '0.179' 0.179."""
    out = []
    for t in texts:
        neg = t.startswith("(") and t.endswith(")")
        body = t.strip("()").lstrip(_SIGNS)
        p = parse_number(body, locale)
        if not p:
            continue
        value, step, suffix, pct = p
        scale = 0.01 if pct else SCALES.get(suffix, 1)
        out.append(((-value if neg else value) * scale, step * scale / 2))
    return out


def drawn(value, read):
    """Is value among the numbers read (at their displayed precision; ▲ / ▼ carry the sign, so its size is enough)?"""
    return any(abs(abs(value) - abs(v)) <= half + 1e-9 * max(1.0, abs(value)) for v, half in read)


# ---- what each sheet must show ------------------------------------------------------------------------------------
def groups(s, values):
    """{group: [numbers]} a number sheet shows, from its expected values (expected.compute)."""
    from . import registry, sparkline
    out = {}

    def add(group, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.setdefault(group, []).append(float(v))
    if s["type"] == "registry":
        skip = set()
        for c in s["columns"]:
            if registry.style(c) == "track":  # its share is in its own column; no label on the segments
                skip.add(registry.label(c))
            if registry.style(c) == "tick":  # the base is the tick, no number
                skip.add(f"{registry.label(c)} · {registry.base_label(c)}")
            if sparkline.is_line(c):  # the last period is a dot, no number (decisions/153)
                skip.add(registry.label(c))
        for row in values.values():
            for col, v in (row.items() if isinstance(row, dict) else []):
                if col not in skip:
                    add(col, v)
    elif s["type"] == "bar":  # values at the bar ends (decisions/087): one group
        for v in values.values():
            for x in (v.values() if isinstance(v, dict) else [v]):
                add("labels", x)
    elif s["type"] == "table":
        for key, v in values.items():
            add(key.split(" | ")[-1], v)
    else:  # kpi: a tile per measure; a card {current, previous, delta}
        for key, v in values.items():
            for x in (v.values() if isinstance(v, dict) else [v]):
                add(key, x)
    return out


@dataclass
class Group:
    sheet: str
    group: str
    status: str
    values: int
    read: int
    ink: float = 0.0  # share of its strips drawn dark; of a mark sheet: share of its zone in the mark colors
    missing: list = field(default_factory=list)  # the first values not read
    kind: str = "numbers"  # numbers | marks (a bar / line / area sheet: values = categories or periods, read = seen)
    note: str = ""


def judge(sheet, group, vals, read, dark, visible, text=False):
    """The Group row of one group: vals its numbers, read [(value, half step)] in its strips, dark their ink share,
    text: lines of text found in them (cells; a narrow '#' column's digits are under INK_MIN of a wide strip)."""
    if not visible:
        return Group(sheet, group, UNCHECKED, len(vals), 0)
    hit = [v for v in vals if drawn(v, read)]
    status = OK if len(hit) == len(vals) else PARTIAL if hit else UNREAD if dark >= INK_MIN or text else FAIL
    return Group(sheet, group, status, len(vals), len(hit), round(dark, 4), [v for v in vals if not drawn(v, read)][:5])


def ink(img):
    """Share of an Image's pixels darker than INK_LUMA."""
    px, n = img.px, img.w * img.h
    return sum(1 for i in range(0, len(px), 3)
               if px[i] * 299 + px[i + 1] * 587 + px[i + 2] * 114 < INK_LUMA * 1000) / n if n else 0.0


# ---- cells: a strip's lines of text laid out on one line (decisions/098) -------------------------------------------
def normalize(img):
    """[luminance] of a strip with its text dark on white: on a colored bar (a run of BAR_RUN or more saturated
    pixels in a row) a pixel is as dark as it is apart from the bar's color (white text on an accent bar -> black,
    dark text on a light pill stays dark); the bar's own end pixels are the bar's."""
    w, px, out = img.w, img.px, []
    for y in range(img.h):
        row = px[y * w * 3:(y + 1) * w * 3]
        lum = [(row[i] * 299 + row[i + 1] * 587 + row[i + 2] * 114) // 1000 for i in range(0, len(row), 3)]
        sat = [max(row[i:i + 3]) - min(row[i:i + 3]) > BAR_SAT for i in range(0, len(row), 3)]
        runs, x = [], 0
        while x < w:
            if sat[x]:
                s = x
                while x < w and sat[x]:
                    x += 1
                if x - s >= BAR_RUN:
                    runs.append((s, x))
            else:
                x += 1
        if runs:
            bar = sorted(lum[i] for a, b in runs for i in range(a, b))[sum(b - a for a, b in runs) // 2]
            span = max(bar, 255 - bar, 1)
            lo, hi = runs[0][0], runs[-1][1]
            for x in range(lo + 1, hi - 1):
                lum[x] = 255 - min(255, abs(lum[x] - bar) * 255 // span)
            lum[lo] = lum[hi - 1] = 255
        out.extend(lum)
    return out


def cells(gray, w, h):
    """[(x, y, w, h)] of the lines of text in a normalized strip (whitened where a column is dark down more than
    CELL_STROKE px: a registry's tick, a rule): runs of rows with a pixel darker than INK_LUMA (a row's gap of one
    inside a line), each cut to its dark columns; slivers and blocks taller than CELL_TALL are not text."""
    for x in range(w):
        y = 0
        while y < h:
            if gray[y * w + x] < INK_LUMA:
                top = y
                while y < h and gray[y * w + x] < INK_LUMA:
                    y += 1
                if y - top > CELL_STROKE:
                    for r in range(top, y):
                        gray[r * w + x] = 255
            y += 1
    dark = [any(v < INK_LUMA for v in gray[y * w:(y + 1) * w]) for y in range(h)]
    out, y = [], 0
    while y < h:
        if not dark[y]:
            y += 1
            continue
        top = y
        while y < h and (dark[y] or (y + 1 < h and dark[y + 1])):
            y += 1
        xs = [x for x in range(w) if any(gray[r * w + x] < INK_LUMA for r in range(top, y))]
        if CELL_MIN_H <= y - top <= CELL_TALL and xs[-1] - xs[0] >= 2:
            out.append((xs[0], top, xs[-1] + 1 - xs[0], y - top))
    return out


def _upscale(gray, w, h, box, k, m=2):
    """(w, h, [luminance]) of a box of a gray picture with a margin of m, k times its size, bilinear."""
    x0, y0 = max(0, box[0] - m), max(0, box[1] - m)
    x1, y1 = min(w, box[0] + box[2] + m), min(h, box[1] + box[3] + m)
    bw, bh = x1 - x0, y1 - y0

    def taps(n):  # (a, b, t) per output pixel along an axis of n source pixels
        out = []
        for i in range(n * k):
            f = min(max(0.0, (i + 0.5) / k - 0.5), n - 1)
            out.append((int(f), min(int(f) + 1, n - 1), f - int(f)))
        return out
    xt, out = taps(bw), []
    for ya, yb, ty in taps(bh):
        ra, rb = gray[(y0 + ya) * w + x0:(y0 + ya) * w + x1], gray[(y0 + yb) * w + x0:(y0 + yb) * w + x1]
        row = [ra[a] * (1 - ty) + rb[a] * ty for a in range(bw)]
        nxt = row[1:] + row[-1:]
        out += [int(row[a] + (nxt[a] - row[a]) * tx) for a, _, tx in xt]
    return bw * k, bh * k, out


def mosaic(img):
    """An Image of a strip's cells side by side, CELL_ZOOM times their size, a dash between them; None without text.
    Windows' OCR drops a lone '1' and a short '39%' in a column, reads them in a line (decisions/098). Fewer than
    CELL_MIN cells are laid as they come and backwards, again, up to CELL_MIN: a line of two '1' '2' is not read,
    of eight is. Lines of CELL_ROW_W px at most."""
    gray = normalize(img)
    boxes = cells(gray, img.w, img.h)
    if not boxes:
        return None
    pieces = [_upscale(gray, img.w, img.h, b, CELL_ZOOM) for b in boxes]
    if len(pieces) < CELL_MIN:
        two = pieces + pieces[::-1]
        pieces = two * -(-CELL_MIN // len(two))
    ph = max(p[1] for p in pieces)
    gap, dash, thick, m = int(ph * 0.4), max(2, int(ph * 0.5)), CELL_ZOOM, 20
    rows, row, x = [], [], 0
    for p in pieces:
        if row and x + p[0] > CELL_ROW_W:
            rows.append(row)
            row, x = [], 0
        row.append(p)
        x += p[0] + 2 * gap + dash
    rows.append(row)
    W = max(sum(p[0] for p in r) + (len(r) - 1) * (2 * gap + dash) for r in rows) + 2 * m
    H = len(rows) * ph * 2 + 2 * m
    canvas = bytearray(b"\xff" * (W * H))
    for n, r in enumerate(rows):
        base, x = m + n * ph * 2 + ph, m  # bottoms on one line
        for k, (pw, hh, g) in enumerate(r):
            for j in range(hh):
                at = (base - hh + j) * W + x
                canvas[at:at + pw] = bytes(g[j * pw:(j + 1) * pw])
            x += pw
            if k < len(r) - 1:
                for j in range(base - ph // 2 + ph // 10, base - ph // 2 + ph // 10 + thick):
                    canvas[j * W + x + gap:j * W + x + gap + dash] = bytes(dash)
                x += 2 * gap + dash
    rgb = bytearray(W * H * 3)
    rgb[0::3] = rgb[1::3] = rgb[2::3] = canvas
    return shots.Image(W, H, bytes(rgb))


def cell_words(words, ru=False):
    """Words read off a mosaic: a word over a dash split, its parts on lines of their own ('1-2' -> '1', '2'); the
    ru engine's '%' read as '96' / '0/6' / '0,6' ('1096' for '10%') also taken as a percent, on a line of its own.
    Words of one cell keep their line: '47' '811' join; the dash keeps cells apart (a gap over a word's height)."""
    from .ocr import Word
    out = []
    for w in words:
        parts = [p for p in re.split(r"[-–—]+", w.text) if p]
        for part in parts:
            out.append(w if len(parts) == 1 and part == w.text else Word(part, w.x, w.y, w.w, w.h, -1 - len(out)))
            m = _RU_PCT.match(_fix(part)) if ru else None
            if m:
                out.append(Word(m.group(1) + "%", w.x, w.y, w.w, w.h, -1 - len(out)))
    return out


# ---- marks: bars, lines, areas (decisions/078) ----------------------------------------------------------------------
def mark_count(s, values):
    """How many marks a bar / line / area sheet must show from its expected values (expected.compute): a bar per
    category with a value other than 0 (a stack's segments, a plan's two measures are one category), a period per
    point of a line or an area with a value."""
    def num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    seen = set()
    for key, v in values.items():
        vs = list(v.values()) if isinstance(v, dict) else [v]
        if any(num(x) and (x != 0 or s["type"] != "bar") for x in vs):
            seen.add(str(key).split(" | ")[0])
    return len(seen)


def _rgb(hexa):
    h = hexa.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mark_colors(book, sheet):
    """The colors a sheet's marks are drawn in, per its panes: the palette of its color field (the datasource's
    <map to>; Tableau 10 without one), else its mark-color, else Desktop's default. None for a continuous color
    (a ramp: no exact color to look for)."""
    root = shots._twb_root(book)
    ws = next((w for w in root.iterfind("./worksheets/worksheet") if w.get("name") == sheet), None)
    if ws is None:
        return None
    maps = {}
    for enc in root.iterfind("./datasources/datasource/style/style-rule[@element='mark']/encoding[@attr='color']"):
        maps.setdefault(enc.get("field"), []).extend(m.get("to") for m in enc.iterfind("map"))
    table_color = ws.find("./table/style/style-rule[@element='mark']/format[@attr='mark-color']")
    out = []
    for pane in ws.iterfind("./table/panes/pane"):
        enc = pane.find("./encodings/color")
        if enc is not None:
            col = enc.get("column", "")
            ref = "[" + col.rsplit("].[", 1)[-1] if "].[" in col else col
            if ref.endswith(":qk]"):
                return None
            out += maps.get(ref) or list(TABLEAU10)
        else:
            mc = pane.find("./style/style-rule[@element='mark']/format[@attr='mark-color']")
            mc = mc if mc is not None else table_color
            out.append(mc.get("value") if mc is not None else DEFAULT_MARK)
    return sorted({c.lower() for c in out if c and re.fullmatch(r"#[0-9a-fA-F]{6}", c)})


def of_color(p, colors, bg, tol=MARK_TOL):
    """Is pixel p one of colors over bg, laid at an opacity of MARK_ALPHA or more (each channel within tol)? Desktop
    draws an area at ~62% (ITSM, golden: #4e79a7 over white is #92adc8) and a line's sloped stretches anti-aliased."""
    for c in colors:
        d = [c[k] - bg[k] for k in range(3)]
        n = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if not n:
            continue
        a = min(1.0, sum((p[k] - bg[k]) * d[k] for k in range(3)) / n)
        if a >= MARK_ALPHA and all(abs(p[k] - bg[k] - a * d[k]) <= tol for k in range(3)):
            return True
    return False


def mark_mask(img, colors, bg=(255, 255, 255), tol=MARK_TOL):
    """bytearray w x h: 1 where the pixel is of one of colors (of_color)."""
    rgb, seen, px = [_rgb(c) for c in colors], {}, img.px
    out = bytearray(img.w * img.h)
    for j, i in enumerate(range(0, len(px), 3)):
        k = px[i:i + 3]
        hit = seen.get(k)
        if hit is None:
            hit = seen[k] = of_color(k, rgb, bg, tol)
        out[j] = hit
    return out


def _runs(counts, least):
    """Number of runs of consecutive entries >= least."""
    n, inside = 0, False
    for c in counts:
        if c >= least and not inside:
            n += 1
        inside = c >= least
    return n


def frame_color(img):
    """The zone's background: the commonest color of its outer rows and columns. Not of the whole zone: thick bars
    can cover most of it (golden_multi_source Orders by Region, 4 bars of 75 px in 400: blue read as the background)."""
    counts = {}
    for x in range(img.w):
        for y in (0, img.h - 1):
            c = img.pixel(x, y)
            counts[c] = counts.get(c, 0) + 1
    for y in range(img.h):
        for x in (0, img.w - 1):
            c = img.pixel(x, y)
            counts[c] = counts.get(c, 0) + 1
    return max(counts, key=counts.get)


def look(img, colors, horizontal=True):
    """What a mark sheet's zone shows -> {visible: colors seen apart from the background, solid: 2 x 2 blocks of
    them, share: of the zone, bars: runs of rows (horizontal) / columns with BAR_MIN solid pixels, cover: share of
    columns from the first to the last with any of them (a line, an area)}."""
    bg = frame_color(img)
    visible = [c for c in colors if max(abs(a - b) for a, b in zip(_rgb(c), bg)) >= SEEN_MIN]
    w, h = img.w, img.h
    m = mark_mask(img, visible, bg) if visible else bytearray(w * h)
    solid = bytearray(w * h)
    for y in range(h - 1):
        i = y * w
        for x in range(w - 1):
            if m[i + x] and m[i + x + 1] and m[i + x + w] and m[i + x + w + 1]:
                solid[i + x] = 1
    if horizontal:
        across = [sum(solid[y * w:(y + 1) * w]) for y in range(h)]
    else:
        across = [sum(solid[x::w]) for x in range(w)]
    cols = [any(m[x::w]) for x in range(w)]
    on = [x for x in range(w) if any(solid[x::w])]  # the span: solid columns (text's colored fringes are specks)
    cover = sum(cols[on[0]:on[-1] + 1]) / (on[-1] - on[0] + 1) if on else 0.0
    px = img.px
    blank = all(max(abs(a - b) for a, b in zip(k, bg)) < SEEN_MIN
                for k in {px[i:i + 3] for i in range(0, len(px), 3)})  # no axis, no label either (decisions/100)
    return {"visible": visible, "solid": sum(solid), "share": sum(m) / (w * h) if w * h else 0.0,
            "bars": _runs(across, BAR_MIN), "cover": cover, "blank": blank}


def judge_marks(sheet, kind, want, seen, visible=True):
    """The Group row of a mark sheet: want marks expected (mark_count), seen = look(...) of its zone."""
    group = {"bar": "bars"}.get(kind, kind)
    if not visible:
        return Group(sheet, group, UNCHECKED, want, 0, kind="marks", note="not wholly on screen")
    if seen is None:
        return Group(sheet, group, UNCHECKED, want, 0, kind="marks", note="continuous colors: no exact mark color")
    share = round(seen["share"], 4)
    if not seen["visible"]:
        return Group(sheet, group, FAIL, want, 0, share, kind="marks", note="marks in the background's color")
    if seen["solid"] < MARK_MIN:  # a zone Desktop left wholly blank: no rows, or the view did not fit it (decisions/100)
        note = "zone drawn blank: no marks, no axes (no data, or too small for the view)" if seen.get("blank") else "no marks in their colors"
        return Group(sheet, group, FAIL, want, 0, share, kind="marks", note=note)
    if kind in DOT_SHEETS:
        return Group(sheet, group, OK, want, want, share, kind="marks")
    if kind == "bar":
        n = seen["bars"]
        ok = abs(n - want) <= max(1, want // 5)
        return Group(sheet, group, OK if ok else PARTIAL, want, n, share, kind="marks",
                     note="" if ok else f"{n} bar(s) seen for {want} categories")
    ok = seen["cover"] >= LINE_COVER or want < 2
    return Group(sheet, group, OK if ok else PARTIAL, want, want if ok else round(want * seen["cover"]), share,
                 kind="marks", note="" if ok else f"drawn over {seen['cover']:.0%} of its span")


# ---- the book ---------------------------------------------------------------------------------------------------------
def activate(book, dashboard, out):
    """A copy of the book that opens on this dashboard (the maximized window, decisions/022, 040)."""
    import zipfile
    with zipfile.ZipFile(book) as z:
        items = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in items if n.lower().endswith(".twb"))
    x = items[twb].decode("utf-8")
    x = re.sub(r"""\s+maximized=(['"])true\1""", "", x)
    x, n = re.subn(r"""(<window class=(['"])dashboard\2)(?=[^>]*\sname=(['"])""" + re.escape(dashboard) + r"""\3)""",
                   r'\1 maximized="true"', x, count=1)
    if n != 1:
        raise RuntimeError(f"{Path(book).name}: no dashboard window {dashboard!r}")
    x = re.sub(r"""<active id=(['"])\d+\1""", '<active id="-1"', x)  # a zone selected in a saved book: its frame (decisions/168)
    items[twb] = x.encode("utf-8")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in items.items():
            z.writestr(name, data)
    return Path(out)


def sheet_zones(book, dashboard):
    """{worksheet: (x, y, w, h) px in the dashboard} of the sheets the dashboard shows; a zone hidden by a switch
    (hidden-by-user on it or a container above it) is left out."""
    root = shots._twb_root(book)
    d = next(x for x in root.iterfind("./dashboards/dashboard") if x.get("name") == dashboard)
    size = d.find("size")
    w, h = int(size.get("maxwidth")), int(size.get("maxheight"))
    out = {}
    for z in d.iter("zone"):
        if z.get("type-v2") is None and z.get("name") and not any(
                a.get("hidden-by-user") == "true" for a in [z, *z.iterancestors("zone")]):
            out[z.get("name")] = _px([int(z.get(k, 0)) for k in ("x", "y", "w", "h")], w, h)
    return out


def _px(box, w, h):
    return (round(box[0] * w / 100000), round(box[1] * h / 100000), round(box[2] * w / 100000),
            round(box[3] * h / 100000))


def column_strips(book, dashboard, zone):
    """{column title: (x, y, w, h) px} of a registry zone: each title zone that stands right on the sheet (its bottom
    at the sheet's top, decisions/064) gives its column's strip, the sheet's height below it."""
    root = shots._twb_root(book)
    d = next(x for x in root.iterfind("./dashboards/dashboard") if x.get("name") == dashboard)
    size = d.find("size")
    w, h = int(size.get("maxwidth")), int(size.get("maxheight"))
    sheet = next(z for z in d.iter("zone") if z.get("name") == zone and z.get("type-v2") is None)
    sx, sy, sw, sh = (int(sheet.get(k, 0)) for k in ("x", "y", "w", "h"))
    out = {}
    for z in d.iter("zone"):  # not the titles of a registry a switch hides over this one (decisions/082)
        if z.get("type-v2") != "text" or any(a.get("hidden-by-user") == "true" for a in [z, *z.iterancestors("zone")]):
            continue
        x, y, zw, zh = (int(z.get(k, 0)) for k in ("x", "y", "w", "h"))
        if abs(y + zh - sy) <= 2 and sx <= x and x + zw <= sx + sw + 2:
            text = " ".join("".join(r.text or "" for r in z.iter("run")).split())
            out[text] = _px((x, sy, zw, sh), w, h)
    return out


def capture(book, dashboard, out_dir):
    """(picture, dashboard box (x, y, w, seen h) in it) of the book opened on this dashboard in Desktop: the dashboard
    itself, a tall one scrolled and stitched (screenshot.capture_dashboard, decisions/078)."""
    from . import desktop_check as dc
    copy = activate(book, dashboard, Path(out_dir) / f"{_safe(dashboard)}.twbx")
    _, w, h, _ = shots.dashboard_info(copy, dashboard)
    got = {}
    r = dc.check(copy, on_loaded=lambda pid: got.setdefault("shots", shots.capture_dashboard(pid, w, h)))
    if r.status != dc.OK:
        raise RuntimeError(f"Desktop {r.status} on dashboard {dashboard!r}: {r.message}")
    win, dash = got["shots"]
    shots.save_png(win, Path(out_dir) / f"{_safe(dashboard)}.window.png")
    shots.save_png(dash, Path(out_dir) / f"{_safe(dashboard)}.png")
    return dash, (0, 0, dash.w, dash.h)


def _safe(name):
    return re.sub(r"[^\w.-]+", "_", name)


def check(book, spec_path, out_dir, capture_fn=capture, ocr_fn=None):
    """-> report {ok, groups [Group as dict], dashboards}; written to out_dir/drawn.json with the cut-out strips."""
    from . import barlabels, expected, formats, nav, ocr, registry, spec as spec_mod
    ocr_fn = ocr_fn or ocr.words
    spec_path, out = Path(spec_path), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    spec = spec_mod.load(spec_path)
    # numbers are read by the marks of the book's own locale (decisions/085); a book without one is drawn in the
    # viewer's: its marks are guessed from the text, as on an HTML page
    locale = shots._twb_root(book).get("locale")
    locale = locale if locale in formats.LOCALES else None
    values = expected.compute(spec, expected.data_path(spec, spec_path.parent))  # by source (decisions/083)
    every = registry.expand(nav.primary(spec))["sheets"]
    sheets = {s["name"]: s for s in every if s["type"] in NUMBER_SHEETS or barlabels.mode(s) == "end"}
    wanted = {n: groups(s, values.get(n, {})) for n, s in sheets.items()}
    marked = {s["name"]: s for s in every if s["type"] in MARK_SHEETS + DOT_SHEETS
              and isinstance(values.get(s["name"]), dict) and mark_count(s, values[s["name"]])}
    looked = {}  # mark sheet -> look(...) of its zone, or None (no exact color)
    dashboards = [d["name"] for d in spec.get("dashboards") or [spec["dashboard"]]]
    strips = {}  # (sheet, group) -> [(picture base path, ink)]
    for dname in dashboards:
        win, (dx, dy, _, vis_h) = capture_fn(book, dname, out)
        boxes = sheet_zones(book, dname)
        for name, s in marked.items():
            box = boxes.get(name)
            if name in looked or box is None or box[1] + box[3] > vis_h or box[2] <= 0 or box[3] <= 0:
                continue  # not here, read on an earlier dashboard, or not wholly on screen
            pic = shots.crop(win, (dx + box[0], dy + box[1], box[2], box[3]))
            shots.save_png(pic, out / f"{_safe(dname)}.{_safe(name)}.marks.png")
            colors = mark_colors(book, name)
            looked[name] = None if colors is None else look(
                pic, colors, s["type"] != "bar" or s.get("orientation", "horizontal") == "horizontal")
        zones = {}  # spec sheet -> its zones on this dashboard
        for zone, box in boxes.items():
            sheet = next((n for n in sheets if zone == n or zone.startswith(n + " · ")), None)
            if sheet is not None and not any(k[0] == sheet for k in strips):  # not read on an earlier dashboard
                zones.setdefault(sheet, []).append((zone, box))
        for sheet, parts in zones.items():
            if any(zy + zh > vis_h or zw <= 0 or zh <= 0 for _, (_, zy, zw, zh) in parts):
                continue  # a zone not wholly on screen: read where it is, else unchecked
            cols = column_strips(book, dname, parts[0][0]) if sheets[sheet]["type"] == "registry" else {}
            for g in wanted[sheet]:
                boxes = [cols[g]] if g in cols else [box for _, box in parts]
                for i, (zx, zy, zw, zh) in enumerate(boxes):
                    pic = shots.crop(win, (dx + zx, dy + zy, zw, zh))
                    base = f"{out / _safe(dname)}.{_safe(sheet)}.{_safe(g)}.{i}"
                    for zoom in ZOOMS:
                        shots.save_png(shots.resize(pic, zw * zoom, zh * zoom) if zoom != 1 else pic,
                                       Path(f"{base}.x{zoom}.png"))
                    mos = mosaic(pic)
                    if mos is not None:
                        shots.save_png(mos, Path(f"{base}.cells.png"))
                    strips.setdefault((sheet, g), []).append((base, ink(pic), mos is not None))
    pics = [Path(f"{base}.x{z}.png") for v in strips.values() for base, _, _ in v for z in ZOOMS]
    mosaics = [Path(f"{base}.cells.png") for v in strips.values() for base, _, text in v if text]
    read_words = ocr_fn(pics + mosaics)
    try:  # the ru engine reads the '1' of '10%' the en one drops; optional
        ru_words = ocr_fn(mosaics, lang="ru") if mosaics else {}
    except RuntimeError:
        ru_words = {}
    rows = []
    for name in sheets:
        for g, vals in wanted[name].items():
            got = strips.get((name, g), [])
            texts = [t for base, _, _ in got for z in ZOOMS
                     for t in tokens(read_words.get(str(Path(f"{base}.x{z}.png").resolve()), []))]
            for base, _, text in got:
                key = str(Path(f"{base}.cells.png").resolve())
                if text:
                    texts += tokens(cell_words(read_words.get(key, []))) + tokens(
                        cell_words(ru_words.get(key, []), ru=True))
            rows.append(judge(name, g, vals, numbers(texts, locale), max((i for _, i, _ in got), default=0.0), bool(got),
                              any(t for _, _, t in got)))
    for name, s in marked.items():
        rows.append(judge_marks(name, s["type"], mark_count(s, values[name]), looked.get(name), name in looked))
    report ={"book": str(book), "dashboards": dashboards, "ok": not any(g.status == FAIL for g in rows),
              "groups": [asdict(g) for g in rows]}
    (out / "drawn.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def summary(report):
    """One line: the FAIL groups first, else the counts."""
    gs = report["groups"]
    fails = [g for g in gs if g["status"] == FAIL]
    if fails:
        return "; ".join(f"{g['sheet']} / {g['group']}: " + (
            f"{g.get('note')} ({g['values']} expected)" if g.get("kind") == "marks"
            else f"none of {g['values']} value(s) drawn") for g in fails[:8])
    count = {k: sum(g["status"] == k for g in gs) for k in (OK, PARTIAL, UNREAD, UNCHECKED)}
    nums = [g for g in gs if g.get("kind", "numbers") == "numbers"]
    read, total = sum(g["read"] for g in nums), sum(g["values"] for g in nums if g["status"] != UNCHECKED)
    marks = [g for g in gs if g.get("kind") == "marks"]
    tail = f"; mark sheets {sum(g['status'] == OK for g in marks)} of {len(marks)} OK" if marks else ""
    return (f"groups {count[OK]} OK, {count[PARTIAL]} partial, {count[UNREAD]} unread, {count[UNCHECKED]} unchecked; "
            f"{read} of {total} values read on screen{tail}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tbuilder check-drawn", description=__doc__.split("\n")[0])
    ap.add_argument("book", type=Path)
    ap.add_argument("spec", type=Path)
    ap.add_argument("-d", "--dir", type=Path, help="pictures and drawn.json (default out/drawn_<book>)")
    a = ap.parse_args(argv)
    out = a.dir or Path("out") / f"drawn_{a.book.stem}"
    if out.exists():
        shutil.rmtree(out)
    r = check(a.book, a.spec, out)
    for g in r["groups"]:
        miss = f"  missing {g['missing']}" if g["status"] in (FAIL, PARTIAL, UNREAD) and g["missing"] else ""
        miss += f"  {g['note']}" if g["note"] else ""
        print(f"{g['status']:<9} {g['read']:>3}/{g['values']:<3} {g['sheet']} / {g['group']}{miss}")
    print(("OK: " if r["ok"] else "FAIL: ") + summary(r))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
