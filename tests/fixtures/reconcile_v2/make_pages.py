"""Pages of the reconcile v2 fixtures (decisions/058), from data/sample/sales.csv:

  canvas.html         charts drawn on <canvas>: no number in the DOM. Chart.js API (chart_shim.js, offline), a canvas
                      with data-labels + data-values, a canvas that exposes no data (unverified).
  filter_select.html  a <select> of Category (Furniture / Office / Tech) that re-renders the KPI tiles and the bars
                      from a JS object: each of the 3 states is checked.

Run: python tests/fixtures/reconcile_v2/make_pages.py (the pages are committed; tests do not run this).
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
ROWS = list(csv.DictReader((HERE.parents[2] / "data" / "sample" / "sales.csv").open(encoding="utf-8")))
REGIONS = sorted({r["Region"] for r in ROWS})
CATEGORIES = sorted({r["Category"] for r in ROWS})
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def total(rows, field):
    return round(sum(float(r[field]) for r in rows), 2)


def by(rows, key, field, members):
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    return [total(groups[m], field) for m in members]


STYLE = """<style>
  body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #222 }
  .kpis { display: flex; gap: 24px; margin-bottom: 16px }
  .kpi .v { font-size: 28px; font-weight: 600 }
  .row { display: flex; gap: 24px; flex-wrap: wrap }
  section { margin-bottom: 16px }
  .bar-row { display: flex; gap: 8px; align-items: center; width: 360px }
  .bar-row span:first-child { width: 60px }
  .fill { background: #4e79a7; height: 14px }
</style>"""


def canvas_page():
    sales_region = by(ROWS, lambda r: r["Region"], "Sales", REGIONS)
    stacked = {c: by([r for r in ROWS if r["Category"] == c], lambda r: r["Region"], "Sales", REGIONS)
               for c in CATEGORIES}
    monthly = by(ROWS, lambda r: MONTHS[int(r["Order Date"][5:7]) - 1], "Sales", MONTHS)
    profit_cat = by(ROWS, lambda r: r["Category"], "Profit", CATEGORIES)
    bar = {"type": "bar", "data": {"labels": REGIONS, "datasets": [{"label": "Sales", "data": sales_region}]},
           "options": {"plugins": {"title": {"display": True, "text": "Sales by region"}}}}
    stack = {"type": "bar", "data": {"labels": REGIONS,
                                     "datasets": [{"label": c, "data": v} for c, v in stacked.items()]},
             "options": {"plugins": {"title": {"display": True, "text": "Sales by region and category"}},
                         "scales": {"x": {"stacked": True}, "y": {"stacked": True}}}}
    line = {"type": "line", "data": {"labels": MONTHS, "datasets": [{"label": "Sales", "data": monthly}]}}
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sales canvas</title>
{STYLE}
<script src="chart_shim.js"></script>
</head><body>
<h1>Sales on canvas</h1>
<div class="kpis"><div class="kpi"><div class="v">{total(ROWS, "Sales"):,.0f}</div><div class="l">Total sales</div></div></div>
<div class="row">
  <section><canvas id="c-region" width="420" height="220"></canvas></section>
  <section><canvas id="c-stack" width="420" height="220"></canvas></section>
</div>
<div class="row">
  <section><h3>Monthly sales 2025</h3><canvas id="c-month" width="420" height="220"></canvas></section>
  <section><h3>Profit by category</h3>
    <canvas id="c-profit" width="420" height="220" data-labels='{json.dumps(CATEGORIES)}'
            data-values='{json.dumps({"Profit": profit_cat})}'></canvas></section>
  <section><h3>Weekly pattern</h3><canvas id="c-sketch" width="300" height="220"></canvas></section>
</div>
<script>
new Chart(document.getElementById("c-region"), {json.dumps(bar)});
new Chart(document.getElementById("c-stack").getContext("2d"), {json.dumps(stack)});
window.MONTHLY = {json.dumps(line)};
new Chart(document.getElementById("c-month"), window.MONTHLY);
// a sketch drawn by hand: the page keeps no data for it
const g = document.getElementById("c-sketch").getContext("2d");
[40, 80, 60, 120, 90].forEach((h, i) => g.fillRect(20 + i * 50, 200 - h, 30, h));
// the profit canvas: drawn from its own data attributes
const p = document.getElementById("c-profit"), pc = p.getContext("2d"), pv = JSON.parse(p.dataset.values).Profit;
pv.forEach((v, i) => pc.fillRect(20 + i * 120, 200 - v / 100, 80, v / 100));
</script>
</body></html>
"""


def filter_page():
    data = {}
    for c in CATEGORIES:
        rows = [r for r in ROWS if r["Category"] == c]
        data[c] = {"sales": total(rows, "Sales"), "profit": total(rows, "Profit"),
                   "regions": dict(zip(REGIONS, by(rows, lambda r: r["Region"], "Sales", REGIONS)))}
    options = "".join(f"<option>{c}</option>" for c in CATEGORIES)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Sales by category</title>
{STYLE}
</head><body>
<h1>Sales by category</h1>
<label for="cat">Category</label> <select id="cat">{options}</select>
<div class="kpis">
  <div class="kpi"><div class="v" id="k-sales"></div><div class="l">Total sales</div></div>
  <div class="kpi"><div class="v" id="k-profit"></div><div class="l">Total profit</div></div>
</div>
<section><h3>Sales by region</h3><div id="bars"></div></section>
<script>
const DATA = {json.dumps(data, indent=1)};
const fmt = (v) => Math.round(v).toLocaleString("en-US");
function render(cat) {{
  const d = DATA[cat], max = Math.max(...Object.values(d.regions));
  document.getElementById("k-sales").textContent = fmt(d.sales);
  document.getElementById("k-profit").textContent = fmt(d.profit);
  document.getElementById("bars").innerHTML = Object.entries(d.regions).map(([r, v]) =>
    `<div class="bar-row"><span>${{r}}</span><div class="fill" style="width:${{200 * v / max}}px"></div><span>${{fmt(v)}}</span></div>`).join("");
}}
const sel = document.getElementById("cat");
sel.addEventListener("change", () => render(sel.value));
render(sel.value);
</script>
</body></html>
"""


if __name__ == "__main__":
    (HERE / "canvas.html").write_text(canvas_page(), encoding="utf-8")
    (HERE / "filter_select.html").write_text(filter_page(), encoding="utf-8")
    print("canvas.html, filter_select.html")
