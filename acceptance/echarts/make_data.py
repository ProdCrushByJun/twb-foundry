"""Synthetic retail sales export and the ECharts dashboard built on it (todo 0.4, decisions/097).

Writes orders.csv (one row per order line, seed 20261024) and sales-overview.html from template.html.in
(the rows are embedded as JSON; the page computes every number in JS; ECharts from the CDN, canvas renderer).
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20261024)

CATEGORIES = {  # category -> [(product, unit price, unit cost share)]
    "Technology": [("Laptop Pro 14", 1150, .72), ("Monitor 27", 320, .68), ("Wireless Mouse", 35, .55),
                   ("Docking Station", 190, .62)],
    "Furniture": [("Standing Desk", 540, .66), ("Ergo Chair", 410, .70), ("Bookcase", 160, .74),
                  ("Desk Lamp", 48, .50)],
    "Office Supplies": [("Paper Ream", 9, .60), ("Binder Set", 14, .55), ("Label Printer", 85, .64),
                        ("Pen Box", 7, .45)],
    "Services": [("Installation", 220, .40), ("Extended Warranty", 130, .30)],
}
CAT_WEIGHT = {"Technology": 34, "Furniture": 26, "Office Supplies": 32, "Services": 8}
REGIONS = [("West", 31), ("East", 29), ("Central", 22), ("South", 18)]
CHANNELS = [("Online", 44), ("Retail Store", 31), ("Partner", 16), ("Phone", 9)]
SEGMENTS = [("Consumer", 52), ("Corporate", 33), ("Home Office", 15)]
SEASON = [.8, .8, .9, .95, 1, 1, .95, 1, 1.1, 1.15, 1.3, 1.45]  # month index -> order volume


def pick(pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


rows, n = [], 40000
day = date(2025, 1, 1)
while day <= date(2025, 12, 31):
    lam = 3.3 * SEASON[day.month - 1] * (0.6 if day.weekday() >= 5 else 1)
    for _ in range(max(0, round(rng.gauss(lam, lam ** 0.5)))):
        n += 1
        cat = rng.choices(list(CAT_WEIGHT), weights=list(CAT_WEIGHT.values()))[0]
        prod, price, cost_share = rng.choice(CATEGORIES[cat])
        qty = rng.choices([2, 5, 10, 20, 50], weights=[30, 30, 20, 12, 8])[0]
        disc = rng.choice([0, 0, 0, .05, .1, .15])
        revenue = round(price * qty * (1 - disc), 2)
        cost = round(price * qty * cost_share * rng.uniform(.95, 1.05), 2)
        rows.append({"Order ID": f"SO-{n}", "Order Date": day.isoformat(), "Region": pick(REGIONS),
                     "Category": cat, "Product": prod, "Channel": pick(CHANNELS), "Segment": pick(SEGMENTS),
                     "Quantity": qty, "Revenue": revenue, "Cost": cost})
    day += timedelta(days=1)

with (HERE / "orders.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

cols = list(rows[0])
data = json.dumps({"cols": cols, "rows": [[r[c] for c in cols] for r in rows]}, separators=(",", ":"))
page = (HERE / "template.html.in").read_text(encoding="utf-8").replace("/*DATA*/null", data)
(HERE / "sales-overview.html").write_text(page, encoding="utf-8")
print(len(rows), "order lines")
