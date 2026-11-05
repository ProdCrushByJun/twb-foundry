"""Sheet fit labs (decisions/068): what Desktop 2025.1 draws for each sheet shape in Standard, Entire View, Fit Width
and Fit Height on a dashboard.

  python tests/fixtures/fit/build_lab.py <out_dir> [lists|charts|tiles|squeeze ...]

Writes lab.csv (seeded) next to this file and, per lab, <out_dir>/<lab>_<mode>.twbx for every mode of MODES[lab]:
'rule' is the generator's book as built (its fits by tbuilder/fit.py, through the gate); another mode is that book
with every dashboard viewpoint's zoom forced to it (standard = no <zoom>), not gated: it shows what the gate refuses.

lists:   KPI tiles strip (COUNT of a string, SUM of an int calc, AVG, an aggregate ratio, SUM), bar of 5 groups
         (horizontal and vertical), registry of 6 teams, bar of 20 items, registry of 20 items, text table.
charts:  line, area with color, heatmap without margins, heatmap with margins, combo, lollipop.
tiles:   the KPI strip alone and a KPI table (Measure Names): the caption and number alignment.
squeeze: bars of 11 / 13 / 14 / 15 / 17 rows and registries of 7 / 8 / 9 / 10 / 12 rows in equal cells, all in
         Entire View: how far a row may shrink below its Standard size (fit.SQUEEZE).
"""
import copy
import json
import random
import sys
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from tbuilder import build as build_mod  # noqa: E402

MODES = {"lists": ["standard", "entire-view", "fit-width", "rule"],
         "charts": ["standard", "entire-view", "fit-width", "rule"],
         "tiles": ["standard", "entire-view", "rule"], "squeeze": ["entire-view"]}
GROUPS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
TEAMS = ["Service Desk", "App Support", "Desktop", "Network Ops", "DBA", "Security"]
ITEMS = [f"Item {chr(65 + i)}{'x' * (i % 4)}" for i in range(20)]
REGIONS = ["East", "North", "South", "West"]
BARS_N, REGS_N = (11, 13, 14, 15, 17), (7, 8, 9, 10, 12)


def write_csv():
    rnd = random.Random(20261022)
    counts = sorted(set(BARS_N + REGS_N))
    lines = ["Order Date,Code,Region,Group,Team,Item,Sales,Profit,Quantity," + ",".join(f"N{n}" for n in counts)]
    for i in range(900):
        month = 1 + i % 12
        day = 1 + rnd.randrange(28)
        g = GROUPS[min(int(rnd.expovariate(0.7)), 4)]
        t = TEAMS[min(int(rnd.expovariate(0.5)), 5)]
        it = ITEMS[min(int(rnd.expovariate(0.15)), 19)]
        sales = round(rnd.uniform(20, 900), 2)
        lines.append(f"2025-{month:02d}-{day:02d},C{10000 + i},{rnd.choice(REGIONS)},{g},{t},{it},{sales},"
                     f"{round(sales * rnd.uniform(-0.1, 0.3), 2)},{rnd.randrange(1, 9)},"
                     + ",".join(f"Value {chr(65 + i % n)}" for n in counts))
    (HERE / "lab.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def sheet(name, kind, title, **kw):
    return {"name": name, "type": kind, "title": title, **kw}


KPI = {"name": "KPI", "type": "kpi", "style": "tiles", "arrange": "strip", "measures": [
    {"field": "Code", "agg": "count", "label": "Orders"},
    {"field": "Big", "label": "Big orders"},
    {"field": "Sales", "agg": "avg", "label": "Mean order, $"},
    {"field": "Margin", "label": "Margin"},
    {"field": "Quantity", "label": "Units"}]}


def spec(lab):
    calcs = [{"name": "Big", "formula": "IF [Sales] > 600 THEN 1 ELSE 0 END"},
             {"name": "Margin", "formula": "SUM([Profit]) / SUM([Sales])", "format": "pct1"}]
    reg = [{"measure": {"field": "Sales"}, "style": "bar", "label": "Sales"},
           {"measure": {"field": "Profit"}, "style": "text", "label": "Profit"},
           {"measure": {"field": "Quantity"}, "style": "text", "label": "Units"}]
    if lab == "lists":
        sheets = [KPI,
                  sheet("Bar5", "bar", "**Bar** 5 groups", dimension="Group", measure={"field": "Sales"}, sort="desc"),
                  sheet("Bar5v", "bar", "**Bar** 5 groups, vertical", dimension="Group", measure={"field": "Sales"},
                        orientation="vertical", sort="desc"),
                  sheet("Reg6", "registry", "**Registry** 6 teams", rows=["Team"], sort="desc", columns=reg),
                  sheet("Bar20", "bar", "**Bar** 20 items", dimension="Item", measure={"field": "Sales"}, sort="desc"),
                  sheet("Reg20", "registry", "**Registry** 20 items", rows=["Item"], sort="desc", columns=reg),
                  sheet("Table", "table", "**Table** team x region", rows="Team", cols="Region",
                        measure={"field": "Sales"})]
        grid = [["KPI"], ["Bar5", "Bar5v", {"sheet": "Reg6", "width": 2}],
                ["Bar20", {"sheet": "Reg20", "width": 2}, "Table"]]
        dash = {"row_heights": [2, 5, 5], "height": 900}
    elif lab == "charts":
        sheets = [sheet("Line", "line", "**Line** by month", date={"field": "Order Date", "level": "month"},
                        measure={"field": "Sales"}),
                  sheet("Area", "area", "**Area** by month and region", date={"field": "Order Date", "level": "month"},
                        measure={"field": "Sales"}, color="Region"),
                  sheet("Combo", "combo", "**Combo** by group", dimension="Group", bar={"field": "Sales"},
                        line={"field": "Profit"}, sort="desc"),
                  sheet("Heat", "heatmap", "**Heatmap** team x region", rows="Team", cols="Region",
                        measure={"field": "Sales"}, color={"scale": "sequential"}),
                  sheet("HeatM", "heatmap", "**Heatmap** with margins", rows="Team", cols="Region",
                        measure={"field": "Sales"}, color={"scale": "sequential"},
                        margins={"rows": "bar", "cols": "bar"}),
                  sheet("Lolli", "lollipop", "**Lollipop** by group", dimension="Group",
                        measure={"field": "Quantity"}, sort="desc")]
        grid = [["Line", "Area", "Combo"], ["Heat", {"sheet": "HeatM", "width": 2}, "Lolli"]]
        dash = {"height": 900}
    elif lab == "tiles":
        sheets = [KPI, {"name": "KPI table", "type": "kpi", "title": "**KPI** table",
                        "measures": [{"field": "Sales"}, {"field": "Profit"}, {"field": "Quantity"}]}]
        grid = [["KPI"], ["KPI table"]]
        dash = {"height": 420}
    else:
        sheets = [sheet(f"Bar{n}", "bar", f"**Bar** {n} rows", dimension=f"N{n}", measure={"field": "Sales"},
                        sort="desc") for n in BARS_N]
        sheets += [sheet(f"Reg{n}", "registry", f"**Registry** {n} rows", rows=[f"N{n}"], sort="desc",
                         columns=reg[:1]) for n in REGS_N]
        grid = [[f"Bar{n}" for n in BARS_N], [f"Reg{n}" for n in REGS_N]]
        dash = {"height": 760}
    return {"$schema": "../../../tbuilder/spec.schema.json", "version": 1,
            "datasource": {"type": "csv", "path": "lab.csv"}, "calcs": calcs, "sheets": sheets,
            "dashboard": {"name": "Lab", "title": f"**Fit** lab: {lab}", "theme": "cards", "width": 1300,
                          "grid": grid, **dash}}


def force(src, dst, mode):
    """Copy src to dst with every dashboard viewpoint's zoom set to mode (standard: no zoom)."""
    with zipfile.ZipFile(src) as z:
        items = {n: z.read(n) for n in z.namelist()}
    twb = next(n for n in items if n.endswith(".twb"))
    root = etree.fromstring(items[twb])
    for win in root.iter("window"):
        if win.get("class") != "dashboard":
            continue
        for vp in win.iter("viewpoint"):
            for zoom in vp.findall("zoom"):
                vp.remove(zoom)
            if mode != "standard":
                etree.SubElement(vp, "zoom", type=mode)
    items[twb] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in items.items():
            z.writestr(n, data)


def main(out_dir, labs):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_csv()
    for lab in labs:
        sp = spec(lab)
        (HERE / f"{lab}.json").write_text(json.dumps(sp, indent=1), encoding="utf-8")
        base = out / f"{lab}_rule.twbx"
        build_mod.build(copy.deepcopy(sp), base, base_dir=str(HERE))
        for mode in MODES[lab]:
            if mode != "rule":
                force(base, out / f"{lab}_{mode}.twbx", mode)
            print(out / f"{lab}_{mode}.twbx")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:] or list(MODES))
