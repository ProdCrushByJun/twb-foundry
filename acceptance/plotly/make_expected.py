"""Writes expected.json for the plotly case from hr_events.csv with pandas (independent of the generator and the HTML)."""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
df = pd.read_csv(HERE / "hr_events.csv", parse_dates=["Event Date"])
hire, ex = df["Event Type"].eq("Hire"), df["Event Type"].eq("Exit")
q = df.groupby([df["Event Date"].dt.quarter, "Event Type"]).size()
exits_dept = df[ex].groupby("Department").size()
mon = df[ex].groupby(["Department", df[ex]["Event Date"].dt.month]).size()
mn = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
heat = {k: v for k, v in {f"{d} | 2025-{m:02d}": int(mon.get((d, m), 0)) for d in exits_dept.index for m in range(1, 13)}.items() if v}  # an empty cell has no mark
bal = {}
for d in exits_dept.index:
    h, e = int((hire & df.Department.eq(d)).sum()), int((ex & df.Department.eq(d)).sum())
    bal[d] = {"Hires": h, "Exits": e, "Net": h - e}
exp = {
    "_source": "hr_events.csv via pandas (make_expected.py); the page shows the same numbers (decisions/102)",
    "spec.json": {
        "KPI": {"SUM(Hire Flag)": int(hire.sum()), "SUM(Exit Flag)": int(ex.sum()), "AGG(Net Change)": int(hire.sum() - ex.sum())},
        "By Quarter": {f"2025-Q{k[0]} | {k[1]}": int(v) for k, v in q.items()},
        "Exits by Dept": {k: int(v) for k, v in exits_dept.items()},
        "Exit Heatmap": heat,
        "Balance": bal,
    },
}
(HERE / "expected.json").write_text(json.dumps(exp, indent=1, ensure_ascii=False), encoding="utf-8")
print(json.dumps(exp["spec.json"]["KPI"]), len(heat))
