"""A copy of a built .twbx that opens with other parameter values (decisions/042): check-desktop sees only the view
at open, so the views a parameter hides (a switch's other views, a metric's other numbers) are checked in copies.

    python tools/param_variant.py in.twbx out.twbx "View=Table" ["Metric=Profit" ...]

Sets the parameter's value (and its formula) everywhere it is declared and, as Desktop saves it, hidden-by-user on
the zones whose visibility flag [Parameters].[X] = "v" changes and on every zone inside them (decisions/082). The
copy then passes the gate like the original.
"""
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

EQ = re.compile(r'\[Parameters\]\.(\[[^\[\]]+\]) = ("[^"]*")')


def variant(src, dst, values):
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in items if n.endswith(".twb"))
    root = etree.fromstring(items[twb])
    params = {c.get("caption"): c for ds in root.find("datasources") if ds.get("name") == "Parameters"
              for c in ds.findall("column")}
    literal = {}
    for caption, v in values.items():
        if caption not in params:
            raise SystemExit(f"no parameter '{caption}' (parameters: {sorted(params)})")
        p = params[caption]
        literal[p.get("name")] = f'"{v}"' if p.get("datatype") == "string" else v
    for c in root.iter("column"):
        if c.get("name") in literal and c.get("param-domain-type"):
            c.set("value", literal[c.get("name")])
            c.find("calculation").set("formula", literal[c.get("name")])
    current = {c.get("name"): c.get("value") for c in params.values()}
    calcs = {(ds.get("name"), c.get("name")): c for ds in root.find("datasources") for c in ds.findall("column")
             if c.find("calculation") is not None}
    graph = root.find("datagraph/graph")
    if graph is not None:
        fields = {n.get("value-output-guid"): n.get("fieldname") for n in graph.iter("single-value-field-node")}
        edges = {e.get("to"): e.get("from") for e in graph.iter("edge")}
        for n in graph.iter("dashboard-zone-visibility-node"):
            ds, col = re.fullmatch(r"\[([^\]]+)\]\.(\[[^\]]+\])", fields[edges[n.get("visibility-input-guid")]]).groups()
            m = EQ.fullmatch(calcs[(ds, col)].find("calculation").get("formula"))
            visible = current[m.group(1)] == m.group(2)
            for c in root.iter("zone"):
                if c.get("id") != n.get("zone-id"):
                    continue
                for z in c.iter("zone"):  # the container and every zone in it, as Desktop saves it (082)
                    if visible:
                        z.attrib.pop("hidden-by-user", None)
                    else:
                        z.set("hidden-by-user", "true")
    items[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)
    return dst


if __name__ == "__main__":
    print(variant(sys.argv[1], sys.argv[2], dict(a.split("=", 1) for a in sys.argv[3:])))
