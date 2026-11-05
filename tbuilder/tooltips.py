"""A sheet's own tooltip: a phrase with fields (todo 3.11, decisions/036).

spec: "tooltip": "Region: <Region>\\nSales: <SUM(Sales)>"
- <Field> is a dimension (or a date) on the sheet, or the one measure of that field on it;
  <AGG(Field)> a measure: SUM, AVG, MIN, MAX, COUNT, COUNTD of a column, AGG(<aggregate calc>) as Tableau names it.
- A measure that is not on the sheet goes on its Tooltip shelf (<tooltip column> in the pane's encodings, the form
  of Sample Superstore); a dimension that is not on the sheet is refused: on the Tooltip shelf it would split the
  marks and change every number.
- A strip / beeswarm (decisions/172): a dot is a row id, so a dimension that is not on the sheet but is one value per
  id (client, warehouse, day) goes on the Tooltip shelf as ATTR() without splitting the dots, the jitter runs along
  the id only (decisions/176: a plain dimension there blanks the sheet); several values per id are refused.
- No helper field (data-ink, decisions/018): a meaning-color flag, a reference line measure is refused.
Written as Desktop's tooltip editor writes it (formatted-text, tbuilder/ink.py style): the text grey, a field's
value bold, **text** bold as a field (a title's markup: no asterisks shown, decisions/176), a line break is the
run 'Æ\\n'; a run of spaces alone is dropped by Desktop, so spaces between two
fields stay in the field's run (Loan Retention: '<[..label_0d:nk]> ').
The gate checks that every field of a tooltip is on the sheet (gate.check_tooltips).
"""
import re
import xml.etree.ElementTree as ET

from . import distviz
from .design import COLOR

TYPES = ("bar", "line", "area", "table", "heatmap", "strip", "beeswarm")
REF = re.compile(r"<([^<>]+)>")
AGG_REF = re.compile(r"^(SUM|AVG|MIN|MAX|COUNT|COUNTD|AGG)\((.+)\)$")
PREFIX = {"sum": "SUM", "avg": "AVG", "min": "MIN", "max": "MAX", "cnt": "COUNT", "ctd": "COUNTD", "usr": "AGG"}
LINE_BREAK = "Æ\n"  # Tableau's line-break run


def of(s):
    return s.get("tooltip")


def check(spec):
    for s in spec["sheets"]:
        if of(s) is not None and s["type"] not in TYPES:
            raise ValueError(f"Sheet '{s['name']}': a tooltip template applies to {', '.join(TYPES)}, not a "
                             f"{s['type']} (its numbers are on the marks)")


def _agg_name(f):
    """'SUM' of [sum:Sales:qk], 'AGG' of an aggregate calc, None for a dimension or a date."""
    if f.kind != "agg":
        return None
    return PREFIX.get(f.name[1:].split(":")[-3])  # a table calc instance: [pcto:sum:Sales:qk]


def _caption(f):
    return getattr(f.col, "caption", f.col.name)


def resolve(b, s, fields, helpers):
    """-> [(text, field | None)] per segment of the template, and the measures it puts on the Tooltip shelf."""
    where = f"Sheet '{s['name']}' tooltip"
    shelf, out = [], []

    def find(ref):
        m = AGG_REF.match(ref.strip())
        on = [f for f in fields + shelf if (_caption(f) == (m.group(2) if m else ref.strip())
                                            or f.col.name == (m.group(2) if m else ref.strip()))]
        if m:
            on = [f for f in on if _agg_name(f) == m.group(1)]
        elif len([f for f in on if f.kind != "agg"]) == 1:
            on = [f for f in on if f.kind != "agg"]
        if len(on) == 1:
            if on[0] in helpers:
                raise ValueError(f"{where}: <{ref}> is a helper field of the sheet, not data (decisions/018)")
            return on[0]
        if len(on) > 1:
            raise ValueError(f"{where}: <{ref}> is ambiguous on this sheet: name the aggregation, "
                             f"<{_agg_name(on[0])}({ref})>")
        if not m and distviz.kind(s) in (distviz.STRIP, distviz.SWARM):
            f = distviz.tooltip_dim(b, s, ref.strip())
            if f is not None:
                shelf.append(f)
                return f
        if not m:
            raise ValueError(f"{where}: <{ref}> is not on the sheet; a dimension on the Tooltip shelf would split "
                             f"the marks: name a measure as <SUM({ref})> or put the field on the sheet")
        agg, name = m.group(1), m.group(2)
        calc = getattr(b.col(name), "calc", None)
        if (agg == "AGG") != bool(calc and calc.is_agg):
            raise ValueError(f"{where}: <{ref}>: " + (f"'{name}' is an aggregate calculation, write <AGG({name})>"
                                                      if agg != "AGG" else
                                                      f"'{name}' is not an aggregate calculation, name its "
                                                      f"aggregation: <SUM({name})>"))
        f = b._measure({"field": name} if agg == "AGG" else {"field": name, "agg": agg.lower()})
        shelf.append(f)
        return f

    for i, line in enumerate(of(s).split("\n")):
        if i:
            out.append((LINE_BREAK, None))
        pos = 0
        for m in REF.finditer(line):
            if m.start() > pos:
                out.append((line[pos:m.start()], None))
            out.append((m.group(0), find(m.group(1))))
            pos = m.end()
        if pos < len(line):
            out.append((line[pos:], None))
    return out, shelf


def write(b, pane, s, segments):
    """customized-tooltip of a pane: text grey, fields bold; spaces alone join the field before them."""
    ft = ET.SubElement(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), "formatted-text")
    runs, bold = [], False  # [attrs, text]; bold: inside **...** of the line (decisions/176)
    for seg, f in segments:
        if f is not None:
            runs.append([{"bold": "true"}, f"<{b.q(f.name)}>"])
            continue
        if seg == LINE_BREAK:
            runs.append([{}, seg])
            bold = False
            continue
        for i, text in enumerate(seg.split("**")):
            bold = bold != (i > 0)
            if not text.strip() and text and runs and runs[-1][1] != LINE_BREAK:
                runs[-1][1] += text  # Desktop drops a run of spaces alone
            elif text.strip():
                runs.append([{"bold": "true"} if bold else {"fontcolor": COLOR["muted"]}, text])
    for attrs, text in runs:
        ET.SubElement(ft, "run", attrs).text = text
