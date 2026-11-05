"""Control numbers of every golden, computed with pandas straight from its CSV / xlsx (decisions/052).

Independent of the generator: nothing is imported from tbuilder, each sheet is a plain pandas groupby written from
the meaning of the spec (and of Tableau, where Desktop confirmed it: decisions 010, 011, 019, 031). The numbers that
README / decisions record from Desktop are asserted here too (DOCUMENTED), so a file is written only when pandas
agrees with Desktop.

  py -3.14 golden/expected/make_expected.py           # writes golden/expected/<golden stem>.json
  py -3.14 golden/expected/make_expected.py --check   # recomputes, exit 1 if a file differs

Needs pandas + openpyxl (not in the project venv on purpose: `python -m tbuilder regress` only reads the JSON files).
File shape: {"_source": ..., "<sheet>": {"<mark>": number | text | null | {"<part>": ...}}} as expected.compute names
them; `regress` compares every listed number with expected.compute(spec) at half a unit of its last written digit.
"""
import datetime as dt
import json
import math
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DATA = ROOT / "data" / "sample"
DECIMALS = 4  # written precision: money has 2 digits anyway, a share 0.01 %; the tolerance is half the last digit


# ---- reading -----------------------------------------------------------------------------------------------------
def read_csv(path, numbers=()):
    """Text as Tableau's text driver reads it: trimmed, empty = null; numbers as floats (null stays NaN)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    for c in df.columns:
        df[c] = df[c].str.strip()
    for c in numbers:
        df[c] = pd.to_numeric(df[c].replace("", None))
    return df


def iso_dates(df, col, fmt="%Y-%m-%d"):
    df[col] = pd.to_datetime(df[col].replace("", None), format=fmt)
    return df


def sales(name="sales.csv"):
    return iso_dates(read_csv(DATA / name, ("Sales", "Profit", "Quantity")), "Order Date")


# ---- shaping -----------------------------------------------------------------------------------------------------
def num(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, str):
        return v
    v = round(float(v), DECIMALS)
    return int(v) if v.is_integer() and abs(v) < 1e15 else v


def month(s):
    return s.dt.strftime("%Y-%m")


def by(df, keys, col, agg="sum"):
    """{"k1 | k2": agg(col)}: one mark per combination of keys present in the data (a null key drops out)."""
    keys = [keys] if isinstance(keys, (str, pd.Series)) else keys
    cols = [k if isinstance(k, str) else k.rename(f"_k{i}") for i, k in enumerate(keys)]
    g = df.groupby(cols, dropna=True)[col]
    vals = getattr(g, agg)() if agg != "sum" else g.sum(min_count=1)
    out = {}
    for k, v in vals.items():
        k = k if isinstance(k, tuple) else (k,)
        out[" | ".join(str(x) for x in k)] = num(v)
    return out


def total(df, col, agg="sum"):
    s = df[col]
    return num(s.sum(min_count=1) if agg == "sum" else getattr(s, agg)())


def kpi(df, *cols):
    return {f"SUM({c})": total(df, c) for c in cols}


def card(df, date, col, step):
    """KPI card: the latest month of the data vs the month `step` months before (1 = MoM, 12 = YoY)."""
    m = df[date].dt.to_period("M")
    cur = m.max()
    a, b = df.loc[m == cur, col].sum(), df.loc[m == cur - step, col].sum()
    return {"current": num(a), "previous": num(b), "delta": num(a / b - 1)}


def median(values):
    return num(pd.Series(list(values)).median())


def mean(values):
    return num(pd.Series(list(values)).mean())


# ---- the goldens -------------------------------------------------------------------------------------------------
def g_sales_grid(df, kpi_cols, bar_color=True):
    """golden_2025_1 and its look-alikes: KPI, bar (Region [x Category]), line by month, Region x Category table."""
    return {"KPI": kpi(df, *kpi_cols),
            "Bar": by(df, ["Region", "Category"] if bar_color else "Region", "Sales"),
            "Line": by(df, month(df["Order Date"]), "Sales"),
            "Table": by(df, ["Region", "Category"], "Sales")}


def golden():
    return g_sales_grid(sales(), ("Profit", "Quantity", "Sales"))


def format_():
    return g_sales_grid(sales(), ("Sales", "Profit", "Quantity"), bar_color=False)


def headers():
    return g_sales_grid(sales(), ("Sales", "Profit"))


def layout_sidebar():
    return g_sales_grid(sales(), ("Sales", "Profit"))


def declutter():
    df = sales()
    out = g_sales_grid(df, ("Sales", "Profit"), bar_color=False)
    out["Area"] = by(df, [month(df["Order Date"]), "Category"], "Sales")
    out["Heatmap"] = by(df, ["Region", "Category"], "Profit")
    return out


def charts():
    df = sales()
    return {"Area": by(df, [month(df["Order Date"]), "Category"], "Sales"),
            "Heatmap": by(df, ["Region", "Category"], "Sales")}


def actions():
    df = sales()
    sales_, profit = by(df, "Region", "Sales"), by(df, "Region", "Profit")
    return {"KPI": kpi(df, "Sales", "Profit"),
            "By Region": {k: {"Sales": sales_[k], "Profit": profit[k]} for k in sales_},
            "By Category": by(df, "Category", "Sales"),
            "Trend": by(df, month(df["Order Date"]), "Sales")}


def actions_v2():
    """decisions/160: the parameter Region pick at its default All, so Picked Sales is all sales."""
    df = sales()
    sales_, profit = by(df, "Region", "Sales"), by(df, "Region", "Profit")
    return {"KPI": {**kpi(df, "Sales"), "AGG(Picked Sales)": total(df, "Sales")},
            "By Region": {k: {"Sales": sales_[k], "Profit": profit[k]} for k in sales_},
            "By Category": by(df, "Category", "Sales"),
            "By Month": by(df, month(df["Order Date"]), "Sales"),
            "Trend": by(df, [month(df["Order Date"]), "Category"], "Sales")}


def registry():
    df = sales()
    rc = ["Region", "Category"]
    s, p, q = by(df, rc, "Sales"), by(df, rc, "Profit"), by(df, rc, "Quantity")
    cs, cp = by(df, "Category", "Sales"), by(df, "Category", "Profit")
    return {"Registry": {k: {"Sales": s[k], "Profit": p[k], "Units": q[k]} for k in s},
            "By Category": {k: {"Sales": cs[k], "Profit": cp[k]} for k in cs}}


def ratio(df, keys):
    s, p = df.groupby(keys)["Sales"].sum(), df.groupby(keys)["Profit"].sum()
    return {(" | ".join(k) if isinstance(k, tuple) else k): num(p[k] / s[k]) for k in s.index}


def calcs():
    df = sales()
    df["Order Size"] = ["Large" if v >= 500 else "Medium" if v >= 300 else "Small" for v in df["Sales"]]
    tech = df.loc[df["Category"] == "Tech", "Sales"].sum()
    return {"KPI": {"SUM(Sales)": total(df, "Sales"), "AGG(Profit Ratio)": num(df["Profit"].sum() / df["Sales"].sum()),
                    "SUM(Tech Sales)": num(tech)},
            "Ratio by Region": ratio(df, "Region"),
            "Sales by Size": by(df, ["Order Size", "Category"], "Sales"),
            "Ratio Matrix": ratio(df, ["Order Size", "Region"])}


def lods():
    df = sales()
    tot = df["Sales"].sum()
    region = df.groupby("Region")["Sales"].sum()
    cell = df.groupby(["Region", "Category"])["Sales"].sum()
    first = df.groupby("Region")["Order Date"].transform("min")
    return {"KPI": {"MIN(Total Sales)": num(tot), "AGG(Max Region Sales)": num(region.max()),
                    "SUM(First Day Orders)": int((df["Order Date"] == first).sum())},
            "Share by Category": {k: num(v / tot) for k, v in df.groupby("Category")["Sales"].sum().items()},
            "Region Mix": {f"{r} | {c}": num(v / region[r]) for (r, c), v in cell.items()},
            "Sales by Region": {f"{r} | {'Big region' if v > 56000 else 'Small region'}": num(v)
                                for r, v in region.items()}}


def lods_view():
    df = sales()
    cat = df.groupby("Category")["Sales"].sum()
    cell = df.groupby(["Region", "Category"])["Sales"].sum()
    region = df.groupby("Region")["Sales"].sum()
    mcell = df.groupby([month(df["Order Date"]), "Category"])["Sales"].sum()
    mtot = df.groupby(month(df["Order Date"]))["Sales"].sum()
    return {"KPI": {"AGG(Max Category Sales)": num(cat.max()), "AVG(Category Sales)": num(cat.mean())},
            # INCLUDE [Category] on a Region bar: the average of the region's category totals (decisions/010)
            "Avg Category by Region": {r: num(cell[r].mean()) for r in region.index},
            "Region Total Grid": {f"{r} | {c}": num(region[r]) for (r, c) in cell.index},
            "Share Grid": {f"{r} | {c}": num(v / region[r]) for (r, c), v in cell.items()},
            "Month Total": {f"{m} | {c}": num(mtot[m]) for (m, c) in mcell.index}}


def tablecalcs():
    df = sales()
    tot = df["Sales"].sum()
    cell = df.groupby(["Region", "Category"])["Sales"].sum()
    region = df.groupby("Region")["Sales"].sum()
    months = df.groupby(month(df["Order Date"]))["Sales"].sum().sort_index()
    diff = {}
    for c in sorted(df["Category"].unique()):  # difference along Region (East, North, South, West) per Category
        prev = None
        for r in sorted(df["Region"].unique()):
            v = cell.get((r, c))
            diff[f"{r} | {c}"] = None if prev is None else num(v - prev)
            prev = v
    pct = [None] + [num((b - a) / abs(a)) for a, b in zip(months, months[1:])]  # the first month has no base
    return {"Category Share": {k: num(v / tot) for k, v in df.groupby("Category")["Sales"].sum().items()},
            # % of total of AVG = AVG / TOTAL(AVG), TOTAL re-aggregates all rows (decisions/011)
            "Avg Share": {k: num(v / df["Sales"].mean()) for k, v in df.groupby("Region")["Sales"].mean().items()},
            "Share in Region": {f"{r} | {c}": num(v / region[r]) for (r, c), v in cell.items()},
            "Region Difference": diff,
            "Running Sales": {k: num(v) for k, v in months.cumsum().items()},
            "MoM Change": dict(zip(months.index, pct))}


def cards():
    df = sales("sales_2y.csv")
    return {"Monthly": {"Sales": card(df, "Order Date", "Sales", 1), "Profit": card(df, "Order Date", "Profit", 1)},
            "Yearly": {"Units": card(df, "Order Date", "Quantity", 12)},
            "Trend": by(df, month(df["Order Date"]), "Sales")}


def layout_kpi_left():
    df = sales("sales_2y.csv")
    return {"KPI": {"Sales": card(df, "Order Date", "Sales", 1), "Profit": card(df, "Order Date", "Profit", 1),
                    "Units": card(df, "Order Date", "Quantity", 1)},
            "Bar": by(df, ["Region", "Category"], "Sales"),
            "Line": by(df, month(df["Order Date"]), "Sales"),
            "Table": by(df, ["Region", "Category"], "Sales")}


def formats():
    df = sales("sales_2y.csv")
    s, p, q = df["Sales"].sum(), df["Profit"].sum(), df["Quantity"].sum()
    return {"Monthly": {"Sales": card(df, "Order Date", "Sales", 1)},
            "Totals": {"SUM(Quantity)": num(q), "AGG(Profit Ratio)": num(p / s), "AGG(Avg Price)": num(s / q),
                       "AGG(Sales Scaled)": num(s * 100000)},
            "Sales by Region": by(df, "Region", "Sales"),
            "Worst Order": by(df, ["Region", "Category"], "Profit", "min"),
            "Ratio": ratio(df, ["Region", "Category"])}


def reflines():
    df = sales("sales_2y.csv")
    m = month(df["Order Date"])
    regions = df.groupby("Region")["Sales"].sum()
    trend = by(df, [m, "Region"], "Sales")
    return {"Monthly": {"Sales": card(df, "Order Date", "Sales", 1), "Profit": card(df, "Order Date", "Profit", 1)},
            # the card's history: one mark per month, the average line over them
            "Monthly · Sales · History · Reference": {"Average": mean(df.groupby(m)["Sales"].sum())},
            "Monthly · Profit · History · Reference": {"Average": mean(df.groupby(m)["Profit"].sum())},
            "Regions": {k: num(v) for k, v in regions.items()},
            "Regions · Reference": {"Average": mean(regions)},
            "Stack": by(df, ["Region", "Category"], "Sales"),
            "Stack · Reference": {"Median": median(regions)},  # over the bar totals, not the segments
            "Categories": by(df, "Category", "Sales"),
            "Categories · Reference": {"Target": 105000},  # the spec's constant
            "Trend": trend,
            "Trend · Reference": {"Average": mean(trend.values())},  # over all marks of the series
            "Total": by(df, m, "Sales"),
            "Total · Reference": {"Target": 15000}}  # the default of parameter Target


def kpi_spark_points():
    """KPI v2 sparklines with max / min / last dots (decisions/059): each dot at the first of the card's kinds the
    month is (Monthly: max, min, last; Latest: last, min), ties mark every tied month."""
    df = sales("sales_2y.csv")
    m = month(df["Order Date"])
    out = {"Monthly": {}, "Latest": {}}

    def history(sheet, label, col, kinds):
        series = df.groupby(m)[col].sum().sort_index()
        hit = {"max": lambda k, v: v == series.max(), "min": lambda k, v: v == series.min(),
               "last": lambda k, v: k == series.index[-1]}
        name = f"{sheet} · {label} · History"
        if sheet == "Monthly":  # history_reference avg
            out[f"{name} · Reference"] = {"Average": mean(series)}
        out[f"{name} · Points"] = {"max": num(series.max()), "min": num(series.min()), "last": num(series.iloc[-1])}
        marks = {}
        for k, v in series.items():
            kind = next((x for x in kinds if hit[x](k, v)), None)
            if kind:
                marks[k] = {"point": kind.capitalize(), "value": num(v)}
        out[f"{name} · Point Marks"] = marks

    for label, col in (("Sales", "Sales"), ("Profit", "Profit"), ("Units", "Quantity")):
        out["Monthly"][label] = card(df, "Order Date", col, 1)
        history("Monthly", label, col, ("max", "min", "last"))
    out["Latest"]["Units"] = card(df, "Order Date", "Quantity", 1)
    history("Latest", "Units", "Quantity", ("last", "min"))
    return out


def kpi_status():
    """KPI status dots (decisions/062): each card's latest month against its base and its status by the spec's
    thresholds, on the card's value or on its change (two thresholds: good / warn / bad, one: good / bad; for a
    measure that is good 'down' lower is better)."""
    df = sales("sales_2y.csv")

    def status(rec, on, th, labels, up=True):
        v = rec["current" if on == "value" else "delta"]
        good, warn, bad = labels
        if len(th) == 1:
            return good if (v >= th[0] if up else v <= th[0]) else bad
        lo, hi = th
        if up:
            return good if v >= hi else warn if v >= lo else bad
        return good if v <= lo else warn if v <= hi else bad

    def cards(step, measures, labels):
        out = {}
        for label, col, on, th, up in measures:
            rec = card(df, "Order Date", col, step)
            out[label] = {**rec, "status": status(rec, on, th, labels, up)}
        return out

    return {"Monthly": cards(1, [("Sales", "Sales", "value", [13000, 15000], True),
                                 ("Profit", "Profit", "change", [-0.2, 0], True),
                                 ("Units", "Quantity", "change", [0, 0.05], False)],
                             ("On track", "At risk", "Off track")),
            "Yearly": cards(12, [("Sales", "Sales", "change", [0], True),
                                 ("Profit", "Profit", "value", [500, 1000], True)],
                            ("Healthy", "Warning", "Critical"))}


def kpi_v2():
    """decisions/037 (specs/kpi_v2.json, decisions/063; specs/kpi_v2_nopill.json: without the pill and the marker,
    decisions/061 - the same numbers): cards with the
    absolute + % delta, the history line's max / min / last and average, the period line (latest month and its base),
    'Data as of' = the latest date of the data."""
    df = sales("sales_2y.csv")
    m = month(df["Order Date"])

    def card2(col):
        c = card(df, "Order Date", col, 1)
        return c | {"diff": num(c["current"] - c["previous"])}

    def points(col):
        s = df.groupby(m)[col].sum().sort_index()
        return {"max": num(s.max()), "min": num(s.min()), "last": num(s.iloc[-1])}

    out = {"Monthly": {"Sales": card2("Sales"), "Profit": card2("Profit"), "Units": card2("Quantity")}}
    for label, col in (("Sales", "Sales"), ("Profit", "Profit"), ("Units", "Quantity")):
        out[f"Monthly · {label} · History · Reference"] = {"Average": mean(df.groupby(m)[col].sum())}
        out[f"Monthly · {label} · History · Points"] = points(col)
    last = df["Order Date"].max().to_period("M")
    out["Monthly · Period Line"] = {"period": last.start_time.strftime("%Y-%m-%d"),
                                    "base": (last - 1).start_time.strftime("%Y-%m-%d")}
    out["Yearly"] = {"Sales": card(df, "Order Date", "Sales", 12), "Profit": card(df, "Order Date", "Profit", 12)}
    out["Stacked"] = {"Units": card2("Quantity")}
    out["Stacked · Units · History · Points"] = points("Quantity")
    out["KPI v2 · Data as of"] = df["Order Date"].max().strftime("%Y-%m-%d")
    return out






def kpi_v3():
    """decisions/088 (specs/kpi_v3.json): area sparklines with month letters; Monthly with max / min dots (its
    legend in the block header), Yearly against the same month a year back; every card shows its base value
    ('previous': the base month's total)."""
    df = sales("sales_2y.csv")
    m = month(df["Order Date"])
    out = {"Monthly": {}, "Yearly": {}}

    def history(sheet, label, col, kinds):
        series = df.groupby(m)[col].sum().sort_index()
        name = f"{sheet} · {label} · History"
        out[f"{name} · Points"] = {"max": num(series.max()), "min": num(series.min()), "last": num(series.iloc[-1])}
        if kinds:
            out[f"{name} · Point Marks"] = {k: {"point": "Max" if v == series.max() else "Min", "value": num(v)}
                                            for k, v in series.items() if v in (series.max(), series.min())}

    for label, col in (("Sales", "Sales"), ("Profit", "Profit")):
        out["Monthly"][label] = card(df, "Order Date", col, 1)
        history("Monthly", label, col, ("max", "min"))
    out["Yearly"]["Units"] = card(df, "Order Date", "Quantity", 12)
    history("Yearly", "Units", "Quantity", ())
    return out



def kpi_progress():
    """decisions/155 (specs/kpi_progress.json): cards against a constant target. Monthly: Dec 2025 vs Nov with the
    sparkline's max / min / last; Yearly: 2025 vs 2024. target, progress = current / target, fill = the progress
    within 0..1 (the bar's length)."""
    df = sales("sales_2y.csv")
    m = month(df["Order Date"])
    y = df["Order Date"].dt.year

    def against(c, goal):
        p = c["current"] / goal
        return c | {"target": goal, "progress": num(p), "fill": num(max(min(p, 1), 0))}

    out = {"Monthly": {}, "Yearly": {}}
    for label, col, goal in (("Sales", "Sales", 15000), ("Profit", "Profit", 1200), ("Units", "Quantity", 100)):
        out["Monthly"][label] = against(card(df, "Order Date", col, 1), goal)
        s = df.groupby(m)[col].sum().sort_index()
        out[f"Monthly · {label} · History · Points"] = {"max": num(s.max()), "min": num(s.min()),
                                                        "last": num(s.iloc[-1])}
    for label, col, goal in (("Sales", "Sales", 200000), ("Profit", "Profit", 15000)):
        a, b = df.loc[y == y.max(), col].sum(), df.loc[y == y.max() - 1, col].sum()
        out["Yearly"][label] = against({"current": num(a), "previous": num(b), "delta": num(a / b - 1)}, goal)
    return out


def registry_v2():
    """decisions/039: rank (within the outer row field), bar / track / share of the 2025 sales, average profit per
    order, 2025 against 2024 (tick base, change), units with profit as the second line, top 2 per repeated field."""
    df = sales("sales_2y.csv")
    y = df["Order Date"].dt.year
    df["S25"], df["S24"] = df["Sales"].where(y == 2025), df["Sales"].where(y == 2024)

    def rank(s):
        return s.rank(method="min", ascending=False).astype(int)

    reg = df.groupby("Region").agg(s25=("S25", "sum"), avgp=("Profit", "mean"))
    share = reg["s25"] / reg["s25"].sum()
    regions = {k: {"#": int(rank(reg["s25"])[k]), "Sales": num(r.s25), "Of total": num(share[k]), "Share": num(share[k]),
                   "Share · value": num(r.s25), "Avg profit": num(r.avgp)} for k, r in reg.iterrows()}
    cat = df.groupby(["Region", "Category"]).agg(s25=("S25", "sum"), s24=("S24", "sum"), q=("Quantity", "sum"),
                                                 p=("Profit", "sum"))
    cat["r"] = cat.groupby(level=0)["s25"].transform(rank)
    categories = {f"{a} | {b}": {"#": int(r.r), "Sales vs PY": num(r.s25), "Sales vs PY · Sales 2024": num(r.s24),
                                 "Change": num(r.s25 / r.s24 - 1), "Units": num(r.q), "Units · Profit": num(r.p)}
                  for (a, b), r in cat.iterrows()}
    out = {"Regions": regions, "Categories": categories}
    for f in ("Region", "Category"):
        g = df.groupby(f).agg(s25=("S25", "sum"), s24=("S24", "sum"))
        g["r"] = rank(g["s25"])
        out[f"Top · {f}"] = {k: {"#": int(r.r), "Sales": num(r.s25), "vs PY": num(r.s25 / r.s24 - 1)}
                             for k, r in g[g["r"] <= 2].iterrows()}
    return out


def registry_single():
    """decisions/099: a registry of one column per style (one pane): sales by region, top 3 categories, region by
    category with subtotals and the grand total, profit bars, 2025 inside the bars, 2025 with a tick at 2024, average
    profit, the share of 2025."""
    df = sales("sales_2y.csv")
    y = df["Order Date"].dt.year
    df["S25"], df["S24"] = df["Sales"].where(y == 2025), df["Sales"].where(y == 2024)
    reg = df.groupby("Region").agg(s=("Sales", "sum"), p=("Profit", "sum"), s25=("S25", "sum"), s24=("S24", "sum"),
                                   avgp=("Profit", "mean"))
    cat = df.groupby("Category")["Sales"].sum().sort_values(ascending=False).head(3)
    nested = {f"{a} | {b}": {"Sales": num(v)} for (a, b), v in df.groupby(["Region", "Category"])["Sales"].sum().items()}
    nested.update({f"{k} | Total": {"Sales": num(r.s)} for k, r in reg.iterrows()})
    nested["Total"] = {"Sales": num(df["Sales"].sum())}
    share = reg["s25"] / reg["s25"].sum()
    return {"One Text": {k: {"Sales": num(r.s)} for k, r in reg.iterrows()},
            "One Text Top": {k: {"Sales": num(v)} for k, v in sorted(cat.items())},
            "One Text Nested": nested,
            "One Bar": {k: {"Profit": num(r.p)} for k, r in reg.iterrows()},
            "One Bar Inside": {k: {"Sales": num(r.s25)} for k, r in reg.iterrows()},
            "One Tick": {k: {"Sales vs PY": num(r.s25), "Sales vs PY · Sales 2024": num(r.s24)}
                         for k, r in reg.iterrows()},
            "One Dot": {k: {"Avg profit": num(r.avgp)} for k, r in reg.iterrows()},
            "One Track": {k: {"Of total": num(share[k])} for k in reg.index}}


def heatmap_v2():
    """decisions/041: month-of-year x region with the marginal totals (and their averages), 2025 vs 2024 change,
    profit bars."""
    df = sales("sales_2y.csv")
    d = df["Order Date"]
    mon = d.dt.strftime("%m %b")  # 'Month': 0-padded month + the first 3 letters of its (English) name
    rows, cols = df.groupby(mon)["Sales"].sum(), df.groupby("Region")["Sales"].sum()
    y = d.dt.year
    df["S25"], df["S24"] = df["Sales"].where(y == 2025, 0), df["Sales"].where(y == 2024, 0)
    ch = df.groupby(["Region", "Category"])[["S25", "S24"]].sum()
    return {"Seasonality": by(df, [mon, "Region"], "Sales"),
            "Seasonality · Row Totals": {k: num(v) for k, v in rows.items()},
            "Seasonality · Row Totals · Reference": {"Average": mean(rows)},
            "Seasonality · Column Totals": {k: num(v) for k, v in cols.items()},
            "Seasonality · Column Totals · Reference": {"Average": mean(cols)},
            "Change": {f"{a} | {b}": num((r.S25 - r.S24) / r.S24) for (a, b), r in ch.iterrows()},
            "Profit": by(df, "Category", "Profit")}


def heatmap_rows():
    """decisions/171: margin (profit per 100 of sales) by region over category x quarter; the label calc is the
    same number where it reaches 10 (no marks of its own)."""
    df = sales("sales_2y.csv")
    d = df["Order Date"]
    q = d.dt.year.astype(str) + "-Q" + d.dt.quarter.astype(str)
    g = df.groupby(["Region", "Category", q.rename("_q")])[["Profit", "Sales"]].sum()
    return {"Margin Map": {f"{a} | {b} | {c}": num(r.Profit / r.Sales * 100) for (a, b, c), r in g.iterrows()}}


def benchmark():
    """decisions/043: the selected region vs the average region per month. sum: the month's total / the regions in
    it (FIXED before any filter); avg: the month's average over all rows. Ends: the first / last month's marks."""
    df = sales("sales_2y.csv")
    m = month(df["Order Date"])

    def compare(region, col, agg, label):
        sel = df[df["Region"] == region].groupby(m)[col].agg(agg)
        allr = df.groupby(m)[col].sum() / df.groupby(m)["Region"].nunique() if agg == "sum" else \
            df.groupby(m)[col].mean()
        return {k: {region: num(sel.get(k)), label: num(allr[k])} for k in sorted(allr.index)}

    def ends(marks, first):
        ks = sorted(marks)
        return {s: ({"first": marks[ks[0]][s]} if first else {}) | {"last": marks[ks[-1]][s]} for s in marks[ks[0]]}

    out = {}
    for label, col, agg in (("Sales", "Sales", "sum"), ("Profit", "Profit", "sum"), ("Quantity", "Quantity", "sum"),
                            ("Avg sale", "Sales", "mean")):
        marks = compare("West", col, agg, "All regions avg")  # parameter Select Region at its default
        out[f"Compare · {label}"] = marks
        out[f"Compare · {label} · Ends"] = ends(marks, first=False)
    east = compare("East", "Sales", "sum", "All Region avg")  # the default label: All <field> avg
    out["East"] = east
    out["East · Reference"] = {"Target range from": 3000, "Target range to": 5000}  # Target Low at its default
    out["East · Ends"] = ends(east, first=True)
    tot = df.groupby(m)["Sales"].sum()
    out["Total"] = {k: num(v) for k, v in tot.items()}
    out["Total · Reference"] = {"Usual from": 13000, "Usual to": 16000, "Average": mean(tot)}
    out["Total · Ends"] = {"Sales": {"first": num(tot.iloc[0]), "last": num(tot.iloc[-1])}}
    return out


def colors():
    df = iso_dates(read_csv(DATA / "sales_plan.csv", ("Sales", "Plan")), "Month")
    m = month(df["Month"])
    s, p = by(df, "Manager", "Sales"), by(df, "Manager", "Plan")
    return {"Regions": by(df, "Region", "Sales"),
            "Managers": by(df, ["Region", "Manager"], "Sales"),
            "Plan": {k: {"SUM(Sales)": s[k], "SUM(Plan)": p[k]} for k in s},
            "Trend": by(df, [m, "Region"], "Sales"),
            "Stack": by(df, [m, "Region"], "Sales"),
            "Gap": {k: num(s[k] - p[k]) for k in s}}


def bar_variants():
    df = iso_dates(read_csv(DATA / "sales_plan.csv", ("Sales", "Plan")), "Month")
    s, p = by(df, "Manager", "Sales"), by(df, "Manager", "Plan")
    return {"Target": s,
            "Target · Reference": {"below target": sum(s[k] < p[k] for k in s)},  # bars below their own plan
            "Totals": by(df, ["Region", "Manager"], "Sales"),
            "Values": s}


def bullet():
    df = iso_dates(read_csv(DATA / "sales_plan.csv", ("Sales", "Plan")), "Month")
    out = {}
    for sheet, dim, bands in (("Managers", "Manager", (80, 95)), ("Regions", "Region", (50, 75, 90))):
        s, p = by(df, dim, "Sales"), by(df, dim, "Plan")
        out[sheet] = s
        ref = {"below target": sum(s[k] < p[k] for k in s)}  # bars below their own plan
        for b in bands:  # bars that end in a zone under b % of their plan
            ref[f"below {b}% of target"] = sum(s[k] < p[k] * b / 100 for k in s)
        out[f"{sheet} · Reference"] = ref
    return out


def bar_in_bar():
    df = iso_dates(read_csv(DATA / "sales.csv", ("Sales", "Profit", "Quantity")), "Order Date")
    return {"Inside": by(df, ["Region", "Category"], "Sales"), "Inside · Total": by(df, "Region", "Sales"),
            "Columns": by(df, ["Region", "Category"], "Profit"), "Columns · Total": by(df, "Region", "Profit")}


def stack_legend_groups():
    df = iso_dates(read_csv(DATA / "sales.csv", ("Sales", "Profit", "Quantity")), "Order Date")
    df["Category"] = df["Category"].map({"Furniture": "Furniture and home furnishings",
                                         "Office": "Office supplies and stationery",
                                         "Tech": "Technology and electronics"})  # the marks by their aliases
    return {"Narrow": by(df, ["Region", "Category"], "Sales"), "Wide": by(df, ["Region", "Category"], "Profit")}


def _last_months(col, n, anchor):
    start = (pd.Timestamp(anchor).to_period("M") - (n - 1)).start_time
    end = (pd.Timestamp(anchor).to_period("M") + 1).start_time
    return col.notna() & (col >= start) & (col < end)


def _range(col, lo, hi):
    """Range filter of dates: both ends inclusive (a datetime up to the end of the max day); nulls drop."""
    return col.notna() & (col >= pd.Timestamp(lo)) & (col < pd.Timestamp(hi) + pd.Timedelta(days=1))


def dates():
    df = read_csv(DATA / "sales_dates.csv", ("Sales", "Units"))
    iso_dates(df, "Order Date", "%d.%m.%Y")
    iso_dates(df, "Shipped At", "%Y-%m-%d %H:%M:%S")
    # Order Date 2024-07-01..2025-06-30; Shipped At "Last 3 months" anchored on the latest Shipped At of the data
    keep = _range(df["Order Date"], "2024-07-01", "2025-06-30") & \
        _last_months(df["Shipped At"], 3, df["Shipped At"].max())
    df = df[keep & (df["Region"] != "")]
    week = (df["Shipped At"].dt.normalize() - pd.to_timedelta(df["Shipped At"].dt.weekday, unit="D"))
    return {"KPI": kpi(df, "Sales", "Units"),
            "Orders": by(df, month(df["Order Date"]), "Sales"),
            "Shipments": by(df, week.dt.strftime("%Y-%m-%d"), "Sales"),  # weeks start on Monday
            "Regions": by(df, "Region", "Sales")}


def dates_us():
    df = read_csv(DATA / "sales_dates_us.csv", ("Sales", "Units"))
    iso_dates(df, "Order Date", "%m/%d/%Y")
    iso_dates(df, "Due Date", "%m/%d/%Y")
    iso_dates(df, "Shipped At", "%Y-%m-%d %H:%M:%S")
    # Order Date last 6 months to the anchor 2025-06-15; Shipped At 2025-01-01..2025-03-31 (datetime: the whole
    # last day); Due Date range without ends = all dates, the null one too
    df = df[_last_months(df["Order Date"], 6, "2025-06-15") & _range(df["Shipped At"], "2025-01-01", "2025-03-31")]
    return {"KPI": kpi(df, "Sales", "Units"),
            "Orders": by(df, month(df["Order Date"]), "Sales"),
            "Due": by(df, "Category", "Sales"),
            "Shipments": by(df, df["Shipped At"].dt.strftime("%Y-%m-%d"), "Sales")}


def excel():
    df = pd.read_excel(DATA / "sales.xlsx", sheet_name="Orders 2025")
    out = {"KPI": kpi(df, "Profit", "Quantity", "Sales"),
           "Bar": by(df, ["Region", "Category"], "Sales"),
           "Line": by(df, month(pd.to_datetime(df["Shipped At"])), "Sales"),
           "Table": by(df, ["Region", "Category"], "Profit", "mean")}  # AVG skips the 10 empty Profit cells
    return out




def maps():
    df = read_csv(DATA / "sales_geo.csv", ("Sales", "Profit"))
    return {"States": by(df, "State", "Sales"), "Countries": by(df, "Ship Country", "Sales"),
            "Cities": by(df, "City", "Profit")}


def maps_color():  # decisions/137: the States' colors are a second measure, a record of their own
    df = read_csv(DATA / "sales_geo.csv", ("Sales", "Profit"))
    return {"States": by(df, "State", "Sales"), "States · Color": by(df, "State", "Profit"),
            "Countries": by(df, "Ship Country", "Profit"), "Cities": by(df, "City", "Sales")}


def products():
    return iso_dates(read_csv(DATA / "sales_products.csv", ("Sales", "Profit", "Quantity")), "Order Date")


def params():
    df = products()
    p = df.groupby("Product")
    top8 = p["Sales"].sum().sort_values(ascending=False).head(8)  # Metric = Sales, Top N = 8 (the defaults)
    top3 = p["Profit"].sum().sort_values(ascending=False).head(3)
    start = df["Order Date"].dt.to_period("M").dt.start_time.dt.strftime("%Y-%m-%d")  # Period = month
    return {"KPI": {"AGG(Metric value)": total(df, "Sales")},
            "Top Products": {k: num(v) for k, v in top8.items()},
            "Most Profitable": {k: num(v) for k, v in top3.items()},
            "Trend": by(df, start, "Sales")}


def top_by():
    """decisions/067: Top N by another measure than the one shown: top 5 products by sales showing their profit, top 4
    by margin SUM(Profit) / SUM(Sales) showing sales, a registry of the top 6 by average quantity."""
    p = products().groupby("Product")
    s, pr, q = p["Sales"].sum(), p["Profit"].sum(), p["Quantity"].mean()
    top5 = s.sort_values(ascending=False).head(5).index
    top4 = (pr / s).sort_values(ascending=False).head(4).index
    top6 = q.sort_values(ascending=False).head(6).index
    return {"Profit of Top Sellers": {k: num(pr[k]) for k in sorted(top5)},
            "Sales of Top Margins": {k: num(s[k]) for k in sorted(top4)},
            "Busiest Products": {k: {"Sales": num(s[k]), "Profit": num(pr[k])} for k in sorted(top6)}}


def params_v2():
    """decisions/148: Top 3 / Bottom 3 (Top count = 3) of products by sales on every sheet type; C = D (360) and E = F
    (240) tie, Desktop breaks ties A-Z for both ends (measured), so Top 3 = A, B, C and Bottom 3 = E, F, C."""
    df = read_csv(DATA / "params_v2.csv", ("Sales", "Profit", "Quantity"))
    df["Month"] = df["Order Date"].str[:7]
    s = df.groupby("Product")["Sales"].sum()
    ranked = pd.DataFrame({"s": s, "k": s.index}).sort_values(["s", "k"], ascending=[False, True])
    top3 = set(ranked.head(3).index)
    bottom = pd.DataFrame({"s": s, "k": s.index}).sort_values(["s", "k"], ascending=[True, True])
    bottom3, bottom2 = set(bottom.head(3).index), set(bottom.head(2).index)
    return {"Bottom Bar": {k: num(s[k]) for k in sorted(bottom3)},
            "Top Bar": {k: num(s[k]) for k in sorted(top3)},
            "Top Line": by(df[df["Product"].isin(top3)], ["Month", "Product"], "Sales"),
            "Top Table": by(df[df["Product"].isin(bottom2)], ["Product", "Region"], "Sales"),
            "Top Heat": by(df[df["Product"].isin(top3)], ["Product", "Region"], "Sales"),
            "Top Registry": {k: {"Sales": num(s[k])} for k in sorted(bottom3)}}


def params_field():
    """decisions/163: parameters read from a field when the workbook opens, at the values they open with. Region
    pick = East (its literal default, the list from Region); As of = MAX(Order Date), Min sale = MIN(Sales), Top
    count = COUNTD(Region) = 4 (default_from calcs over the whole data). Ties C = D (360) at the 3rd / 4th place: both
    in the Top 4."""
    df = read_csv(DATA / "params_v2.csv", ("Sales", "Profit", "Quantity"))
    as_of, min_sale, top_n = df["Order Date"].max(), df["Sales"].min(), df["Region"].nunique()
    df["Month"] = df["Order Date"].str[:7]
    before = df["Sales"].where(df["Order Date"] < as_of, 0)
    s = df.groupby("Product")["Sales"].sum()
    ranked = pd.DataFrame({"s": s, "k": s.index}).sort_values(["s", "k"], ascending=[False, True])
    return {"KPI": {"AGG(Region sales)": num(df.loc[df["Region"] == "East", "Sales"].sum()),
                    "AGG(Sales to date)": num(before.sum()),
                    "AGG(Big sales)": num(df.loc[df["Sales"] > min_sale, "Sales"].sum())},
            "Top Bar": {k: num(s[k]) for k in sorted(ranked.head(top_n).index)},
            "To Date": {k: num(v) for k, v in before.groupby(df["Month"]).sum().items()}}


def top_after():
    """decisions/086: Region = West. Top 5 by sales ranked after the filters (RANK, Competition: ties kept) against
    the Top N filter ranked before them (the overall top 5, drawn with their West sales); the top 3 by average
    quantity among the products whose West sales are at most 3 800 (the measure filter comes before the rank)."""
    df = products()
    west = df[df["Region"] == "West"]
    p = west.groupby("Product")
    s, q = p["Sales"].sum(), p["Quantity"].mean()
    rank5 = s.rank(method="min", ascending=False)
    overall = df.groupby("Product")["Sales"].sum().sort_values(ascending=False).head(5).index
    small = q[s <= 3800]
    rank3 = small.rank(method="min", ascending=False)
    return {"Top 5 in Region": {k: num(s[k]) for k in sorted(rank5[rank5 <= 5].index)},
            "Top 5 Overall": {k: num(s[k]) for k in sorted(overall) if k in s.index},
            "Busiest Small Sellers": {k: num(q[k]) for k in sorted(rank3[rank3 <= 3].index)}}


def bar_dates():
    """decisions/090: bars along a date (a bar per month stacked by category, per quarter stacked by Size) and the
    calc Size = Large (Sales >= 500) / Medium (>= 200) / Small in its manual order."""
    df = sales()
    df["Size"] = ["Large" if s >= 500 else "Medium" if s >= 200 else "Small" for s in df["Sales"]]
    quarter = df["Order Date"].dt.year.astype(str) + "-Q" + df["Order Date"].dt.quarter.astype(str)
    return {"Sales by Month": by(df, [month(df["Order Date"]), "Category"], "Sales"),
            "Orders by Size": by(df, "Size", "Sales", "count"),
            "Sales by Quarter": by(df, [quarter, "Size"], "Sales")}


def nav():
    """decisions/040: three dashboards over shared sheets, the Region filter at (All)."""
    df = sales()
    s, p = by(df, "Region", "Sales"), by(df, "Region", "Profit")
    return {"KPI": kpi(df, "Sales", "Profit"),
            "By Category": by(df, "Category", "Sales"),
            "Trend": by(df, month(df["Order Date"]), "Sales"),
            "By Region": {k: {"Sales": s[k], "Profit": p[k]} for k in s},
            "Matrix": by(df, ["Region", "Category"], "Sales")}


def multi_source():
    """decisions/083: two data sources in one book, each sheet on its own: sales.csv (KPI with the margin, sales by
    region) and sales_plan.csv (plan and attainment, Top 4 managers by sales at the parameter's default); both
    filter cards at (All). Sales and Region are columns of both files: each sheet sums its own."""
    df, plan = sales(), read_csv(DATA / "sales_plan.csv", ("Sales", "Plan"))
    top4 = plan.groupby("Manager")["Sales"].sum().sort_values(ascending=False).head(4)
    return {"Orders KPI": {"SUM(Sales)": total(df, "Sales"),
                           "AGG(Margin)": num(df["Profit"].sum() / df["Sales"].sum())},
            "Orders by Region": by(df, "Region", "Sales"),
            "Plan KPI": {"SUM(Plan)": total(plan, "Plan"), "AGG(Attainment)": num(plan["Sales"].sum() / plan["Plan"].sum())},
            "Sales by Manager": {k: num(v) for k, v in sorted(top4.items())}}


def switch_registry():
    """decisions/082: sales.csv (KPI) and sales_plan.csv (a switch of two registries and a bar). Every view has its
    numbers, shown or hidden: sales and plan by manager with the attainment, by region; sales by manager."""
    df, plan = sales(), read_csv(DATA / "sales_plan.csv", ("Sales", "Plan"))
    m = plan.groupby("Manager")[["Sales", "Plan"]].sum()
    r = plan.groupby("Region")[["Sales", "Plan"]].sum()
    return {"Orders KPI": kpi(df, "Sales", "Profit"),
            "Plan by Manager": {k: {"Sales": num(x.Sales), "Plan": num(x.Plan), "Attainment": num(x.Sales / x.Plan)}
                                for k, x in m.iterrows()},
            "Plan by Region": {k: {"Sales": num(x.Sales), "Plan": num(x.Plan)} for k, x in r.iterrows()},
            "Plan Chart": by(plan, "Manager", "Sales")}


def dual_axis():
    """decisions/044: combo (sales bars + profit line), donut with its total and legend shares, lollipop."""
    df = sales("sales_2y.csv")
    s, p = by(df, "Region", "Sales"), by(df, "Region", "Profit")
    cat = df.groupby("Category")["Sales"].sum()
    return {"Combo": {k: {"SUM(Sales)": s[k], "SUM(Profit)": p[k]} for k in s},
            "Donut": {k: num(v) for k, v in cat.items()},
            "Donut · Total": num(cat.sum()),
            "Donut · Legend": {k: {"value": num(v), "share": num(v / cat.sum())} for k, v in cat.items()},
            "Lollipop": by(df, "Region", "Quantity")}


def pareto():
    """decisions/157: cost and ticket count by cause largest first (ties by name), the running share of the total;
    the vital few: the causes whose running share before them is under 80 %."""
    df = read_csv(DATA / "complaints.csv", ("Cost",))
    out = {}
    for sheet, col, agg, label in (("Cost Pareto", "Cost", "sum", "SUM(Cost)"),
                                   ("Count Pareto", "Ticket", "count", "COUNT(Ticket)")):
        g = df.groupby("Cause")[col].agg(agg)
        g = g.reset_index().sort_values([col, "Cause"], ascending=[False, True]).set_index("Cause")[col]
        run = g.cumsum() / g.sum()
        out[sheet] = {k: {label: num(g[k]), "Cumulative": num(run[k])} for k in g.index}
        if sheet == "Cost Pareto":
            vital = (run - g / g.sum()) < 0.8
            out["Cost Pareto · Vital"] = {"count": int(vital.sum()), "share": num(run[vital].iloc[-1])}
    return out


def totals():
    """decisions/036: grand totals of a table as the aggregate over the rows (AVG of all orders, not of the cells),
    'All' as the label of the second table, registry subtotals per region and the grand total row."""
    df = sales()

    def grid(col, agg, label):
        out = {}
        for (r, c), v in df.groupby(["Region", "Category"])[col].agg(agg).items():
            out[f"{r} | {c}"] = num(v)
        for r, v in df.groupby("Region")[col].agg(agg).items():
            out[f"{r} | {label}"] = num(v)
        for c, v in df.groupby("Category")[col].agg(agg).items():
            out[f"{label} | {c}"] = num(v)
        out[f"{label} | {label}"] = num(df[col].agg(agg))
        return out

    def row(part):
        return {"Sales": num(part["Sales"].sum()), "Avg profit": num(part["Profit"].mean()),
                "Order sizes": int(part["Quantity"].nunique())}

    reg = {f"{r} | {c}": row(g) for (r, c), g in df.groupby(["Region", "Category"])}
    reg |= {f"{r} | Total": row(g) for r, g in df.groupby("Region")}
    reg["Total"] = row(df)
    return {"Sales": grid("Sales", "sum", "Total"), "Avg Profit": grid("Profit", "mean", "All"), "Registry": reg,
            "Regions": by(df, "Region", "Sales")}


def registry_totals():
    """decisions/081: a registry total under bar columns is the measure over the rows of its partition: Sales the sum,
    Margin SUM(Profit) / SUM(Sales) of all the rows (not a sum or average of the row margins); subtotals per region."""
    df = sales()

    def row(part):
        return {"Sales": num(part["Sales"].sum()), "Margin": num(part["Profit"].sum() / part["Sales"].sum()),
                "Units": num(part["Quantity"].sum())}

    def cat(part):
        return {"Sales": num(part["Sales"].sum()), "Profit": num(part["Profit"].sum()),
                "Margin %": num(part["Profit"].sum() / part["Sales"].sum())}

    regions = {r: row(g) for r, g in df.groupby("Region")} | {"TOTAL": row(df)}
    cats = {f"{r} | {c}": cat(g) for (r, c), g in df.groupby(["Region", "Category"])}
    cats |= {f"{r} | Total": cat(g) for r, g in df.groupby("Region")}
    cats["Total"] = cat(df)
    return {"Regions": regions, "Categories": cats}


def registry_spark_pill():
    """decisions/096: a spark is the quarter sums of Sales (2024-01-01, 8 quarters, an empty one 0) as 8 block glyphs
    from the series' lowest to its highest (INT(7 * (v - lo) / (hi - lo) + 0.5), flat -> the middle one); a pill is the
    level of SUM(Profit): High from 7000, OK from 5000, else Low."""
    df = sales("sales_2y.csv")
    glyphs = "▁▂▃▄▅▆▇█"
    quarters = pd.period_range("2024Q1", periods=8, freq="Q")
    out = {}
    for region, g in df.groupby("Region"):
        per = g.groupby(g["Order Date"].dt.to_period("Q"))["Sales"].sum().reindex(quarters, fill_value=0)
        lo, hi = per.min(), per.max()
        idx = [3 if hi == lo else int(7 * (v - lo) / (hi - lo) + 0.5) for v in per]
        profit = g["Profit"].sum()
        out[region] = {"Sales": num(g["Sales"].sum()), "Quarterly sales": "".join(glyphs[i] for i in idx),
                       "Profit": "High" if profit >= 7000 else "OK" if profit >= 5000 else "Low"}
    return {"Regions": out}


def registry_spark_line():
    """decisions/153: a line spark is the month sums of Sales over 24 months from 2024-01; its dot (the registry's
    column) the last month, December 2025; the other columns the region's Sales and Profit."""
    df = sales("sales_2y.csv")
    months = pd.period_range("2024-01", periods=24, freq="M")
    regions, line = {}, {}
    for region, g in df.groupby("Region"):
        per = g.groupby(g["Order Date"].dt.to_period("M"))["Sales"].sum()
        per = per[per.index.isin(months)]
        for m, v in per.items():
            line[f"{region} | {m.strftime('%Y-%m')}"] = num(v)
        regions[region] = {"Sales": num(g["Sales"].sum()), "Profit": num(g["Profit"].sum()),
                           "Monthly sales": num(per.get(months[-1], float("nan")))}
    return {"Regions": regions, "Regions · Monthly sales": line}


def registry_totals_marks():
    """decisions/134: rank / track / dot / tick / highlight columns under registry totals. A rank is blank on a total
    (rows: by Sales desc, managers within their region), the track is the share of the whole source (100 % on the grand
    total, a region's on its subtotal), the dot's average and the tick's bar are the measure of the partition, the
    tick's Plan line blank on a total."""
    df = read_csv(DATA / "sales_plan.csv", ("Sales", "Plan"))
    whole = df["Sales"].sum()

    def ranks(sums):
        return {k: int(v) for k, v in sums.rank(ascending=False, method="min").items()}

    def region(part, rank):
        return {"#": rank, "Of total": num(part["Sales"].sum() / whole), "Avg plan": num(part["Plan"].mean()),
                "Sales": num(part["Sales"].sum())}

    def manager(part, rank):
        return {"Sales vs plan": num(part["Sales"].sum()), "Sales vs plan · Plan": num(part["Plan"].sum()) if rank else None,
                "#": rank, "Of total": num(part["Sales"].sum() / whole), "Plan": num(part["Plan"].sum())}

    r_rank = ranks(df.groupby("Region")["Sales"].sum())
    regions = {r: region(g, r_rank[r]) for r, g in df.groupby("Region")} | {"TOTAL": region(df, None)}
    managers = {}
    for r, g in df.groupby("Region"):
        m_rank = ranks(g.groupby("Manager")["Sales"].sum())
        managers |= {f"{r} | {m}": manager(h, m_rank[m]) for m, h in g.groupby("Manager")}
        managers[f"{r} | Total"] = manager(g, None)
    managers["Total"] = manager(df, None)
    return {"Regions": regions, "Managers": managers}


def filters_v2():
    """decisions/035, Tableau's filter order: the context filter Region = North first, FIXED and Top 5 over it (all
    channels), then the Channel filter (Online, Retail) on every sheet."""
    df = iso_dates(read_csv(DATA / "sales_stores.csv", ("Sales", "Profit")), "Order Date")
    ctx = df[df["Region"] == "North"]
    top5 = ctx.groupby("Product")["Sales"].sum().sort_values(ascending=False).head(5).index
    shown = ctx[ctx["Channel"].isin(["Online", "Retail"])]
    return {"KPI": {"SUM(Sales)": total(shown, "Sales"),
                    "AGG(Share of region)": num(shown["Sales"].sum() / ctx["Sales"].sum())},
            "Top Products": by(shown[shown["Product"].isin(top5)], "Product", "Sales"),
            "By City": by(shown, "City", "Sales")}


def filters_cards():
    """decisions/162, header cards: Region single slider at West, City wildcard 'o' (contains, with case), Sales
    range 100..400 per row (a Null drops out), Channel Online + Retail behind an Apply button."""
    df = read_csv(DATA / "sales_stores.csv", ("Sales", "Profit"))
    shown = df[(df["Region"] == "West") & df["City"].str.contains("o", regex=False, na=False)
               & df["Sales"].between(100, 400) & df["Channel"].isin(["Online", "Retail"])]
    return {"KPI": {"SUM(Sales)": total(shown, "Sales")},
            "By City": by(shown, "City", "Sales"), "By Product": by(shown, "Product", "Sales")}


def filters_cards_panel():
    """decisions/162, right panel: Region single value list at East, Channel list Online + Partner with Apply."""
    df = read_csv(DATA / "sales_stores.csv", ("Sales", "Profit"))
    shown = df[(df["Region"] == "East") & df["Channel"].isin(["Online", "Partner"])]
    return {"By City": by(shown, "City", "Sales"), "By Product": by(shown, "Product", "Sales")}


def tablecalc_funcs():
    """decisions/034: rank (competition / dense asc), window avg / min / max, LOOKUP, RUNNING_SUM, FIRST / LAST
    windows, TOTAL, INDEX; every compute-using as in the spec."""
    df = sales()
    reg = df.groupby("Region")["Sales"].sum()
    orders = df.groupby("Region")["Sales"].count()
    mon = df.groupby(month(df["Order Date"]))["Sales"].sum().sort_index()
    rc = df.groupby(["Region", "Category"])["Sales"].sum()
    cat_total = rc.groupby(level=1).transform("sum")  # TOTAL along Region: per category
    lo, hi = rc.groupby(level=0).transform("min"), rc.groupby(level=0).transform("max")  # along Category
    key = lambda k: f"{k[0]} | {k[1]}"  # noqa: E731
    as_dict = lambda s: {k: num(v) for k, v in s.items()}  # noqa: E731
    return {"Sales Rank": as_dict(reg.rank(method="min", ascending=False).astype(int)),
            "Orders Rank": as_dict(orders.rank(method="min", ascending=False).astype(int)),
            "Orders Dense Rank": as_dict(orders.rank(method="dense").astype(int)),
            "Sales vs Avg": as_dict(reg - reg.mean()),
            "Moving Avg": as_dict(mon.rolling(3, min_periods=1).mean()),
            "Prev Month": as_dict(mon.shift(1)),
            "Running": as_dict(mon.cumsum()),
            "Cumulative": as_dict(mon.expanding().mean()),
            "Remaining": as_dict(mon[::-1].cumsum()[::-1]),
            "Share": {key(k): num(v) for k, v in (rc / cat_total).items()},
            "Min-Max": {key(k): num(v) for k, v in ((rc - lo) / (hi - lo)).items()},
            "Index": {key(k): i + 1 for i, k in enumerate(rc.index)}}


def tablecalc_v2():
    """decisions/147: SIZE, RANK_UNIQUE, RUNNING_AVG / MIN / MAX / COUNT, WINDOW_COUNT / MEDIAN, PREVIOUS_VALUE and the
    NULL / tie rules, per Region along Month (pandas: NaN is skipped by the folds, a mark of NaN keeps its place)."""
    df = read_csv(DATA / "tablecalc_v2.csv", numbers=("Sales", "Refunds")).sort_values(["Region", "Month"])
    out = {n: {} for n in ("Size", "Unique Rank", "Unique Rank Asc", "Running Refunds", "Running Avg", "Running Min",
                           "Running Max", "Running Count", "Window Count", "Window Sum Refunds", "Window Median",
                           "Previous Value")}
    for reg, g in df.groupby("Region"):
        g = g.reset_index(drop=True)
        s, r = g["Sales"], g["Refunds"]
        run = r.expanding()
        prev = (s.cumsum())  # PREVIOUS_VALUE(0) + SUM(Sales) = the running total of Sales
        cols = {"Size": pd.Series([len(g)] * len(g)),
                "Unique Rank": s.rank(method="first", ascending=False),
                "Unique Rank Asc": s.rank(method="first", ascending=True),
                "Running Refunds": run.sum().where(run.count() > 0),
                "Running Avg": run.mean(), "Running Min": run.min(), "Running Max": run.max(),
                "Running Count": run.count().where(run.count() > 0),
                "Previous Value": prev}
        for i in range(len(g)):
            w1 = r.iloc[max(0, i - 1):i + 2]
            w2 = r.iloc[max(0, i - 1):i + 1]
            w3 = s.iloc[max(0, i - 2):i + 1]
            cols.setdefault("Window Count", {})[i] = int(w1.count()) or None
            cols.setdefault("Window Sum Refunds", {})[i] = w2.sum() if w2.count() else None
            cols.setdefault("Window Median", {})[i] = w3.median()
        for name, vals in cols.items():
            for i, m in enumerate(g["Month"]):
                v = vals[i]
                out[name][f"{m} | {reg}"] = None if v is None or v != v else num(v)
    return {n: dict(sorted(d.items())) for n, d in out.items()}


def fields():
    """decisions/033: Region by its aliases, the Product Line group (Core, Growth, the rest Other)."""
    df = products()
    alias = {"East": "East coast", "North": "North side", "South": "South belt", "West": "West coast"}
    df["R"] = df["Region"].map(alias)
    line = {p: "Core" for p in ("Atlas", "Beacon", "Cobalt", "Delta")} | \
           {p: "Growth" for p in ("Ember", "Falcon", "Granite")}
    df["L"] = df["Product"].map(line).fillna("Other")
    return {"Regions": by(df, "R", "Sales"), "Lines": by(df, "L", "Sales"), "Matrix": by(df, ["R", "L"], "Sales")}


def fields_v2():
    """decisions/151: the Order Size calc (aliases), a group over it, a group over Quantity (aliases)."""
    df = products()
    sales = df["Sales"]
    size = sales.map(lambda v: "Large" if v >= 300 else "Medium" if v >= 150 else "Small")
    df["S"] = size.map({"Large": "Large order", "Medium": "Medium order", "Small": "Small order"})
    df["T"] = size.map({"Large": "Top orders", "Medium": "The rest", "Small": "The rest"})
    df["B"] = df["Quantity"].map(lambda q: "1-4 units" if q <= 4 else "5-8 units" if q <= 8 else "9+ units")
    return {"Sizes": by(df, "S", "Sales"), "Tiers": by(df, "T", "Sales"), "Bands": by(df, "B", "Sales"),
            "Matrix": by(df, ["T", "B"], "Sales")}



def tile_grid():
    """decisions/154: sales per state; the tile map at the CSV's Tile Row / Tile Col, the wall by sales descending
    within each region (a tie by the state), three to a row."""
    df = read_csv(DATA / "sales_states.csv", ("Sales", "Profit"))
    s = df.groupby("State")["Sales"].sum()
    first = df.drop_duplicates("State").set_index("State")
    tiles = {k: {"row": int(first.loc[k, "Tile Row"]), "col": int(first.loc[k, "Tile Col"])} for k in sorted(s.index)}
    ranked = pd.DataFrame({"s": s, "k": s.index, "g": first.loc[s.index, "Region"]}).sort_values(
        ["s", "k"], ascending=[False, True])
    ranked["i"] = ranked.groupby("g").cumcount()
    wall = {k: {"row": int(i // 3 + 1), "col": int(i % 3 + 1), "group": g}
            for k, g, i in zip(ranked["k"], ranked["g"], ranked["i"])}
    vals = by(df, "State", "Sales")
    return {"State Tiles": vals, "State Tiles · Tiles": tiles,
            "Region Wall": vals, "Region Wall · Tiles": dict(sorted(wall.items()))}





def theme_cards():
    """decisions/030: the card theme over cards MoM, bars, a monthly line and a registry."""
    df = sales("sales_2y.csv")
    s, p = by(df, ["Region", "Category"], "Sales"), by(df, ["Region", "Category"], "Profit")
    return {"KPI": {"Sales": card(df, "Order Date", "Sales", 1), "Profit": card(df, "Order Date", "Profit", 1),
                    "Units": card(df, "Order Date", "Quantity", 1)},
            "Regions": by(df, "Region", "Sales"),
            "Trend": by(df, month(df["Order Date"]), "Sales"),
            "Registry": {k: {"Sales": s[k], "Profit": p[k]} for k in s}}


def shell():
    """decisions/029: the shell (sidebar, topbar) around KPI, bar, line and table on sales.csv."""
    df = sales()
    return {"KPI": kpi(df, "Sales", "Profit"), "Bar": by(df, "Region", "Sales"),
            "Line": by(df, month(df["Order Date"]), "Sales"), "Table": by(df, ["Region", "Category"], "Sales")}


def interactive():
    """decisions/042 at the parameter defaults: Metric = Sales, Period = L6M (the latest date's month and the 5
    before it: DATEDIFF('month', date, FIXED MAX) < 6), View = Chart (the table sheet still has its numbers)."""
    df = products()
    d = df["Order Date"]
    last = d.max()
    df = df[(last.year * 12 + last.month) - (d.dt.year * 12 + d.dt.month) < 6]
    return {"Trend": by(df, month(df["Order Date"]), "Sales"),
            "Products Chart": by(df, "Product", "Sales"),
            "Products Table": by(df, ["Product", "Region"], "Sales")}


def params_filters_v3():
    """decisions/057 at the parameter defaults: Cutoff 2025-09-30 (a date), Top count 5 (an integer list), Target
    margin 0.25 (a real), With West true (a boolean). The shared context filter keeps Order Date <= Cutoff (a boolean
    calc); Top N ranks over those rows; a sheet's own filters: values (Region, a boolean calc, a text calc) before the
    aggregation, the measure filters (SUM(Sales) >= 9000, Margin >= 0.14) on each mark after it."""
    df = products()
    ctx = df[df["Order Date"] <= pd.Timestamp("2025-09-30")]
    shown = ctx["Sales"].sum()  # With West = true: every region
    margin = ctx["Profit"].sum() / ctx["Sales"].sum()
    top5 = ctx.groupby("Product")["Sales"].sum().sort_values(ascending=False).head(5)
    ne = ctx[ctx["Region"].isin(["North", "East"]) & (ctx["Profit"] > 0)]
    big = ctx.groupby("Product")["Sales"].sum()
    large = ctx[ctx["Quantity"] >= 3].groupby("Region")[["Profit", "Sales"]].sum()
    large_margin = large["Profit"] / large["Sales"]
    return {"KPI": {"AGG(Shown sales)": num(shown), "AGG(Margin gap)": num(margin - 0.25)},
            "Top Products": {k: num(v) for k, v in top5.sort_index().items()},
            "North East": by(ne, "Product", "Sales"),
            "Big Products": {k: num(v) for k, v in big[big >= 9000].items()},
            "Large Orders": {k: num(v) for k, v in large_margin[large_margin >= 0.14].items()},
            "Trend": by(ctx, month(ctx["Order Date"]), "Sales")}


def scatter():
    df = products()
    p = df.groupby("Product")[["Sales", "Profit", "Quantity"]].sum()

    def points(x, y, frame=p):
        return {(" | ".join(k) if isinstance(k, tuple) else k): {f"SUM({x})": num(r[x]), f"SUM({y})": num(r[y])}
                for k, r in frame.iterrows()}
    pr = df.groupby(["Product", "Region"])[["Sales", "Quantity"]].sum()
    return {"Products": points("Quantity", "Sales"),
            "Products · Axis Lines": {"SUM(Quantity)": mean(p["Quantity"]), "SUM(Sales)": mean(p["Sales"])},
            "Profitability": points("Sales", "Profit"),
            "Profitability · Axis Lines": {"SUM(Sales)": median(p["Sales"]), "SUM(Profit)": median(p["Profit"])},
            "Regions": points("Quantity", "Sales", pr),
            "Margin": points("Quantity", "Profit")}


def _tableau_str(v):
    """STR() of a float: 17 significant digits, no trailing '.0' (decisions/031)."""
    return f"{v:.17g}"


def _week_sunday(d):
    """WEEK(): week 1 holds Jan 1, weeks start on Sunday (Desktop: Dec 29..31 2024 = W53, decisions/031)."""
    jan1 = dt.date(d.year, 1, 1)
    return (d.timetuple().tm_yday - 1 + (jan1.weekday() + 1) % 7) // 7 + 1


def _monday(d):
    """DATEDIFF('week') counts Monday boundaries, the book's start of week (decisions/031: Ship Weeks 78)."""
    return d - dt.timedelta(days=d.weekday())










def _hour_min(s, unit):
    """Boundaries of `unit` ('h' / 'min') crossed between two datetimes, as DATEDIFF counts them (decisions/051)."""
    return s.dt.floor(unit)


def dates_v2():
    """decisions/051: ISO with T, DD.MM.YYYY HH:MM, D.M.YYYY, D/M/YYYY; each read with its format written by hand."""
    df = read_csv(DATA / "sales_dates_v2.csv", ("Sales", "Units"))
    iso_dates(df, "Ordered At", "%Y-%m-%dT%H:%M")
    iso_dates(df, "Shipped At", "%d.%m.%Y %H:%M")
    iso_dates(df, "Paid On", "%d.%m.%Y")  # %d / %m read one digit too
    iso_dates(df, "Booked On", "%d/%m/%Y")
    # Ordered At 2024-01-01 09:00 .. 2024-12-31 18:00 (both moments in); Shipped At last 12 months to the latest
    o = df["Ordered At"]
    df = df[(o >= "2024-01-01 09:00") & (o <= "2024-12-31 18:00") &
            _last_months(df["Shipped At"], 12, df["Shipped At"].max())]
    o, s = df["Ordered At"], df["Shipped At"]
    ship_hours = (_hour_min(s, "h") - _hour_min(o, "h")).dt.total_seconds() // 3600
    week = s.dt.normalize() - pd.to_timedelta(s.dt.weekday, unit="D")
    two = lambda m: m.dt.strftime("%Y-%m")  # noqa: E731  'Paid Month' = YEAR + "-" + 0-padded MONTH
    return {"KPI": {**kpi(df, "Sales", "Units"), "SUM(Ship Hours)": num(ship_hours.sum()),
                    "AGG(Active Hours)": int(o.dt.floor("h").nunique())},
            "Orders": by(df, month(o), "Sales"),
            "Shipments": by(df, week.dt.strftime("%Y-%m-%d"), "Sales"),
            "Hours": by(df, [o.dt.strftime("%H:00"), "Channel"], "Sales"),
            "Paid": by(df, [two(df["Paid On"]), "Channel"], "Sales"),
            "Booked": by(df, [two(df["Booked On"]), "Channel"], "Sales")}


def dates_v2_us():
    """decisions/051: M/D/YYYY H:MM, M/D/YYYY (en_US), ISO with T and seconds."""
    df = read_csv(DATA / "sales_dates_v2_us.csv", ("Sales", "Units"))
    iso_dates(df, "Ordered At", "%m/%d/%Y %H:%M")
    iso_dates(df, "Paid On", "%m/%d/%Y")
    iso_dates(df, "Logged At", "%Y-%m-%dT%H:%M:%S")
    # Logged At 2024-03-01 10:00 .. 2024-11-30 12:30:30; Paid On last 6 months to the anchor 2024-12-15
    lg = df["Logged At"]
    df = df[(lg >= "2024-03-01 10:00") & (lg <= "2024-11-30 12:30:30") & _last_months(df["Paid On"], 6, "2024-12-15")]
    o, lg = df["Ordered At"], df["Logged At"]
    due = o + pd.Timedelta(hours=2)
    minutes_left = (_hour_min(due, "min") - _hour_min(lg, "min")).dt.total_seconds() // 60
    return {"KPI": {**kpi(df, "Sales", "Units"), "SUM(Minutes Left)": num(minutes_left.sum()),
                    "SUM(Late Logs)": int((o + pd.Timedelta(hours=1) < lg).sum())},
            "Orders": by(df, month(o), "Sales"),
            "Logs": by(df, lg.dt.strftime("%Y-%m-%d"), "Sales"),
            "Hours": by(df, [o.dt.strftime("%H:00"), "Channel"], "Sales"),
            "Paid": by(df, [month(df["Paid On"]), "Channel"], "Sales")}



def funnel():
    """decisions/159: users per stage; Funnel by users desc, conversion over the stage above (none on the first);
    Social Funnel (Channel = Social) in the process order, conversion over Visit."""
    df = read_csv(DATA / "funnel.csv", numbers=("Users",))
    order = ["Visit", "Sign-up", "Trial", "Purchase", "Renewal"]

    def rows(g, stages, base):
        out = {}
        for i, k in enumerate(stages):
            b = None if base == "previous" and i == 0 else g[stages[i - 1]] if base == "previous" else g[stages[0]]
            out[k] = {"value": num(g[k]), "conversion": None if b is None else num(g[k] / b)}
        return out

    every = df.groupby("Stage")["Users"].sum()
    social = df[df["Channel"] == "Social"].groupby("Stage")["Users"].sum()
    return {"Funnel": rows(every, list(every.sort_values(ascending=False).index), "previous"),
            "Social Funnel": rows(social, order, "first")}


# golden stem -> (function, data file relative to the root, what the numbers are)
GOLDENS = {
    "golden_2025_1": (golden, "data/sample/sales.csv", "KPI, bar Region x Category, line by month, table"),
    "golden_format_2025_1": (format_, "data/sample/sales.csv", "KPI, bar Region, line, table"),
    "golden_headers_2025_1": (headers, "data/sample/sales.csv", "KPI, bar Region x Category, line, table"),
    "golden_layout_sidebar_2025_1": (layout_sidebar, "data/sample/sales.csv", "as golden_headers"),
    "golden_declutter_2025_1": (declutter, "data/sample/sales.csv", "all 6 sheet types"),
    "golden_charts_2025_1": (charts, "data/sample/sales.csv", "area month x Category, heatmap"),
    "golden_actions_2025_1": (actions, "data/sample/sales.csv", "KPI, registry Region, bar Category, line"),
    "golden_actions_v2_2025_1": (actions_v2, "data/sample/sales.csv", "KPI with a parameter calc, registry Region "
                                 "(parameter action), bars Category / month (highlight, URL), line by Category"),
    "golden_registry_2025_1": (registry, "data/sample/sales.csv", "registry Region x Category and Category"),
    "golden_registry_totals_2025_1": (registry_totals, "data/sample/sales.csv", "registry totals under bar and "
                                                                                "bar_inside columns, subtotals"),
    "golden_registry_spark_pill_2025_1": (registry_spark_pill, "data/sample/sales_2y.csv", "registry spark (block glyphs) "
                                                                                        "and pill (level)"),
    "golden_registry_spark_line_2025_1": (registry_spark_line, "data/sample/sales_2y.csv", "registry line spark "
                                                                                        "(month sums, last dot)"),
    "golden_registry_totals_marks_2025_1": (registry_totals_marks, "data/sample/sales_plan.csv", "registry rank, track, "
                                            "dot, tick and highlight under totals"),
    "golden_calcs_2025_1": (calcs, "data/sample/sales.csv", "ratio calc, IF calc, bin calc"),
    "golden_lods_2025_1": (lods, "data/sample/sales.csv", "FIXED: total, region, first-day orders"),
    "golden_lods_view_2025_1": (lods_view, "data/sample/sales.csv", "INCLUDE / EXCLUDE Category"),
    "golden_tablecalcs_2025_1": (tablecalcs, "data/sample/sales.csv", "share, AVG share, difference, running, MoM"),
    "golden_cards_2025_1": (cards, "data/sample/sales_2y.csv", "MoM / YoY cards, trend"),
    "golden_layout_kpi_left_2025_1": (layout_kpi_left, "data/sample/sales_2y.csv", "MoM cards, bar, line, table"),
    "golden_formats_2025_1": (formats, "data/sample/sales_2y.csv", "card, KPI calcs, bar, MIN table, ratio heatmap"),
    "golden_reflines_2025_1": (reflines, "data/sample/sales_2y.csv", "cards + history average, avg / median / "
                                                                     "constant / parameter lines"),
    "golden_colors_2025_1": (colors, "data/sample/sales_plan.csv", "bars, plan vs fact, series, gap"),
    "golden_benchmark_2025_1": (benchmark, "data/sample/sales_2y.csv", "selected region vs the average region, line "
                                                                       "ends, band edges"),
    "golden_heatmap_v2_2025_1": (heatmap_v2, "data/sample/sales_2y.csv", "month-of-year x region with marginal "
                                                                         "totals, change 2025 vs 2024, profit bars"),
    "golden_heatmap_rows_2025_1": (heatmap_rows, "data/sample/sales_2y.csv", "two row fields (region bold over "
                                                                             "category), labels from 10 only"),
    "golden_dual_axis_2025_1": (dual_axis, "data/sample/sales_2y.csv", "combo, donut with its total and legend, "
                                                                       "lollipop"),
    "golden_pareto_2025_1": (pareto, "data/sample/complaints.csv", "Pareto: cost and tickets by cause, running "
                                                                    "share, the vital few under 80 %"),
    "golden_totals_2025_1": (totals, "data/sample/sales.csv", "grand totals both ways (sum, average), registry "
                                                              "subtotals and the total row"),
    "golden_tablecalc_funcs_2025_1": (tablecalc_funcs, "data/sample/sales.csv", "RANK / RANK_DENSE, WINDOW_*, LOOKUP, "
                                                                                "RUNNING_SUM, FIRST / LAST, TOTAL, "
                                                                                "INDEX"),
    "golden_tablecalc_v2_2025_1": (tablecalc_v2, "data/sample/tablecalc_v2.csv", "SIZE, RANK_UNIQUE, RUNNING_AVG / "
                                                                                 "MIN / MAX / COUNT, WINDOW_COUNT / "
                                                                                 "MEDIAN, PREVIOUS_VALUE, NULL, ties"),
    "golden_params_v2_2025_1": (params_v2, "data/sample/params_v2.csv", "Top N / Bottom N on bar, line, table, heatmap and "
                                                                       "registry, tie order A-Z, aliases, heading"),
    "golden_params_field_2025_1": (params_field, "data/sample/params_v2.csv", "parameters from a field when the "
                                                                             "workbook opens: lists and defaults"),
    "golden_fields_2025_1": (fields, "data/sample/sales_products.csv", "Region aliases, the Product Line group with "
                                                                      "Other"),
    "golden_tile_grid_2025_1": (tile_grid, "data/sample/sales_states.csv", "a US tile map from the data's row / "
                                                                         "column, a wall ranked by region"),
    "golden_funnel_2025_1": (funnel, "data/sample/funnel.csv", "stages by users with the conversion over the stage "
                                                               "above; Social in process order over the visits"),
    "golden_fields_v2_2025_1": (fields_v2, "data/sample/sales_products.csv", "a calc with aliases, order and colors, "
                                                                           "groups over a calc and a number, a "
                                                                           "group filter"),
    "golden_nav_2025_1": (nav, "data/sample/sales.csv", "three dashboards over shared sheets, Region (All)"),
    "golden_filters_v2_2025_1": (filters_v2, "data/sample/sales_stores.csv", "context Region = North, Top 5 "
                                                                          "products, Channel Online + Retail"),
    "golden_shell_2025_1": (shell, "data/sample/sales.csv", "brand sidebar and top bar, Region and Category (All)"),
    "golden_filters_cards_2025_1": (filters_cards, "data/sample/sales_stores.csv", "single slider Region = West, "
                                                                                 "wildcard City 'o', Sales 100..400, "
                                                                                 "Channel with Apply"),
    "golden_filters_cards_panel_2025_1": (filters_cards_panel, "data/sample/sales_stores.csv", "single value list "
                                                                                             "Region = East, Channel "
                                                                                             "list with Apply"),
    "golden_multi_source_2025_1": (multi_source, "data/sample/sales.csv and data/sample/sales_plan.csv",
                                   "two data sources, Category and Region (All), Top 4 managers"),
    "golden_folders_2025_1": (multi_source, "data/sample/sales.csv and data/sample/sales_plan.csv",
                              "multi_source with field folders, Category and Region (All), Top 4 managers"),
    "golden_switch_registry_2025_1": (switch_registry, "data/sample/sales.csv and data/sample/sales_plan.csv",
                                      "a switch of two registries and a bar on the plan source, every view"),
    "golden_kpi_v2_nopill_2025_1": (kpi_v2, "data/sample/sales_2y.csv", "cards abs + % delta (no pill, no marker), "
                                                                        "history max / min / last and average, period "
                                                                        "line, data as of"),
    "golden_kpi_v2_2025_1": (kpi_v2, "data/sample/sales_2y.csv", "cards abs + % delta, pill and marker bars, history "
                                                                 "max / min / last and average, period line, data as "
                                                                 "of"),
    "golden_kpi_spark_points_2025_1": (kpi_spark_points, "data/sample/sales_2y.csv", "KPI sparklines with max / min "
                                                                                     "/ last dots: marked months"),
    "golden_kpi_v3_2025_1": (kpi_v3, "data/sample/sales_2y.csv", "KPI area sparklines, month letters, max / min dots "
                                                                 "with one legend, the base value as a number"),
    "golden_kpi_progress_2025_1": (kpi_progress, "data/sample/sales_2y.csv", "KPI cards against a target: share, "
                                                                             "progress bar and thin, over the target"),
    "golden_registry_v2_2025_1": (registry_v2, "data/sample/sales_2y.csv", "rank, share, track, dot, tick at 2024, "
                                                                           "change, two-line cell, top 2 per field"),
    "golden_registry_single_2025_1": (registry_single, "data/sample/sales_2y.csv", "one column per style: one pane, "
                                                                                   "id 1 without x-axis-name"),
    "golden_kpi_status_2025_1": (kpi_status, "data/sample/sales_2y.csv", "KPI status dots by thresholds on the value "
                                                                         "or the change"),
    "golden_theme_cards_2025_1": (theme_cards, "data/sample/sales_2y.csv", "card theme: KPI strip, bar, line, "
                                                                            "registry on cards (decisions/030, 070)"),
    "golden_hyper_2025_1": (dates, "data/sample/sales_dates.csv", "golden_dates as a packaged .hyper (decisions/026, "
                                                                  "080): after range + relative filters"),
    "golden_dates_us_2025_1": (dates_us, "data/sample/sales_dates_us.csv", "after relative (anchor 2025-06-15), "
                                                                           "datetime range, open range"),
    "golden_dates_v2_us_2025_1": (dates_v2_us, "data/sample/sales_dates_v2_us.csv", "M/D H:MM / M/D / ISO T (en_US); "
                                                                                    "timed range + relative 6 months"),
    "golden_excel_2025_1": (excel, "data/sample/sales.xlsx", "sheet Orders 2025, 10 empty Profit cells"),
    "golden_maps_2025_1": (maps, "data/sample/sales_geo.csv", "states, countries, cities"),
    "golden_maps_color_2025_1": (maps_color, "data/sample/sales_geo.csv", "states sized by sales and colored by "
                                                                          "profit, countries by profit, cities"),
    "golden_params_2025_1": (params, "data/sample/sales_products.csv", "parameter defaults: Sales, Top 8, month"),
    "golden_params_filters_v3_2025_1": (params_filters_v3, "data/sample/sales_products.csv",
                                        "date / integer list / real / boolean parameters, context filter on a boolean "
                                        "calc, a sheet's own filters, measure filters"),
    "golden_top_by_2025_1": (top_by, "data/sample/sales_products.csv", "Top N by another measure: by a column, by an "
                                                                       "aggregate calc, a registry by an average"),
    "golden_top_after_2025_1": (top_after, "data/sample/sales_products.csv", "Top N after the filters (RANK 1..N) "
                                                                             "against before them; after a measure "
                                                                             "filter"),
    "golden_bar_dates_2025_1": (bar_dates, "data/sample/sales.csv", "bars along a month / a quarter stacked by a "
                                                                     "field, a calc in its manual order"),
    "golden_scatter_2025_1": (scatter,"data/sample/sales_products.csv", "points, average / median axis lines"),
    "golden_bar_variants_2025_1": (bar_variants, "data/sample/sales_plan.csv", "target per bar, stack totals, "
                                                                              "value column (decisions/095)"),
    "golden_bullet_2025_1": (bullet, "data/sample/sales_plan.csv", "bullet graph: target per bar, zones at "
                                                                 "percents of it (decisions/152)"),
    "golden_stack_legend_groups_2025_1": (stack_legend_groups, "data/sample/sales.csv", "stack with the legend under the "
                                          "block by groups, wrapped between members (decisions/185)"),
    "golden_bar_in_bar_2025_1": (bar_in_bar, "data/sample/sales.csv", "total bar with its parts inside "
                                                                      "(decisions/156)"),
    "golden_interactive_2025_1": (interactive, "data/sample/sales_products.csv", "Metric Sales, Period L6M, View "
                                                                                "Chart (decisions/042)"),
}

# Numbers README / decisions record from Desktop 2025.1: (golden, sheet, mark, part or None, value, digits, source).
# pandas must round to them, or nothing is written.
DOCUMENTED = [
    ("golden_funnel_2025_1", "Funnel", "Visit", "value", 172349, 0, "decisions/159 (Desktop snapshot)"),
    ("golden_funnel_2025_1", "Funnel", "Trial", "conversion", 0.52, 2, "decisions/159 (Desktop snapshot 52%)"),
    ("golden_funnel_2025_1", "Funnel", "Renewal", "conversion", 0.70, 2, "decisions/159 (Desktop snapshot 70%)"),
    ("golden_funnel_2025_1", "Social Funnel", "Renewal", "value", 1185, 0, "decisions/159 (Desktop snapshot)"),
    ("golden_funnel_2025_1", "Social Funnel", "Purchase", "conversion", 0.023, 3, "decisions/159 (Desktop 2.3%)"),
    ("golden_2025_1", "KPI", "SUM(Sales)", None, 224710, 0, "golden/README.md"),
    ("golden_2025_1", "KPI", "SUM(Profit)", None, 23550, 0, "golden/README.md"),
    ("golden_2025_1", "KPI", "SUM(Quantity)", None, 2610, 0, "golden/README.md"),
    ("golden_2025_1", "Table", "North | Furniture", None, 23294, 0, "tests/test_expected.py GOLDEN_SEEN"),
    ("golden_2025_1", "Table", "West | Tech", None, 18611, 0, "tests/test_expected.py GOLDEN_SEEN"),
    ("golden_kpi_progress_2025_1", "Monthly", "Sales", "progress", 1.03, 2, "decisions/155: 103% on screen"),
    ("golden_kpi_progress_2025_1", "Monthly", "Profit", "progress", 0.69, 2, "decisions/155: 69%"),
    ("golden_kpi_progress_2025_1", "Monthly", "Units", "progress", 1.04, 2, "decisions/155: 104%"),
    ("golden_kpi_progress_2025_1", "Yearly", "Sales", "progress", 0.89, 2, "decisions/155: 89%"),
    ("golden_kpi_progress_2025_1", "Yearly", "Profit", "progress", 0.95, 2, "decisions/155: 95%"),
    ("golden_cards_2025_1", "Monthly", "Sales", "current", 15462, 0, "golden/README.md, decisions/013"),
    ("golden_cards_2025_1", "Monthly", "Sales", "delta", 0.105, 3, "golden/README.md: 10,5%"),
    ("golden_cards_2025_1", "Monthly", "Profit", "current", 825.4, 1, "golden/README.md"),
    ("golden_cards_2025_1", "Monthly", "Profit", "delta", -0.344, 3, "golden/README.md: 34,4%"),
    ("golden_cards_2025_1", "Yearly", "Units", "current", 104, 0, "golden/README.md"),
    ("golden_cards_2025_1", "Yearly", "Units", "delta", -0.063, 3, "golden/README.md: 6,3%"),
    ("golden_colors_2025_1", "Regions", "East", None, 35353, 0, "golden/README.md, decisions/016"),
    ("golden_colors_2025_1", "Plan", "Denis", "SUM(Sales)", 18760, 0, "golden/README.md"),
    ("golden_colors_2025_1", "Plan", "Denis", "SUM(Plan)", 16709, 0, "golden/README.md"),
    ("golden_colors_2025_1", "Gap", "Denis", None, 2051, 0, "golden/README.md"),
    ("golden_colors_2025_1", "Gap", "Igor", None, -1343, 0, "golden/README.md"),
    ("golden_actions_2025_1", "By Region", "East", "Sales", 52354, 0, "golden/README.md (East selected)"),
    ("golden_actions_2025_1", "By Region", "East", "Profit", 4875, 0, "golden/README.md (East selected)"),
    ("golden_actions_2025_1", "Trend", "2025-02", None, 24338, 0, "golden/README.md (hover February)"),
    ("golden_dates_us_2025_1", "KPI", "SUM(Sales)", None, 31462, 0, "golden/README.md"),
    ("golden_dates_us_2025_1", "KPI", "SUM(Units)", None, 211, 0, "golden/README.md"),
    ("golden_hyper_2025_1", "KPI", "SUM(Sales)", None, 22258, 0, "decisions/080 (Desktop capture)"),
    ("golden_hyper_2025_1", "KPI", "SUM(Units)", None, 157, 0, "decisions/080 (Desktop capture)"),
    ("golden_params_2025_1", "KPI", "AGG(Metric value)", None, 170548, 0, "golden/README.md, decisions/020"),
    ("golden_excel_2025_1", "KPI", "SUM(Profit)", None, 23078, 0, "golden/README.md, decisions/025"),
    ("golden_excel_2025_1", "KPI", "SUM(Sales)", None, 224710, 0, "golden/README.md"),
    ("golden_excel_2025_1", "Table", "East | Furniture", None, 43.02, 2, "golden/README.md"),
    ("golden_excel_2025_1", "Table", "North | Tech", None, 80.28, 2, "golden/README.md"),
    ("golden_excel_2025_1", "Table", "West | Tech", None, 31.21, 2, "golden/README.md"),
    ("golden_reflines_2025_1", "Regions · Reference", "Average", None, 79333, 0, "golden/README.md, decisions/028"),
    ("golden_reflines_2025_1", "Stack · Reference", "Median", None, 80778, 0, "golden/README.md"),
    ("golden_reflines_2025_1", "Trend · Reference", "Average", None, 3305, 1.0,  # the label showed 3 305 for 3 305,55
     "golden/README.md, decisions/028"),
    ("golden_reflines_2025_1", "Monthly · Sales · History · Reference", "Average", None, 13222, 0, "golden/README.md"),
    ("golden_reflines_2025_1", "Monthly · Profit · History · Reference", "Average", None, 1023, 0,
     "golden/README.md"),
    ("golden_maps_2025_1", "States", "California", None, 53191, 0, "golden/README.md, decisions/046"),
    ("golden_maps_2025_1", "States", "Texas", None, 41003, 0, "golden/README.md"),
    ("golden_maps_2025_1", "States", "Minnesota", None, 4612, 0, "golden/README.md"),
    ("golden_maps_2025_1", "Countries", "United States", None, 91580, 0, "golden/README.md"),
    ("golden_maps_2025_1", "Countries", "Canada", None, 43461, 0, "golden/README.md"),
    ("golden_maps_2025_1", "Countries", "Australia", None, 5145, 0, "golden/README.md"),
    ("golden_maps_2025_1", "Cities", "Los Angeles", None, 4806, 0, "golden/README.md"),
    ("golden_maps_2025_1", "Cities", "Minneapolis", None, 490, 0, "golden/README.md"),
    ("golden_maps_color_2025_1", "States", "California", None, 53191, 0, "golden/README.md, decisions/137"),
    ("golden_maps_color_2025_1", "Countries", "United States", None, 10193, 0, "golden/README.md"),
    ("golden_maps_color_2025_1", "Countries", "Canada", None, 4718, 0, "golden/README.md"),
    ("golden_maps_color_2025_1", "Countries", "Australia", None, 694, 0, "golden/README.md"),
    ("golden_scatter_2025_1", "Products · Axis Lines", "SUM(Quantity)", None, 205, 0, "decisions/047: Avg: 205"),
    ("golden_scatter_2025_1", "Products · Axis Lines", "SUM(Sales)", None, 10659, 0, "decisions/047: Avg: $10 659"),
    ("golden_scatter_2025_1", "Profitability · Axis Lines", "SUM(Sales)", None, 10729, 0, "decisions/047"),
    ("golden_scatter_2025_1", "Profitability · Axis Lines", "SUM(Profit)", None, 1314, 0, "decisions/047"),
    ("golden_calcs_2025_1", "KPI", "SUM(Tech Sales)", None, 78575, 0, "tests/test_expected.py CALCS_SEEN_KPI"),
    ("golden_calcs_2025_1", "KPI", "AGG(Profit Ratio)", None, 0.105, 3, "tests/test_expected.py: 10,5%"),
    ("golden_calcs_2025_1", "Ratio Matrix", "Large | North", None, 0.142, 3, "tests/test_expected.py: 14,2%"),
    ("golden_lods_2025_1", "KPI", "AGG(Max Region Sales)", None, 58862, 0, "tests/test_expected.py LODS_SEEN_KPI"),
    ("golden_lods_2025_1", "KPI", "SUM(First Day Orders)", None, 4, 0, "tests/test_expected.py LODS_SEEN_KPI"),
    ("golden_lods_2025_1", "Region Mix", "North | Furniture", None, 0.398, 3, "tests/test_expected.py: 39,8%"),
    ("golden_lods_view_2025_1", "KPI", "AVG(Category Sales)", None, 74903, 0, "decisions/010: 74 903"),
    ("golden_lods_view_2025_1", "KPI", "AGG(Max Category Sales)", None, 78575, 0, "tests/test_expected.py"),
    ("golden_lods_view_2025_1", "Region Total Grid", "South | Tech", None, 58862, 0, "tests/test_expected.py"),
    ("golden_tablecalcs_2025_1", "Share in Region", "North | Furniture", None, 0.3983, 4, "tests/test_expected.py"),
    ("golden_tablecalcs_2025_1", "Region Difference", "South | Office", None, 8429, 0, "tests/test_expected.py"),
    ("golden_tablecalcs_2025_1", "Region Difference", "East | Tech", None, None, None, "Desktop: first mark empty"),
    ("golden_tablecalcs_2025_1", "MoM Change", "2025-06", None, 0.67, 2, "tests/test_expected.py: 67%"),
    ("golden_tablecalcs_2025_1", "Running Sales", "2025-12", None, 224710, 0, "tests/test_expected.py; decisions/034 "
                                                                              "Running Dec 224 709,68"),
    ("golden_dates_v2_us_2025_1", "KPI", "SUM(Sales)", None, 2494714, 0, "decisions/051 (Desktop capture)"),
    ("golden_dates_v2_us_2025_1", "KPI", "SUM(Minutes Left)", None, 457750, 0, "decisions/051"),
    ("golden_dates_v2_us_2025_1", "KPI", "SUM(Late Logs)", None, 508, 0, "decisions/051"),
    ("golden_dates_v2_us_2025_1", "Paid", "2024-12 | Store", None, 10854, 0, "decisions/051"),
    ("golden_dates_v2_us_2025_1", "Hours", "20:00 | Store", None, 95678, 0, "decisions/051"),
    # decisions/149, Desktop capture (check-drawn) of the golden: what DATEPARSE reads and what it turns into NULL
    ("golden_params_filters_v3_2025_1", "KPI", "AGG(Shown sales)", None, 128632, 0, "decisions/057 (Desktop capture)"),
    ("golden_params_filters_v3_2025_1", "KPI", "AGG(Margin gap)", None, -0.106, 3, "decisions/057 (Desktop capture)"),
    # decisions/059, PrintWindow capture of the golden: the dot labels ($17,3K: thousands with one decimal) and the
    # dot colors (good = Max, bad = Min, accent = Last; Units is good 'down', so its max is the red dot)
    *[("golden_kpi_spark_points_2025_1", f"{s} · {m} · History · Point Marks", month, "point", kind, None,
       "decisions/059 (Desktop capture: dot color)")
      for s, m, month, kind in [
          ("Monthly", "Sales", "2025-03", "Max"), ("Monthly", "Sales", "2024-07", "Min"),
          ("Monthly", "Sales", "2025-12", "Last"), ("Monthly", "Profit", "2024-10", "Max"),
          ("Monthly", "Profit", "2024-06", "Min"), ("Monthly", "Profit", "2025-12", "Last"),
          ("Monthly", "Units", "2024-11", "Max"), ("Monthly", "Units", "2024-07", "Min"),
          ("Monthly", "Units", "2025-12", "Last"), ("Latest", "Units", "2024-07", "Min"),
          ("Latest", "Units", "2025-12", "Last")]],
    *[("golden_kpi_spark_points_2025_1", f"Monthly · {m} · History · Point Marks", month, "value", v, d,
       "decisions/059 (Desktop capture: dot label)")
      for m, month, v, d in [
          ("Sales", "2025-03", 17300, 50.0), ("Sales", "2024-07", 5600, 50.0), ("Sales", "2025-12", 15500, 50.0),
          ("Profit", "2024-10", 1904, 0), ("Profit", "2024-06", 347, 0), ("Profit", "2025-12", 825, 0),
          ("Units", "2024-11", 139, 0), ("Units", "2024-07", 73, 0), ("Units", "2025-12", 104, 0)]],
    # decisions/070, PrintWindow capture of the golden (ru_RU): KPI strip 15 462 / 825,4 / 104
    *[("golden_theme_cards_2025_1", "KPI", m, "current", v, d, "decisions/070 (Desktop capture: card number)")
      for m, v, d in [("Sales", 15462, 0), ("Profit", 825.4, 1), ("Units", 104, 0)]],
    # decisions/062, PrintWindow capture of the golden: the dot's pixel is the status's token (good #3ea8a6, warn
    # #f2a93b, bad #ff5c60), the card's number next to it
    *[("golden_kpi_status_2025_1", s, m, "status", st, None, "decisions/062 (Desktop capture: dot color)")
      for s, m, st in [("Monthly", "Sales", "On track"), ("Monthly", "Profit", "Off track"),
                       ("Monthly", "Units", "At risk"), ("Yearly", "Sales", "Healthy"), ("Yearly", "Profit", "Warning")]],
    *[("golden_kpi_status_2025_1", s, m, "current", v, d, "decisions/062 (Desktop capture: card number)")
      for s, m, v, d in [("Monthly", "Sales", 15500, 50.0), ("Monthly", "Profit", 825.4, 1), ("Monthly", "Units", 104, 0),
                         ("Yearly", "Profit", 825.4, 1)]],
    # decisions/061, PrintWindow capture of the golden (ru_RU): $15,5K ▲ $1,5K | 10,5% MoM; 825,4 ▼ 432 | 34,4%;
    # 104 ▲ 2 | 2,0%; vs PY 61,5% / 103,1%; history labels $17,3K / 1 904 / 139, averages $13,2K / 1 023 / 106
    *[("golden_kpi_v2_nopill_2025_1", sheet, mark, part, v, d, "decisions/061 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Monthly", "Sales", "current", 15500, 50.0), ("Monthly", "Sales", "diff", 1500, 50.0),
          ("Monthly", "Sales", "delta", 0.105, 3), ("Monthly", "Profit", "current", 825.4, 1),
          ("Monthly", "Profit", "diff", -432, 0), ("Monthly", "Profit", "delta", -0.344, 3),
          ("Monthly", "Units", "current", 104, 0), ("Monthly", "Units", "diff", 2, 0),
          ("Monthly", "Units", "delta", 0.02, 3), ("Yearly", "Sales", "delta", 0.615, 3),
          ("Yearly", "Profit", "delta", 1.031, 3),
          ("Monthly · Sales · History · Points", "max", None, 17300, 50.0),
          ("Monthly · Profit · History · Points", "max", None, 1904, 0),
          ("Monthly · Units · History · Points", "max", None, 139, 0),
          ("Monthly · Sales · History · Reference", "Average", None, 13200, 50.0),
          ("Monthly · Profit · History · Reference", "Average", None, 1023, 0),
          ("Monthly · Units · History · Reference", "Average", None, 106, 0)]],
    # decisions/063, PrintWindow capture of golden_kpi_v2 (ru_RU): the same cards with the pills '▲ 61,5% vs PY',
    # '▲ 103,1% vs PY', '▲ 2 | 2,0% MoM' in their filled bars
    *[("golden_kpi_v2_2025_1", sheet, mark, part, v, d, "decisions/063 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Monthly", "Sales", "current", 15500, 50.0), ("Monthly", "Sales", "diff", 1500, 50.0),
          ("Monthly", "Sales", "delta", 0.105, 3), ("Monthly", "Profit", "current", 825.4, 1),
          ("Monthly", "Profit", "diff", -432, 0), ("Monthly", "Profit", "delta", -0.344, 3),
          ("Monthly", "Units", "current", 104, 0), ("Monthly", "Units", "diff", 2, 0),
          ("Monthly", "Units", "delta", 0.02, 3), ("Yearly", "Sales", "delta", 0.615, 3),
          ("Yearly", "Profit", "delta", 1.031, 3), ("Stacked", "Units", "diff", 2, 0),
          ("Stacked", "Units", "delta", 0.02, 3),
          ("Monthly · Sales · History · Points", "max", None, 17300, 50.0),
          ("Monthly · Profit · History · Points", "max", None, 1904, 0),
          ("Monthly · Units · History · Points", "max", None, 139, 0),
          ("Monthly · Sales · History · Reference", "Average", None, 13200, 50.0),
          ("Monthly · Profit · History · Reference", "Average", None, 1023, 0),
          ("Monthly · Units · History · Reference", "Average", None, 106, 0)]],
    # decisions/061, PrintWindow capture of golden_benchmark (ru_RU): the line-end labels and the band / average
    *[("golden_benchmark_2025_1", sheet, series, part, v, d, "decisions/061 (Desktop capture: line-end label)")
      for sheet, series, part, v, d in [
          ("Compare · Sales · Ends", "West", "last", 4050, 0), ("Compare · Profit · Ends", "West", "last", 208.2, 1),
          ("Compare · Profit · Ends", "All regions avg", "last", 206.3, 1),
          ("Compare · Quantity · Ends", "West", "last", 29, 0),
          ("Compare · Avg sale · Ends", "West", "last", 450.0, 1),
          ("Compare · Avg sale · Ends", "All regions avg", "last", 498.8, 1),
          ("East · Ends", "East", "last", 4733, 0), ("East · Ends", "All Region avg", "first", 2983, 0),
          ("East · Ends", "All Region avg", "last", 3866, 0), ("Total · Ends", "Sales", "first", 11934, 0),
          ("Total · Ends", "Sales", "last", 15462, 0)]],
    ("golden_benchmark_2025_1", "Total · Reference", "Average", None, 13222, 0, "decisions/061 (Desktop capture)"),
    *[("golden_dual_axis_2025_1", sheet, mark, part, v, d, "decisions/061 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Combo", "West", "SUM(Sales)", 85565, 0), ("Combo", "South", "SUM(Sales)", 70213, 0),
          ("Donut · Total", None, None, 317333, 0), ("Donut · Legend", "Furniture", "value", 105263, 0),
          ("Donut · Legend", "Office", "share", 0.34, 2), ("Donut · Legend", "Tech", "value", 103853, 0),
          ("Lollipop", "East", None, 685, 0), ("Lollipop", "South", None, 555, 0)]],
    *[("golden_totals_2025_1", sheet, mark, part, v, d, "decisions/061 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Sales", "East | Total", None, 52354, 0), ("Sales", "Total | Tech", None, 78575, 0),
          ("Sales", "Total | Total", None, 224710, 0), ("Avg Profit", "North | All", None, 62.49, 2),
          ("Avg Profit", "All | Furniture", None, 48.94, 2), ("Avg Profit", "All | All", None, 47.10, 2),
          ("Registry", "South | Total", "Sales", 58862, 0), ("Registry", "South | Total", "Avg profit", 47.66, 2),
          ("Registry", "East | Office", "Order sizes", 8, 0)]],
    *[("golden_tablecalc_funcs_2025_1", sheet, mark, None, v, d, "decisions/061 (Desktop capture)")
      for sheet, mark, v, d in [
          ("Sales Rank", "East", 4, 0), ("Sales Rank", "South", 1, 0), ("Orders Rank", "North", 2, 0),
          ("Orders Rank", "West", 2, 0), ("Orders Rank", "East", 4, 0), ("Orders Dense Rank", "South", 3, 0),
          ("Orders Dense Rank", "West", 2, 0), ("Share", "East | Furniture", 0.251, 3),
          ("Share", "North | Furniture", 0.311, 3), ("Min-Max", "West | Tech", 0.907, 3),
          ("Min-Max", "South | Tech", 0.796, 3), ("Index", "West | Tech", 12, 0), ("Prev Month", "2025-01", None, None)]],
    *[("golden_fields_2025_1", "Matrix", mark, None, v, 0, "decisions/061 (Desktop capture)")
      for mark, v in [("North side | Growth", 8798), ("North side | Other", 21757), ("East coast | Core", 13403),
                      ("West coast | Other", 23832), ("South belt | Growth", 7820)]],
    ("golden_nav_2025_1", "KPI", "SUM(Sales)", None, 224710, 0, "decisions/061 (Desktop capture)"),
    ("golden_nav_2025_1", "KPI", "SUM(Profit)", None, 23550, 0, "decisions/061 (Desktop capture)"),
    *[("golden_heatmap_v2_2025_1", sheet, mark, None, v, d, "decisions/061 (Desktop capture)")
      for sheet, mark, v, d in [
          ("Seasonality", "01 Jan | East", 4759, 0), ("Seasonality", "01 Jan | North", 9056, 0),
          ("Seasonality", "06 Jun | West", 10615, 0), ("Seasonality", "07 Jul | South", 3292, 0),
          ("Seasonality · Row Totals", "01 Jan", 25356, 0), ("Seasonality · Row Totals", "12 Dec", 25033, 0),
          ("Seasonality · Column Totals", "East", 78646, 0), ("Seasonality · Column Totals", "West", 85565, 0),
          ("Change", "East | Tech", 0.845, 3), ("Change", "North | Tech", -0.275, 3),
          ("Change", "South | Furniture", -0.025, 3)]],
    # decisions/065, PrintWindow capture of golden_registry_v2 (ru_RU): '27% (47 811)', '▼ 27,5%', '1 381' ...
    *[("golden_registry_v2_2025_1", sheet, mark, part, v, d, "decisions/065 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Regions", "North", "#", 1, 0), ("Regions", "North", "Sales", 47811, 0),
          ("Regions", "North", "Share", 0.27, 2), ("Regions", "North", "Share · value", 47811, 0),
          ("Regions", "West", "Avg profit", 38.41, 2), ("Regions", "East", "Share", 0.25, 2),
          ("Regions", "South", "#", 4, 0), ("Regions", "South", "Avg profit", 27.61, 2),
          ("Categories", "East | Tech", "#", 1, 0), ("Categories", "East | Tech", "Change", 0.845, 3),
          ("Categories", "North | Tech", "Sales vs PY", 9745, 0), ("Categories", "North | Tech", "Change", -0.275, 3),
          ("Categories", "North | Office", "Sales vs PY", 21771, 0),
          ("Categories", "South | Furniture", "Change", -0.025, 3), ("Categories", "East | Furniture", "Units", 210, 0),
          ("Categories", "East | Furniture", "Units · Profit", 1381, 0),
          ("Top · Region", "North", "vs PY", 0.362, 3), ("Top · Region", "West", "#", 2, 0),
          ("Top · Category", "Office", "Sales", 64299, 0), ("Top · Category", "Furniture", "vs PY", 0.209, 3)]],
    # decisions/081, PrintWindow capture of golden_registry_totals (ru_RU): totals under bar columns, '10,5%' in pct1
    *[("golden_registry_totals_2025_1", sheet, mark, part, v, d, "decisions/081 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Regions", "TOTAL", "Sales", 224710, 0), ("Regions", "TOTAL", "Margin", 0.105, 3),
          ("Regions", "TOTAL", "Units", 2610, 0), ("Categories", "East | Total", "Profit", 4875, 0),
          ("Categories", "North | Total", "Margin %", 0.13, 2), ("Categories", "Total", "Profit", 23550, 0),
          ("Categories", "Total", "Sales", 224710, 0)]],
    # decisions/082, PrintWindow captures of the golden at each value of Breakdown (tests/fixtures/switch_registry)
    *[("golden_switch_registry_2025_1", sheet, mark, part, v, d, "decisions/082 (Desktop capture)")
      for sheet, mark, part, v, d in [
          ("Orders KPI", "SUM(Sales)", None, 224710, 0), ("Orders KPI", "SUM(Profit)", None, 23550, 0),
          ("Plan by Manager", "Igor", "Sales", 20990, 0), ("Plan by Manager", "Igor", "Plan", 22333, 0),
          ("Plan by Manager", "Igor", "Attainment", 0.94, 3), ("Plan by Manager", "Denis", "Attainment", 1.123, 3),
          ("Plan by Manager", "Clara", "Sales", 13690, 0), ("Plan by Region", "West", "Sales", 36570, 0),
          ("Plan by Region", "West", "Plan", 36770, 0), ("Plan by Region", "North", "Plan", 30974, 0)]],
    # decisions/092, check-drawn capture of the re-saved golden (tests/fixtures/golden_shots/golden_shell_2025_1.png)
    *[("golden_shell_2025_1", sheet, mark, part, v, 0, "decisions/092 (Desktop capture)")
      for sheet, mark, part, v in [("KPI", "SUM(Sales)", None, 224710), ("KPI", "SUM(Profit)", None, 23550),
                                   ("Table", "East | Furniture", None, 18840), ("Table", "North | Office", None, 14205),
                                   ("Table", "West | Tech", None, 18611)]],
    # decisions/067, PrintWindow capture of the golden: the top 6 products by AVG(Quantity), their sales and profit
    *[("golden_top_by_2025_1", "Busiest Products", p, part, v, 0, "decisions/067 (Desktop capture)")
      for p, s, pr in [("Atlas", 10983, 1944), ("Beacon", 17414, 1917), ("Falcon", 7318, 1150), ("Iris", 16983, 5517),
                       ("Meridian", 11963, 1477), ("Pioneer", 11249, 235)]
      for part, v in (("Sales", s), ("Profit", pr))],
]


def documented_mismatches(stem, got):
    bad = []
    for g, sheet, mark, part, want, digits, src in DOCUMENTED:
        if g != stem:
            continue
        v = got.get(sheet, {}) if mark is None else got.get(sheet, {}).get(mark)  # mark None: a one-number record
        v = v.get(part) if part and isinstance(v, dict) else v
        # digits: the decimals Desktop showed (half a unit of them, plus the written rounding); a float: the tolerance
        tol = None if digits is None else digits if isinstance(digits, float) else \
            0.5 * 10 ** -digits + 0.5 * 10 ** -DECIMALS
        ok = v == want if tol is None else isinstance(v, (int, float)) and abs(v - want) <= tol
        if not ok:
            bad.append(f"{stem}: {sheet} / {mark}{' / ' + part if part else ''} = {v!r}, {src} says {want!r}")
    return bad


def build(stem):
    fn, data, what = GOLDENS[stem]
    return {"_source": f"pandas over {data} (golden/expected/make_expected.py, decisions/052): {what}", **fn()}


def main(argv):
    check = "--check" in argv
    files, bad, drift = {}, [], []
    for stem in GOLDENS:
        got = build(stem)
        bad += documented_mismatches(stem, got)
        files[HERE / f"{stem}.json"] = json.dumps(got, ensure_ascii=False, indent=1) + "\n"
    for path, text in files.items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                drift.append(path.name)
        elif not bad:  # all or nothing: a file is written only when pandas agrees with every documented number
            path.write_text(text, encoding="utf-8")
    for b in bad:
        print("DOCUMENTED", b)
    for d in drift:
        print("DRIFT", d)
    n = sum(1 for g in DOCUMENTED if g[0] in GOLDENS)
    print(f"{len(GOLDENS)} goldens, {n} documented numbers checked, {len(bad)} mismatches"
          + (f", {len(drift)} files differ" if check else ""))
    return 1 if bad or drift else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
