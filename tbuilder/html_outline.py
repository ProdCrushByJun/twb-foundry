"""HTML dashboard -> outline (deterministic): render in headless Chrome, collect blocks with boxes.

The outline is the factual input for the HTML->spec step: what is on the page and where.
Deciding what each block *means* (which CSV field, which chart type) is the procedure's job.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from lxml import html as lhtml

from .match import parse_number, unit_suffix

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
JS = (Path(__file__).parent / "outline.js").read_text(encoding="utf-8")
# Before the page's own scripts: remember every element given a 'click' listener (outline.js collectClicks,
# decisions/174). The DOM keeps no list of listeners, and jQuery / d3 .on('click') end in addEventListener.
CLICK_HOOK = ("<script>(()=>{const add=EventTarget.prototype.addEventListener;"
              "EventTarget.prototype.addEventListener=function(t,f,o){if(t==='click'){"
              "(window.__tbClicks=window.__tbClicks||new Set()).add(this)}return add.call(this,t,f,o)}})();</script>")


def _chrome():
    for p in CHROME_CANDIDATES:
        if Path(p).is_file():
            return p
    raise RuntimeError("Chrome not found; set CHROME_CANDIDATES")


def style_profile(raw):
    """The profile a mock was drawn in: the first line of the `tb profile-css` block in its page (decisions/195)."""
    m = re.search(r"/\*\s*tb profile-css ([\w-]+)\s*\*/", raw)
    return m.group(1) if m else None


def _instrumented_copy(html_path, tmp):
    src = Path(html_path).resolve()
    raw = src.read_text(encoding="utf-8", errors="replace")
    base = f'<base href="{src.parent.as_uri()}/">'
    hook = f"<script>window.addEventListener('load',()=>setTimeout(()=>{{{JS}}},400));</script>"
    low = raw.lower()
    i = low.find("<head>")
    raw = raw[: i + 6] + base + CLICK_HOOK + raw[i + 6:] if i >= 0 else base + CLICK_HOOK + raw
    j = raw.lower().rfind("</body>")
    raw = raw[:j] + hook + raw[j:] if j >= 0 else raw + hook
    copy = Path(tmp) / "page.html"
    copy.write_text(raw, encoding="utf-8")
    return copy


def _run_chrome(args, timeout=60):
    cmd = [_chrome(), "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
           "--virtual-time-budget=12000", *args]
    return subprocess.run(cmd, capture_output=True, timeout=timeout, encoding="utf-8", errors="replace")


def _inside(inner, outer, slack=2):
    x, y, w, h = inner
    X, Y, W, H = outer
    return x >= X - slack and y >= Y - slack and x + w <= X + W + slack and y + h <= Y + H + slack


def _wraps_visual(block, visuals):
    """A bars block that holds a chart / table / list is a wrapper of visuals, not bars (decisions/108)."""
    return any(_inside(v["box"], block["box"]) for v in visuals)


def _nearest_heading(b, headings):
    """Closest heading above the block that overlaps it horizontally (or sits inside it at the top)."""
    x, y, w, h = b
    best, dist = None, 10 ** 9
    for hd in headings:
        hx, hy, hw, hh = hd["box"]
        overlap = min(x + w, hx + hw) - max(x, hx)
        if overlap <= 0:
            continue
        gap = y - (hy + hh)
        if -h < gap < 160 and abs(gap) < dist and hy <= y + 4:
            best, dist = hd["text"], abs(gap)
    return best


def _split(blocks, axis):
    """Split blocks into bands separated by empty gaps along axis (0 = x/columns, 1 = y/rows)."""
    bands, end = [], float("-inf")
    for b in sorted(blocks, key=lambda b: b["box"][axis]):
        start, size = b["box"][axis], b["box"][axis + 2]
        if start >= end:
            bands.append([])
        bands[-1].append(b)
        end = max(end, start + size)
    return bands


def _layout(blocks):
    """Recursive XY-cut -> {"rows"|"cols": [...]} tree with block ids as leaves (maps to Tableau containers)."""
    if len(blocks) == 1:
        return blocks[0]["id"]
    for axis, kind in ((1, "rows"), (0, "cols")):
        bands = _split(blocks, axis)
        if len(bands) > 1:
            return {kind: [_layout(band) for band in bands]}
    return {"overlap": [b["id"] for b in blocks]}  # cannot be separated: blocks overlap


def locale(lang):
    """<html lang> -> the workbook's locale (decisions/085): 'ru', 'ru-RU' -> ru_RU; anything else, none -> en_US."""
    return "ru_RU" if lang.strip().lower().split("-")[0].split("_")[0] == "ru" else "en_US"


_YEARISH = re.compile(r"^(19|20)\d\d(\s*[-–—]\s*(19|20)\d\d)?$")


def _real_slicers(controls, blocks):
    """Static slicers (decisions/112) minus what only looks like one: a KPI card (caption + number) or a caption with
    a value that is a figure; the rest is decided against the data columns in match.match."""
    def figure(v):
        return bool(parse_number(v)) and not _YEARISH.match(v.strip())
    return [c for c in controls if c["kind"] != "slicer"
            or not (any(figure(o) for o in c["options"]) or any(_inside(b["box"], c["box"]) for b in blocks))]


def _series_colors(raw):
    """Legends read from the page (decisions/133): swatches of one container and size, two of them in a row or a
    column, with distinct captions and colors; plus the colors a canvas chart (ECharts, Chart.js) was given by series
    name. Each -> {source, series: {name: '#RRGGBB'}}; the data decides which column the names are values of (match)."""
    near = lambda a, b: abs(a - b) <= 3
    out, groups = [], {}
    for sw in raw.get("swatches", []):
        size = (None, None) if sw["where"] == "text" else (round(sw["box"][2] / 2), round(sw["box"][3] / 2))  # words differ in width
        groups.setdefault((sw["where"], sw.get("group")) + size, []).append(sw)
    for (where, _, _, _), items in groups.items():
        aligned = any(near(a["box"][1], b["box"][1]) or near(a["box"][0], b["box"][0])
                      for i, a in enumerate(items) for b in items[i + 1:])
        series = {}
        for sw in items:
            series.setdefault(sw["name"], sw["color"])
        if aligned and len(series) >= 2 and len(set(series.values())) >= 2:
            out.append({"source": where if where in ("html", "text") else "svg", "series": series, "box": items[0]["box"]})
    for ch in raw.get("charts", []):
        if len(ch.get("colors") or {}) >= 2:
            out.append({"source": ch.get("lib", "canvas"), "series": ch["colors"], "heading": ch.get("heading", "")})
    return out


def _paints(raw):
    """Colors of the marks themselves (decisions/135): a single series' color and a color-by-measure scale. The same
    paint read from a library and from its svg is kept once (the library's)."""
    out, seen = [], set()
    for p in sorted(raw.get("paints", []), key=lambda p: p["source"] in ("svg", "css")):
        key = (p["kind"], p.get("color") or tuple(p.get("colors", [])[:1]), p.get("heading", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _clicks(raw, blocks):
    """Click groups of outline.js with the block each one sits in (by the center of its elements' union box)."""
    out = []
    for g in (raw.get("clicks") or {}).get("groups", []):
        bx = g.pop("boxes", []) or [[0, 0, 0, 0]]
        x0, y0 = min(b[0] for b in bx), min(b[1] for b in bx)
        x1, y1 = max(b[0] + b[2] for b in bx), max(b[1] + b[3] for b in bx)
        c = ((x0 + x1) / 2, (y0 + y1) / 2, 0, 0)
        block = next((b["id"] for b in sorted(blocks, key=lambda b: b["box"][2] * b["box"][3])
                      if _inside(c, b["box"])), None)
        out.append({**g, "box": [x0, y0, x1 - x0, y1 - y0], "block": block})
    return out


def data_clicks(outline):
    """Clicks on the data (not on a button, tab, link or form field): what dashboard.actions carry (decisions/174)."""
    return [g for g in outline.get("clicks", []) if not g.get("control")]


def build_outline(raw):
    """Turn the raw JS dump into blocks the procedure reasons about."""
    visuals = ([("svg", s) for s in raw["svgs"]] + [("canvas", c) for c in raw["canvases"]]
               + [("bars", g) for g in raw["bar_groups"]] + [("table", t) for t in raw["tables"]]
               + [("list", l) for l in raw["lists"]] + [("image", i) for i in raw["images"]])
    held = [v for kind, v in visuals if kind in ("svg", "canvas", "table", "list", "image")]
    visuals = [(k, v) for k, v in visuals if not (k == "bars" and _wraps_visual(v, held))]
    blocks = []
    for kind, v in visuals:
        if any(kind2 != "table" and _inside(v["box"], o["box"]) and v is not o for kind2, o in visuals
               if kind != "table" and (o["box"][2] * o["box"][3]) > (v["box"][2] * v["box"][3])):
            continue  # nested inside a bigger chart block
        blocks.append({"kind": kind, **v})
    kpis = [n for n in raw["numbers"] if not any(_inside(n["box"], b["box"]) for b in blocks)]
    for n in kpis:  # '40.2 h': the number and its unit (decisions/090)
        unit = unit_suffix(n["text"])
        blocks.append({"kind": "kpi", **n, **({"unit": unit} if unit else {})})
    for i, b in enumerate(blocks):
        b["id"] = f"b{i + 1}"
        b["heading"] = _nearest_heading(b["box"], raw["headings"])
    return {
        "title": raw["title"],
        "lang": raw.get("lang", ""),
        "locale": locale(raw.get("lang", "")),  # the spec's "locale" (decisions/085)
        "page": raw["page"],
        "palette": raw["palette"],
        "fonts": raw["fonts"],
        "headings": [h["text"] for h in sorted(raw["headings"], key=lambda h: (h["box"][1], h["box"][0]))],
        "blocks": blocks,
        "layout": _layout(blocks) if blocks else None,
        "controls": _real_slicers(raw["controls"], blocks),
        "texts": raw.get("texts", []),  # every visible text with a digit (tbuilder/reconcile.py)
        "canvases": raw["canvases"],  # each with data: its chart's numbers were read (decisions/058)
        "svg_labels": raw.get("svg_labels", []),  # every svg <text> with its box (decisions/127)
        "grid_labels": raw.get("grid_labels", []),  # the labels of each html grid with their boxes (decisions/200)
        "lines": raw.get("lines", []),  # svg polylines + the gridlines of their svg (decisions/123)
        "paints": _paints(raw),  # single-series colors and color scales (decisions/135)
        "series_colors": _series_colors(raw),  # legends / chart series colors (decisions/133)
        "charts": raw.get("charts", []),  # the numbers of canvas charts, from the chart's data
        "clicks": _clicks(raw, blocks),  # elements with a click handler, by block (decisions/174)
        "clicks_delegated": (raw.get("clicks") or {}).get("delegated", False),  # one handler on the document
        "states": raw.get("states", []),  # the page after each other option of a control (decisions/058)
        "states_skipped": raw.get("states_skipped", 0),
    }


def outline(html_path, screenshot=None, width=1600, height=1000):
    with tempfile.TemporaryDirectory() as tmp:
        copy = _instrumented_copy(html_path, tmp)
        res = _run_chrome([f"--window-size={width},{height}", "--dump-dom", copy.as_uri()])
        node = lhtml.fromstring(res.stdout or "<html/>").find(".//script[@id='tb-outline']")
        if node is None:
            raise RuntimeError(f"outline script did not run for {html_path}: {res.stderr[-400:]}")
        raw = json.loads(node.text)
        if screenshot:
            pw, ph = raw["page"]
            Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
            _run_chrome([f"--window-size={max(pw, 400)},{min(max(ph, 300), 6000)}",
                         f"--screenshot={Path(screenshot).resolve()}", Path(html_path).resolve().as_uri()])
    o = build_outline(raw)
    o["profile"] = style_profile(Path(html_path).read_text(encoding="utf-8", errors="replace"))
    return o
