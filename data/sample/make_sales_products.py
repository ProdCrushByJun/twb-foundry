"""Deterministic sample with many products (2025, daily orders) for parameters: metric switch, Top N, period.

16 products with their own price level, margin and order size, so the top products by Sales, Profit and Quantity
differ; more products than the 12 bars a block may show (design rule I4).
Run: python data/sample/make_sales_products.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

PRODUCTS = ["Atlas", "Beacon", "Cobalt", "Delta", "Ember", "Falcon", "Granite", "Harbor", "Iris", "Juniper",
            "Kestrel", "Lumen", "Meridian", "Nova", "Orbit", "Pioneer"]
REGIONS = ["East", "North", "South", "West"]


def main():
    rnd = random.Random(2025)
    traits = {p: (rnd.uniform(40, 400), rnd.uniform(-0.15, 0.35), rnd.randint(1, 9)) for p in PRODUCTS}
    rows = []
    start = dt.date(2025, 1, 1)
    for _ in range(640):
        day = start + dt.timedelta(days=rnd.randrange(365))
        product = rnd.choice(PRODUCTS)
        price, margin, size = traits[product]
        sales = round(price * rnd.uniform(0.6, 1.4), 2)
        profit = round(sales * (margin + rnd.uniform(-0.05, 0.05)), 2)
        quantity = max(1, size + rnd.randint(-1, 2))
        rows.append([day.isoformat(), rnd.choice(REGIONS), product, sales, profit, quantity])
    rows.sort()
    out = Path(__file__).with_name("sales_products.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order Date", "Region", "Product", "Sales", "Profit", "Quantity"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
