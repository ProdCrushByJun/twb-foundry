# Hotel cancellations: the showcase book

One command builds the book from nothing:

```bash
python examples/hotels/build.py
```

It downloads the data, prepares it, builds `spec.json` in the style of `profiles/hotels/profile.yaml`, applies the edits the generator has no option for, runs the gate and checks the numbers against the raw file. The book: `out/hotels/hotel_cancellations.twbx`. Add `--desktop` to also open it in Tableau Desktop 2025.1 and compare what Desktop saves.

## Data
Nuno António, Ana de Almeida, Luís Nunes, *Hotel booking demand datasets*, Data in Brief 22 (2019), 41-49, [doi:10.1016/j.dib.2018.11.126](https://doi.org/10.1016/j.dib.2018.11.126). Licence: CC BY 4.0, as listed for the article by [Europe PMC](https://europepmc.org/article/PMC/PMC6297060).

File used: `hotels.csv` from the [TidyTuesday copy](https://github.com/rfordatascience/tidytuesday/tree/main/data/2020/2020-02-11), one table of 119,390 rows. It is not stored in this repo. Both hotels are in Portugal, names removed by the authors. Arrivals from 1 Jul 2015 to 31 Aug 2017. `prep.py` drops no rows.

## Where the look came from
The look comes from one book, the block forms from two others. No sheet, calc, picture or data of these books is in the workbook, and the books are not in this repo: they have no licence for reuse.

| Used for | Book | Author |
|---|---|---|
| Style: colors, font, card padding and gaps | [Demo Insurance Dashboards - Broker Portfolio Redesign](https://public.tableau.com/views/DemoInsuranceDashboards-BrokerPortfolioRedesign/InsuranceDashboard-PortfolioView) | Ellen Blackburn |
| Heatmap with total bars; bars by month | [New York Citizen Service Request](https://public.tableau.com/views/citizeenservicerequests/main) | Nur Adhyaksa |
| Value bars and change bars, the phrase with the change in the header | [Regional Overview](https://public.tableau.com/views/RegionalOverview_17215502498410/RegionalOverview) | Muhammad Azhar |

Their colors and sizes are written in the profile, so the build does not read these books.

## Edits after the build
The generator has no option for these, so `build.py` applies them after it, in this order:
1. `hotels.ops.json`: average lines off on the heatmap's total bars, axis titles off on the lower bars.
2. `month_axis.py`: months as a continuous axis, 26 month labels were cut to "Au..".
3. `hotels.ops2.json`: axis titles off on the month bars.
4. `totals_label.py`: "All" over the total bars at the right of the heatmap.
5. `hide_nulls.py`: no grey "N nulls" badge on the lower bars after a click on the heatmap.

## What the book cannot tell
- 14,587 non-refund bookings are 99.4% cancelled, mostly groups and offline agents. The authors do not explain it. They inflate the long lead time figure: 57% at 181+ days, 38% without them. The dashboard shows both; these two numbers are only here.
- A click on the heatmap filters the other charts and their numbers. The Lead time card stays whole, it is the selector. The title and subtitle do not follow a click.
- Other / 181+ shows 0%, based on 4 bookings. Corporate / 181+ has 47.
- More cancelled bookings in 2017 is partly more bookings: +23% cancelled on +11% bookings.

## Other files
- `make_mock.py`: the HTML mock, every number counted from the data. It takes the CSS from the `hotels` profile.
- `verify_numbers.py`: the book's numbers counted again from the raw file, without `prep.py` or the generator.
- `reconcile.json`: the number of the mock accepted by hand in `tb reconcile`, with its reason. To compare the mock with the book's values, after `build.py`:

  ```bash
  python examples/hotels/make_mock.py
  python -m tbuilder reconcile examples/hotels/spec.json examples/hotels/data/page.html --case examples/hotels/reconcile.json
  ```
