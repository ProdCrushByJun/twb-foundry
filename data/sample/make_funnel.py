"""Deterministic product funnel sample (2025, monthly, by channel) for the funnel sheet (decisions/159).

Five stages in process order (not alphabetical: the stage order is the field's manual order); each channel keeps
its own share of users from one stage to the next, so the conversions differ by channel.
Run: python data/sample/make_funnel.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

STAGES = ["Visit", "Sign-up", "Trial", "Purchase", "Renewal"]
CHANNELS = {"Search": (0.32, 0.55, 0.38, 0.70), "Social": (0.18, 0.42, 0.30, 0.58),
            "Email": (0.41, 0.61, 0.45, 0.77)}  # share kept at each step after Visit
VISITS = {"Search": 5200, "Social": 7400, "Email": 2100}


def main():
    rnd = random.Random(159)
    rows = []
    for month in range(1, 13):
        for channel, keep in CHANNELS.items():
            users = round(VISITS[channel] * rnd.uniform(0.85, 1.15))
            for i, stage in enumerate(STAGES):
                if i:
                    users = round(users * keep[i - 1] * rnd.uniform(0.92, 1.08))
                rows.append([dt.date(2025, month, 1).isoformat(), channel, stage, users])
    out = Path(__file__).with_name("funnel.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Month", "Channel", "Stage", "Users"])
        w.writerows(rows)


if __name__ == "__main__":
    main()
