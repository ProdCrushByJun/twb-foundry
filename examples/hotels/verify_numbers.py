"""The book's numbers against the raw source file, counted here without prep.py or the generator; exits 1 on a difference."""
import csv, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from tbuilder import expected
sys.stdout.reconfigure(encoding="utf8")
R = list(csv.DictReader(open(HERE / "data" / "raw_hotels.csv", encoding="utf8")))
MON = "January February March April May June July August September October November December".split()
SEG = {"Online TA": "Online agents", "Offline TA/TO": "Offline agents", "Groups": "Groups", "Direct": "Direct", "Corporate": "Corporate"}
BANDS = ["0-7", "8-30", "31-90", "91-180", "181+"]
def band(d):
    d = int(d)
    return "0-7" if d <= 7 else "8-30" if d <= 30 else "31-90" if d <= 90 else "91-180" if d <= 180 else "181+"
for r in R:
    r["c"] = int(r["is_canceled"]); r["b"] = band(r["lead_time"]); r["s"] = SEG.get(r["market_segment"], "Other")
    r["nr"] = r["deposit_type"] == "Non Refund"; r["h"] = r["hotel"].split()[0]; r["y"] = r["arrival_date_year"]
    r["m"] = MON.index(r["arrival_date_month"]) + 1
def rate(f):
    x = [r["c"] for r in R if f(r)]
    return sum(x) / len(x)
checks = []
def add(name, ours, book):
    ok = abs(ours - book) < 1e-6 * max(1, abs(ours))
    checks.append(ok)
    if not ok:
        print("DIFF", name, ours, book)
spec = json.load(open(HERE / "spec.json", encoding="utf8"))
exp = expected.compute(spec, str(HERE / spec["datasource"]["path"]))
add("rows", 119390, len(R))
add("cancelled", 44224, sum(r["c"] for r in R))
add("non-refund", 14587, sum(r["nr"] for r in R))
add("non-refund rate", 99.4, round(rate(lambda r: r["nr"]) * 100, 1))
ins = exp["Lead Time Heat · Insight"]
add("week", ins["Rate Week"], rate(lambda r: r["b"] == "0-7"))
add("long", ins["Rate Long"], rate(lambda r: r["b"] == "181+"))
add("long, no non-refund", ins["Rate Long No Refund Excluded"], rate(lambda r: r["b"] == "181+" and not r["nr"]))
for s in list(SEG.values()) + ["Other"]:
    add(s, exp["Lead Time Heat · Row Totals"][s], rate(lambda r: r["s"] == s))
    for b in BANDS:
        add(f"{s} {b}", exp["Lead Time Heat"][f"{s} | {b}"], rate(lambda r: r["s"] == s and r["b"] == b))
for b in BANDS:
    add(b, exp["Lead Time Heat · Column Totals"][b], rate(lambda r: r["b"] == b))
for h in ("City", "Resort"):
    rows = [r for r in R if r["h"] == h]
    add(f"{h} rate", exp[f"{h} Rate"][f"AGG({h} Rate Calc)"], rate(lambda r: r["h"] == h))
    note = exp[f"{h} Rate · Notes"][f"{h} hotel"]
    add(f"{h} cancelled", note[f"{h} Cancelled Count"], sum(r["c"] for r in rows))
    add(f"{h} bookings", note[f"{h} Booking Count"], len(rows))
    for key, v in exp[f"{h} Months"].items():
        ym, outcome = key.split(" | ")
        y, m = ym.split("-")
        add(f"{h} {key}", v, sum(1 for r in rows if r["y"] == y and r["m"] == int(m) and r["c"] == (outcome == "Cancelled")))
    add(f"{h} months", sum(exp[f"{h} Months"].values()), len(rows))
    for m in range(1, 9):
        c17 = sum(r["c"] for r in rows if r["y"] == "2017" and r["m"] == m)
        c16 = sum(r["c"] for r in rows if r["y"] == "2016" and r["m"] == m)
        add(f"{h} 2017 {m}", exp["Cancelled 2017 Bars"][f"{MON[m - 1][:3]} | {h}"], c17)
        add(f"{h} change {m}", exp["Change Bars"][f"{MON[m - 1][:3]} | {h}"], c17 - c16)
c17 = sum(r["c"] for r in R if r["y"] == "2017" and r["m"] <= 8)
c16 = sum(r["c"] for r in R if r["y"] == "2016" and r["m"] <= 8)
add("change pct", exp["Cancelled 2017 Bars · Insight"]["Change Pct"], (c17 - c16) / c16)
print(f"{sum(checks)} of {len(checks)} numbers match the raw file")
sys.exit(0 if all(checks) else 1)
