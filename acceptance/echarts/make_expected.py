"""Writes expected.json for the echarts case from orders.csv with pandas (independent of the generator and the HTML)."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
df = pd.read_csv(HERE / "orders.csv", parse_dates=["Order Date"])
rev, cost, n = df.Revenue.sum(), df.Cost.sum(), len(df)
month = (df.groupby(df["Order Date"].dt.month).Revenue.sum() / 1000).round().astype(int)
cat = (df.groupby("Category").Revenue.sum() / 1000).round().astype(int).sort_values(ascending=False)
chan = df.groupby("Channel").Revenue.sum().round().astype(int)
top = df.groupby("Product").agg(rev=("Revenue", "sum"), n=("Order ID", "count"), cost=("Cost", "sum")).sort_values("rev", ascending=False).head(10)
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
exp = {
    "_source": "orders.csv via pandas (make_expected.py); the page shows the same numbers (decisions/097)",
    "spec.json": {
        "KPI": {"SUM(Revenue)": round(rev, 2), "COUNT(Order ID)": n, "AGG(Avg Order Value)": round(rev / n),
                "AGG(Profit Margin)": round((rev - cost) / rev, 3)},
        "By Month": {f"2025-{i:02d}": int(v) for i, v in month.items()},
        "By Category": {k: int(v) for k, v in cat.items()},
        "Channel Mix": {k: int(v) for k, v in chan.items()},
        "Top Products": {p: {"Revenue, $K": round(r.rev / 1000), "Orders": int(r.n),
                             "Margin": round((r.rev - r.cost) / r.rev, 3)} for p, r in top.iterrows()},
    },
}
(HERE / "expected.json").write_text(json.dumps(exp, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(exp["spec.json"]["KPI"]), len(top))
