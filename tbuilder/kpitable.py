"""The KPI table (a `kpi` sheet in the default style, also arrange 'strip'): Measure Names on Columns, Measure Values as
text (decisions/106). Three things Tableau does on its own and the HTML does not:

  labels   a column header is the measure's name; the spec's `label` is the alias of the Measure Names member
           (<column name='[:Measure Names]'><aliases><alias key='"[ds].[sum:Revenue:qk]"' value='Revenue'/>)
  order    Measure Names sort alphabetically; the spec order is a manual-sort in the view (as colors.measure_order)
  numbers  one automatic format for all Measure Values shows a whole sum as '527.0' next to a real measure: an integer
           measure without a format of its own gets the whole-number default-format (n#,##0)
"""
import xml.etree.ElementTree as ET

from .colors import MEASURE_NAMES

WHOLE = {"type": "number", "decimals": 0}
KEEPS_INTEGER = ("sum", "min", "max", "count", "countd")  # avg and the like give fractions: no whole-number format


def is_table(s):
    """A kpi sheet drawn as one table (not tiles or cards: those are a worksheet per measure)."""
    return s["type"] == "kpi" and s.get("style", "table") not in ("tiles", "cards")


def _keeps_integer(b, m):
    col = b.col(m["field"])
    return col.datatype == "integer" and (getattr(getattr(col, "calc", None), "is_agg", False)
                                          or m.get("agg", "sum") in KEEPS_INTEGER)


def whole_formats(b):
    """Gives the integer measures of the KPI tables a whole-number format, unless the spec set one or the field is
    used as a fraction elsewhere (a field has one default-format, decisions/032)."""
    spec = b.spec
    tables = [s for s in spec["sheets"] if is_table(s)]
    fractional = {m["field"] for s in spec["sheets"] for m in _all_measures(s) if not _keeps_integer(b, m)}
    for s in tables:
        for m in s["measures"]:
            name = m["field"]
            if "format" in m or name in fractional or not _keeps_integer(b, m):
                continue
            col = b.col(name)
            calc = getattr(col, "calc", None)
            if calc is not None:
                if calc.fmt is None:
                    calc.fmt = WHOLE
            elif name not in b.number_formats:
                b.number_formats[name] = WHOLE


def _all_measures(s):
    from . import formats
    return formats.measures(s)


def aliases(b):
    """{Measure Names member: label} of the KPI tables, in the spec order; only the measures with a `label`."""
    out = {}
    for s in b.worksheets:
        if not is_table(s):
            continue
        labels = [m["label"] for m in s["measures"] if "label" in m]
        if len(set(labels)) != len(labels):
            raise ValueError(f"KPI '{s['name']}': column labels must be unique, got {labels}")
        for m in s["measures"]:
            if "label" not in m:
                continue
            key = b.q(b._measure(m).name)
            if out.setdefault(key, m["label"]) != m["label"]:
                raise ValueError(f"KPI '{s['name']}': '{m['field']}' is labelled '{m['label']}' here and "
                                 f"'{out[key]}' in another KPI table; a Measure Names alias is the workbook's")
    return out


def column(parent, found):
    """The datasource column [:Measure Names] with the labels as aliases."""
    el = ET.SubElement(parent, "column", caption="Measure Names", datatype="string", name=MEASURE_NAMES,
                       role="dimension", type="nominal")
    al = ET.SubElement(el, "aliases")
    for key, label in found.items():
        ET.SubElement(al, "alias", key=f'"{key}"', value=label)
    return el


def measure_order(b, view, s, names):
    """The columns in the spec order (a manual-sort of Measure Names, as colors.measure_order writes it)."""
    if not is_table(s):
        return
    sort = ET.SubElement(view, "manual-sort", column=b.q(MEASURE_NAMES), direction="ASC")
    d = ET.SubElement(sort, "dictionary")
    for m in names:
        ET.SubElement(d, "bucket").text = f'"{b.q(m.name)}"'
