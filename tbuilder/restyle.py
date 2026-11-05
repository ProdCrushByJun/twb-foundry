"""Restyle a workbook someone else made (todo 6.1, decisions/049): the project's design system on its style XML only.

  python -m tbuilder restyle <in.twbx|.twb> -o <out.twbx> [--theme cards|flat]

What changes (design.py tokens, context/design-rules.md, decisions 008, 012, 018, 030), and only in style XML:
- font: the workbook font Arial (style-rule element="all", theme.workbook_style's form); Tableau's own text families
  are taken off runs and worksheet style-rules so the text inherits it, their weight kept as bold;
- data-ink (decisions/008): the declutter rules of build.DECLUTTER merged into every worksheet's style: no
  gridlines, zero lines, axis rulers and ticks, row banding, table dividers;
- titles: a worksheet's own title on the block scale (14 bold, 12 in the card theme; lines after the first are the
  9pt muted subtitle), a dashboard text whose largest run is 16pt or more on the dashboard scale (24 / 10, theme
  20 / 11); dark title text in the token text color, light text (on a dark band) kept;
- colors: a pane's single mark color snapped to the tokens: greys to the nearest grey token, colors to the
  nearest of accent / good / bad; dark grey text to the grey text tokens;
- borders: none on sheet and text zones (a flat page, as the generator draws with theme flat);
- theme cards, the default (decisions/030, 168; --theme flat leaves no cards): the dashboard on the canvas, every sheet zone a card face (1px card_border,
  card_bg, padding card_padding).

What never changes: everything else. The output's XML differs from the input only inside style nodes (STYLE_TAGS
outside the datasources) and in the font attributes of runs (RUN_FONT); invariant() proves it, and the datasources
are compared byte for byte. The edit is a byte splice of the original file: untouched XML keeps its exact bytes.
"""
import colorsys
import copy
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import xml.parsers.expat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import design
from .build import DECLUTTER
from .design import COLOR, FONT, SPACE

CARDS = "cards"
FLAT = "flat"
THEMES = (CARDS, FLAT)
FONT_FAMILY = "Arial"  # theme.FONTS: web-safe only
STYLE_TAGS = ("style", "zone-style")
RUN_FONT = ("fontname", "fontsize", "fontcolor", "bold")
# Text families restyle takes off: Tableau's own and the common web text fonts. Anything else (icon fonts, a brand
# font) stays where its author put it.
TEXT_FAMILIES = re.compile(r"^(Tableau\b.*|Arial.*|Segoe UI.*|Calibri.*|Helvetica.*|Verdana|Trebuchet MS|Georgia|"
                           r"Times New Roman|Lato.*|Open Sans.*|Roboto.*|Benton Sans.*)$")
HEAVY = re.compile(r"(Medium|Semibold|Bold|Black|Heavy)", re.I)
DASH_TITLE_MIN_PT = 16  # a dashboard text whose largest run is at least this is the dashboard's title
GREYS = ("text", "subtitle", "muted", "mark_muted", "cell_bar", "canvas")  # grey tokens, dark to light
HUES = ("accent", "good", "bad")
ZONE_ORDER = ("border-color", "border-style", "border-width", "margin", "margin-top", "margin-right",
              "margin-bottom", "margin-left", "padding", "background-color")  # as Desktop writes zone-style
LINE_BREAK = "\n"
CARD_CONTENT_MIN_PX = 40  # a smaller sheet (a KPI tile, a button) stays without a card: the padding would eat it
DEFAULT_SIZE = (1000, 800)  # Desktop's default dashboard size, when the book has no fixed <size>


# ---- XML with byte spans --------------------------------------------------------------------------------------
@dataclass
class Doc:
    raw: bytes
    root: ET.Element
    span: dict  # id(element) -> (start, end) byte offsets of the element in raw
    parent: dict  # id(element) -> parent element
    edits: list = field(default_factory=list)  # (start, end, bytes)

    def start_tag_end(self, el):
        """Byte offset right after el's start tag."""
        i, quote = self.span[id(el)][0], None
        while True:
            c = self.raw[i:i + 1]
            if quote:
                quote = None if c == quote else quote
            elif c in (b"'", b'"'):
                quote = c
            elif c == b">":
                return i + 1
            i += 1

    def end_tag_start(self, el):
        """Byte offset of el's end tag ('</tag>'); None for a self-closing element."""
        s, e = self.span[id(el)]
        tail = self.raw[s:e]
        return None if tail.endswith(b"/>") else s + tail.rindex(b"</")

    def inside(self, el, tag):
        p = self.parent.get(id(el))
        while p is not None:
            if p.tag == tag:
                return True
            p = self.parent.get(id(p))
        return False


def parse(raw):
    """raw .twb bytes -> Doc: an ElementTree whose every element knows its byte span in raw."""
    root, stack, span, parent = None, [], {}, {}
    p = xml.parsers.expat.ParserCreate()
    p.ordered_attributes = True
    p.buffer_text = True

    def start(name, attrs):
        nonlocal root
        el = ET.Element(name, dict(zip(attrs[::2], attrs[1::2])))
        if stack:
            stack[-1].append(el)
            parent[id(el)] = stack[-1]
        else:
            root = el
        span[id(el)] = [p.CurrentByteIndex, None]
        stack.append(el)

    def end(name):
        el = stack.pop()
        i = p.CurrentByteIndex
        span[id(el)][1] = raw.index(b">", i) + 1 if raw[i:i + 2] == b"</" else i

    def text(data):
        el = stack[-1]
        if len(el):
            el[-1].tail = (el[-1].tail or "") + data
        else:
            el.text = (el.text or "") + data

    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = start, end, text
    p.Parse(raw, True)
    return Doc(raw, root, {k: tuple(v) for k, v in span.items()}, parent)


def _esc(s, attr):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if attr:
        s = s.replace('"', "&quot;").replace("'", "&apos;").replace("\n", "&#10;").replace("\r", "&#13;")
    return s


def _start(el, close=False):
    attrs = "".join(f" {k}='{_esc(v, True)}'" for k, v in el.attrib.items())
    return f"<{el.tag}{attrs}{' /' if close else ''}>"


def serialize(el):
    """el as Tableau writes XML: single quotes, '<x />' when empty (no whitespace added)."""
    if not len(el) and not el.text:
        return _start(el, True)
    out = [_start(el), _esc(el.text or "", False)]
    for c in el:
        out += [serialize(c), _esc(c.tail or "", False)]
    return "".join(out) + f"</{el.tag}>"


def apply(doc):
    """doc.raw with doc.edits spliced in."""
    out, pos = [], 0
    for s, e, b in sorted(doc.edits, key=lambda x: (x[0], x[1])):
        if s < pos:
            raise ValueError(f"restyle: overlapping edits at byte {s}")
        out += [doc.raw[pos:s], b]
        pos = e
    return b"".join(out + [doc.raw[pos:]])


# ---- edits ---------------------------------------------------------------------------------------------------
def _replace(doc, original, new):
    """Replace the element original (in doc) by new when they differ."""
    text = serialize(new)
    if text != serialize(original):
        doc.edits.append((*doc.span[id(original)], text.encode("utf-8")))


def _insert(doc, at, new):
    doc.edits.append((at, at, serialize(new).encode("utf-8")))


def _append_child(doc, el, new):
    """new as el's last child (zone-style after the child zones, as Desktop writes it)."""
    end = doc.end_tag_start(el)
    if end is not None:
        return _insert(doc, end, new)
    s, e = doc.span[id(el)]  # '<zone ... />' -> '<zone ...>new</zone>'
    doc.edits.append((s, e, (_start(el) + serialize(new) + f"</{el.tag}>").encode("utf-8")))


def _rgb(hex_):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_ or ""):
        return None
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def _nearest(hex_, names):
    rgb = _rgb(hex_)
    return min(names, key=lambda n: sum((a - b) ** 2 for a, b in zip(rgb, _rgb(COLOR[n]))))


def _lightness(hex_):
    return colorsys.rgb_to_hls(*(c / 255 for c in _rgb(hex_)))[1]


def _grey(hex_):
    r, g, b = _rgb(hex_)
    return max(r, g, b) - min(r, g, b) < 40


def mark_color(hex_):
    """A single mark color on the token palette: tokens stay, greys go to the nearest grey token, colors to the
    nearest of accent / good / bad. Colors with alpha and other forms stay."""
    if _rgb(hex_) is None or hex_.lower() in {v.lower() for v in COLOR.values()}:
        return hex_
    return COLOR[_nearest(hex_, GREYS if _grey(hex_) else HUES)]


def text_color(hex_, role):
    """A title / subtitle run's color: default or dark grey text takes the role's token; light text (on a dark
    band) and colored text stay."""
    if hex_ is None or (_rgb(hex_) is not None and _grey(hex_) and _lightness(hex_) <= 0.6):
        return role
    return hex_


# ---- what restyle does ---------------------------------------------------------------------------------------
@dataclass
class Report:
    theme: str = CARDS
    counts: dict = field(default_factory=dict)

    def add(self, what, n=1):
        if n:
            self.counts[what] = self.counts.get(what, 0) + n

    def __str__(self):
        return ", ".join(f"{k} {v}" for k, v in self.counts.items()) or "nothing to change"


def _scale(theme):
    return {**FONT, **(design.FONT_CARDS if theme == CARDS else {})}


def _font_off(el):
    """Take a Tableau / web text family off a run (its weight becomes bold). True if el changed."""
    name = el.get("fontname")
    if not name or not TEXT_FAMILIES.match(name):
        return False
    del el.attrib["fontname"]
    if HEAVY.search(name):
        el.set("bold", "true")
    return True


def _restyle_runs(runs, sizes, colors, report, what):
    """Lines of a formatted text: the first is the title (bold), the rest the subtitle."""
    line = 0
    for r in runs:
        k = min(line, 1)
        r.set("fontsize", str(sizes[k]))
        if k == 0:
            r.set("bold", "true")
        r.set("fontcolor", text_color(r.get("fontcolor"), colors[k]))
        if LINE_BREAK in (r.text or ""):
            line += 1
    report.add(what)


def _run_edits(doc, runs_before, runs_after):
    for a, b in zip(runs_before, runs_after):
        if a.attrib != b.attrib:
            doc.edits.append((doc.span[id(a)][0], doc.start_tag_end(a), _start(b).encode("utf-8")))


def _set_format(rules, style, element, attr, value, scope=None):
    """Make style say attr=value for element (and scope): existing formats of that attr are overridden (any scope
    when scope is None), a missing one is added to the element's first rule. True if anything changed."""
    hits = [f for r in rules for f in r.findall("format") if f.get("attr") == attr
            and (scope is None or f.get("scope") == scope)]
    changed = False
    for f in hits:
        if f.get("value") != value:
            f.set("value", value)
            changed = True
    if not any(f.get("scope") == scope and f.get("field") is None and f.get("class") is None for f in hits):
        if not rules:
            rules.append(ET.SubElement(style, "style-rule", element=element))
        ET.SubElement(rules[0], "format", {"attr": attr, **({"scope": scope} if scope else {}), "value": value})
        changed = True
    return changed


def declutter(style):
    """build.DECLUTTER merged into a worksheet style. True if it changed."""
    changed = False
    for element, formats in DECLUTTER:
        rules = style.findall(f"style-rule[@element='{element}']")
        for f in formats:
            changed |= _set_format(rules, style, element, f["attr"], f["value"], f.get("scope"))
    return changed


def _style_fonts(style):
    """Text families off a worksheet's style-rules (a heavy one becomes font-weight bold). True if changed."""
    changed = False
    for rule in style.findall("style-rule"):
        for f in rule.findall("format[@attr='font-family']"):
            if TEXT_FAMILIES.match(f.get("value", "")):
                rule.remove(f)
                if HEAVY.search(f.get("value")):
                    keys = {k: v for k, v in f.attrib.items() if k not in ("attr", "value")}
                    ET.SubElement(rule, "format", {"attr": "font-weight", **keys, "value": "bold"})
                changed = True
    return changed


def _worksheet(doc, ws, theme, report):
    table = ws.find("table")
    st = table.find("style")
    new = copy.deepcopy(st) if st is not None else ET.Element("style")
    if declutter(new):
        report.add("worksheets decluttered")
    if _style_fonts(new):
        report.add("worksheet fonts")
    if st is not None:
        _replace(doc, st, new)
    else:  # before <panes>, where Desktop writes it
        _insert(doc, doc.span[id(table.find("panes"))][0], new)
    for pane in table.iter("pane"):
        pst = pane.find("style")
        if pst is None:
            continue
        new = copy.deepcopy(pst)
        for f in new.findall("style-rule[@element='mark']/format[@attr='mark-color']"):
            if mark_color(f.get("value")) != f.get("value"):
                f.set("value", mark_color(f.get("value")))
                report.add("mark colors")
        _replace(doc, pst, new)
    title = ws.find("layout-options/title/formatted-text")
    if title is not None:
        runs = title.findall("run")
        after = [copy.deepcopy(r) for r in runs]
        for r in after:
            _font_off(r)
        sc = _scale(theme)
        _restyle_runs(after, (sc["block_title"], sc["block_subtitle"]), (COLOR["text"], COLOR["muted"]), report,
                      "sheet titles")
        _run_edits(doc, runs, after)


def _zone_set(st, values):
    """Set zone-style formats, written in Desktop's order. True if changed."""
    have = {f.get("attr"): f for f in st.findall("format")}
    changed = False
    for a, v in values.items():
        if a in have:
            changed |= have[a].get("value") != v
            have[a].set("value", v)
        else:
            have[a] = ET.SubElement(st, "format", attr=a, value=v)
            changed = True
    order = {a: i for i, a in enumerate(ZONE_ORDER)}
    fs = st.findall("format")
    for f in fs:
        st.remove(f)
    for f in sorted(fs, key=lambda f: order.get(f.get("attr"), len(order))):
        st.append(f)
    return changed


def _card_fits(z, width, height):
    """A sheet zone keeps at least CARD_CONTENT_MIN_PX each way inside a card's border and padding."""
    inset = 2 * (SPACE["card_padding"] + design.CARD_BORDER_PX)
    return min(int(z.get("w", 0)) * width / 100000 - inset,
               int(z.get("h", 0)) * height / 100000 - inset) >= CARD_CONTENT_MIN_PX


def _dashboard(doc, db, theme, report):
    sc = _scale(theme)
    if theme == CARDS:
        st = db.find("style")
        new = copy.deepcopy(st) if st is not None else ET.Element("style")
        _set_format(new.findall("style-rule[@element='table']"), new, "table", "background-color", COLOR["canvas"])
        if st is not None:
            _replace(doc, st, new)
        else:  # before <size> (golden: <style /> then <size>)
            _insert(doc, doc.span[id(db.find("size") if db.find("size") is not None else db.find("zones"))][0], new)
        report.add("canvas")
    title = db.find("layout-options/title/formatted-text")  # the dashboard title object's text
    texts = [title] if title is not None else []
    texts += [ft for z in db.iter("zone") if z.get("type-v2") == "text" for ft in z.findall("formatted-text")]
    size = db.find("size")
    width, height = (int((size.attrib if size is not None else {}).get(k, d))
                     for k, d in (("maxwidth", DEFAULT_SIZE[0]), ("maxheight", DEFAULT_SIZE[1])))
    zones = db.find("zones")  # the main layout; the device layouts keep their own
    for z in (zones.iter("zone") if zones is not None else []):
        sheet = z.get("name") is not None and z.get("type-v2") is None
        if not (sheet or z.get("type-v2") == "text"):
            continue
        if sheet and theme == CARDS and not _card_fits(z, width, height):
            report.add("too small for a card")
            continue
        zs = z.find("zone-style")
        new = copy.deepcopy(zs) if zs is not None else ET.Element("zone-style")
        if theme == CARDS and sheet:
            values = {"border-color": COLOR["card_border"], "border-style": "solid",
                      "border-width": str(design.CARD_BORDER_PX), "padding": str(SPACE["card_padding"]),
                      "background-color": COLOR["card_bg"]}
            what = "cards"
        else:
            values = {"border-color": "#000000", "border-style": "none", "border-width": "0"} \
                if {f.get("attr"): f.get("value") for f in new.findall("format")}.get("border-style", "none") \
                != "none" else {}
            what = "borders removed"
        if values and _zone_set(new, values):
            report.add(what)
            if zs is not None:
                _replace(doc, zs, new)
            else:
                _append_child(doc, z, new)
    for ft in texts:
        runs = ft.findall("run")
        after = [copy.deepcopy(r) for r in runs]
        for r in after:
            _font_off(r)
        if max([int(float(r.get("fontsize", 0))) for r in runs] or [0]) >= DASH_TITLE_MIN_PT:
            _restyle_runs(after, (sc["dash_title"], sc["dash_subtitle"]),
                          (COLOR["text"], COLOR["subtitle"] if theme == CARDS else COLOR["muted"]), report,
                          "dashboard titles")
        _run_edits(doc, runs, after)


def _workbook_font(doc, report):
    root = doc.root
    st = root.find("style")
    new = copy.deepcopy(st) if st is not None else ET.Element("style")
    rules = new.findall("style-rule[@element='all']")
    if _set_format(rules, new, "all", "font-family", FONT_FAMILY):
        report.add("workbook font")
    if st is not None:
        _replace(doc, st, new)
    else:  # right after <preferences> (theme.workbook_style), else before <datasources>
        pref = root.find("preferences")
        at = doc.span[id(pref)][1] if pref is not None else doc.span[id(root.find("datasources"))][0]
        _insert(doc, at, new)


def restyle_xml(raw, theme=CARDS):
    """.twb bytes -> (restyled bytes, Report)."""
    if theme not in THEMES:
        raise ValueError(f"restyle: unknown theme {theme!r} (known: {', '.join(THEMES)})")
    doc = parse(raw)
    report = Report(theme)
    _workbook_font(doc, report)
    ws_root = doc.root.find("worksheets")
    for ws in (ws_root if ws_root is not None else []):
        _worksheet(doc, ws, theme, report)
    db_root = doc.root.find("dashboards")
    for db in (db_root if db_root is not None else []):
        _dashboard(doc, db, theme, report)
    out = apply(doc)
    invariant(raw, out)
    return out, report


# ---- the invariant -------------------------------------------------------------------------------------------
def _without_style(raw):
    """Canonical XML of raw without its style nodes (STYLE_TAGS outside the datasources) and run font attributes;
    whitespace-only text is dropped (indentation)."""
    doc = parse(raw)
    for el in list(doc.root.iter()):
        for c in list(el):
            if c.tag in STYLE_TAGS and not doc.inside(c, "datasources"):
                el.remove(c)
        if el.tag == "run":
            for a in RUN_FONT:
                el.attrib.pop(a, None)
    for el in doc.root.iter():
        if el.text is not None and not el.text.strip():
            el.text = None
        if el.tail is not None and not el.tail.strip():
            el.tail = None
    return ET.canonicalize(ET.tostring(doc.root, encoding="unicode"))


def _datasources(raw):
    doc = parse(raw)
    ds = doc.root.find("datasources")
    return b"" if ds is None else raw.__getitem__(slice(*doc.span[id(ds)]))


def invariant(before, after):
    """Raise ValueError unless after differs from before only in style nodes; the datasources byte for byte."""
    if _datasources(before) != _datasources(after):
        raise ValueError("restyle invariant: <datasources> changed")
    a, b = _without_style(before), _without_style(after)
    if a != b:
        i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        raise ValueError(f"restyle invariant: non-style XML changed near ...{a[max(0, i - 120):i + 80]!r} -> "
                         f"{b[max(0, i - 120):i + 80]!r}")


# ---- files ---------------------------------------------------------------------------------------------------
def _twb_name(z):
    names = [n for n in z.namelist() if n.lower().endswith(".twb") and "/" not in n]
    if len(names) != 1:
        raise ValueError(f"restyle: expected one .twb at the root of the package, found {names}")
    return names[0]


def read_twb(path):
    path = Path(path)
    if path.suffix.lower() == ".twb":
        return path.read_bytes()
    with zipfile.ZipFile(path) as z:
        return z.read(_twb_name(z))


def restyle_file(src, out, theme=CARDS):
    """Restyle src (.twbx or .twb) into out (same kind). Every other package member is copied as is."""
    src, out = Path(src), Path(out)
    if src.suffix.lower() != out.suffix.lower():
        raise ValueError(f"restyle: {src.name} -> {out.name}: input and output must both be .twbx or .twb")
    if src.resolve() == out.resolve():
        raise ValueError("restyle: the output must be a new file (the input is never rewritten)")
    out.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".twb":
        new, report = restyle_xml(src.read_bytes(), theme)
        out.write_bytes(new)
        return report
    with zipfile.ZipFile(src) as z:
        name = _twb_name(z)
        new, report = restyle_xml(z.read(name), theme)
        fd, tmp = tempfile.mkstemp(suffix=".twbx", dir=out.parent)
        os.close(fd)
        tmp = Path(tmp)
        try:
            with zipfile.ZipFile(tmp, "w") as w:
                for info in z.infolist():
                    data = new if info.filename == name else z.read(info.filename)
                    w.writestr(info, data, compress_type=info.compress_type)
            shutil.move(tmp, out)
        finally:
            tmp.unlink(missing_ok=True)
    return report
