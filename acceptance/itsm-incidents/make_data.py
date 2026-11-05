"""Synthetic ITSM incident export (ServiceNow-like) and the HTML report built on it.

Writes incidents.csv (one row per incident, seed 20261022) and itsm-incidents.html: template.html.in (not .html:
regress takes the one page next to reconcile.json) with the rows embedded as JSON; the page computes every number in JS (Chart.js from cdnjs). Times are whole minutes, no time zone:
the page parses them as UTC, so durations have no DST shift.
"""
import csv
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20261022)

START, END = datetime(2025, 1, 1), datetime(2025, 6, 30)
AS_OF = datetime(2025, 6, 30, 18, 0)

PRIORITIES = [("1 - Critical", 3, 4, 8), ("2 - High", 12, 10, 24), ("3 - Moderate", 55, 26, 72),
              ("4 - Low", 30, 50, 120)]  # name, weight %, median hours to resolve, SLA target hours
CATEGORIES = [("Software", 28), ("Access", 20), ("Hardware", 18), ("Network", 16), ("Email", 10), ("Database", 8)]
GROUP_OF = {  # category -> [(group, weight)]
    "Software": [("App Support", 70), ("Service Desk", 30)],
    "Access": [("Service Desk", 80), ("Security", 20)],
    "Hardware": [("Desktop Support", 85), ("Service Desk", 15)],
    "Network": [("Network Ops", 90), ("Security", 10)],
    "Email": [("Service Desk", 60), ("App Support", 40)],
    "Database": [("DBA", 90), ("App Support", 10)],
}
GROUP_SPEED = {"Service Desk": 0.6, "Desktop Support": 1.2, "Network Ops": 0.9, "App Support": 1.3, "DBA": 1.1,
               "Security": 1.5}
CHANNELS = [("Portal", 38), ("Email", 22), ("Phone", 18), ("Chat", 12), ("Monitoring", 10)]
HOUR_WEIGHTS = [1, 1, 1, 1, 1, 2, 4, 8, 14, 16, 15, 13, 10, 13, 14, 13, 11, 8, 5, 4, 3, 2, 2, 1]


def pick(pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


rows, n = [], 12000
day = START
while day <= END:
    growth = 1 + 0.25 * (day - START).days / (END - START).days
    volume = (16 if day.weekday() < 5 else 6) * growth
    for _ in range(max(0, round(rng.gauss(volume, volume ** 0.5)))):
        n += 1
        opened = day + timedelta(hours=rng.choices(range(24), weights=HOUR_WEIGHTS)[0], minutes=rng.randrange(60))
        prio = rng.choices(PRIORITIES, weights=[p[1] for p in PRIORITIES])[0]
        cat = pick(CATEGORIES)
        group = pick(GROUP_OF[cat])
        channel = "Monitoring" if cat in ("Network", "Database") and rng.random() < 0.35 else pick(CHANNELS)
        hours = prio[2] * GROUP_SPEED[group] * math.exp(rng.gauss(0, 0.8))
        resolved = opened + timedelta(minutes=max(5, round(hours * 60)))
        if resolved > AS_OF:
            state = rng.choices(["New", "In Progress", "On Hold"], weights=[2, 6, 2])[0]
            made_sla = (AS_OF - opened) <= timedelta(hours=prio[3])
            resolved_s = ""
        else:
            state = "Resolved" if AS_OF - resolved < timedelta(days=7) else "Closed"
            made_sla = (resolved - opened) <= timedelta(hours=prio[3])
            resolved_s = resolved.strftime("%Y-%m-%d %H:%M:%S")
        rows.append({"Number": f"INC{n:07d}", "Opened": opened.strftime("%Y-%m-%d %H:%M:%S"),
                     "Resolved": resolved_s, "Priority": prio[0], "Category": cat, "Assignment Group": group,
                     "Channel": channel, "State": state, "Made SLA": "true" if made_sla else "false"})
    day += timedelta(days=1)

with (HERE / "incidents.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

cols = list(rows[0])
data = json.dumps({"cols": cols, "rows": [[r[c] for c in cols] for r in rows]}, separators=(",", ":"))
page = (HERE / "template.html.in").read_text(encoding="utf-8").replace("/*DATA*/null", data)
(HERE / "itsm-incidents.html").write_text(page, encoding="utf-8")
print(len(rows), "incidents")
