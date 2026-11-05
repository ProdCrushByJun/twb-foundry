"""Style/layout fingerprint of Tableau workbooks (XML parse only)."""
import collections
import glob
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import survey_public as survey  # noqa: E402

HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def depth(z, d=0):
    kids = z.findall("zone")
    return max([depth(k, d + 1) for k in kids], default=d)


def fmt_values(el, attr):
    return [f.get("value") for f in el.iter("format") if f.get("attr") == attr]


def analyze(path):
    root = survey.twb_root(path)
    out = {"dashboards": []}
    fonts = collections.Counter()
    for a in ("font-family",):
        fonts.update(fmt_values(root, a))
    for r in root.iter("run"):
        if r.get("fontname"):
            fonts[r.get("fontname")] += 1
    colors = collections.Counter(c.lower() for c in HEX.findall(open_text(root)))
    out["fonts"] = fonts.most_common(6)
    out["colors"] = colors.most_common(14)
    out["palettes"] = [
        [c.text for c in p.findall("color")] for p in root.iter("color-palette") if p.get("custom") == "true"
    ][:4]
    out["parameters"] = sum(len(d.findall("column")) for d in root.iter("datasource") if d.get("name") == "Parameters")
    out["lod"] = sum(bool(re.search(r"\{\s*(FIXED|INCLUDE|EXCLUDE)", c.get("formula", ""), re.I))
                     for c in root.iter("calculation"))
    pats = collections.Counter()
    for ws in root.iter("worksheet"):
        c = survey.classify(ws)
        if c:
            pats[c["pattern"]] += 1
    out["sheet_patterns"] = pats.most_common(10)
    out["actions"] = len(root.findall("actions/action"))
    for db in root.iter("dashboard"):
        if db.get("type") == "storyboard":
            continue
        size = db.find("size")
        zones = list(db.find("zones").iter("zone")) if db.find("zones") is not None else []
        types = collections.Counter(z.get("type-v2") or ("sheet" if z.get("name") else "?") for z in zones)
        bgs = collections.Counter()
        for z in zones:
            for f in z.findall("zone-style/format"):
                if f.get("attr") == "background-color":
                    bgs[f.get("value").lower()] += 1
        margins = collections.Counter(f.get("value") for z in zones for f in z.findall("zone-style/format")
                                      if f.get("attr") in ("margin", "padding"))
        db_bg = [f.get("value") for f in db.findall("style/style-rule/format") if f.get("attr") == "background-color"]
        top = db.find("zones")
        out["dashboards"].append(dict(
            name=db.get("name"),
            size=dict(size.attrib) if size is not None else None,
            zones=len(zones),
            floating=sum(1 for z in zones if z.get("is-floating") == "true" or z.get("floating") == "true"),
            depth=max([depth(z) for z in top.findall("zone")], default=0) if top is not None else 0,
            types=dict(types.most_common()),
            zone_bg=bgs.most_common(5),
            dash_bg=db_bg,
            margins=margins.most_common(4),
            dzv=sum(1 for z in zones if z.get("hidden-by-user") or z.find("zone-visibility") is not None
                    or "visibility" in " ".join(z.attrib)),
            hidden_titles=sum(1 for z in zones if z.get("show-title") == "false"),
            device_layouts=[d.get("name") for d in db.findall("devicelayouts/devicelayout")
                            if d.get("auto-generated") != "true"],
        ))
    return out


def open_text(root):
    from lxml import etree
    return etree.tostring(root).decode("utf-8", "replace")


if __name__ == "__main__":
    # A folder of books or the books themselves; a single file used to glob to nothing and print {}
    paths = [p for a in sys.argv[1:] for p in ([a] if a.lower().endswith(".twbx") else sorted(glob.glob(a + "/*.twbx")))]
    res = {p.replace("\\", "/").split("/")[-1][:-5]: analyze(p) for p in paths}
    print(json.dumps(res, ensure_ascii=False, indent=1))
