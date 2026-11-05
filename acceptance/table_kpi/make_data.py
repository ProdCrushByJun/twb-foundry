"""Synthetic retail sales export and a plain HTML/CSS business report on it (todo 0.4, decisions/103).

Writes sales.csv (one row per order line, Jan 2024 - Dec 2025, seed 20261026) and sales-report.html:
no chart library, no JS; every number on the page is computed here from the same rows.
"""
import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
rng = random.Random(20261026)

REGIONS = [("East", 30, 1.06), ("West", 28, 1.12), ("Central", 24, 0.97), ("South", 18, 0.91)]  # name, weight, 2025 growth
CATS = {  # category -> (2025 growth, [(product, weight, price, margin), ...])
    "Furniture": (0.94, [("Bookcase", 22, 380, .12), ("Chair", 38, 240, .16), ("Desk", 18, 520, .09), ("Table", 22, 450, .05)]),
    "Technology": (1.14, [("Phone", 34, 410, .22), ("Laptop", 16, 980, .14), ("Monitor", 26, 330, .19), ("Printer", 24, 270, .11)]),
    "Office Supplies": (1.04, [("Binder", 40, 42, .31), ("Paper", 32, 30, .36), ("Pen Set", 16, 24, .28), ("Storage Box", 12, 66, .24)]),
}
CAT_W = {"Furniture": 26, "Technology": 38, "Office Supplies": 36}
SEASON = [.8, .78, .9, .92, .95, 1.0, .96, .98, 1.08, 1.12, 1.22, 1.35]


def pick(pairs, w):
    return rng.choices(pairs, weights=[w(p) for p in pairs])[0]


rows, n = [], 10000
day = date(2024, 1, 1)
while day <= date(2025, 12, 31):
    lam = 3.2 * SEASON[day.month - 1] * (1.0 if day.year == 2024 else 1.07) * (0.55 if day.weekday() >= 5 else 1.0)
    for _ in range(max(0, round(rng.gauss(lam, lam ** .5)))):
        reg = pick(REGIONS, lambda r: r[1] * (r[2] if day.year == 2025 else 1))
        cat = rng.choices(list(CATS), weights=[CAT_W[c] * (CATS[c][0] if day.year == 2025 else 1) for c in CATS])[0]
        prod = pick(CATS[cat][1], lambda p: p[1])
        qty = rng.choices([1, 2, 3, 4, 5], weights=[40, 28, 16, 10, 6])[0]
        disc = rng.choice([0, 0, 0, .05, .1, .2])
        sales = round(prod[2] * qty * (1 - disc) * rng.uniform(.93, 1.07), 2)
        profit = round(sales * (prod[3] - disc * .8) + rng.uniform(-.02, .02) * sales, 2)
        n += 1
        rows.append({"Order ID": f"US-{n}", "Order Date": day.isoformat(), "Region": reg[0], "Category": cat,
                     "Product": prod[0], "Quantity": qty, "Sales": sales, "Profit": profit})
    day += timedelta(days=1)

with (HERE / "sales.csv").open("w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)


# ---- the numbers of the page ----
def agg(sel):
    r = [x for x in rows if sel(x)]
    s, p = sum(x["Sales"] for x in r), sum(x["Profit"] for x in r)
    return {"sales": s, "profit": p, "units": sum(x["Quantity"] for x in r), "orders": len(r), "margin": p / s if s else 0}


def ym(x):
    return x["Order Date"][:7]


cur, prev = agg(lambda x: ym(x) == "2025-12"), agg(lambda x: ym(x) == "2025-11")
MINUS = "−"


def money(v):
    return f"${v:,.0f}"


def kfmt(v):
    return f"${v / 1000:,.1f}K"


def pct_delta(a, b):
    d = (a / b - 1) * 100
    return f"{'+' if d >= 0 else MINUS}{abs(d):.1f}%", d >= 0


def pp_delta(a, b):
    d = (a - b) * 100
    return f"{'+' if d >= 0 else MINUS}{abs(d):.1f} pp", d >= 0


def kpi(name, value, a, b, good_up=True, pp=False):
    txt, up = (pp_delta if pp else pct_delta)(a, b)
    cls = "good" if up == good_up else "bad"
    arrow = "&#9650;" if up else "&#9660;"
    return (f'<div class="card kpi"><div class="name">{name}</div><div class="value">{value}</div>'
            f'<div class="delta {cls}">{arrow} {txt} <span>vs Nov 2025</span></div></div>')


kpis = "\n    ".join([
    kpi("Sales", kfmt(cur["sales"]), cur["sales"], prev["sales"]),
    kpi("Profit", kfmt(cur["profit"]), cur["profit"], prev["profit"]),
    kpi("Profit margin", f"{cur['margin'] * 100:.1f}%", cur["margin"], prev["margin"], pp=True),
    kpi("Orders", f"{cur['orders']:,}", cur["orders"], prev["orders"]),
    kpi("Units sold", f"{cur['units']:,}", cur["units"], prev["units"]),
])


def trow(label, a25, a24, cls="", indent=False):
    ch, up = pct_delta(a25["sales"], a24["sales"])
    mpp, mup = pp_delta(a25["margin"], a24["margin"])
    lab = f'<td class="ind">{label}</td>' if indent else f"<td>{label}</td>"
    return (f'<tr class="{cls}">{lab}<td class="num">{money(a25["sales"])}</td><td class="num {"good" if up else "bad"}">{ch}</td>'
            f'<td class="num">{money(a25["profit"])}</td><td class="num">{a25["margin"] * 100:.1f}%</td>'
            f'<td class="num {"good" if mup else "bad"}">{mpp}</td><td class="num">{a25["units"]:,}</td></tr>')


def y(year, **kw):
    return lambda x: ym(x)[:4] == year and all(x[k] == v for k, v in kw.items())


detail = []
for reg in (r[0] for r in REGIONS):
    detail.append(f'<tr class="grp"><td colspan="7">{reg}</td></tr>')
    for cat in CATS:
        detail.append(trow(cat, agg(y("2025", Region=reg, Category=cat)), agg(y("2024", Region=reg, Category=cat)), indent=True))
    detail.append(trow(f"{reg} total", agg(y("2025", Region=reg)), agg(y("2024", Region=reg)), "sub"))
a25, a24 = agg(y("2025")), agg(y("2024"))
detail.append(trow("Grand total", a25, a24, "grand"))

by_prod = defaultdict(float)
by_prod24 = defaultdict(float)
for x in rows:
    (by_prod if ym(x)[:4] == "2025" else by_prod24)[x["Product"]] += x["Sales"]
top = sorted(by_prod.items(), key=lambda kv: -kv[1])[:5]
toprows = []
for i, (p, s) in enumerate(top, 1):
    ch, up = pct_delta(s, by_prod24[p])
    toprows.append(f'<tr><td class="rk">{i}</td><td>{p}</td><td class="num">{money(s)}</td>'
                   f'<td class="num">{s / a25["sales"] * 100:.1f}%</td><td class="num {"good" if up else "bad"}">{ch}</td></tr>')

NL = "\n        "
page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Retail Sales Report</title>
<style>
  :root {{ --bg: #f4f5f7; --card: #ffffff; --line: #e2e5ea; --text: #1f2933; --muted: #6b7684; --good: #1e8e5a; --bad: #c8412f; --head: #0d3a6b; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font: 13px/1.4 "Segoe UI", Arial, sans-serif; }}
  .page {{ width: 1280px; margin: 0 auto; padding: 20px; }}
  header {{ margin-bottom: 16px; }}
  h1 {{ font-size: 22px; margin: 0; font-weight: 600; }}
  .sub {{ color: var(--muted); margin-top: 2px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 16px; margin-bottom: 16px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 14px 16px; }}
  .kpi .name {{ color: var(--muted); font-size: 12px; }}
  .kpi .value {{ font-size: 30px; font-weight: 600; margin-top: 4px; }}
  .kpi .delta {{ font-size: 12px; font-weight: 600; margin-top: 2px; }}
  .kpi .delta span {{ color: var(--muted); font-weight: 400; }}
  .good {{ color: var(--good); }} .bad {{ color: var(--bad); }}
  .row {{ display: grid; grid-template-columns: 2fr 1fr; gap: 16px; align-items: start; }}
  h2 {{ font-size: 14px; margin: 0 0 2px; font-weight: 600; }}
  .hint {{ color: var(--muted); font-size: 11px; margin-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ text-align: left; color: #fff; background: var(--head); font-weight: 600; font-size: 11px; padding: 6px 8px; }}
  th.num, td.num {{ text-align: right; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid var(--line); }}
  td.ind {{ padding-left: 24px; }}
  td.rk {{ width: 28px; color: var(--muted); }}
  tr.grp td {{ font-weight: 600; background: #eef1f5; }}
  tr.sub td {{ font-weight: 600; }}
  tr.grand td {{ font-weight: 700; border-top: 2px solid var(--text); }}
</style>
</head>
<body>
<div class="page">
  <header>
    <h1>Retail Sales Report</h1>
    <div class="sub">December 2025 against November 2025 · full year 2025 against 2024 · all regions</div>
  </header>
  <section class="kpis">
    {kpis}
  </section>
  <section class="row">
    <div class="card">
      <h2>Sales by region and category</h2>
      <div class="hint">2025 totals; change against 2024</div>
      <table>
        <thead><tr><th>Region / category</th><th class="num">Sales</th><th class="num">vs 2024</th><th class="num">Profit</th><th class="num">Margin</th><th class="num">Margin vs 2024</th><th class="num">Units</th></tr></thead>
        <tbody>
        {NL.join(detail)}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>Top 5 products</h2>
      <div class="hint">by 2025 sales</div>
      <table>
        <thead><tr><th>#</th><th>Product</th><th class="num">Sales</th><th class="num">Share</th><th class="num">vs 2024</th></tr></thead>
        <tbody>
        {NL.join(toprows)}
        </tbody>
      </table>
    </div>
  </section>
</div>
</body>
</html>
"""
(HERE / "sales-report.html").write_text(page, encoding="utf-8")
print(len(rows), "order lines")
