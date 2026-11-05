"""Deterministic two-year sample (2024-2025) for KPI cards: month-over-month and year-over-year deltas.

Same columns and categories as sales.csv. Run: python data/sample/make_sales_2y.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

REGIONS = ["East", "North", "South", "West"]
CATEGORIES = ["Furniture", "Office", "Tech"]


def main():
    rnd = random.Random(2024)
    day, end = dt.date(2024, 1, 1), dt.date(2025, 12, 31)
    rows = []
    while day <= end:
        for _ in range(rnd.choice([0, 1, 1, 2])):
            growth = 1 + 0.25 * (day.year - 2024)  # 2025 sells more than 2024
            qty = rnd.randint(1, 6)
            sales = round(rnd.uniform(40, 700) * growth, 2)
            profit = round(sales * rnd.uniform(-0.15, 0.3), 2)
            rows.append([day.isoformat(), rnd.choice(REGIONS), rnd.choice(CATEGORIES), sales, profit, qty])
        day += dt.timedelta(days=1)
    out = Path(__file__).with_name("sales_2y.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order Date", "Region", "Category", "Sales", "Profit", "Quantity"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
