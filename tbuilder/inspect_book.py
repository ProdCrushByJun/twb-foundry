"""inspect (decisions/188): read-only listing of a book: sources, parameters, sheets, dashboards, calculated fields.

Reads only the .twb (inside a .twbx too); Hyper and images are not unpacked."""
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def read_twb_bytes(path):
    """(twb bytes, label) of a .twb or .twbx; the .twb nearest to the archive root."""
    p = Path(path)
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            names = sorted((n for n in z.namelist() if n.lower().endswith(".twb")), key=lambda n: n.count("/"))
            if not names:
                raise ValueError(f"no .twb inside {p}")
            return z.read(names[0]), names[0]
    return p.read_bytes(), p.name


def calc_fields(ds):
    """(caption, internal name, formula) of every calculated column of a datasource, in file order."""
    out = []
    for col in ds.findall("column"):
        calc = col.find("calculation")
        if calc is not None and calc.get("class") == "tableau" and calc.get("formula") is not None:
            out.append((col.get("caption") or "", col.get("name") or "", calc.get("formula")))
    return out


def zone_lines(dashboard):
    """A dashboard's sheet and text zones as patch's block and title ops name them (decisions/189)."""
    from .gate import _is_card
    zones = dashboard.find("zones")
    out = []
    for z in (zones.iter("zone") if zones is not None else []):
        if _is_card(z):
            what = f"card of {[c.get('name') for c in z.iter('zone') if c.get('name') and c.get('type-v2') is None]}"
        elif z.get("type-v2") == "text":
            words = " ".join("".join(r.text or "" for r in z.iter("run")).split())
            what = f"text '{words[:47] + '...' if len(words) > 50 else words}'"
        elif z.get("name") and z.get("type-v2") is None:
            what = f"sheet '{z.get('name')}'"
        else:
            continue
        style = {f.get("attr"): f.get("value") for f in z.findall("zone-style/format")}
        shown = {k: style[k] for k in ("padding", "margin", "background-color", "border-style") if k in style}
        out.append(f"      zone {z.get('id')}: {what}" + (f"  {shown}" if shown else ""))
    return out


def inspect_text(path):
    data, label = read_twb_bytes(path)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"{label}: XML parse error: {e}") from e
    out = [f"=== {label} ===", ""]
    dss = root.findall("./datasources/datasource")
    out.append(f"DATASOURCES ({len([d for d in dss if d.get('name') != 'Parameters'])}):")
    for ds in dss:
        if ds.get("name") != "Parameters":
            out.append(f"  - {ds.get('caption') or ds.get('name')}  (name={ds.get('name')})")
    params = [(c.get("caption") or c.get("name"), c.get("value"))
              for ds in dss if ds.get("name") == "Parameters" for c in ds.findall("column") if c.get("value") is not None]
    if params:
        out += ["", f"PARAMETERS ({len(params)}):"] + [f"  - {n}  (current={v})" for n, v in params]
    for tag, title in (("worksheets/worksheet", "WORKSHEETS"), ("dashboards/dashboard", "DASHBOARDS")):
        items = root.findall(f"./{tag}")
        out += ["", f"{title} ({len(items)}):"]
        for i in items:
            out.append(f"  - {i.get('name')}")
            out += zone_lines(i)
    total = 0
    for ds in dss:
        fields = [] if ds.get("name") == "Parameters" else calc_fields(ds)  # a parameter is not a calculation
        if not fields:
            continue
        out += ["", f"CALCULATED FIELDS in [{ds.get('caption') or ds.get('name')}] ({len(fields)}):"]
        for caption, name, formula in fields:
            one = " ".join(formula.split())
            out += [f"  - {caption or name}", f"      name: {name}",
                    f"      = {one[:107] + '...' if len(one) > 110 else one}"]
        total += len(fields)
    out += ["", f"TOTAL calculated fields: {total}"]
    return "\n".join(out)


def main(argv):
    if len(argv) != 1:
        print("usage: python -m tbuilder inspect <book.twbx|.twb>", file=sys.stderr)
        return 2
    print(inspect_text(argv[0]))
    return 0
