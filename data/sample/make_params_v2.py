"""params_v2.csv: six products with TIED totals (decisions/148): C = D = 360 at the 3rd/4th place, E = F = 240 at the
5th/6th (first measured with D, C and F, E in this order: Desktop picked C, so not the data order).
Each product: 3 months x 4 regions, equal Sales in every row."""
import csv
from pathlib import Path

PER_ROW = [("C", 30), ("D", 30), ("B", 40), ("E", 20), ("F", 20), ("A", 50)]
REGIONS = ["North", "South", "East", "West"]
MONTHS = ["2025-01-15", "2025-02-15", "2025-03-15"]

rows = []
for product, sales in PER_ROW:
    for d in MONTHS:
        for r in REGIONS:
            rows.append([d, r, product, sales, sales // 5, 2])
with open(Path(__file__).with_name("params_v2.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["Order Date", "Region", "Product", "Sales", "Profit", "Quantity"])
    w.writerows(rows)
