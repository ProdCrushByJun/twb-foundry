---
name: to-tableau
description: One pass from an HTML dashboard (+ CSV/xlsx) to a checked .twbx for Tableau Desktop 2025.1 — analyze, questions to the user, spec by the procedure, one reconcile, lint + dashboard-designer, a look at the view, one full check, a report. Use when the user asks for "/to-tableau", "make the same in Tableau", "HTML to Tableau", "move this dashboard to Tableau", "here is a dashboard and data, I need a .twbx", or gives an HTML dashboard with a data file and wants a Tableau workbook. For edits of a finished workbook (section "Edits after the build"): "change the colors / fonts in the book", "fix this calc", "fix the workbook".
---

# /to-tableau — HTML dashboard → checked .twbx

The project's main requirement is **zero errors**: a file is handed over only after a green `to-tableau-check` (lint 0 errors, gate, Desktop OK, drawn, resave without differences, reconcile 0 mismatches).

Python: the project's environment (`.venv/Scripts/python` if there is one, else `python`), always with `PYTHONUTF8=1`, from the repo root. Below, `tb` = `<python> -m tbuilder`.

Run a case in a new session with a clean history: a long history is re-read on every step.

**Order:** data decisions and blockers → spec → one `reconcile` → designer → the view through `to-tableau-preview` → one full `to-tableau-check` at the end. Numbers are closed before the view; the view check does not repeat the reconciliation.

**Long commands** (`reconcile`, `to-tableau-preview`, `to-tableau-check`): `run_in_background` only, then wait for the notification. Do not poll the output or write `until … sleep`: each poll is a turn with the full context.

Before the first step read `procedures/html-to-spec.md` whole: these are the mapping rules, the skill does not repeat them.

## User profile
A profile is the folder `profiles/<name>/`: tokens, preferences, the user's MD files. Which one applies: `--profile`, then `spec.profile`, then `TB_PROFILE`, then `house`. The user named a profile → write `"profile": "<name>"` in the spec, so the case can be reproduced. Do not ask if they did not name one: without a profile it is `house`. Exception: `outline.json` has a `profile` (the mock was drawn in that style) → write it in the spec the same way; another profile named by the user is stronger. No such profile on this machine (error P1) → ask. Otherwise lint P4 warns about the mismatch.

```
tb user-profile [<name>]        # JSON: tokens, palettes, legend, theme, prefer, avoid, style_book, context, missing
```
- **The user's MD**: read the files of `context.read`, all of them and in order, **before §4**. A glossary changes labels in the spec, metric rules change calcs and aggregates, a brandbook changes headers and accents. MD does not change numbers from the source; a contradiction with the HTML is a §3 question. `context.skipped` (over ~40K tokens): do not read, list them in the report.
- **In §4**: the build takes the tokens itself, do not copy them into the spec. `prefer` and `avoid`: when choosing a type where the HTML leaves a choice. `legend: card`: a legend card instead of colored words. `palettes.categorical`: member colors through `fields.<field>.color`, in order, where a categorical palette is needed (C2).
- **`prefer` chosen from workbooks** (`/pick-charts`): the value is a spec type or its variant, the key is the block's question (`comparison`, `trend`, `part_to_whole`, `table`, `distribution`, `relationship`, `geography`, `flow`, `kpi`). If the HTML leaves a choice, take this type and name it in the report; do not change a block whose form the HTML sets. How the block works in its workbook: `refs/<sheet>.md` of the profile, a line in `refs.md`.
- **The profile's `layout`**: the command takes the dashboard's layout itself, do not repeat rows and columns in the spec by hand. `tb pick-layout profiles/<name>/` shows the slots; pick a sheet for each, then `tb pick-layout profiles/<name>/ --spec <spec.json> --map S1=<sheet> ...`. If the HTML sets another layout, that is a §3 question.
- A spec field is stronger than the profile. A profile does not switch off lint or the gate; lint group P is like any other.

## 1. Input
- Needed: the path to the HTML (a local file) and to the data (CSV or .xlsx). No data → ask; do not make data up from the HTML (procedure §0).
- Case name `<name>`: short, Latin letters, from the HTML's name. Everything goes to `out/to_tableau_<name>/`: `spec.json`, `reconcile.json`, `report.md`, the workbook.
- No need to copy the data: the spec's path to the CSV is relative to the spec's folder (`"path": "../../acceptance/x/data.csv"`).

## 2. Facts
```
tb profile <data>                          # types, distinct counts, date format; .xlsx without --sheet lists the sheets
tb analyze <page.html> <data> -d out/to_tableau_<name>
```
- Look at `page.png` (Read): what charts, cards, background, font.
- `outline.json`: blocks, layout, controls, `page` (size). `evidence.json`: field candidates.
- All the numbers of the page (not only recognized blocks): `tb outline <page.html>` → `texts`, or read the HTML. The outline often misses KPI tiles on hand-made pages: look in the HTML and `page.png`.
- The selection on load: `outline.controls[].selected` (and `multiple`). Read the page's scripts: what recalculates on a filter or click (subtitle, insight lines), where the numbers come from (seeded JS → are they in the CSV?).
- **Clicks on data**: `python -c` → `outline.clicks` where `control: false` (block, `values`, `heading`) + grep the mock's notes / requirements for "click", "highlight", "cross-filter". Each such click is an action in §4 or a gaps line "Lost interactivity".
- Do not read `outline.json` / `evidence.json` whole (20–40K tokens): select the keys you need through `python -c` / `jq` (`blocks[].{id,type,title}`, `controls`, `page`); the full JSON only for a block you have a question about.

## 3. Data decisions and blockers: one block, before the spec
First check what stops the book from being built at all (no column for a KPI, a number that cannot be reproduced, unclear units or dates): found at the end, these cost most. Collect all ambiguities and ask **once** through AskUserQuestion (clickable options, the recommended one first, up to 4 questions in a call; if more, a second call right after). Real forks only, no questions for form's sake:

| Topic | When to ask | Options |
|---|---|---|
| ~~**Style**~~ | **do not ask**: always house (a good-looking dashboard, not a copy of the HTML); faithful only if the user asked for "one to one" themselves | — |
| **Theme** | the HTML has white panels on a gray background | cards (default, do not write `theme`) / `theme: flat` without cards. With `sidebar`/`topbar` only `flat`: do not ask, write it under "not moved" |
| **Filter on open** | a preset or value is selected in the HTML (`default`) | open with the HTML's selection (default) / open with "all" |
| **A number without evidence** | a KPI or label is reproduced from the data by no aggregate | do not move it (in the report) / the user names the formula |
| **Several candidates** | a block has ≥ 2 fields or aggregates with different meanings (`count` vs `countd`, Sales vs Revenue) | the candidates from evidence |
| **Units** | evidence with `÷1000` / the HTML in MW, $K, the data in kW, $ | source units + format (`units: K/M`) / refuse |
| **Highlight threshold** | a registry with highlights, no threshold in the legend | values from the HTML text / the user's own |
| **Dates** | `profile` did not settle the format (01/02/2024) | DD/MM / MM/DD / an export in ISO |

Do not ask what the procedure settles (`sort` by monotony, headers from the HTML, archetype by layout). Write the answers in `report.md` (section "Questions").

## 4. Spec
By `procedures/html-to-spec.md` §2–3: block → sheet, layout → `dashboard.grid`, headers, calcs, fields, filters, totals, reference lines. The style is **house**: colors with a meaning instead of a categorical palette; the HTML's main color, if it is not blue, → `dashboard.accent`; member order and labels as on the page. Put in the spec explicitly what gives color: `color: {highlight | good}`, `header.color` of a registry, `style: cards` of a KPI with a date (K1). faithful (`theme_font`, `fields.<field>.color` from the HTML's palette) only on a direct request for "one to one".
- Several tabs or pages in the HTML → `dashboards` + `nav` (tabs | sidebar), by the procedure; `check-desktop` opens only the first dashboard: say "Desktop: first checked" in the report.
- A click on a mark or label filters or highlights other blocks (§2 "Clicks on data") → `dashboard.actions` by procedure §8: a highlight whose targets lack the same field → `filter`.
- Clickable metrics, period tabs (L6M / L12M / All), a view switch (chart/table) in the HTML → `parameters` + a sheet `buttons` / `switch`, `control: "radio"`, `period` of the parameter, by procedure §8c. `check-desktop` sees the default values; other values through a copy: `python tools/param_variant.py <in.twbx> <out.twbx> "View=Table"` + `check-desktop`, in the report "Desktop: values checked …".

Next to it, `reconcile.json`:
- `state`: only if a filter **without** `default` and the HTML shows a selection (a filter with `default` needs no state);
- `accepted`: each number deliberately not moved, `{number, context, reason}`; the reasons = the report's "not moved" section. A `mismatch` cannot be accepted without a reason that explains the difference. A block that is not in the spec is a rule without `number` (any number in this context, in all filter states).
- `options`: reconcile checks each value of a select or filter buttons; options whose text is not the field's value ("East — Boston, Back Bay") are mapped: `{"<option>": {"<field>": [values] | null}}` (`null` = All). In the report: `unverified` (canvas without data, small numbers, unmapped options) and `ambiguous`.

## 4a. One reconcile: numbers before the view
```
tb reconcile out/to_tableau_<name>/spec.json <page.html> --case out/to_tableau_<name>/reconcile.json -o out/to_tableau_<name>/reconcile_report.json
```
Go through all `mismatch` and `missing` in one sitting: fix the bindings in the spec, reasons in `accepted`. Repeat only after an edit that changes numbers (field, aggregate, calc, filter), not after cosmetics.

## 5. Lint + designer
```
tb lint out/to_tableau_<name>/spec.json
```
Lint builds the book itself, without Desktop: `BUILD` lines are everything the build would stop on, in one list. Fix them all in one go, before the first real build. Then the agent `dashboard-designer` (Agent, subagent_type `dashboard-designer`) on this spec + HTML/outline/evidence, with the style mode from §3. It edits the spec **in place** (the spec pins no golden), does not change numbers, runs lint and build without Desktop itself and does not return a spec that does not build; its list "needs generator work" goes to the report. With faithful, tell the agent not to touch colors, theme and font from the HTML. The result: lint 0 errors, each warn with a reason in the report. A1 (a click in the mock or notes, no `actions`): add actions; if it cannot be moved, a reason in gaps "Lost interactivity".

## 6. The view: through a preview
```
tb to-tableau-preview out/to_tableau_<name>/spec.json -o out/to_tableau_<name>/<name>.twbx
```
build + gate + Desktop + drawn, no lint or reconcile, about a minute. The book is `<name>_preview.twbx`: **this is not acceptance, do not hand this book over.** Open the snapshot (its path is in the output) next to `page.png` and compare colors, block types, axis labels, scrolling. **Write down all findings from the snapshot and fix them in one go**, then the next preview: not one edit per run.

## 7. One full check at the end
```
tb to-tableau-check out/to_tableau_<name>/spec.json <page.html> --case out/to_tableau_<name>/reconcile.json -o out/to_tableau_<name>/<name>.twbx
```
Steps: lint → build (gate inside) → gate → desktop (only if clean so far) → drawn (each dashboard open in Desktop, numbers of KPIs, registries and tables read from the snapshot; FAIL = a registry column drew nothing; WARN = a group not read by OCR or off screen: name it in the report) → resave → reconcile (runs after a Desktop failure too: findings in one run). The verdict:
- **OK** (exit 0): the book is ready;
- **FAIL** (exit 1): the book is deleted; fix the spec by the FAIL line and repeat;
- **INCOMPLETE** (exit 2): a step did not run (no Chrome / `--no-desktop`): do not hand the book over.

The output is short: problem lines, verdict, step times, the path to the snapshot and to the full log (`<name>_check.log`, with the whole reconcile report). Open the log only on WARN/FAIL and only the part you need (`grep`, `tail`); `drawn.json` and intermediate snapshots on WARN/FAIL of the group in question. Open the final snapshot once after OK, next to `page.png`: a verdict of OK does not see a book that came out gray-blue instead of green.

**Desktop queue:** `out/desktop-queue.md` is needed only if other sessions work in parallel. Then before `to-tableau-preview` and `to-tableau-check`: if the last entry is "busy" by another less than 30 min ago, wait; else append "busy: <who>, since HH:MM", re-read (give way if someone signed up earlier), afterwards "free: <who>, HH:MM". No other sessions: do not touch the queue.

**A fix cycle: no more than 3 times** for one cause. Then stop and show the user the whole error (the FAIL line, the gate/reconcile text) and what was tried. Fix **the spec**, not the generator's code and not the case file for the sake of green: a `mismatch` is a wrong binding.

If you had to do something the procedure does not have, that is a hole in the procedure: name it in the report (and, if working in the project's repo, propose an edit of `procedures/html-to-spec.md`).

## 8. Report to the user
`out/to_tableau_<name>/report.md` and briefly in the chat (by procedure §5):
- **profile** (if not `house`): the name; which MD were read and what each changed in the spec ("glossary.md: Revenue → Net sales, 3 labels"); what was not read because of the limit;
- **file**: the path to the .twbx, the verdict of `to-tableau-check` (lint / gate / reconcile summary / Desktop seconds / drawn summary / resave; images and `drawn.json` next to the book in `drawn_<name>/`);
- **questions and answers** of §3;
- **what can be fixed in words**, one line: fonts, colors, titles, spacing, card background and borders, number format, mark color and opacity, series colors, labels, tooltip, legends, filter view, grid, axes, row, column and dashboard sizes (section "Edits after the build");
- **moved**: HTML block → sheet → field/aggregate (a table);
- **simplified**, with a reason;
- **not moved**, with a reason (= `accepted` in reconcile.json + blocks without a sheet);
- **choices without clear evidence** (a measure by its title, a choice among several candidates, `elsewhere` in reconcile: list them so that a person sees them);
- **lost interactivity** (required, also in `gaps.md`): each click on data from the outline / notes → an action (`source` → targets, filter / highlight) or the reason why not; no clicks: say so;
- **lint warns** with reasons; "needs generator work" from the designer;
- what the checks do not prove, one line: drawn reads only number sheets and only what fits the window (list UNCHECKED); the view as a whole is not compared with the screenshot.

## Edits after the build
When the book exists and needs an edit, not a rebuild ("change the colors / fonts in the book", "fix this calc", "fix the workbook"):
1. First `tb inspect <book>`: sources, parameters, sheets, dashboards, all calculated fields (caption, internal name, formula). Read only.
2. Formulas, sheets, names, SQL, parameters: through `tb patch` (ops.json, gate before and after). If a formula refers to a column not in the extract, `patch` refuses: the number appears only after an extract refresh in Tableau.
3. Formatting too through `tb patch`, operations `text` (font, size, color, weight, alignment of a sheet), `title` (title of a sheet or a text zone of a dashboard, one line and new words are possible), `block` (margins, background, card border; `canvas`: the dashboard's background), `number_format` (a field's number format across the book), `marks` (mark color, size, opacity), `lines` (grid, zero line, axis lines, row dividers), `table_size` (row height, width of columns and of the row header; a sheet may get a scrollbar), `axis` (show or hide an axis, its title), `labels` (labels on marks), `series_colors` (the color of each field value across the book, the value as in the data), `tooltip` (remove, restore, own text with `<Field>`), `legend` (show or hide, title, font), `filter_view` (the view of a value filter card), `dashboard_size` (dashboard size; when shrinking, look at the titles), `color_scale` (colors and range of a continuous scale), `reference_line` (color, weight, line, label), `sheet_title` (the sheet's own title on the dashboard), `map_style` (the map's base). `number_format` with `sheet` changes the format on that sheet only. `tb inspect` shows the numbers of zones and cards. The form of the keys is at the top of `tbuilder/patch.py`. No `regress` or golden; the check is `tb patch ... --resave` of this file only.
4. A value outside the design system and new gate findings on design come as WARNING, the file is written: the user chose the value, pass the warnings on and do not fix the generator for them. Other gate findings block the file. An edit `patch` cannot do (named palettes, label position, block order): replace the value directly in the XML and check with `tb check-desktop` and `tb check-drawn`.
5. Keep the operations in `<book>.ops.json` next to the book. The edit lives only in that file and is lost on a rebuild from the spec. After a rebuild apply the same `ops.json` again and tell the user; a refusal means a sheet or zone is gone.
