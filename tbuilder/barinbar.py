"""Bar-in-bar (decisions/156; reference 'Ungrouped Stacked Bar Chart'): the member's
total as a wide muted bar, the parts of its color field side by side inside it, each in its color.

Spec: bar {dimension, measure, color: <field>, parts: inside, orientation: vertical, sort?, legend?}.
- vertical only: with both axes continuous Desktop draws a bar along the rows' axis, so a horizontal one ran
  along the position (lab 156: thin bars labelled -1.000 / 0.000 / 1.000);
- the total and each part labelled at its end, every label shown (no cull), the axes hidden (design rule I9); the parts in the categorical palette
  (fields.<field>.color when given; C2: up to 5 parts), the total in the bar-in-cell grey (C1);
- not with a plan, reference lines, total 'end', value_column, labels, Top N, a date_level, a facet or a table
  calculation on the measure.

XML (the reference's sheet '1', Desktop 2025.1):
- the measure twice on its shelf, folded synchronized ('(M + M)', class 1, as a donut's: dualaxis.py); the member and
  a continuous position on the other shelf: '(member * position)' (reference '(Region * INDEX())');
- position = INDEX() - (SIZE() + 1) / 2 along the part field: the parts at -(N-1)/2 .. (N-1)/2 a step apart, the
  total's layer (no part field on its marks) a single mark at 0. Its INDEX() alone puts the total at 1 and the
  parts at 1..N: the parts off the total's centre;
- each layer's mark size in units of the position axis (mark-sizing marks-scaling-on, use-custom-mark-size,
  custom-mark-size-in-axis-units, mark-alignment-center): the total N + TOTAL_PAD wide, a part PART wide, whatever
  the zone's size; the position axis fixed to the total's width and GAP more, so neither edge is clipped and members stand apart.
"""
import xml.etree.ElementTree as ET

from .design import COLOR

PART = 0.75  # a part's width, a step of 1 between parts
TOTAL_PAD = 0.5  # the total wider than its N steps: the outer parts clear of its edges; sizes exact in binary
# (Desktop rewrites 3.3 as 3.2999999999999998)
GAP = 1.0  # the position axis this much wider than the total: the gap between two members' totals
SELECTION = "selection-relaxation-allow"


def on(s):
    return s["type"] == "bar" and s.get("parts") == "inside"


def pos_calc(s):
    return f"{s['name']} · Position"


def total_record(s):
    """expected.py record of the members' totals (the wide bars' labels)."""
    return f"{s['name']} · Total"


def check(spec):
    for s in spec["sheets"]:
        if s["type"] != "bar" or "parts" not in s:
            continue
        where = f"Sheet '{s['name']}'"
        if not isinstance(s.get("color"), str) or s["color"] == s["dimension"]:
            raise ValueError(f"{where}: parts 'inside' needs 'color': the field whose parts stand inside the "
                             f"member's bar (decisions/156)")
        if s.get("orientation") != "vertical":
            raise ValueError(f"{where}: parts 'inside' is a vertical bar: set orientation 'vertical' (with both "
                             f"axes continuous Desktop draws a horizontal one along the position; decisions/156)")
        other = [k for k in ("plan", "reference", "total", "value_column", "labels", "top", "date_level", "facet",
                             "margin") if k in s]
        if other or "table_calc" in s["measure"]:
            raise ValueError(f"{where}: parts 'inside' does not go with "
                             f"{', '.join(other) or 'a table calculation'} (decisions/156)")


def calcs(spec):
    return [{"name": pos_calc(s), "formula": "INDEX() - (SIZE() + 1) / 2", "compute_using": [s["color"]]}
            for s in spec["sheets"] if on(s)]


def encode(b, s, fields):
    """The position after the bar's fields (dimension, measure, part)."""
    if on(s):
        from .build import Field
        fields.append(Field(b.col(pos_calc(s)), "agg", "user"))


def parts_n(b, s):
    """The most parts a member has: the total's width in steps."""
    per = {}
    for k in b.expected.get(s["name"], {}):
        member = k.split(" | ")[0]
        per[member] = per.get(member, 0) + 1
    return max(per.values(), default=1)


def table(b, table_el, style, s, fields):
    """The fold, the hidden axes and the fixed position axis (worksheet style), a pane per layer, the shelves."""
    from .colors import _rule
    d, m, part, pos = fields[:4]
    mscope, pscope, xy = "rows", "cols", "y"  # vertical only (check)
    n = parts_n(b, s)
    half = (n + TOTAL_PAD + GAP) / 2
    axis = _rule(style, "axis", before=("cell", "header", "label", "mark", "pane", "table", "worksheet", "gridline",
                                        "zeroline", "table-div"))
    head = [ET.Element("encoding", {"attr": "space", "class": "0", "field": b.q(pos.name),
                                    "field-type": "quantitative", "max": f"{half:g}", "min": f"{-half:g}",
                                    "range-type": "fixed", "scope": pscope, "type": "space"}),
            ET.Element("encoding", {"attr": "space", "class": "1", "field": b.q(m.name), "field-type": "quantitative",
                                    "fold": "true", "scope": mscope, "synchronized": "true", "type": "space"})]
    head += [ET.Element("format", {"attr": "display", "class": cls, "field": b.q(f.name), "scope": scope,
                                   "value": "false"})
             for cls, f, scope in (("0", m, mscope), ("1", m, mscope), ("0", pos, pscope))]
    for i, el in enumerate(head):
        axis.insert(i, el)
    panes = ET.SubElement(table_el, "panes")
    default = ET.SubElement(panes, "pane", {"selection-relaxation-option": SELECTION})
    ET.SubElement(ET.SubElement(default, "view"), "breakdown", value="auto")
    ET.SubElement(default, "mark", {"class": "Bar"})
    layers = [(n + TOTAL_PAD, [], [("mark-color", COLOR["cell_bar"])]), (PART, [("color", part)], [])]
    for i, (size, encs, fmts) in enumerate(layers, 1):
        attrs = {"id": str(i), "selection-relaxation-option": SELECTION, f"{xy}-axis-name": b.q(m.name)}
        if i == 2:
            attrs[f"{xy}-index"] = "1"
        pane = ET.SubElement(panes, "pane", attrs)
        ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
        ET.SubElement(pane, "mark", {"class": "Bar"})
        ET.SubElement(pane, "mark-sizing", {"custom-mark-size-in-axis-units": f"{size:g}",
                                            "mark-alignment": "mark-alignment-center",
                                            "mark-sizing-setting": "marks-scaling-on", "use-custom-mark-size": "true"})
        if encs:
            e = ET.SubElement(pane, "encodings")
            for tag, f in encs:
                ET.SubElement(e, tag, column=b.q(f.name))
        rule = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", element="mark")
        for attr, value in fmts + [("mark-labels-show", "true")]:  # culled, a part's label next to a taller one hid
            ET.SubElement(rule, "format", attr=attr, value=value)
    member = f"({b.q(d.name)} * {b.q(pos.name)})"
    shelf = f"({b.q(m.name)} + {b.q(m.name)})"
    ET.SubElement(table_el, "rows").text = shelf
    ET.SubElement(table_el, "cols").text = member


def expected(s, rows, dim, value, grouped):
    """member -> its total (the wide bar's label)."""
    return grouped(rows, [dim(s["dimension"])], value(s["measure"]))


# ---- gate (decisions/156) ----------------------------------------------------------------------------------------
FORMULA = "INDEX() - (SIZE() + 1) / 2"


def gate(root):
    """A bar-in-bar sheet (two Bar layers of a fold, each sized in axis units) as it reads: the total's layer without
    the part field, so one bar per member; the parts' layer colored by it; the position centred along that part field
    (else the parts pile on one spot or leave the total's centre); the total wider than a part and the position axis
    fixed wide enough for the total (else its edges are clipped)."""
    from .gate import DUAL_SHELF_REF, Issue
    issues = []
    for ws in root.iter("worksheet"):
        table, where = ws.find("table"), f"worksheet '{ws.get('name')}'"
        panes = [p for p in table.iterfind("panes/pane[@id]")
                 if p.find("mark[@class='Bar']") is not None
                 and p.find("mark-sizing[@use-custom-mark-size='true']") is not None]
        fold = table.find("style/style-rule[@element='axis']/encoding[@fold='true']")
        if len(panes) != 2 or fold is None:
            continue
        pscope = "rows" if fold.get("scope") == "cols" else "cols"
        refs = DUAL_SHELF_REF.findall(table.findtext(pscope) or "")
        pos = next((r for r in refs if ":qk" in r and r.split("].[")[-1].startswith("usr:")), None)
        if pos is None:
            continue
        sizes = [float(p.find("mark-sizing").get("custom-mark-size-in-axis-units", "1")) for p in panes]
        colors = [p.find("encodings/color") for p in panes]
        total, part = (0, 1) if colors[0] is None else (1, 0)
        if colors[part] is None or colors[total] is not None:
            issues.append(Issue("bar-in-bar", where, "one layer is the total (no color) and the other the parts "
                                                     "(color by the part field): the total splits or the parts "
                                                     "are one bar"))
            continue
        inst = pos.split("].[")[-1].rstrip("]")
        ci = next((c for c in table.iter("column-instance") if c.get("name") == f"[{inst}]"), None)
        col = ci.get("column") if ci is not None else None
        calc = next((c.find("calculation") for c in table.iter("column") if c.get("name") == col), None)
        tc = ci.find("table-calc") if ci is not None else None
        if calc is None or " ".join(calc.get("formula", "").split()) != FORMULA:
            issues.append(Issue("bar-in-bar", where, f"the position is not {FORMULA}: the parts leave the total's "
                                                     f"centre"))
        elif tc is None or tc.get("ordering-field") != colors[part].get("column"):
            issues.append(Issue("bar-in-bar", where, "the position does not run along the part field: the parts "
                                                     "stand on one spot"))
        if sizes[total] <= sizes[part]:
            issues.append(Issue("bar-in-bar", where, f"the total ({sizes[total]:g}) is not wider than a part "
                                                     f"({sizes[part]:g}): the parts hide it"))
        rng = table.find(f"style/style-rule[@element='axis']/encoding[@field='{pos}'][@range-type='fixed']")
        half = sizes[total] / 2
        if rng is None or float(rng.get("max", 0)) <= half or float(rng.get("min", 0)) >= -half:
            issues.append(Issue("bar-in-bar", where, f"the position axis is not fixed wider than -{half:g}..{half:g}: "
                                                     f"the total bar is clipped or touches the next member's"))
    return issues
