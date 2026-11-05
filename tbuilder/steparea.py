"""Step line and step area (decisions/144, 158): step: true on a line or an area holds each value until the next
period, a vertical jump at each change.

Spec: step on a line (144) or an area (158); labels: last on a step area names its last value (a step line labels its
ends as any line: benchmark.ends).

XML (forms from Desktop books):
- a line: <format attr='line-interpolation' value='step'/> in the pane's mark rule (the step line books, 144);
- an area: Desktop 2025.1 keeps line-interpolation on an Area but draws it linear (the snapshot of 158: slopes between
  the months), so the area is the reference 'Stepped Area Chart': Bars as wide as their period on the date axis,
  their left edge at the date, side by side a stepped silhouette:
  <mark class='Bar'/><mark-sizing custom-mark-size-in-axis-units=<days> mark-alignment='mark-alignment-left'
  mark-sizing-setting='marks-scaling-on' use-custom-mark-size='true'/>. The width is in days on a date axis
  (reference: 7.0 on weeks); a month is 31 (28..31 days: a few days over the next bar, opaque, never a gap), a
  quarter 92, a year 366. Its last period has its width too (a step line's last value has none). The label of the
  last value: 'most-recent' (the latest date's mark, as a KPI history's bars write it), not 'line-ends' (lines).
  has-stroke false (reference): without it each bar keeps a white border, a 1 px gap between the steps (snapshot);
  <cols include-empty='true'> (Show Empty, as RWFD Call Center writes it on Rows): the periods without rows
  get their mark, so a running total holds its level over them instead of a hole (snapshot of 158); not under panels
  (facet): Desktop then shows an empty panel column next to theirs.
"""
import xml.etree.ElementTree as ET

from . import facetgrid

DAYS = {"day": 1, "week": 7, "month": 31, "quarter": 92, "year": 366}  # a bar per period, never narrower


def is_step(s):
    return s["type"] in ("line", "area") and bool(s.get("step"))


def is_area(s):
    return is_step(s) and s["type"] == "area"


def width(s):
    return DAYS[s["date"].get("level", "month")]


def labelled(s):
    """A step area with labels at its end: its last value (labels: last) or a panel's name (facet cols, 144)."""
    return is_area(s) and (s.get("labels") == "last" or bool(facetgrid.cols(s)))


def label_data(b, pane, s, fields):
    """'most-recent' is the latest date: Desktop declares MAX(date) as the pane's label-data (a KPI history's bars;
    the re-save of 158 added it to a step area without it)."""
    if not labelled(s):
        return
    date = b.col(s["date"]["field"]).name
    latest = next(f for f in fields if f.kind == "agg" and f.col.name == date and f.name.startswith("[max:"))
    ET.SubElement(pane, "label-data", column=b.q(latest.name))


def mark(pane, s):
    """A step area's marks: Bars as wide as the period, from the date to the right (before the encodings)."""
    if not is_area(s):
        return
    pane.find("mark").set("class", "Bar")
    ET.SubElement(pane, "mark-sizing", {"custom-mark-size-in-axis-units": f"{float(width(s))}",
                                        "mark-alignment": "mark-alignment-left",
                                        "mark-sizing-setting": "marks-scaling-on", "use-custom-mark-size": "true"})


def shelves(s, cols_el):
    if is_area(s) and not facetgrid.facet(s):  # panels: an empty panel column besides theirs (snapshot of 158)
        cols_el.set("include-empty", "true")


def pane_style(pane, s):
    if is_area(s) and s.get("labels") == "ends":
        raise ValueError(f"Sheet '{s['name']}': a step area labels its last value only (labels: last)")
    if not is_step(s):
        return
    st = pane.find("style")
    st = ET.SubElement(pane, "style") if st is None else st
    rule = st.find("style-rule[@element='mark']")
    rule = ET.SubElement(st, "style-rule", element="mark") if rule is None else rule
    if s["type"] == "line":
        ET.SubElement(rule, "format", attr="line-interpolation", value="step")
        return
    for f in list(rule.iterfind("format")):  # the line-end labels (its value, a panel's name) on the latest bar
        if f.get("attr") == "mark-labels-mode" and f.get("value") == "line-ends":
            f.set("value", "most-recent")
        elif f.get("attr") == "mark-labels-line-first":
            rule.remove(f)
    ET.SubElement(rule, "format", attr="has-stroke", value="false")  # no border: Desktop's own leaves a white line
