"""A profile from workbooks (decisions/194): what the books do, counted in their XML.

`tb copy-style <book...> --out profiles/<name>/` reads .twbx, .twb and Preferences.tps, counts for each token what the
chosen dashboards use (a fact is one zone, one text or one mark rule) and writes the most frequent value to profile.yaml
and every alternative to tokens.md. Not ML, and no data of a book is read. What a color means (good, bad, accent) is a
guess from its hue: the command names these guesses and the user confirms them (--set corrects one).
"""
import collections
import colorsys
import json
import re
import shutil
import zipfile
from pathlib import Path

import yaml
from lxml import etree

from . import design, shell, user_profile

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
BOOK_TYPES = (".twbx", ".twb", ".tps")
UNITS = 100000  # a zone's x, y, w, h are shares of the dashboard
CANVAS_AREA = 0.6  # a colored zone over this share of the dashboard is its background, not a card
SIDEBAR_W, SIDEBAR_H = 25000, 80000  # a tall narrow colored zone
BAND_W, BAND_H = 90000, 15000  # a wide low colored zone: a brand strip, a spec's topbar.color and not a token
TOP_SHARE = 25000  # the dashboard's title is in a text zone that starts this high
BLOCK_TITLE_MIN = 10  # pt: smaller is a column title or a note, not a block's header
AUTO_SIZE = (1200, 800)  # px, a dashboard without a fixed size: to read gaps between its cards
CARD_GAP_MAX = 60  # px: farther apart is not a gap between neighbours
SCALE_LOW_MIN = 7  # contrast with black of a scale's light end
PALETTE_MAX = 5  # rule C2
GOOD_HUE, BAD_HUES = (90, 200), ((0, 25), (335, 360))  # degrees: green to teal, red to coral
GREY_SATURATION = 0.15
MEANINGS = ("accent", "good", "bad")
LAYOUT = ("layout-flow", "layout-basic")
RULE_TEXT = re.compile(r"[\sÆ]+")
# Tokens, in the order of tokens.md: the fact's key -> (group, key in profile.yaml)
TOKENS = {k: ("color", k) for k in ("canvas", "card_bg", "card_border", "sidebar_bg", "text", "subtitle", "muted", "accent", "good",
                                    "bad", "scale_low", "scale_mid")}
TOKENS.update({k: ("font", k) for k in ("dash_title", "dash_subtitle", "block_title", "block_subtitle")})
TOKENS.update({k: ("space", k) for k in ("card_margin", "card_padding", "card_padding_kpi")})


class SourceError(ValueError):
    pass


def read(path):
    """The XML of a .twbx, .twb or .tps."""
    path = Path(path)
    if path.suffix.lower() not in BOOK_TYPES:
        hint = " A link is downloaded first: see .claude/skills/copy-style/SKILL.md." if re.match(r"https?:", str(path)) else ""
        raise SourceError(f"{path}: not a workbook ({', '.join(BOOK_TYPES)}).{hint}")
    if not path.is_file():
        raise SourceError(f"{path}: no such file")
    try:
        if path.suffix.lower() != ".twbx":
            return etree.fromstring(path.read_bytes(), PARSER)
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".twb") and "/" not in n), None)
            if name is None:
                raise SourceError(f"{path}: no .twb inside")
            return etree.fromstring(z.read(name), PARSER)
    except (zipfile.BadZipFile, etree.XMLSyntaxError) as e:
        raise SourceError(f"{path}: cannot read it: {e}") from e


def dashboards(root):
    return [d for d in root.iter("dashboard") if d.get("type") != "storyboard"]


def outline(path):
    """What `--list` prints: the dashboards of a book, to choose one."""
    out = []
    for d in dashboards(read(path)):
        size = d.find("size")
        zones = d.find("zones")
        out.append({"name": d.get("name"), "size": dict(size.attrib) if size is not None else None,
                    "sheets": sum(1 for z in (zones.iter("zone") if zones is not None else ()) if _kind(z) is None and z.get("name"))})
    return out


# ---- colors ------------------------------------------------------------------------------------------------
def _solid(value, under="#ffffff"):
    """A format's color as a solid #rrggbb on what is under it; None for none at all (#00000000)."""
    value = (value or "").lower()
    if len(value) == 7:
        return value
    if len(value) != 9:
        return None
    alpha = int(value[7:], 16) / 255
    if not alpha:
        return None
    return "#" + "".join(f"{round(int(value[i:i + 2], 16) * alpha + int(under[i:i + 2], 16) * (1 - alpha)):02x}" for i in (1, 3, 5))


def _hsv(c):
    return colorsys.rgb_to_hsv(*(int(c[i:i + 2], 16) / 255 for i in (1, 3, 5)))


def _is_grey(c):
    h, s, v = _hsv(c)
    return s < GREY_SATURATION or v < 0.2


def _hue_good(c):
    return not _is_grey(c) and GOOD_HUE[0] <= _hsv(c)[0] * 360 <= GOOD_HUE[1]


def _hue_bad(c):
    return not _is_grey(c) and any(lo <= _hsv(c)[0] * 360 <= hi for lo, hi in BAD_HUES)


def _is_dark(c):
    return shell.contrast(c, "#ffffff") > shell.contrast(c, "#333333")


def _style(z):
    return {f.get("attr"): f.get("value") for f in z.findall("zone-style/format")}


def _kind(z):
    return z.get("type-v2") or z.get("type")


def _px(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


# ---- a dashboard -------------------------------------------------------------------------------------------
def _lines(runs):
    """Runs of a formatted text by line: [[(size, color, bold)]], empty lines dropped. No fontsize: the default size,
    which is no fact."""
    lines, line = [], []
    for r in runs:
        if RULE_TEXT.sub("", r.text or ""):
            line.append((_px(r.get("fontsize")) or None, (r.get("fontcolor") or "").lower()[:7] or None, r.get("bold") == "true"))
        if "\n" in (r.text or "") or "Æ" in (r.text or ""):
            lines.append(line)
            line = []
    return [x for x in lines + [line] if x]


def _is_kpi(ws):
    """A number on its own: nothing on rows and columns."""
    return ws is not None and not (ws.findtext("table/rows") or "").strip() and not (ws.findtext("table/columns") or "").strip()


class _Board:
    """Counts one dashboard's zones into facts (a Counter per token), notes what no token holds."""

    def __init__(self, db, sheets, facts, notes):
        self.sheets, self.facts, self.notes = sheets, facts, notes
        self.canvas = "#ffffff"
        self.titles, self.faces, self.colored_words, self.legends = [], [], 0, 0
        size = db.find("size")
        self.px = (_px(size.get("maxwidth") or size.get("minwidth")) or AUTO_SIZE[0],
                   _px(size.get("maxheight") or size.get("minheight")) or AUTO_SIZE[1]) if size is not None else AUTO_SIZE
        top = db.find("zones")
        for f in db.findall("style/style-rule[@element='table']/format[@attr='background-color']"):
            self.canvas = _solid(f.get("value")) or self.canvas
        for z in top.findall("zone") if top is not None else ():
            self._find_canvas(z)
        facts["canvas"][self.canvas] += 1
        for z in top.findall("zone") if top is not None else ():
            self._walk(z, self.canvas, None)
        self._title()
        self._gaps()
        facts["theme"]["cards" if len(self.faces) >= 2 else "flat"] += 1
        facts["legend"]["card" if self.legends > self.colored_words else "words"] += 1

    def _find_canvas(self, z):
        """The dashboard's background set on its root zones, when its own style has none."""
        bg = _solid(_style(z).get("background-color"), self.canvas)
        if _px(z.get("w")) * _px(z.get("h")) < CANVAS_AREA * UNITS ** 2:
            return
        self.canvas = bg or self.canvas
        for k in z.findall("zone"):
            self._find_canvas(k)

    def _walk(self, z, under, face):
        """face: the id of the card this zone is in, None on the canvas."""
        st, kind = _style(z), _kind(z)
        w, h = _px(z.get("w")), _px(z.get("h"))
        bg = _solid(st.get("background-color"), under)
        here = bg or under
        big = w * h >= CANVAS_AREA * UNITS ** 2
        if bg and kind in LAYOUT and h >= SIDEBAR_H and w <= SIDEBAR_W:
            self.facts["sidebar_bg"][bg] += 1
        elif bg and bg != self.canvas and w >= BAND_W and h <= BAND_H and _is_dark(bg):
            self.notes["brand strips (a spec's topbar.color)"][bg] += 1
        elif face is None and not big and (kind in LAYOUT or (kind is None and z.get("name"))) and self._is_face(st, bg, under):
            self._face(z, st, here)
            face = id(z)
        if kind == "text":
            self._text(z, here, face)
        elif kind in ("color", "size-legend", "shape-legend"):
            self.legends += 1
        elif kind is None and z.get("name") and z.get("show-title") != "false":
            ws = self.sheets.get(z.get("name"))
            if ws is not None:
                lines = _lines(ws.findall("layout-options/title/formatted-text/run"))
                if lines and not self._foreign(here):
                    self.titles.append((_px(z.get("y")), lines, face))
        for f in z.findall("zone-style/format") if kind is None and z.get("name") else ():
            if f.get("attr") == "margin":
                self.notes["sheet zone margin (zone_margin stays)"][_px(f.get("value"))] += 1
        for k in z.findall("zone"):
            self._walk(k, here, face)

    @staticmethod
    def _is_face(st, bg, under):
        return (bg and bg != under) or st.get("border-style") == "solid"

    def _face(self, z, st, face):
        self.faces.append(([_px(z.get(a)) for a in "xywh"], _px(st.get("margin"))))
        self.facts["card_bg"][face] += 1
        solid = st.get("border-style") == "solid" and _px(st.get("border-width")) > 0
        self.facts["card_border"][(st.get("border-color") or face).lower()[:7] if solid else face] += 1
        names = [k.get("name") for k in z.iter("zone") if _kind(k) is None and k.get("name")]
        kpi = any(_is_kpi(self.sheets.get(n)) for n in names)
        self.facts["card_padding_kpi" if kpi else "card_padding"][_px(st.get("padding"))] += 1

    def _gaps(self):
        """card_margin is half of what is seen between two cards (design.SPACE): their margins, and the distance between
        their zones, as books that part cards with an empty zone do (reference, margin 0). A card with no neighbour: its
        margin."""
        for (x, y, w, h), margin in self.faces:
            gaps = []
            for (x2, y2, w2, h2), margin2 in self.faces:
                if y2 < y + h and y < y2 + h2 and x2 >= x + w:
                    gaps.append((x2 - x - w) * self.px[0] / UNITS + margin + margin2)
                if x2 < x + w and x < x2 + w2 and y2 >= y + h:
                    gaps.append((y2 - y - h) * self.px[1] / UNITS + margin + margin2)
            near = min(gaps, default=None)
            if near == 0:  # touching: parts of one card, not two
                continue
            self.facts["card_margin"][margin if near is None or near > CARD_GAP_MAX else round(near / 2)] += 1

    def _foreign(self, under):
        """Text on a dark panel of a light dashboard says nothing of the dashboard's text colors."""
        return _is_dark(under) and not _is_dark(self.canvas)

    def _text(self, z, under, face):
        lines = _lines(z.findall("formatted-text/run"))
        self.colored_words += sum(1 for ln in lines for _, c, _b in ln if c and not _is_grey(c))
        if lines and not self._foreign(under):
            self.titles.append((_px(z.get("y")), lines, face))

    def _block(self, lines):
        size, color, bold = lines[0][0]
        self.facts["block_title"][size] += 1
        if color and bold:  # a title in plain weight may be a note in grey
            self.facts["text"][color] += 1
        for ln in lines[1:2]:
            if ln[0][0]:
                self.facts["block_subtitle"][ln[0][0]] += 1
            if ln[0][1]:
                self.facts["muted"][ln[0][1]] += 1

    def _title(self):
        """The largest first line in the top of the dashboard is its title. A block's header is the largest text of its
        card (column titles are text zones too); on the canvas every other text large enough is one."""
        if not self.titles:
            return
        top = [t for t in self.titles if t[0] < TOP_SHARE] or self.titles
        title = max(top, key=lambda t: (t[1][0][0][0] or 0, -t[0]))
        size, color, _ = title[1][0][0]
        if size:
            self.facts["dash_title"][size] += 1
        if color:
            self.facts["text"][color] += 1
        for ln in title[1][1:2]:
            if ln[0][0]:
                self.facts["dash_subtitle"][ln[0][0]] += 1
            if ln[0][1]:
                self.facts["subtitle"][ln[0][1]] += 1
        cards = {}
        for t in self.titles:
            first = t[1][0][0][0] or 0
            if t is title or first > (size or first) or first < BLOCK_TITLE_MIN:
                continue
            if t[2] is None:
                self._block(t[1])
            elif t[2] not in cards or first > (cards[t[2]][1][0][0][0] or 0):
                cards[t[2]] = t
        for t in cards.values():
            self._block(t[1])


# ---- marks and palettes ------------------------------------------------------------------------------------
def _field(column):
    """A shelf's or an encoding's field without its datasource."""
    return (column or "").rsplit("].[", 1)[-1].strip("[]")


def _marks(root, scope, facts):
    """The colors of the marks of the sheets in scope: their mark-color, the color maps of their sheet and of the
    datasource fields they put on color, and the custom palettes of these."""
    used = {_field(c.get("column")) for ws in scope for c in ws.iter("color")}
    encodings = [e for ws in scope for e in ws.iter("encoding")]
    encodings += [e for d in root.iter("datasource") for e in d.findall("style/style-rule/encoding") if _field(e.get("field")) in used]
    colors, seen = facts["marks"], set()
    for ws in scope:
        for f in ws.iter("format"):
            if f.get("attr") == "mark-color" and _solid(f.get("value")):
                colors[_solid(f.get("value"))] += 1
    palettes = [p for p in root.findall("preferences/color-palette")]
    for e in encodings:
        if id(e) in seen or e.get("attr") != "color":
            continue
        seen.add(id(e))
        for m in e.findall("map"):
            if _solid(m.get("to")):
                colors[_solid(m.get("to"))] += 1
        palettes += e.findall("color-palette")
    for p in palettes:
        _palette(p, facts)


def _palette(p, facts):
    """Scales from a custom palette: the light end of a sequential one, the middle and the sign ends of a diverging one."""
    colors = [c for c in (_solid(x.text) for x in p.findall("color")) if c]
    if not colors:
        return
    kind = p.get("type")
    if kind == "ordered-sequential":
        low = max((colors[0], colors[-1]), key=lambda c: shell.contrast(c, "#000000"))
        if shell.contrast(low, "#000000") >= SCALE_LOW_MIN:  # both ends dark: not a scale from a light end
            facts["scale_low"][low] += 1
    elif kind == "ordered-diverging":
        facts["scale_mid"][colors[len(colors) // 2]] += 1
        ends = sorted((colors[0], colors[-1]), key=_hue_good, reverse=True)
        if _hue_good(ends[0]) and _hue_bad(ends[1]):
            facts["good"][ends[0]] += 1
            facts["bad"][ends[1]] += 1
    elif kind in (None, "regular"):
        facts["palettes"][tuple(colors)] += 1


def _meanings(facts):
    """accent, good, bad from the marks' colors, by hue: good and bad only as a pair, a lone red may be a brand's accent."""
    marks, why = facts["marks"], {}
    color = [(c, n) for c, n in marks.most_common() if not _is_grey(c)]
    good = [(c, n) for c, n in color if _hue_good(c)]
    bad = [(c, n) for c, n in color if _hue_bad(c)]
    if good and bad:
        for role, found in (("good", good), ("bad", bad)):
            for c, n in found:
                facts[role][c] += n
    for role in ("good", "bad"):
        if facts[role]:
            why[role] = "green or teal at one end, red at the other" if role == "good" else "its pair"
    taken = {c for role in ("good", "bad") for c in (facts[role].most_common(1)[0][0:1] if facts[role] else ())}
    for c, n in color:
        if c not in taken:
            facts["accent"][c] += n
    if facts["accent"]:
        why["accent"] = "the most frequent colored mark that is neither good nor bad"
    return why


def _categorical(facts):
    """The custom palette the book names, else its colored marks by frequency: up to PALETTE_MAX, three at least."""
    if facts["palettes"]:
        return list(facts["palettes"].most_common(1)[0][0][:PALETTE_MAX])
    color = [c for c, _ in facts["marks"].most_common() if not _is_grey(c)]
    return color[:PALETTE_MAX] if len(color) >= 3 else []


# ---- several books -----------------------------------------------------------------------------------------
def count(books, dashboard=None):
    """Facts of the books -> (facts, notes, [{file, dashboards}])."""
    facts, notes = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
    read_books = []
    if dashboard and len(books) > 1:
        raise SourceError("--dashboard is one dashboard of one book; several books are counted whole")
    for path in books:
        root = read(path)
        family = collections.Counter()
        boards = dashboards(root)
        if dashboard:
            boards = [d for d in boards if d.get("name") == dashboard]
            if not boards:
                have = ", ".join(repr(d.get("name")) for d in dashboards(root))
                raise SourceError(f"{path}: no dashboard '{dashboard}' (there are: {have})")
        by_name = {w.get("name"): w for w in root.iter("worksheet")}
        scope = {}
        for db in boards:
            _Board(db, by_name, facts, notes)
            top = db.find("zones")
            for z in top.iter("zone") if top is not None else ():
                if z.get("name") in by_name:
                    scope[z.get("name")] = by_name[z.get("name")]
                    family.update(r.get("fontname") for r in z.iter("run") if r.get("fontname"))
                if _kind(z) == "text":
                    family.update(r.get("fontname") for r in z.findall("formatted-text/run") if r.get("fontname"))
        family.update(f.get("value") for r in root.findall("style/style-rule[@element='all']") for f in r.findall("format[@attr='font-family']"))
        family.update(r.get("fontname") for ws in scope.values() for r in ws.iter("run") if r.get("fontname"))
        facts["family"].update(family)
        _marks(root, list(scope.values()) or ([] if boards else list(by_name.values())), facts)
        read_books.append({"file": str(path), "dashboards": [d.get("name") for d in boards]})
    return facts, notes, read_books


def _readable(color):
    """What must be read, moved to the contrast floor (lint P2, as C8): the gate is not taste, and a book may be below it
    (reference: #898989 on #f5f5f5). -> notes of what moved."""
    from .design_lint import PROFILE_TEXT  # it needs the tokens of a profile, this module writes them
    notes = []
    for fg, bg, floor in PROFILE_TEXT:
        if floor and fg in color:
            back = color.get(bg, design.COLOR[bg])
            was, end = color[fg], "#000000" if not _is_dark(back) else "#ffffff"
            for k in range(101):
                color[fg] = "#" + "".join(f"{round(int(was[i:i + 2], 16) + (int(end[i:i + 2], 16) - int(was[i:i + 2], 16)) * k / 100):02x}"
                                          for i in (1, 3, 5))
                if shell.contrast(color[fg], back) >= floor:
                    break
            if color[fg] != was:
                notes.append(f"{fg}: {was} in the books, {color[fg]} here, to read at {floor}:1 on {bg} {back}")
    return notes


def _roomy(space):
    """A card's padding, moved to its floor (the gate: at least half the gap between cards, decisions/070): a book with
    floating blocks has cards with no padding of their own. Only where the book gives a gap. -> notes of what moved."""
    notes, floor = [], space.get("card_margin")
    for k in ("card_padding", "card_padding_kpi") if floor is not None else ():
        was = space.get(k)
        if (design.SPACE[k] if was is None else was) < floor:
            space[k] = floor
            shown = f"{design.SPACE[k]} by default" if was is None else f"{was} in the books"
            notes.append(f"{k}: {shown}, {floor} here, inside a card at least half the gap between cards (card_margin {floor})")
    return notes


def choose(facts):
    """-> (the profile's values, the guessed meanings, what was moved to read or to fit). The most frequent value of each token; a
    tie goes to the first seen. A token with no fact is left out: it comes from based_on."""
    why = _meanings(facts)
    tokens = {"color": {}, "font": {}, "space": {}}
    for key, (group, name) in TOKENS.items():
        if facts[key]:
            tokens[group][name] = facts[key].most_common(1)[0][0]
    for small, big in (("dash_subtitle", "dash_title"), ("block_subtitle", "block_title")):  # the header's order holds
        if small in tokens["font"] and big in tokens["font"] and tokens["font"][small] >= tokens["font"][big]:
            del tokens["font"][small]
    if facts["family"].most_common(1)[:1] and facts["family"].most_common(1)[0][0] in _families():
        tokens["font"]["family"] = facts["family"].most_common(1)[0][0]
    moved = _readable(tokens["color"]) + _roomy(tokens["space"])
    out = {"tokens": {g: v for g, v in tokens.items() if v}}
    palette = _categorical(facts)
    if palette:
        out["palettes"] = {"categorical": palette}
    for key in ("theme", "legend"):
        if facts[key]:
            out[key] = facts[key].most_common(1)[0][0]
    return out, why, moved


def _families():
    return user_profile.SCHEMA["properties"]["tokens"]["properties"]["font"]["properties"]["family"]["enum"]


# ---- writing -----------------------------------------------------------------------------------------------
def _alternatives(counter, chosen):
    return ", ".join(f"{k} ({n})" for k, n in counter.most_common() if k != chosen) or "-"


def report(values, why, moved, facts, notes, books, sets):
    """tokens.md: where each token came from, how often, what else the books use."""
    tokens = values.get("tokens", {})
    lines = ["# Tokens from workbooks", "", "Written by `tb copy-style`. A count is how many zones, texts or mark rules use the value.",
             "", "## Sources", ""]
    lines += [f"- `{b['file']}`: " + (", ".join(f"'{d}'" for d in b["dashboards"]) or "palettes only") for b in books] or ["- none: tokens set by hand"]
    lines += ["", "## Tokens", "", "| Token | Value | Count | Alternatives |", "|---|---|---|---|"]
    for key, (group, name) in TOKENS.items():
        value = tokens.get(group, {}).get(name)
        counter = facts[key]
        shown = "from based_on: no fact in the books" if value is None else f"`{value}`"
        lines.append(f"| {group}.{name} | {shown} | {counter[value] if value is not None else 0} of {sum(counter.values())} | "
                     f"{_alternatives(counter, value)} |")
    family = tokens.get("font", {}).get("family")
    lines.append(f"| font.family | {'`' + family + '`' if family else 'from based_on'} | {facts['family'][family] if family else 0} of "
                 f"{sum(facts['family'].values())} | {_alternatives(facts['family'], family)} |")
    for key in ("theme", "legend"):
        lines.append(f"| {key} | `{values.get(key, '-')}` | {facts[key][values.get(key)]} of {sum(facts[key].values())} | "
                     f"{_alternatives(facts[key], values.get(key))} |")
    lines += ["", "## Categorical palette", "", ", ".join(f"`{c}`" for c in values.get("palettes", {}).get("categorical", [])) or "None: fewer than 3 colors."]
    if moved:
        lines += ["", "## Moved from the books", ""] + [f"- {m}" for m in moved]
    lines += ["", "## Meaning to confirm", "", "A color's meaning is a guess from its hue. Correct one with "
              "`tb copy-style --out <folder> --set color.good=#rrggbb`.", ""]
    lines += [f"- **{role}** `{tokens['color'][role]}`: {why[role]}" for role in MEANINGS if role in why and role in tokens.get("color", {})] or ["- nothing guessed"]
    lines += ["", "## In the books, not in the profile", ""]
    other = [f"- {title}: {_alternatives(counter, None)}" for title, counter in sorted(notes.items()) if counter]
    grey = collections.Counter({c: n for c, n in facts["marks"].items() if _is_grey(c)})
    if grey:
        other.append(f"- grey marks (mark_muted, history stay): {_alternatives(grey, None)}")
    if facts["family"] and not family:
        other.append(f"- font {facts['family'].most_common(1)[0][0]}: text widths are measured for {', '.join(_families())} only")
    lines += other or ["- nothing"]
    if sets:
        lines += ["", "## Set by hand", ""] + [f"- {k} = `{v}`" for k, v in sets.items()]
    return "\n".join(lines) + "\n"


def _parse_set(text):
    m = re.fullmatch(r"(color|font|space)\.(\w+)=(.+)", text)
    if not m:
        raise SourceError(f"--set {text}: expected group.key=value, group color, font or space")
    group, key, value = m.groups()
    return group, key, int(value) if group != "color" and value.isdigit() else value


def _source(file, meta):
    out = {"kind": "public" if meta.get("url") else "server" if meta.get("workbook_id") else "file", "file": file}
    out.update({k: v for k, v in meta.items() if v})
    return out


def _is_palette_file(path):
    return Path(path).suffix.lower() == ".tps"


def write(out_dir, books, dashboard=None, sets=(), meta=None, brandbook=None):
    """profile.yaml (what it already holds stays, what the books say replaces it) and tokens.md in out_dir; books are
    copied to its refs/. -> what the skill must know: the path, the token count, the meanings to confirm."""
    meta = {k: v for k, v in (meta or {}).items() if v}
    out_dir = Path(out_dir)
    if meta and len(books) != 1:
        raise SourceError("--url, --site and --workbook-id describe one book")
    facts, notes, read_books = count(books, dashboard)
    values, why, moved = choose(facts) if books else ({}, {}, [])
    path = out_dir / "profile.yaml"
    old = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}
    profile = {"profile_version": 1, "based_on": user_profile.HOUSE, **old, **values}
    pairs = [_parse_set(s) for s in sets]
    for group, key, value in pairs:
        profile.setdefault("tokens", {}).setdefault(group, {})[key] = value
    refs = [f"refs/{Path(book).name}" for book in books]
    theirs = [_source(f, meta) for f, b in zip(refs, books) if not _is_palette_file(b)]
    if len(theirs) == 1:
        profile["style_book"] = {**theirs[0], **({"dashboard": dashboard} if dashboard else {})}
    elif theirs:
        profile.pop("style_book", None)
    keep = [s for s in old.get("sources", []) if s.get("kind") == "brandbook" and s.get("file") != brandbook]
    many = theirs if len(theirs) > 1 else []
    tps = [{"kind": "file", "file": f} for f, b in zip(refs, books) if _is_palette_file(b)]
    sources = keep + many + tps + ([{"kind": "brandbook", "file": brandbook}] if brandbook else [])
    if sources or "sources" in profile:
        profile["sources"] = sources
    found = user_profile.problems(profile)
    if found:
        raise SourceError("The profile would be invalid:\n" + "\n".join(f"  - {p}" for p in found))
    out_dir.mkdir(parents=True, exist_ok=True)
    for book, rel in zip(books, refs):
        target = out_dir / rel
        target.parent.mkdir(exist_ok=True)
        if Path(book).resolve() != target.resolve():
            shutil.copyfile(book, target)
    path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    report_path = out_dir / "tokens.md"
    if books or not report_path.is_file():
        report_path.write_text(report(values, why, moved, facts, notes, read_books, {f"{g}.{k}": v for g, k, v in pairs}), encoding="utf-8")
    elif pairs or brandbook:
        extra = [f"- {g}.{k} = `{v}`" for g, k, v in pairs] + ([f"- source: brand book `{brandbook}`"] if brandbook else [])
        report_path.write_text(report_path.read_text(encoding="utf-8") + "\n## Set by hand\n\n" + "\n".join(extra) + "\n", encoding="utf-8")
    colors = values.get("tokens", {}).get("color", {})
    return {"profile": str(path), "report": str(report_path), "dashboards": read_books,
            "tokens": sum(len(v) for v in profile.get("tokens", {}).values()),
            "moved": moved, "confirm": {role: {"value": colors[role], "why": why[role]} for role in MEANINGS if role in why and role in colors}}


def css(name):
    """CSS variables of a profile for an HTML mock (decisions/194): every token as the build sees it."""
    profile = user_profile.load(name)
    with design.apply(profile):
        font = {**design.FONT, **(design.FONT_CARDS if design.BOOK["theme"] == "cards" else {})}
        family = design.BOOK["theme_font"] or "Tableau Book"
        lines = [f"  --tb-color-{k.replace('_', '-')}: {v};" for k, v in design.COLOR.items()]
        lines += [f"  --tb-font-{k.replace('_', '-')}: {v}pt;" for k, v in font.items()]
        lines += [f"  --tb-space-{k.replace('_', '-')}: {v}px;" for k, v in design.SPACE.items()]
        lines.append(f'  --tb-font-family: "{family}", Arial, sans-serif;')
    return f"/* tb profile-css {name} */\n:root {{\n" + "\n".join(lines) + "\n}\n"


def listing():
    """One line per profile, to choose a mock's style from (decisions/195). `example` is a template, not a style."""
    lines = []
    for d in sorted(p for p in user_profile.ROOT.iterdir() if (p / "profile.yaml").is_file() and p.name != "example"):
        try:
            profile = user_profile.load(d.name)
        except user_profile.ProfileError as e:
            lines.append(f"{d.name}: broken: {e}")
            continue
        book = profile.get("style_book", {})
        source = book.get("url") or book.get("file") or book.get("workbook_id")
        with design.apply(profile):
            look = (f"accent {design.COLOR['accent']}, canvas {design.COLOR['canvas']}, card {design.COLOR['card_bg']}, "
                    f"theme {design.BOOK['theme']}")
        where = f"; from {source}" + (f", dashboard {book['dashboard']}" if book.get("dashboard") else "") if source else ""
        lines.append(f"{d.name}: {look}{where}")
    return lines


def to_json(result):
    return json.dumps(result, ensure_ascii=False, indent=1)
