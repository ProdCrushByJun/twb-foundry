"""Synthetic logistics shipments export and a BI-tool style 'export HTML' page built on it (todo 0.4, decisions/104).

Writes shipments.csv (one row per shipment, 2024-2025, seed 20261026) and bi-export.html from template.html.in
(rows embedded as JSON; the page computes every number in JS and draws SVG with absolutely positioned visuals).
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20261026)

REGIONS = [("Northeast", 22, 1.10), ("Southeast", 24, 0.95), ("Midwest", 20, 0.90), ("Southwest", 16, 1.00), ("West", 18, 1.20)]
CARRIERS = [("BlueLine", 30, .96, 1.00), ("RapidHaul", 24, .90, 0.95), ("NorthStar", 20, .94, 1.10), ("Gulf Freight", 15, .86, 0.90), ("TransAlpha", 11, .92, 1.05)]
MODES = [("Road", 55, 1.0, 4), ("Rail", 20, 0.7, 6), ("Air", 10, 3.2, 2), ("Sea", 15, 0.5, 11)]
SEASON = [.80, .78, .90, .95, 1.0, 1.0, .95, .98, 1.08, 1.15, 1.25, 1.30]


def pick(pairs, w=1):
    return rng.choices([p[0] for p in pairs], weights=[p[w] for p in pairs])[0]


def row_of(pairs, name):
    return next(p for p in pairs if p[0] == name)


rows, n = [], 70000
day = date(2024, 1, 1)
while day <= date(2025, 12, 31):
    growth = 1.0 if day.year == 2024 else 1.12
    lam = 2.7 * SEASON[day.month - 1] * growth * (0.45 if day.weekday() >= 5 else 1.0)
    for _ in range(max(0, round(rng.gauss(lam, lam ** 0.5)))):
        n += 1
        reg, car, mode = pick(REGIONS), pick(CARRIERS), pick(MODES)
        weight = int(round(rng.lognormvariate(6.2, .7) * (1.4 if mode in ("Rail", "Sea") else 1.0), -1)) or 10
        cost = weight * 0.9 * row_of(MODES, mode)[2] * row_of(REGIONS, reg)[2] * row_of(CARRIERS, car)[3] * rng.uniform(.85, 1.2)
        days = max(1, round(rng.gauss(row_of(MODES, mode)[3], 1.2)))
        on_time = 1 if rng.random() < row_of(CARRIERS, car)[2] - (0.03 if day.month in (11, 12) else 0) else 0
        rows.append({"Shipment ID": f"SH-{n}", "Ship Date": day.isoformat(), "Region": reg, "Carrier": car, "Mode": mode,
                     "Weight kg": weight, "Freight Cost": int(round(cost)), "Transit Days": days, "On Time Flag": on_time})
    day += timedelta(days=1)

with (HERE / "shipments.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

cols = list(rows[0])
data = json.dumps({"cols": cols, "rows": [[r[c] for c in cols] for r in rows]}, separators=(",", ":"))
page = (HERE / "template.html.in").read_text(encoding="utf-8").replace("/*DATA*/null", data)
(HERE / "bi-export.html").write_text(page, encoding="utf-8")
print(len(rows), "shipments")
