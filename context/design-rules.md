# Dashboard design rules (one checklist)

Design comes from real business reports; **data-ink ratio and spacing between elements are mandatory**.

How a rule is checked:
- **lint**: `python -m tbuilder lint <spec.json>` (tbuilder/design_lint.py) on the spec and data, before the build;
- **gate**: during the build (tbuilder/gate.py), the file is not handed over;
- **visual**: a screenshot in Desktop 2025.1, read by the agent `dashboard-designer`;
- **agent**: the agent's judgment on the spec + HTML (the metric's meaning, texts).

Lint levels: `error` (a violation, must be fixed), `warn` (almost surely a violation; stays only with a reason in the report), `info` (a recommendation).

## Layout and sizes
| ID | Rule | Check |
|---|---|---|
| D1 | A standard dashboard size: width 1000 / 1100 / 1200 / 1250 / 1280 / 1300 / 1400 / 1450 / 1500 / 1600 / 1900, height 700–960; a long read 1200–1666 × up to 1450; mobile 375×560 | lint warn |
| D2 | A tiled grid only, archetype A / B / C. KPI on top (B) or in a column on the left (A): the most important thing in the top left corner | lint warn |
| D3 | A registry goes at the bottom of its column (a small summary table is an ordinary block) | lint warn |
| D4 | No more than 6 blocks with charts on a dashboard (KPIs do not count): otherwise a second dashboard or a switch | lint warn |
| D5 | **Spacing**: no element is pressed against another or the edge. All margins and paddings only from `design.SPACE` (4 / 8 / 12 / 16 …), the block header is apart from the chart. **Outer** (Layout → Outer padding) = the zone's `margin`: the distance to a neighbor, the parent's background shows through. **Inner** (Layout → Inner padding) = `padding`: from the zone's edge to its content, painted with the zone's background. In the card theme: a gap between cards of 12 (`card_margin` 6 + 6), a dashboard edge of 12 (`theme_edge` 6 + 6), one number; a card's inner by weight (KPI 12, chart / table 16) and **at least half the gap** (inner ≥ outer); parts inside a card: margin 0 at the edge (padding holds them), 4 between each other. Text with its own background (a header ribbon, a filled column header) acts as a container with a background: padding from tokens | gate + visual |
| D6 | **Card theme** (the default; `dashboard.theme: "flat"`: the plain look without cards): canvas `canvas`, a block is a card with a 1px border `card_border` and background `card_bg` (the border is optional: `card_border: false` leaves only the canvas tone); borders and dividers (a 1px zone of color `rule`) only from tokens. The dashboard header stands on the canvas | gate + visual |
| D7 | **Consistency**: the same elements are made the same way: tiles of one KPI row have one fit, one alignment, one set of font sizes; block headers have one structure. Text is aligned to one edge (left): a tile's label and number, headers, labels start at one x in their zone; center only for planned exceptions (a pill, a total inside a donut) | gate + visual |
| D8 | **A sheet's fit**: on a dashboard Entire View by default (752 of 803 sheets of the reference books), long lists Fit Width with a scroll; Standard only where the generator's layout rests on it | gate |
| D9 | **Chart height**: a sheet with an axis (line, area, bar, combo, scatter, KPI history) keeps at least 20 px of plot in its zone under the axes, their titles and headers (`fit.PLOT_MIN_PX`): otherwise Desktop draws axes without marks or an empty zone | lint warn (an estimate by weights) + the generator refuses + gate |

## Text
| ID | Rule | Check |
|---|---|---|
| T1 | A dashboard header is required: `dashboard.title`; a subtitle (source, period, "Data updated: …") | lint error / warn |
| T2 | The title's keyword in bold: "**Regions** Overview"; the same in a block header through `**…**` ("**Sales** by region") | lint info |
| T3 | A block title names the measure and cut ("Sales **by region**") or asks a question ("Who is behind plan?"). Then the axis and the field label do not repeat the header and are hidden | agent + visual |
| T4 | Do not write an interaction hint ("Click to filter") by hand: `dashboard.actions` adds it. A hint without an action is a lie | lint error |
| T5 | Short text: a header of ≤ 3 lines of the block's width | gate |
| T6 | Units in the title ("Sales, $"), not in each label; precision by meaning (634.6K, 13.0%) | agent |
| T7 | Block headers are the generator's text zones (do not switch `block_headers` off): otherwise Tableau draws the sheet's title itself, without a subtitle and outside the spacing system | lint warn |
| T8 | **Column headers on the left**: rarely in the center (over a pill), **never on the right**. A number stands under its header, on the left too: Desktop puts a right-aligned number in a registry's text cell past the end of the `MIN(1)` bar and shortens the bar for the label, so the number drifts from the column's edge and from its header, and a cell highlight becomes a pink block left of the number | generator (a registry has no right alignment) + a test; the spec has no alignment, lint does not check it |
| T9 | **A block title of 1–2 words (at most 4), the explanation on the second line (`subtitle`)**: "**Heavy** delays" / "over 120 min, dot = a delivery"; "**When**" / "share of delays by day and wave, %". Do not put a long phrase, a threshold, "what a mark means" or explanatory units in `title`. A one-word unit after a comma ("Sales by region, %") is fine in the title too (T6), a full "in pieces by reason" goes to the subtitle. Replaces T3 in length only: the title still names the measure / cut or asks a question | lint warn (> 4 words) + the agent moves it |

## Color
| ID | Rule | Check |
|---|---|---|
| C1 | The base is gray, color only with a meaning: a highlight `color: {highlight}`, good / bad, a plan behind the actual. The highlight color is the book's accent: `dashboard.accent` or `#4e79a7` | lint info / agent |
| C2 | A categorical palette (`color: "Field"`) only with ≤ 5 values. More: highlight 1–2 values, the rest gray | lint warn |
| C3 | No more than 3 lines of different colors: otherwise spaghetti, highlight one or two series | lint warn |
| C4 | A legend as colored words in the subtitle (`{accent:East}`, `{good:…}`, `{bad:…}`), not a separate card | lint info + visual |
| C5 | The good / bad direction by the metric's meaning: costs, churn, days to close are good going down (`good: down`) | agent |
| C6 | Plan and previous period gray behind the actual (`plan`), not a second bright color | agent |
| C7 | The brand color only in the shell: the background of a brand sidebar and header strip (`sidebar.color`, `topbar.color`). Marks do not have it: their color has a meaning (C1). A brand close to a color of meaning (good / bad / the book's accent, RGB distance < 64) reads as that meaning. The same for `dashboard.accent`: closer than 64 to good / bad, a highlight reads as "good / bad" | lint warn |
| C8 | Text on the brand color is readable: contrast ≥ 4.5:1 (WCAG AA). The generator itself takes white or dark `#333333`, whichever contrasts more; if neither is enough, the brand gets darker or lighter. The same for a registry's header strip (`header`) and a white number on `bar_color` (table colors from the HTML under the faithful style), and without `bar_color` on `dashboard.accent` (the house accent `#4e79a7` gives 4.4:1 and is not checked, the look stays). The same for a gray sidebar: `text` on `sidebar_bg` of a profile | lint error + gate (text on a zone's fill) |
| C9 | Text on white no lighter than `#898989` (contrast ≥ 3.5:1). Colored words and a KPI delta in a good / bad color lighter than the floor: in the card theme they are drawn with the tokens `good_text` / `bad_text` (without the theme: info, the theme fixes it, not the spec) | lint info |
| C10 | A heatmap of more than 3 cells has its own scale `color: {scale: sequential}` (light gray → accent), not Tableau's default palette | lint warn |
| C11 | A diverging scale (`scale: diverging`, bad ← gray → good) only with `center`: the value that means "even" (0 for a change, the plan for attainment). Without it the neutral color lands in the middle of the data | lint error |

## Data-ink
| ID | Rule | Check |
|---|---|---|
| I1 | Declutter is on: no grids, zero lines, axis rulers, row bands. An exception: a signed bar (negatives, `color.good`, a diverging scale) has a solid zero line along the measure axis: zero is the base of comparison | lint warn + generator |
| I2 | No labels that repeat the block header (an axis title, a field label), no borders or extra lines | visual |
| I3 | Bars by category are sorted by the measure (`sort: desc`); alphabetical order only for ordinal dimensions | lint warn |
| I4 | No more than 12 bars in a block: beyond that a Top N or a registry | lint warn |
| I5 | A bare text table is the last option: a registry with bars in cells (`registry`) or a heatmap reads faster | lint info |
| I6 | No helper fields in the tooltip (say, "Cell: 1" of a registry) | visual |
| I7 | A reference line is a gray dashed line labeled "Average 76" (the generator always labels it); no more than one per sheet, a second one with a reason | lint warn |
| I8 | A registry's total under a bar column is a number without a bar: the total does not stretch the rows' bars. A total's bar (`total.bar`) only for a ratio or average, where the total is not longer than the longest row bar; a sum does not draw one. The total is a bold number on the row's gray background, no rule: the total's zero bar in the total's fill color | lint warn + gate (a total's bar of 0) |
| I9 | **Labels at the bar's end instead of an axis**: a horizontal bar by members without a stack, plan, date or target (`reference` target) defaults to `labels: end` (with a line across all bars, avg, median, const, param, band, too: the axis is hidden, the line has its own label): the value at the bar's end, the measure axis hidden, row headers 10pt `#333333` with a set width; next to the headers the zone holds the widest label + 20 px + 40 px of bar. The axis back: `labels: none`, only with a reason (more than 12 bars, a scale is needed). An axis hidden without labels is an error | lint warn (`labels: none`) + the generator refuses ("too narrow") + gate (`bar-labels`) + check-drawn (labels are read) |

## KPI
| ID | Rule | Check |
|---|---|---|
| K1 | If the data has a date: KPI cards (`style: cards`: period, number, a delta with its base, a gray history), not tiles | lint info |
| K2 | A delta always has a base of comparison (MoM, vs PY, vs plan) and a color by the metric's meaning (`good`) | agent (cards do it themselves) |
| K3 | Points on a sparkline (`history_points`) mark no more than 3 periods: with a tie on max / min there are more points, remove max or min | lint warn |
| K4 | KPI status dots (`status`) come with a status legend as a line in the block's or dashboard's header: each status name and its color are named on the same dashboard (`status_legend`) | lint error |

## User profile
Only the profile in effect is checked; `house` has no findings. The profile's tokens replace the values of `design.py` in all the rules above.

| ID | Rule | Check |
|---|---|---|
| P1 | The profile reads: token keys from `design.py`, hex, the schema, `based_on`, locked rules. Broken: no build, lint gives only this finding. No `style_book` / `sources` file or `context_dirs` folder: warn | lint error / warn |
| P2 | Profile colors as text: `text` on `card_bg` and `canvas`, `subtitle` on `canvas`: contrast ≥ 4.5:1 (like C8); `muted`, `good_text`, `bad_text` on `card_bg`: no weaker than `#898989` on white (like C9). A pair the profile did not touch is not checked | lint error / warn |
| P3 | `palettes.categorical` is no longer than the C2 threshold (5; `rules.C2.max_categories` changes it) | lint warn |
| P4 | The book is built in the profile the mock was drawn in (`outline.json`, the `tb profile-css` block) | lint warn |

A profile's `rules:` changes only the level warn ↔ info and the C2 threshold. Errors stay errors. C8, C9, D5, I* cannot be changed (P1).

## What the agent must not change
Measures, aggregations, filters in meaning, calc formulas, the set of blocks with data from the HTML. Numbers after an edit must match the numbers before it (`expected.compute`). If a rule needs generator work, it is not worked around: it goes to the report.
