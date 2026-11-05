"""Deterministic sample with non-ISO dates for decisions/019 (date formats, period filters).

sales_dates.csv: Order Date and Due Date (+30 days) as DD.MM.YYYY, Shipped At as a datetime (YYYY-MM-DD HH:MM:SS,
times up to 23:59:59), one order without an Order Date (a null the range filter drops) and one in February 2025
without a Due Date (a null a range filter over all dates keeps). 2024-01 .. 2025-06.
sales_dates_us.csv: the same orders with the dates as MM/DD/YYYY (en_US locale); the first rows have a day <= 12,
so Tableau can only read them right through the locale.
Run: python data/sample/make_sales_dates.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

REGIONS = ["East", "North", "South", "West"]
CATEGORIES = ["Furniture", "Office", "Tech"]


def main():
    rnd = random.Random(2019)
    day, end = dt.date(2024, 1, 1), dt.date(2025, 6, 30)
    orders = []
    while day <= end:
        for _ in range(rnd.choice([0, 1, 1])):
            shipped = dt.datetime.combine(day + dt.timedelta(days=rnd.randint(0, 6)), dt.time()) + dt.timedelta(
                seconds=rnd.choice([0, 86399, rnd.randint(0, 86399)]))
            orders.append([day, shipped, rnd.choice(REGIONS), rnd.choice(CATEGORIES), rnd.randint(20, 900),
                           rnd.randint(1, 6)])
        day += dt.timedelta(days=1)
    orders[5][0] = None  # an order without an Order Date
    no_due = next(i for i, o in enumerate(orders) if o[0] and o[0] >= dt.date(2025, 2, 10))  # a null kept by 'all'
    head = ["Order Date", "Shipped At", "Due Date", "Region", "Category", "Sales", "Units"]
    for name, fmt in [("sales_dates.csv", "%d.%m.%Y"), ("sales_dates_us.csv", "%m/%d/%Y")]:
        out = Path(__file__).with_name(name)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(head)
            for i, (d, shipped, *rest) in enumerate(orders):
                due = (d + dt.timedelta(days=30)).strftime(fmt) if d and i != no_due else ""
                w.writerow([d.strftime(fmt) if d else "", shipped.strftime("%Y-%m-%d %H:%M:%S"), due, *rest])
        print(f"{out}: {len(orders)} rows")


if __name__ == "__main__":
    main()
