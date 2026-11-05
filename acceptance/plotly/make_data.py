"""Synthetic HR events export and the Plotly dashboard built on it (todo 0.4, decisions/102).

Writes hr_events.csv (one row per hire or exit, seed 20261025) and hr-overview.html from template.html.in
(rows embedded as JSON; the page computes every number in JS; Plotly.js from the CDN).
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20261025)

DEPTS = [("Engineering", 34, 118000), ("Sales", 26, 84000), ("Support", 18, 56000),
         ("Operations", 12, 67000), ("Finance", 6, 92000), ("People", 4, 74000)]
LEVELS = [("Junior", 36, .72), ("Mid", 34, 1.0), ("Senior", 22, 1.32), ("Lead", 8, 1.65)]
SOURCES = [("Job Board", 38), ("Referral", 27), ("Agency", 20), ("Campus", 15)]
HIRE_SEASON = [1.1, 1.15, 1.3, 1.2, 1.0, .9, .8, .85, 1.25, 1.2, .9, .6]   # month index -> hiring volume
EXIT_SEASON = [1.3, 1.0, .9, .9, .95, 1.0, 1.0, .9, .95, 1.0, 1.0, 1.4]    # exits peak after the new year and the bonus
BASE_SALARY = {d[0]: d[2] for d in DEPTS}
LEVEL_MULT = {lv[0]: lv[2] for lv in LEVELS}


def pick(pairs, w=1):
    return rng.choices([p[0] for p in pairs], weights=[p[w] for p in pairs])[0]


rows, n = [], 5000
day = date(2025, 1, 1)
while day <= date(2025, 12, 31):
    if day.weekday() < 5:
        for kind, base, season in (("Hire", 2.3, HIRE_SEASON), ("Exit", 1.9, EXIT_SEASON)):
            lam = base * season[day.month - 1]
            for _ in range(max(0, round(rng.gauss(lam, lam ** 0.5)))):
                n += 1
                dept = pick(DEPTS)
                lvl = pick(LEVELS)
                sal = BASE_SALARY[dept] * LEVEL_MULT[lvl] * rng.uniform(.9, 1.12)
                rows.append({"Event ID": f"HR-{n}", "Event Date": day.isoformat(), "Event Type": kind,
                             "Department": dept, "Level": lvl, "Source": pick(SOURCES),
                             "Salary": int(round(sal, -2))})
    day += timedelta(days=1)

with (HERE / "hr_events.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

cols = list(rows[0])
data = json.dumps({"cols": cols, "rows": [[r[c] for c in cols] for r in rows]}, separators=(",", ":"))
page = (HERE / "template.html.in").read_text(encoding="utf-8").replace("/*DATA*/null", data)
(HERE / "hr-overview.html").write_text(page, encoding="utf-8")
print(len(rows), "events")
