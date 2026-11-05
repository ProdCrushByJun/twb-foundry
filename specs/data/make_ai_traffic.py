"""Synthetic weekly web sessions by traffic platform (decisions/140): the AI share grows week by week.
Fixed seed, no real data. Run: python specs/data/make_ai_traffic.py -> specs/data/ai_traffic.csv"""
import csv
import datetime as dt
import random
from pathlib import Path

PLATFORMS = {"ChatGPT": 0.46, "Perplexity": 0.18, "Gemini": 0.14, "Copilot": 0.11, "Claude": 0.07, "Other AI": 0.04}

rnd = random.Random(140)
rows = []
start = dt.date(2026, 3, 2)  # a Monday
for w in range(26):
    week = start + dt.timedelta(weeks=w)
    total = int(52000 + rnd.gauss(0, 2500))
    ai = int(total * (0.018 + 0.0012 * w + rnd.gauss(0, 0.0015)))
    rows.append((week.isoformat(), "Non-AI", total - ai))
    for p, share in PLATFORMS.items():
        drift = 1 + (0.03 * w if p == "Claude" else -0.008 * w if p == "ChatGPT" else 0)
        rows.append((week.isoformat(), p, max(1, int(ai * share * drift * rnd.uniform(0.85, 1.15)))))
with open(Path(__file__).with_name("ai_traffic.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["week", "platform", "sessions"])
    w.writerows(rows)
