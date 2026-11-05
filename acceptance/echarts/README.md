# acceptance/echarts

Synthetic ECharts 5.5 dashboard (canvas renderer) as a /to-tableau acceptance case (todo 0.4, decision 097).

- `make_data.py` writes `orders.csv` (1115 rows, 2025, seed 20261024) and `sales-overview.html` (from `template.html.in`, rows embedded as JSON, ECharts from CDN).
- `make_expected.py` (system python with pandas) writes `expected.json` from the CSV, independent of the HTML and the generator.
- `spec.json`, `reconcile.json`, `expected.json` are the regress case.

Page: 4 KPI (Revenue, Orders, Average order value, Profit margin), smooth area line by month, horizontal bar by category, donut by channel, top-10 product table.

## Answers to the /to-tableau questions (defaults, no user)

- Style: house; theme: cards; dashboard size 1280 x 900.
- Revenue KPI in units M, 2 decimals; Avg Order Value as currency, 0 decimals; Profit Margin pct 1 decimal.
- Filters: none (the page has none). Dates: ISO.
- Calcs by hand (evidence found no candidate): Profit Margin, Avg Order Value, Revenue K.

## Transferred / simplified / not transferred

- Transferred: all 4 KPI values, line values by month, bar values with labels, donut shares, top-10 numbers (checked against pandas).
- Simplified: smooth line + area fill becomes a straight line; donut labels "name pct%" become a legend with value and share; month axis shows every other month; colors from the house palette, not the HTML blue; KPI strip shows tiles in a different order with default captions.
- Not transferred: Category column of the top table; markers on the line; tooltips.
- Reconcile: no manual accepts (decisions/105, 119).
