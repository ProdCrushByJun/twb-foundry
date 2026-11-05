"""Deterministic sample for filters v2 (decisions/035): Region -> City (each city in one region, for the cascade of
only relevant values), Channel (a default of two values out of three), 16 products (Top N within a context region).
Run: python data/sample/make_sales_stores.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

CITIES = {"East": ["Boston", "Newark", "Albany"], "North": ["Duluth", "Fargo", "Bismarck"],
          "South": ["Austin", "Mobile", "Tampa"], "West": ["Fresno", "Eugene", "Reno"]}
CHANNELS = ["Online", "Retail", "Partner"]
PRODUCTS = ["Atlas", "Beacon", "Cobalt", "Delta", "Ember", "Falcon", "Granite", "Harbor", "Iris", "Juniper",
            "Kestrel", "Lumen", "Meridian", "Nova", "Orbit", "Pioneer"]


def main():
    rnd = random.Random(35)
    price = {p: rnd.uniform(40, 400) for p in PRODUCTS}
    rows = []
    start = dt.date(2025, 1, 1)
    for _ in range(800):
        region = rnd.choice(list(CITIES))
        product = rnd.choice(PRODUCTS)
        sales = round(price[product] * rnd.uniform(0.6, 1.4), 2)
        rows.append([(start + dt.timedelta(days=rnd.randrange(365))).isoformat(), region,
                     rnd.choice(CITIES[region]), rnd.choice(CHANNELS), product, sales,
                     round(sales * rnd.uniform(-0.1, 0.3), 2)])
    rows.sort()
    out = Path(__file__).with_name("sales_stores.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order Date", "Region", "City", "Channel", "Product", "Sales", "Profit"])
        w.writerows(rows)
    print(f"{out}: {len(rows)} rows")


if __name__ == "__main__":
    main()
