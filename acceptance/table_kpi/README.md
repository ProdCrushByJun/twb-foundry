# acceptance/table_kpi

Synthetic plain HTML/CSS business report (no chart library, no JS) as a /to-tableau acceptance case: KPI cards with deltas plus tables (todo 0.4, decision 103).

- `make_data.py` writes `sales.csv` (2130 order lines, 2024-2025, seed 20261026) and `sales-report.html` (every page number computed from the same rows).
- `make_expected.py` (system python with pandas) writes `expected.json` from the CSV, independent of the HTML and the generator.
- `spec.json`, `reconcile.json` (no accepted numbers after 110), `expected.json` are the regress case.

Page: 5 KPI cards (Sales, Profit, Profit margin, Orders, Units sold: December 2025 against November 2025, arrow + percent or pp), detail table "Sales by region and category" (region group rows, category rows, region subtotal rows, grand total; Sales, vs 2024, Profit, Margin, Margin vs 2024 in pp, Units), "Top 5 products" (rank, Sales, Share of the year, vs 2024).

## Answers to the /to-tableau questions (defaults, no user)

- Style: house; theme: cards; dashboard 1600 x 960 (two registries side by side, 7:4 against the HTML 2:1: 6 + 4 panes of >= 100 px do not fit 1280, decisions/129).
- Filters: none. Dates: ISO.
- Calcs by hand: Sales 2025/2024, Profit 2025, Margin 2025, Margin Change pp, Units 2025 (share and change are registry columns: share is a FIXED LOD, decisions/109).

## Transferred / simplified / not transferred

- Transferred: 5 KPI cards with previous-month delta (Profit margin as a ratio measure `per: Sales`, change in pp), the registry with region subtotals and a grand total, the top-5 registry; "vs 2024" and "Share" are delta/share columns with sign and color (share from the grand total via FIXED LOD) (all checked against pandas).
- Simplified: Margin vs 2024 has no "pp" unit; the card page is wider than the HTML (1600 against 1280).
- Not transferred: group rows in the HTML style (region is a row header).
- Reconcile accepts nothing by hand after 105 and 110 (`reconcile.json` is empty).
