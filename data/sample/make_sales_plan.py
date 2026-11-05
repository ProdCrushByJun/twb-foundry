"""Deterministic plan-vs-fact sample (2025, monthly) for color with meaning: plan, gap to plan, highlight.

Two managers per region; each has a performance factor, so some end the year above plan and some below.
Run: python data/sample/make_sales_plan.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

MANAGERS = {"East": ["Anna", "Boris"], "North": ["Clara", "Denis"], "South": ["Elena", "Fedor"],
            "West": ["Galina", "Igor"]}


def main():
    rnd = random.Random(2025)
    rows = []
    for region, names in MANAGERS.items():
        for name in names:
            factor = rnd.uniform(0.9, 1.15)
            base = rnd.uniform(800, 1600)
            for month in range(1, 13):
                plan = round(base * (1 + 0.03 * month), 2)
                sales = round(plan * factor * rnd.uniform(0.9, 1.1), 2)
                rows.append([dt.date(2025, month, 1).isoformat(), region, name, sales, plan])
    rows.sort()
    out = Path(__file__).with_name("sales_plan.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Month", "Region", "Manager", "Sales", "Plan"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
