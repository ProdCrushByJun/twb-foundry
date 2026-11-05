"""Reference sums for the dates v2 golden, computed with pandas (decisions/051) - independent of tbuilder's parser:
each column is read with its format string written by hand, not detected.

Run with a Python that has pandas (not the project .venv):  python tests/fixtures/dates_v2/pandas_sums.py
Writes pandas_sums.json next to this file; tests/test_dates_v2.py compares expected.compute with it.
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data" / "sample"


def month(s):
    return s.dt.strftime("%Y-%m")


def hour(s):
    return s.dt.strftime("%H:00")


def table(df, key):
    """{'<key> | <channel>': sum of Sales}, as expected.py names table cells."""
    g = df.groupby([key, "Channel"])["Sales"].sum()
    return {f"{k} | {c}": int(v) for (k, c), v in g.items()}


def ru():
    df = pd.read_csv(DATA / "sales_dates_v2.csv")
    df["Ordered At"] = pd.to_datetime(df["Ordered At"], format="%Y-%m-%dT%H:%M")
    df["Shipped At"] = pd.to_datetime(df["Shipped At"], format="%d.%m.%Y %H:%M")
    df["Paid On"] = pd.to_datetime(df["Paid On"], format="%d.%m.%Y")  # %d/%m accept one digit
    df["Booked On"] = pd.to_datetime(df["Booked On"], format="%d/%m/%Y")
    # filters: Ordered At 2024-01-01 09:00 .. 2024-12-31 18:00; Shipped At in the last 12 months up to the last ship
    # date's month (nulls out)
    last = df["Shipped At"].max()
    first_month = (last.to_period("M") - 11).to_timestamp()
    end = (last.to_period("M") + 1).to_timestamp()
    df = df[(df["Ordered At"] >= "2024-01-01 09:00") & (df["Ordered At"] <= "2024-12-31 18:00")
            & (df["Shipped At"] >= first_month) & (df["Shipped At"] < end)]
    ship_hours = ((df["Shipped At"].dt.floor("h") - df["Ordered At"].dt.floor("h")).dt.total_seconds() // 3600).sum()
    orders = df.groupby(month(df["Ordered At"]))["Sales"].sum()
    return {
        "_filtered_rows": len(df),
        "KPI": {"SUM(Sales)": int(df["Sales"].sum()), "SUM(Units)": int(df["Units"].sum()),
                "SUM(Ship Hours)": int(ship_hours), "AGG(Active Hours)": int(df["Ordered At"].dt.floor("h").nunique())},
        "Orders": {k: int(v) for k, v in orders.items()},
        "Hours": table(df.assign(h=hour(df["Ordered At"])), "h"),
        "Paid": table(df.assign(m=month(df["Paid On"])), "m"),
        "Booked": table(df.assign(m=month(df["Booked On"])), "m"),
    }


def us():
    df = pd.read_csv(DATA / "sales_dates_v2_us.csv")
    df["Ordered At"] = pd.to_datetime(df["Ordered At"], format="%m/%d/%Y %H:%M")
    df["Paid On"] = pd.to_datetime(df["Paid On"], format="%m/%d/%Y")
    df["Logged At"] = pd.to_datetime(df["Logged At"], format="%Y-%m-%dT%H:%M:%S")
    # filters: Logged At 2024-03-01 10:00 .. 2024-11-30 12:30:30; Paid On in the last 6 months up to 2024-12-15
    df = df[(df["Logged At"] >= "2024-03-01 10:00") & (df["Logged At"] <= "2024-11-30 12:30:30")
            & (df["Paid On"] >= "2024-07-01") & (df["Paid On"] <= "2024-12-31")]
    due = df["Ordered At"] + pd.Timedelta(hours=2)  # minute boundaries crossed from the log to 2 hours after the order
    minutes = ((due.dt.floor("min") - df["Logged At"].dt.floor("min")).dt.total_seconds() // 60).sum()
    late = int((df["Ordered At"] + pd.Timedelta(hours=1) < df["Logged At"]).sum())
    orders = df.groupby(month(df["Ordered At"]))["Sales"].sum()
    return {
        "_filtered_rows": len(df),
        "KPI": {"SUM(Sales)": int(df["Sales"].sum()), "SUM(Units)": int(df["Units"].sum()),
                "SUM(Minutes Left)": int(minutes), "SUM(Late Logs)": late},
        "Orders": {k: int(v) for k, v in orders.items()},
        "Hours": table(df.assign(h=hour(df["Ordered At"])), "h"),
        "Paid": table(df.assign(m=month(df["Paid On"])), "m"),
    }


if __name__ == "__main__":
    out = Path(__file__).with_name("pandas_sums.json")
    out.write_text(json.dumps({"_source": f"pandas {pd.__version__}, {Path(__file__).name}",
                               "dates_v2.json": ru(), "dates_v2_us.json": us()}, indent=1) + "\n", encoding="utf-8")
    print(out)
