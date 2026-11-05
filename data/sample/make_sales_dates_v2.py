"""Deterministic sample with the date shapes of decisions/051 (dates v2): ISO with 'T', no leading zeros, a time of
day after a day-first or month-first date.

sales_dates_v2.csv (text-file locale ru_RU):
  Ordered At  YYYY-MM-DDTHH:MM        '2024-01-05T09:30'
  Shipped At  DD.MM.YYYY HH:MM        '06.01.2024 14:05' (one order not shipped: empty)
  Paid On     D.M.YYYY                '7.1.2024'
  Booked On   D/M/YYYY                '3/1/2024'
sales_dates_v2_us.csv (en_US), the same orders:
  Ordered At  M/D/YYYY H:MM           '1/5/2024 9:30'
  Paid On     M/D/YYYY                '1/7/2024'
  Logged At   YYYY-MM-DDTHH:MM:SS     '2024-01-05T10:12:45'

Rows whose dates all have a day <= 12 come first (4 089 of 12 800 rows, more than Desktop samples to pick the order): they read both day-first and month-first,
so Desktop can only order day and month right through the locale (decisions/019, known Desktop quirks).
Run: python data/sample/make_sales_dates_v2.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

REGIONS = ["East", "North", "South", "West"]
CHANNELS = ["Online", "Store"]


def orders():
    rnd = random.Random(2051)
    day, end, out = dt.date(2024, 1, 1), dt.date(2024, 12, 31), []
    while day <= end:
        for _ in range(rnd.randint(25, 45)):  # ~4 000 ambiguous rows first: more than Desktop samples
            at = dt.datetime.combine(day, dt.time(rnd.randint(8, 20), rnd.choice([0, 5, 30, 59])))
            shipped = at + dt.timedelta(minutes=rnd.choice([1, 59, 60, 61, rnd.randint(60, 72 * 60)]))
            paid = day + dt.timedelta(days=rnd.randint(0, 5))
            booked = day - dt.timedelta(days=rnd.randint(0, min(day.day - 1, 5)))
            logged = at + dt.timedelta(seconds=rnd.choice([0, 59, 3599, 3600, rnd.randint(0, 7200)]))
            out.append(dict(at=at, shipped=shipped, paid=paid, booked=booked, logged=logged,
                            region=rnd.choice(REGIONS), channel=rnd.choice(CHANNELS),
                            sales=rnd.randint(20, 900), units=rnd.randint(1, 6)))
        day += dt.timedelta(days=1)
    out[7]["shipped"] = None  # an order not shipped yet: a null the relative filter drops
    # day <= 12 in every non-ISO date first: these rows read both ways
    return sorted(out, key=lambda o: not ambiguous(o))


def ambiguous(o):
    """Every non-ISO date of the order has a day <= 12: it reads day-first and month-first."""
    return max(o["shipped"].day if o["shipped"] else 1, o["paid"].day, o["booked"].day, o["at"].day) <= 12


def nz(d):
    """Day and month without leading zeros: (5, 1, 2024)."""
    return d.day, d.month, d.year


def main():
    rows = orders()
    ru = Path(__file__).with_name("sales_dates_v2.csv")
    with ru.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Ordered At", "Shipped At", "Paid On", "Booked On", "Region", "Channel", "Sales", "Units"])
        for o in rows:
            w.writerow([o["at"].strftime("%Y-%m-%dT%H:%M"),
                        o["shipped"].strftime("%d.%m.%Y %H:%M") if o["shipped"] else "",
                        "%d.%d.%d" % nz(o["paid"]), "%d/%d/%d" % nz(o["booked"]),
                        o["region"], o["channel"], o["sales"], o["units"]])
    us = Path(__file__).with_name("sales_dates_v2_us.csv")
    with us.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Ordered At", "Paid On", "Logged At", "Region", "Channel", "Sales", "Units"])
        for o in rows:
            a, p = o["at"], o["paid"]
            w.writerow([f"{a.month}/{a.day}/{a.year} {a.hour}:{a.minute:02d}", f"{p.month}/{p.day}/{p.year}",
                        o["logged"].strftime("%Y-%m-%dT%H:%M:%S"), o["region"], o["channel"], o["sales"],
                        o["units"]])
    print(f"{ru}, {us}: {len(rows)} rows, {sum(map(ambiguous, rows))} ambiguous first")


if __name__ == "__main__":
    main()
