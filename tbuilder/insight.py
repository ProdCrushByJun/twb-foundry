"""Text lines of a block (decisions/045): the insight line under a block header, a note under a KPI tile's number,
the color legend as a line of the block header.

- insight: "<phrase with [Calc]>" on a bar / line / area / table / heatmap / registry sheet. A text worksheet
  '<sheet> · Insight' under the block header: the phrase at 10pt muted, its **bold** parts in the text color, every
  [Calc] (an aggregate calc: one value for the block) shown by Tableau and following the filters ("Busiest day:
  **[Peak Day] ([Peak Day Closures])**; weekend adds only [Weekend Closures]."). Form: the card text of decisions/037
  (a sheet without rows and columns, the calcs on Text, a customized-label of runs, zoom entire-view).
- note: the same phrase as a KPI tile measure's third line, under its number ("[Incidents Share] of total").
- legend "inline" (bar / line / area colored by a field with fields.<field>.color, decisions/033): the legend as a
  line of the block header, a colored square and the member's label per member, instead of the 160px legend
  column (C4: the legend in the header, as the reference authors do).
  legend {position: below, groups: [{label, values}]} (decisions/173): the same legend as a text zone under the block,
  one line per group ("warehouse: ■ ... ■ ..."), every member of the color field once; without groups one line. A
  horizontal stack with a legend of ours draws the first member of fields.<color>.order at the left: the view
  sorts the field backwards (stack_order).
- a [Calc] with good: up | down (spec calcs, decisions/139) shows as its change: "▲ 11.4%" in the good text color,
  "▼ 60.3%" in the bad one (up: a rise is good). Two generated calcs, one per side of zero, each with the arrows in
  its number format, in two runs: the KPI cards' Diff Good / Diff Bad (decisions/037).
Without these keys nothing here changes the output.

expected: '<sheet> · Insight' {calc: value}, '<kpi> · Notes' {tile label: {calc: value}}. reconcile: a number of
the phrase is the one the page shows with the same words right before or after it.
"""
import re
import xml.etree.ElementTree as ET

from . import design, formats
from .design import COLOR, FONT, SPACE

KIND = "insight_line"  # the worksheet of an insight line
TYPES = ("bar", "line", "area", "table", "heatmap", "registry")
LEGEND_TYPES = ("bar", "line", "area")
REF = re.compile(r"\[([^\[\]]+)\]")
SEP = re.compile(r"[·|•;]")  # the separators reconcile cuts a page text at
WORD = re.compile(r"[^\W\d_]{2,}")
MAX_LINES = 2
SQUARE = "■ "  # the legend's color swatch
LEGEND_GAP = "    "  # after a member's label (inside its run: Desktop drops a run of spaces only)


def tokens(text):
    """'a **[X] b**' -> [(text, bold, is_ref)]: literal text and calc references, ** toggles bold."""
    out = []
    for i, part in enumerate(text.split("**")):
        bold, pos = i % 2 == 1, 0
        for m in REF.finditer(part):
            if m.start() > pos:
                out.append((part[pos:m.start()], bold, False))
            out.append((m.group(1), bold, True))
            pos = m.end()
        if pos < len(part):
            out.append((part[pos:], bold, False))
    return out


def refs(text):
    return list(dict.fromkeys(t for t, _, r in tokens(text) if r))


def signed(spec):
    """{calc name: good 'up' | 'down'} of the calcs shown as a change with its arrow."""
    return {c["name"]: c["good"] for c in spec.get("calcs", []) if "good" in c}


def side_calcs(name):
    return f"{name} · Good", f"{name} · Bad"


def calcs(spec):
    """Good / Bad sides of a signed calc: IF [X] >= 0 THEN [X] END (<= 0 with good down), the arrows in the calc's
    number format (kpi2.arrow_format)."""
    from .kpi2 import arrow_format
    fmt = {c["name"]: c for c in spec.get("calcs", [])}
    out = []
    for n, good in signed(spec).items():
        g, bad = side_calcs(n)
        up = good == "up"
        f = arrow_format(fmt[n])
        out += [{"name": g, "formula": f"IF [{n}] {'>=' if up else '<='} 0 THEN [{n}] END", "format": f},
                {"name": bad, "formula": f"IF [{n}] {'<' if up else '>'} 0 THEN [{n}] END", "format": f}]
    return out


def note(m):
    return m.get("note")


def inline(s):
    """The sheet draws its own legend (a line of the header, or under the block: decisions/173), no legend card."""
    return bool(s.get("legend"))


def below(s):
    """The legend under the block: legend {position: below, groups?: [{label, values}]} (decisions/173)."""
    lg = s.get("legend")
    return isinstance(lg, dict) and lg.get("position", "header") == "below"


def record(name):
    return f"{name} · Insight"


def notes_record(name):
    return f"{name} · Notes"


def part(s):
    return {"name": record(s["name"]), "type": KIND, "sheet": s}


# ---- checks ------------------------------------------------------------------------------------------------------
def _check_phrase(where, text, calcs):
    if text.count("**") % 2:
        raise ValueError(f"{where}: unbalanced ** in '{text}'")
    names = refs(text)
    if not names:
        raise ValueError(f"{where}: '{text}' names no [Calc]; a fixed text goes in the subtitle")
    aggs = sorted(n for n, c in calcs.calcs.items() if c.is_agg and not c.table_calc)
    for n in names:
        c = calcs.calcs.get(n)
        if c is None or not c.is_agg or c.table_calc:
            raise ValueError(f"{where}: [{n}] must be an aggregate calc (one value for the block, e.g. "
                             f"SUM([Sales]) / COUNTD([Customer])); aggregate calcs: {aggs}")


def check(spec, calcs):
    """Spec errors of the insight lines, the tile notes and the inline legends (calcs: the formula.CalcSet)."""
    headers = spec.get("block_headers", True)
    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        head = headers and (s.get("title") or s.get("subtitle"))
        if "insight" in s:
            if s["type"] not in TYPES:
                raise ValueError(f"{where}: insight applies to {', '.join(TYPES)}; a KPI tile takes a 'note'")
            if not head:
                raise ValueError(f"{where}: the insight line stands under the block header: give the sheet a title "
                                 f"or a subtitle")
            _check_phrase(where, s["insight"], calcs)
        for m in s.get("measures", []):
            if note(m) is not None:
                if s["type"] != "kpi" or s.get("style") != "tiles":
                    raise ValueError(f"{where}: 'note' is a line under a KPI tile's number (kpi style 'tiles')")
                _check_phrase(f"{where} note of '{m['field']}'", note(m), calcs)
        for k in ("measure", "plan"):
            if isinstance(s.get(k), dict) and note(s[k]) is not None:
                raise ValueError(f"{where}: 'note' is a line under a KPI tile's number (kpi style 'tiles')")
        if "legend" in s:
            color = s.get("color")
            if s["type"] not in LEGEND_TYPES or not isinstance(color, str):
                raise ValueError(f"{where}: legend 'inline' needs a {'/'.join(LEGEND_TYPES)} sheet colored by a "
                                 f"field (color: '<field>')")
            if "color" not in spec.get("fields", {}).get(color, {}):
                raise ValueError(f"{where}: legend 'inline' draws the colors of fields.{color}.color; give the "
                                 f"members their colors there (Tableau's own palette is not known to the spec)")
            if not head and not below(s):
                raise ValueError(f"{where}: legend 'inline' is a line of the block header: give the sheet a title "
                                 f"or a subtitle")
            _check_groups(where, s, spec["fields"][color])


def _check_groups(where, s, props):
    """legend.groups: each member of fields.<color>.color in one group, no unknown member (decisions/173)."""
    lg = s["legend"]
    if not isinstance(lg, dict) or "groups" not in lg:
        return
    seen = [v for g in lg["groups"] for v in g["values"]]
    unknown = [v for v in seen if v not in props["color"]]
    left = [v for v in props["color"] if v not in seen]
    if unknown or left or len(seen) != len(set(seen)):
        raise ValueError(f"{where}: legend.groups must list every member of the color field once "
                         f"(not in fields.<color>.color: {unknown}; in no group: {left})")


# ---- worksheets --------------------------------------------------------------------------------------------------
def sheets(b):
    return [part(s) for s in b.spec["sheets"] if "insight" in s]


def dashboard_sheets(b, names):
    """The insight sheets of the sheets on a dashboard."""
    return [record(s["name"]) for s in b.spec["sheets"] if "insight" in s and s["name"] in names]


def _shown_calcs(b, text):
    """The calcs a phrase shows: a signed calc as its Good and Bad sides."""
    sg = signed(b.spec)
    return [x for n in refs(text) for x in (side_calcs(n) if n in sg else (n,))]


def fields(b, text):
    """The phrase's calcs as text fields: a text aggregate discrete (:nk), a number :qk."""
    return [b._measure({"field": n}, text=True) for n in _shown_calcs(b, text)]


def shape(b, p):
    """sheet_shape of an insight line: its calcs on Text, no rows or columns."""
    fs = fields(b, p["sheet"]["insight"])
    return fs, None, None, [("text", b.q(f.name)) for f in fs], True, None


def runs(b, text, fs, pt):
    """[(text, attrs)] of a phrase: literal text muted, **bold** parts bold in the text color, [Calc] as its field."""
    by = {getattr(f.col, "caption", f.col.name): f for f in fs}
    out = []
    for t, bold, ref in tokens(text):
        attrs = {"bold": "true", "fontcolor": COLOR["text"]} if bold else {"fontcolor": COLOR["muted"]}
        attrs["fontsize"] = str(pt)
        if ref and t in signed(b.spec):  # the change: one side shows, in its color (decisions/139)
            g, bad = side_calcs(t)
            out += [(f"<{b.q(by[g].name)}>", {**attrs, "fontcolor": COLOR["good_text"]}),
                    (f"<{b.q(by[bad].name)}>", {**attrs, "fontcolor": COLOR["bad_text"]})]
        elif ref:
            out.append((f"<{b.q(by[t].name)}>", attrs))
        elif not t.strip() and out:  # a run of spaces only is dropped by Desktop: keep them in the run before
            out[-1] = (out[-1][0] + t, out[-1][1])
        else:
            out.append((t, attrs))
    return out


def label(b, pane, p, fs):
    """customized-label of an insight line: the phrase, left-aligned."""
    ft = ET.SubElement(ET.SubElement(pane, "customized-label"), "formatted-text")
    for text, attrs in runs(b, p["sheet"]["insight"], fs, FONT["insight"]):
        ET.SubElement(ft, "run", {"fontalignment": "0", **attrs}).text = text


def note_fields(b, tile):
    return fields(b, note(tile["measure"])) if note(tile["measure"]) else []


def note_label(b, ft, tile, fs):
    """The tile's third line: a line break, then the note phrase."""
    if not note(tile["measure"]):
        return
    ET.SubElement(ft, "run").text = "Æ\n"  # Tableau's line-break run
    for text, attrs in runs(b, note(tile["measure"]), fs, FONT["tile_note"]):
        ET.SubElement(ft, "run", attrs).text = text


def note_lines(s):
    """[(pt, 1)] a KPI tiles sheet adds to its tiles' text: one note line when any of its measures has one."""
    return [(FONT["tile_note"], 1)] if any(note(m) for m in s.get("measures", [])) else []


# ---- layout ------------------------------------------------------------------------------------------------------
def _shown(b, s):
    """The phrase as the page will read it, for its width: the calcs by their expected values."""
    got = b.expected.get(record(s["name"]), {})
    text = ""
    for t, _, ref in tokens(s["insight"]):
        text += _display(got.get(t), b.calcs.calcs[t].fmt) if ref else t
    return text.replace("**", "")


def _display(v, fmt):
    if v is None:
        return "0000"
    if isinstance(v, str):
        return v
    return formats.render(v, fmt) if formats.is_number_format(fmt) else f"{v:,.1f}"


def px(b, s, width_px):
    """Height of a block's insight zone: its lines, the pane padding, the gap under it; 0 without one."""
    if "insight" not in s:
        return 0
    n = design.text_lines(_shown(b, s), FONT["insight"], width_px)
    if n > MAX_LINES:
        raise ValueError(f"Sheet '{s['name']}': the insight needs ~{n} lines at {FONT['insight']}pt in a "
                         f"{width_px}px block (max {MAX_LINES}): shorten it or widen the block")
    return design.line_px(FONT["insight"]) * n + design.CARD_TEXT_PAD_PX + SPACE["header_gap"]


def zone(b, parent, s, box, cell):
    """The insight zone under the block header (box: x, y, w, h in zone units): margin-top 0 under the header, the
    header gap under it, the block's edges at its sides. Returns its height, 0 without one."""
    from . import spacing
    from .build import _sub
    if "insight" not in s:
        return 0
    x, y, w, h = box
    m = spacing.margins(box, cell, b.block_headers, edge=b._edge())
    m["top"], m["bottom"] = 0, SPACE["header_gap"]
    b._zone_style(_sub(parent, "zone", h=str(h), id=b._zid(), name=record(s["name"]), show_title="false", w=str(w),
                       x=str(x), y=str(y)), m)
    return h


# ---- inline legend -----------------------------------------------------------------------------------------------
def _order(b, s):
    p = b.spec["fields"][s["color"]]
    return p.get("order") or sorted(p["color"])


def _members(b, s, values):
    field = s["color"]
    return [(b.fields.shown(field, v), b.spec["fields"][field]["color"][v]) for v in values]


def legend(b, s):
    """[(label, color)] of a legend in the header, in the field's order; [] without one (or under the block)."""
    if not inline(s) or below(s):
        return []
    return _members(b, s, _order(b, s))


def below_lines(b, s):
    """The legend under the block: [(group label or '', [(label, color)])], one line per group; the groups in the
    spec order, their members in the field's order (decisions/173)."""
    if not below(s):
        return []
    order = _order(b, s)
    groups = s["legend"].get("groups") or [{"label": "", "values": order}]
    return [(g["label"], _members(b, s, [v for v in order if v in g["values"]])) for g in groups]


def stack_order(b, view, s):
    """A horizontal stacked bar drawn from the field's order: Tableau stacks the first member of the color field's
    sort farthest from the axis, so the view sorts the field backwards (manual-sort, as a plan's Measure Names:
    colors.measure_order). Only where our own legend names the order (inline / under the block); a legend card
    shows Tableau's order (decisions/173)."""
    if s["type"] != "bar" or s.get("orientation", "horizontal") != "horizontal" or not isinstance(s.get("color"), str) \
            or not inline(s) or "order" not in b.spec["fields"].get(s["color"], {}):
        return
    f = b._dim(s["color"])
    sort = ET.SubElement(view, "manual-sort", column=b.q(f.name), direction="ASC")
    d = ET.SubElement(sort, "dictionary")
    for v in reversed(b.spec["fields"][s["color"]]["order"]):
        ET.SubElement(d, "bucket").text = f'"{v}"'  # as fields._bucket
    for i, el in enumerate(view):  # the view's sorts by column, as Desktop saves them (decisions/057, 185)
        if el.tag == "computed-sort" and el.get("column") > sort.get("column"):
            view.remove(sort)
            view.insert(i, sort)
            break


def legend_wrap(tokens, pt, width_px):
    """The tokens of a legend (a group label, a member with its swatch) by the lines they take in width_px: Desktop's
    text metric, not the character estimate (decisions/185). Each token counts with the gap after it, the last of a
    line too, and the zone keeps its text pad: a line that only just holds its ink must not wrap on its own."""
    lines, line = [[]], ""
    for tok in tokens:
        tok = tok.rstrip() + LEGEND_GAP
        if lines[-1] and design.text_px(line + tok, pt) + design.HEADER_TEXT_PAD_PX > width_px:
            lines.append([])
            line = ""
        lines[-1].append(tok)
        line += tok
    return lines


def too_wide(tokens, pt, width_px):
    """The tokens of a legend wider than width_px on a line of their own: nothing can show them whole."""
    return [tok.rstrip() for tok in tokens if design.text_px(tok.rstrip(), pt) + design.HEADER_TEXT_PAD_PX > width_px]


def _tokens(label, items):
    return ([label + ": "] if label else []) + [SQUARE + lab + LEGEND_GAP for lab, *_ in items]


def below_rows(b, s, width_px, pt):
    """The lines the legend under the block is drawn in, [(group label or '', members)]: the wrap is ours, an explicit
    break between members (Desktop breaks a free wrap inside a label, a no-break space too: decisions/185). A label
    wider than the block is refused: it would be cut."""
    rows = []
    for label, items in below_lines(b, s):
        tokens = _tokens(label, items)
        wide = too_wide(tokens, pt, width_px)
        if wide:
            raise ValueError(f"Sheet '{s['name']}': the legend under the block has {width_px}px and cannot show "
                             f"{wide[0]!r} ({design.text_px(wide[0], pt)}px) whole: widen the block or shorten the label")
        members = iter(items)
        for i, line in enumerate(legend_wrap(tokens, pt, width_px)):
            first = label if i == 0 else ""
            rows.append((first, [next(members) for _ in line[1 if first else 0:]]))
    return rows


def below_px(b, s, width_px, pt):
    """Height of the legend under the block with its margins, 0 without one."""
    rows = below_rows(b, s, width_px, pt)
    return design.line_px(pt) * len(rows) + SPACE["zone_margin"] + b._edge() if rows else 0


def below_zone(b, parent, s, box, cell, pt, width_px):
    """The text zone of the legend under the block (box, cell: x, y, w, h in zone units; width_px: inside its margins):
    per line the group label muted and the members, the lines apart by a break run."""
    from . import spacing
    from .build import _sub
    x, y, w, h = box
    z = _sub(parent, "zone", forceUpdate="true", h=str(h), id=b._zid(), type_v2="text", w=str(w), x=str(x), y=str(y))
    ft = _sub(z, "formatted-text")
    for i, (label, items) in enumerate(below_rows(b, s, width_px, pt)):
        if i:
            ET.SubElement(ft, "run").text = "Æ\n"
        if label:
            ET.SubElement(ft, "run", fontcolor=COLOR["muted"], fontsize=str(pt)).text = label + ": "
        legend_runs(ft, items, pt, False)
    b._zone_style(z, spacing.margins(box, cell, b.block_headers, edge=b._edge()))


def legend_text(items):
    return "".join(SQUARE + lab + LEGEND_GAP for lab, *_ in items).rstrip()


def legend_px(b, s, width_px, pt):
    """Height of the legend line(s) in the header."""
    items = legend(b, s)
    if not items:
        return 0
    return design.line_px(pt) * design.text_lines(legend_text(items), pt, width_px)


def legend_runs(ft, items, pt, after_text):
    """The legend line at the end of a header text: a line break, then per member its swatch in its color and its
    label muted. An item (label, color, glyph) has its own swatch (a status dot: decisions/062)."""
    if not items:
        return
    if after_text:
        ET.SubElement(ft, "run").text = "Æ\n"
    for i, (lab, color, *glyph) in enumerate(items):
        ET.SubElement(ft, "run", fontcolor=color.lower(), fontsize=str(pt)).text = glyph[0] if glyph else SQUARE
        ET.SubElement(ft, "run", fontcolor=COLOR["muted"], fontsize=str(pt)).text = \
            lab + (LEGEND_GAP if i < len(items) - 1 else "")


# ---- expected numbers and reconcile ------------------------------------------------------------------------------
def expected(spec, calcs, rows, out):
    """The phrases' values over the rows the workbook shows (one mark: no dimensions on the sheet)."""
    from .formula import View
    view = View([], rows)
    for s in spec["sheets"]:
        if "insight" in s:
            out[record(s["name"])] = {n: calcs.agg_value(n, rows, view) for n in refs(s["insight"])}
        noted = [m for m in s.get("measures", []) if note(m)] if s["type"] == "kpi" else []
        if noted:
            out[notes_record(s["name"])] = {m.get("label", m["field"]): {n: calcs.agg_value(n, rows, view)
                                                                          for n in refs(note(m))} for m in noted}


def _words(t):
    return [w.lower() for w in WORD.findall(t)]


def adjacency(text, values):
    """{calc: (words before, words after)} of each number calc of a phrase: the literal words between it and the
    previous / next number calc in its segment; a text calc reads as its value ('Busiest day: Thu (')."""
    out = {}
    toks = tokens(text)
    for i, (t, _, ref) in enumerate(toks):
        if not ref or isinstance(values.get(t), str):
            continue

        def side(seq, last):
            acc = []
            for u, _, r in seq:
                if r and not isinstance(values.get(u), str):  # the next number: its own words
                    break
                cut = SEP.split((values.get(u) if r else u) or "")
                acc.append(cut[-1] if last else cut[0])
                if len(cut) > 1:  # the segment ends
                    break
            return acc
        after = "".join(side(toks[i + 1:], False))
        before = "".join(reversed(side(reversed(toks[:i]), True)))
        out[t] = (_words(before), _words(after))
    return out


def entries(s, exp, fmt, entry):
    """reconcile entries of a sheet's insight line and its tiles' notes: entry(sheet, key, tags, value, part, fmt)
    -> dict; each carries 'phrase' (words before, words after) that the page must show right next to the number."""
    out = []
    phrases = []
    if "insight" in s:
        phrases.append((s["insight"], exp.get(record(s["name"]), {}), [], "insight"))
    if s["type"] == "kpi":
        got = exp.get(notes_record(s["name"]), {})
        for m in s.get("measures", []):
            if note(m):
                lab = m.get("label", m["field"])
                phrases.append((note(m), got.get(lab, {}), [lab], f"note of '{lab}'"))
    for text, values, tags, where in phrases:
        for n, (before, after) in adjacency(text, values).items():
            e = entry(s["name"], "", tags + [n], values.get(n), part=where, fmt=fmt({"field": n}))
            e["phrase"] = (before, after)
            out.append(e)
    return out


def next_to(f, phrase):
    """Does the page show the number f with the phrase's words right before or after it?"""
    text, start = f.get("around") or (f["text"], f.get("start"))  # a number in an element of its own (decisions/200)
    if start is None:
        return False
    pre = _words(SEP.split(text[:start])[-1])
    post = _words(SEP.split(text[start + len(f["number"]):])[0])

    def agree(page, words):
        k = min(len(page), len(words))
        return k > 0 and page[:k] == words[:k]
    before, after = phrase
    return agree(pre[::-1], before[::-1]) or agree(post, after)
