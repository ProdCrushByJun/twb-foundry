"""Treemap (decisions/138): a rectangle per member of the label, its area the size measure, nested in the group.

Spec: {type: treemap, size, label, group?, value?, color?}
- size: the measure on Size (the area);
- label: the dimension a rectangle stands for, its text;
- group: a dimension one level up: the rectangles of a member stay together (Keyword Research 'Treemap');
- value: true -> a second line under the label, the size measure;
- color: none -> the house sequential scale by the size measure (scale_low -> accent, the heatmap's, decisions/041),
  as the reference authors color by the value (references G2G, Citizen); {highlight: [members of group, or of
  label without a group]} -> those accent, the rest muted, no legend (the meaning in the subtitle, decisions/016).

XML (forms from 7 Desktop books, data/refs/treemap): empty Rows and Columns, <mark class='Square'/> (Keyword
Research, Citizen), the measure on <size>, the group on <lod> ahead of the label on <text> (the nesting follows the
marks card order), the scale in the worksheet style-rule 'mark' (Citizen, G2G); in the pane style-rule 'mark'
mark-labels-show + mark-labels-cull (all 7: the labels that do not fit are hidden) and a white stroke between the
rectangles (G2G, Student Portrait, Citizen). Label color stays automatic: light text on dark rectangles.
"""
from . import heatmap
from .design import COLOR

TYPE, BUBBLES = "treemap", "bubbles"  # packed bubbles: the treemap as circles (decisions/141, NADAC 'Sheet 3')
SCALE = {"scale": "sequential"}
def stroke():
    return ("has-stroke", "true"), ("stroke-color", COLOR["card_bg"])




def is_treemap(s):
    return s["type"] in (TYPE, BUBBLES)


def highlight(s):
    c = s.get("color")
    return isinstance(c, dict) and "highlight" in c


def highlight_field(s):
    return s.get("group", s["label"])


def highlight_calc(s):
    return f"{s['name']} · Highlight"


def check(spec, prof):
    """Highlight members are in their field (the schema checks the shapes)."""
    for s in spec["sheets"]:
        if not is_treemap(s) or not highlight(s):
            continue
        f = prof.col(highlight_field(s))
        missing = [v for v in s["color"]["highlight"] if v not in f.distinct]
        if missing:
            raise ValueError(f"Sheet '{s['name']}': highlight values {missing} are not in '{highlight_field(s)}' "
                             f"(values: {f.distinct[:12]})")


def calcs(spec):
    """The highlight flag: [group] = "A" OR ... (a row-level boolean dimension, as colors.highlight)."""
    return [{"name": highlight_calc(s),
             "formula": " OR ".join(f'[{highlight_field(s)}] = "{v}"' for v in s["color"]["highlight"])}
            for s in spec["sheets"] if is_treemap(s) and highlight(s)]


def palettes(b):
    """The highlight flag's palette map: accent / muted (build._palettes)."""
    out = {}
    for s in b.worksheets:
        if is_treemap(s) and highlight(s):
            col = b.calc_cols[highlight_calc(s)].name
            out[f"[none:{col}:nk]"] = (col, "None", [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])])
    return out


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape).
    fields: label, size measure, then the group, the highlight flag."""
    d, m = b._dim(s["label"]), b._measure(s["size"])
    fields = [d, m]
    if highlight(s):
        c = b._dim(highlight_calc(s))
        fields.append(c)
        enc = [("color", b.q(c.name))]
    else:
        enc = [("color", b.q(m.name))]
    enc.append(("size", b.q(m.name)))
    if "group" in s:
        g = b._dim(s["group"])
        fields.append(g)
        enc.append(("lod", b.q(g.name)))
    enc.append(("text", b.q(d.name)))
    if s.get("value"):
        enc.append(("text", b.q(m.name)))
    return fields, None, None, enc, True, None


def style(b, style_el, s, fields):
    """The sequential scale by the size measure in the worksheet's 'mark' rule."""
    if is_treemap(s) and not highlight(s):
        heatmap.encoding(style_el, SCALE, b.q(fields[1].name), *heatmap.palette(SCALE))


def mark_style(rule, s):
    """The pane's 'mark' rule after the labels: white lines between the rectangles."""
    if is_treemap(s):
        for attr, value in stroke():
            rule.append(rule.makeelement("format", {"attr": attr, "value": value}))


def expected(s, rows, dim, value, grouped):
    """(group,) label -> the size measure."""
    keys = ([dim(s["group"])] if "group" in s else []) + [dim(s["label"])]
    return grouped(rows, keys, value(s["size"]))
