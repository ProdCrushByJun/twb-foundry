"""Tally chart patterns across downloaded Tableau Public workbooks (XML parse only)."""
import collections
import glob
import json
import re
import sys
import zipfile

from lxml import etree

PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


def twb_root(path):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".twb") and "/" not in n)
        return etree.fromstring(z.read(name), PARSER)


DATE_CONT = re.compile(r"\[(tyr|tqr|tmn|twk|tdy|yr|qr|mn|dy|wk|md|tmdy):[^\]]*:qk\]")
DIM = re.compile(r"\[(none|yr|qr|mn|dy|wk|my):[^\]]*:(nk|ok)\]")


def semantic(marks, rows, cols, enc, dual, meas):
    s = set(marks)
    shelves = rows + cols
    no_shelves = not rows.strip() and not cols.strip()
    has_date = bool(DATE_CONT.search(shelves))
    m_rows, m_cols = meas(rows), meas(cols)
    has_dim = bool(DIM.search(shelves))
    geo = "geometry" in enc or "Latitude" in shelves or "Multipolygon" in s
    if geo:
        return "map"
    if "Pie" in s:
        return "donut (pie dual-axis)" if dual else "pie"
    if no_shelves:
        if s <= {"Shape", "Automatic", "Text"} and "Shape" in s:
            return "icon / decoration"
        return "KPI / BAN text"
    if "GanttBar" in s and "Bar" in s:
        return "bar + target (gantt/bullet)"
    if "Area" in s:
        return "area" + (" + line" if "Line" in s else "")
    if dual:
        if "Bar" in s and "Line" in s:
            return "combo bar + line"
        if "Circle" in s and ("Line" in s or "Bar" in s or "Automatic" in s):
            return "lollipop / line+dots"
        return "other dual-axis"
    if m_rows and m_cols and not has_date:
        return "scatter"
    if "Line" in s or (s == {"Automatic"} and has_date):
        return "line" + (" (color)" if "color" in enc else "")
    if "Square" in s or ("text" in enc and "color" in enc and not m_rows and not m_cols):
        return "heatmap / highlight table"
    if "Text" in s or (not m_rows and not m_cols and "text" in enc):
        return "text table"
    if "Bar" in s or (s == {"Automatic"} and has_dim and (m_rows or m_cols)):
        return "stacked bar (color)" if "color" in enc else "bar"
    if "Circle" in s or "Shape" in s:
        return "dot plot / shapes"
    return "other: " + "+".join(sorted(s))


def classify(ws):
    t = ws.find("table")
    if t is None:
        return None
    panes = t.findall("panes/pane")
    marks = [p.find("mark").get("class") for p in panes if p.find("mark") is not None]
    rows, cols = t.findtext("rows") or "", t.findtext("cols") or ""
    enc_tags = {e.tag for p in panes for e in p.findall("encodings/*")}
    meas = lambda s: len(re.findall(r"\[(sum|avg|cnt|ctd|min|max|usr|attr|median|pcto|win|rank)[^\]]*:qk\]", s))
    dual = len(panes) > 1 and (meas(rows) >= 2 or meas(cols) >= 2)
    main = [m for m in marks if m] or ["?"]
    pat = semantic(main, rows, cols, enc_tags, dual, meas)
    return dict(pattern=pat, marks=main, encodings=sorted(enc_tags), dual=dual,
                calc_tablecalc=bool(t.find(".//table-calc") is not None or "pcto:" in rows + cols),
                reflines=len(t.findall(".//reference-line")))


def main(paths):
    pats, encs, feats = collections.Counter(), collections.Counter(), collections.Counter()
    per_wb = {}
    for p in paths:
        try:
            root = twb_root(p)
        except Exception as e:
            print("skip", p, e, file=sys.stderr)
            continue
        wb = p.split("/")[-1].split("\\")[-1]
        calcs = [c.get("formula", "") for c in root.iter("calculation")]
        feats["workbooks"] += 1
        feats["wb with LOD"] += any(re.search(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", f, re.I) for f in calcs)
        feats["wb with parameters"] += any(d.get("name") == "Parameters" for d in root.iter("datasource"))
        feats["wb with map (lat/lon generated)"] += b"Latitude (generated)" in etree.tostring(root)
        feats["wb with images"] += any(z.get("type-v2") == "bitmap" for z in root.iter("zone"))
        feats["wb with floating layout"] += any(z.get("is-floating") or z.get("floating") for z in root.iter("zone"))
        feats["wb with dashboard actions"] += root.find("actions") is not None
        kinds = collections.Counter()
        for ws in root.iter("worksheet"):
            c = classify(ws)
            if not c:
                continue
            pats[c["pattern"]] += 1
            kinds[c["pattern"]] += 1
            for e in c["encodings"]:
                encs[e] += 1
            feats["sheets"] += 1
            feats["sheets with reference lines"] += c["reflines"] > 0
        per_wb[wb] = dict(kinds)
    print(json.dumps(dict(features=feats, patterns=pats.most_common(40), encodings=encs.most_common(),
                          per_workbook=per_wb), indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sorted(glob.glob(sys.argv[1] + "/*.twbx")))
