"""Deterministic large CSV for the Hyper path (decisions/026): sales.csv columns plus a high-cardinality Customer.

  python tools/make_big_csv.py -n 1000000 -o out/big/sales_1m.csv
  python -m tbuilder build tools/big_1m.json -o out/big/hyper_1m.twbx   (44.7 MB > 20 MB: packaged as Hyper)

Rows are written as they are generated (constant memory). Dates 2023-01-01..2025-12-31; every 997th row has no
Profit (nulls go through the extract as nulls). The data is not committed: regenerate it with the same -n.
"""
import argparse
import csv
import datetime as dt
import random
from pathlib import Path

REGIONS = ["East", "North", "South", "West"]
CATEGORIES = ["Furniture", "Office", "Tech"]
FIRST, DAYS = dt.date(2023, 1, 1), 3 * 365


def write(n, out, seed=26):
    rnd = random.Random(seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Order Date", "Region", "Category", "Customer", "Sales", "Profit", "Quantity"])
        for i in range(n):
            sales = round(rnd.uniform(5, 900), 2)
            profit = "" if i % 997 == 0 else round(sales * rnd.uniform(-0.15, 0.3), 2)
            w.writerow([(FIRST + dt.timedelta(days=rnd.randrange(DAYS))).isoformat(), rnd.choice(REGIONS),
                        rnd.choice(CATEGORIES), f"C{rnd.randrange(20000):05d}", sales, profit, rnd.randint(1, 9)])
    return out


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("-n", type=int, default=1_000_000)
    a.add_argument("-o", "--out", type=Path, required=True)
    args = a.parse_args()
    p = write(args.n, args.out)
    print(f"{p}: {args.n} rows, {p.stat().st_size / 2**20:.1f} MB")
