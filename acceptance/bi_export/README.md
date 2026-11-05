# acceptance/bi_export

Synthetic "Power BI / Looker Studio export HTML" page as a /to-tableau acceptance case (todo 0.4, decision 104).

- `make_data.py` writes `shipments.csv` (1849 shipments, 2024-2025, seed 20261026) and `bi-export.html` (from `template.html.in`, rows embedded as JSON).
- `make_expected.py` (system python with pandas) writes `expected.json` from the CSV, independent of the HTML and the generator.
- `spec.json`, `reconcile.json` (empty: nothing accepted), `expected.json` are the regress case.

Page: a 1280 x 740 report canvas where every visual is an absolutely positioned `div` (left/top/width/height in px, service classes `visualContainer`, `cardVisual`), a banner with two static slicers (Year, Region), 4 KPI cards (Shipments, Freight cost, On-time delivery, Avg transit days), clustered SVG bar (shipments by carrier, series 2024 / 2025, nested `g`), SVG line (freight cost by month, 24 points), HTML matrix Region x year with Total row and column.

## Answers to the /to-tableau questions (defaults, no user)

- Style: house; theme: cards; dashboard size 1280 x 900.
- Filters: none transferred (the slicers are static text: Year "2024 - 2025", Region "All" = the whole file).
- Calcs by hand: Year (string, the matrix column and bar series), On-time Rate, Avg Transit.
- Layout: KPI strip, bar + line side by side, matrix full width.

## Transferred / simplified / not transferred

- Transferred: 4 KPI values, 10 bar values, matrix cells and totals (checked against pandas), 24 monthly points (the line has no labels: reconcile reads each vertex against the $-axis and compares it with the workbook, decisions/123).
- Simplified: slicers; axis ticks ("$30K", "Jan 24") are not checked by reconcile; the bar series palette is the page's (#118DFF / #12239E via `fields.Year.color`, decisions/130); the single line stays on the house accent.
- Not transferred: absolute pixel layout, the two slicers, tooltips.
