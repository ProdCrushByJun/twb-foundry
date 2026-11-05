"""Writes expected.json for the bi_export case from shipments.csv with pandas (independent of the generator and the HTML)."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
df = pd.read_csv(HERE / "shipments.csv", parse_dates=["Ship Date"])
df["Year"] = df["Ship Date"].dt.year.astype(str)
cnt = df.groupby(["Carrier", "Year"]).size()
month = df.groupby(df["Ship Date"].dt.to_period("M"))["Freight Cost"].sum()
cost = df.groupby(["Region", "Year"])["Freight Cost"].sum()
exp = {
    "_source": "shipments.csv via pandas (make_expected.py); the page shows the same numbers (decisions/104)",
    "spec.json": {
        "KPI": {
            "COUNT(Shipment ID)": int(len(df)),
            "SUM(Freight Cost)": int(df["Freight Cost"].sum()),
            "AGG(On-time Rate)": float(df["On Time Flag"].sum() / len(df)),
            "AGG(Avg Transit)": float(df["Transit Days"].mean()),
        },
        "By Carrier": {f"{k[0]} | {k[1]}": int(v) for k, v in cnt.items()},
        "By Month": {p.strftime("%Y-%m"): int(v) for p, v in month.items()},
        "Region Matrix": {f"{k[0]} | {k[1]}": int(v) for k, v in cost.items()},
    },
}
(HERE / "expected.json").write_text(json.dumps(exp, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(exp["spec.json"]["KPI"]))
