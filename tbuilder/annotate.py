"""Point annotations of a line / area (polish-26): annotate {top: N} labels the N largest values only.

A static <annotation class='point'> (WebsiteTraffic, Waffle Charts) pins a tuple of values and goes stale when the
data or a filter changes; a label calc keeps the N largest marks named: IF RANK(agg) <= N THEN agg END along the
date (null elsewhere: no label), on the Label shelf with the labels shown.
"""


def calc_name(s):
    return f"{s['name']} · Top"


def on(s):
    return s["type"] in ("line", "area") and "annotate" in s


def calcs(spec):
    aggregates = {c["name"] for c in spec.get("calcs", []) if _is_agg(c["formula"])}
    out = []
    for s in spec["sheets"]:
        if not on(s):
            continue
        m = s["measure"]
        expr = f"[{m['field']}]" if m["field"] in aggregates else f"{m.get('agg', 'sum').upper()}([{m['field']}])"
        out.append({"name": calc_name(s), "formula": f"IF RANK({expr}) <= {s['annotate']['top']} THEN {expr} END",
                    "compute_using": [s["date"]["field"]], **({"format": m["format"]} if "format" in m else {})})
    return out


def _is_agg(formula):
    f = formula.upper()
    return any(f"{a}(" in f for a in ("SUM", "AVG", "MIN", "MAX", "COUNT", "MEDIAN")) and "{" not in f


def encode(b, s, fields, enc):
    """The top calc on the Label shelf; -> labels shown."""
    if not on(s):
        return False
    t = b._measure({"field": calc_name(s)})
    fields.append(t)
    enc.append(("text", b.q(t.name)))
    return True
