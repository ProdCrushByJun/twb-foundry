"""Writes expected.json for the table_kpi case from sales.csv with pandas (independent of the generator and the HTML)."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
df = pd.read_csv(HERE / "sales.csv", parse_dates=["Order Date"])
df["ym"] = df["Order Date"].dt.strftime("%Y-%m")
df["y"] = df["Order Date"].dt.year


def kpi(name, f):
    cur, prev = f(df[df.ym == "2025-12"]), f(df[df.ym == "2025-11"])
    return {"current": round(float(cur), 2), "previous": round(float(prev), 2), "delta": float(cur / prev - 1)}


def margin(name):  # a ratio card: the value is Profit / Sales of the period, the change in percentage points
    def of(x):
        return x.Profit.sum() / x.Sales.sum()
    cur, prev = of(df[df.ym == "2025-12"]), of(df[df.ym == "2025-11"])
    return {"current": float(cur), "previous": float(prev), "delta": float((cur - prev) * 100)}


def block(g):
    a, b = g[g.y == 2025], g[g.y == 2024]
    m25, m24 = a.Profit.sum() / a.Sales.sum(), b.Profit.sum() / b.Sales.sum()
    return {"Sales": round(a.Sales.sum(), 2), "vs 2024": a.Sales.sum() / b.Sales.sum() - 1, "Profit": round(a.Profit.sum(), 2),
            "Margin": m25, "Margin vs 2024": (m25 - m24) * 100, "Units": int(a.Quantity.sum())}


reg = {}
for (r, c), g in df.groupby(["Region", "Category"]):
    reg[f"{r} | {c}"] = block(g)
for r, g in df.groupby("Region"):
    reg[f"{r} | Total"] = block(g)
reg["Total"] = block(df)

a25 = df[df.y == 2025]
by25, by24 = a25.groupby("Product").Sales.sum(), df[df.y == 2024].groupby("Product").Sales.sum()
top = {}
for i, (p, s) in enumerate(by25.sort_values(ascending=False).head(5).items(), 1):
    top[p] = {"#": i, "Sales": round(s, 2), "Share": s / by25.sum(), "vs 2024": s / by24[p] - 1}

exp = {
    "_source": "sales.csv via pandas (make_expected.py); the page shows the same numbers (decisions/103)",
    "spec.json": {
        "KPI": {"Sales": kpi("Sales", lambda x: x.Sales.sum()), "Profit": kpi("Profit", lambda x: x.Profit.sum()),
                "Profit margin": margin("Profit margin"),
                "Orders": kpi("Orders", lambda x: len(x)), "Units sold": kpi("Units sold", lambda x: x.Quantity.sum())},
        "Region Category": reg,
        "Top Products": top,
    },
}
(HERE / "expected.json").write_text(json.dumps(exp, indent=1, ensure_ascii=False), encoding="utf-8")
print(len(reg), "registry rows;", list(top))
