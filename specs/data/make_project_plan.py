"""Synthetic project plan for the Gantt demo (specs/roadmap26.json, polish-26): 12 tasks, start / end dates, status.

Run: python specs/data/make_project_plan.py -> specs/data/project_plan.csv (fixed seed: the same file every run).
"""
import csv
import datetime as dt
import random
from pathlib import Path

TASKS = ["01 Kickoff", "02 Requirements", "03 Data audit", "04 Design", "05 Data model", "06 ETL build",
         "07 Dashboard build", "08 Review", "09 UAT", "10 Training", "11 Go-live", "12 Hypercare"]
TODAY = dt.date(2026, 2, 18)  # the plan's 'now': done before it, in progress across it, planned after it


def main():
    rnd = random.Random(26)
    start = dt.date(2026, 1, 5)
    rows = []
    for i, task in enumerate(TASKS):
        days = rnd.randint(5, 21)
        end = start + dt.timedelta(days=days)
        status = "Done" if end <= TODAY else "In progress" if start <= TODAY else "Planned"
        rows.append({"task": task, "start": start.isoformat(), "end": end.isoformat(), "status": status})
        start = start + dt.timedelta(days=rnd.randint(3, max(4, days - 2)))  # the next overlaps this one
    out = Path(__file__).with_name("project_plan.csv")
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["task", "start", "end", "status"])
        w.writeheader()
        w.writerows(rows)
    print(out, len(rows))


if __name__ == "__main__":
    main()
