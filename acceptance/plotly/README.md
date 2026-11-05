# acceptance/plotly

Synthetic Plotly.js 2.35 dashboard (SVG renderer, CDN) as a /to-tableau acceptance case (todo 0.4, decision 102).

- `make_data.py` writes `hr_events.csv` (1146 rows, 2025, seed 20261025) and `hr-overview.html` (from `template.html.in`, rows embedded as JSON).
- `make_expected.py` (system python with pandas) writes `expected.json` from the CSV, independent of the HTML and the generator.
- `spec.json`, `reconcile.json` (empty: nothing accepted), `expected.json` are the regress case.

Page: 3 KPI (Hires, Exits, Net headcount change "+92"), stacked bar by quarter (Hire / Exit), horizontal bar of exits by department, heatmap department x month with cell values, small table "Department balance".

## Answers to the /to-tableau questions (defaults, no user)

- Style: house; theme: cards; dashboard size 1280 x 900.
- Filters: none (the page has none). Dates: ISO.
- Calcs by hand (evidence found no candidate): Hire Flag, Exit Flag, Net Change. The heatmap columns are the date itself: `cols: Event Date, date_level: month`, headers "Jan" (decisions/125).
- Layout: heatmap and table each got a full-width row (side by side the build refused: heatmap now needs 671 px (was 935), the cell had 496; registry needs more height).

## Transferred / simplified / not transferred

- Transferred: 3 KPI values, quarter bars by Event Type, exits by department with labels, 72 heatmap cells, balance table (checked against pandas).
- Simplified: net change shown as 92 (no "+"); KPI captions and order differ in the picture; legend sits outside the cards; heatmap and bar-by-department show scroll bars.
- Not transferred: tooltips, hover, the HTML grid (heatmap and table side by side).
- Reconcile accepted 0 numbers; the heatmap cells are matched by their row and column labels (decisions/127), the empty cell (People, Apr: 0 on the page, blank in the workbook) stays "unverified"; the bar labels of the svg charts stay "elsewhere" / "unverified" (127 debt), covered by expected.json.
