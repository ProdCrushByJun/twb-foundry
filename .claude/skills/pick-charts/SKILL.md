---
name: pick-charts
description: Choose blocks and a layout from workbooks the user likes — links, a Tableau Public search, a Server / Cloud search, local .twbx — and put the choice in a user profile (profiles/<name>/). Catalogs every dashboard and sheet with a status (covered / partial / not supported yet), shows a numbered gallery, writes refs.md, prefer, requests for what the generator lacks and a reading of each chosen sheet. Use for "/pick-charts", "pick blocks from these workbooks", "I want charts like in this workbook", "what from this workbook can we do", "pick charts from this workbook", "use this dashboard's layout". Style (colors, fonts) is /copy-style; building a book is /to-tableau.
---

# Blocks and a layout from workbooks

Result: `profiles/<name>/refs/catalog.json`, `refs/gallery.md`, `refs.md`, `prefer` and `layout` in `profile.yaml`, `refs/<sheet>.md`. A choice only steers /to-tableau: no data of a book is read and no XML of it is copied (decisions/196). All through `python -m tbuilder`, written `tb` below.

## 1. Get the books
- **Links or files:** use them. A file goes straight to step 2.
- **Search on Public:** `tableau-public` MCP `search_visualizations`; show the 5 best by name and author with one AskUserQuestion.
- **Search on Server / Cloud:** `tableau` MCP `search-content` with `contentTypes: ["workbook"]`, then `download-workbook` with `includeExtract: false`. Read-only: nothing is published, no data used.
- **Public download:** `tableau-public` MCP `download_workbook_twbx` with the name from the URL. If the author closed the download, say so: a picture gives no XML and such a book is out.

## 2. Catalog
```
tb book-catalog <book> --out profiles/<name>/ [--url <link> | --site <site> --workbook-id <id>]
```
One book per command when it has a link or an id. It copies the book to `refs/` and keeps earlier books and their numbers.

**Previews.** Public strips the pictures from its books. For each dashboard get one and put it where the gallery looks, `refs/previews/<book file name>/<dashboard, spaces and punctuation as _>.png`: Public `get_workbook_image`, Server `get-view-image`. Run `tb book-catalog --out profiles/<name>/` again.

## 3. Gallery
Show `refs/gallery.md`: **read the dashboards' pictures** and name what they show next to the numbers. A status comes from marks and shelves, so it can be wrong where a sheet is built by a trick; where the picture and the status disagree, say so and trust the picture.

| Status | Means | What happens on a pick |
|---|---|---|
| covered | the generator has this form | `prefer` |
| partial | it has the base; `Missing` says what is not there | `prefer`; the gap goes in `refs.md`, tell the user |
| not supported yet | it has no such form | a request in `requests.md` of the profile; a port is a separate session (experimental) |

Sheets that only hold a label or an icon have no number. Ask what to take with AskUserQuestion when the choice is short, otherwise in words: sheets by number, `B1` a whole book, `L2` a dashboard's layout.

## 4. Pick
```
tb pick-charts profiles/<name>/ --pick "3 7 L2"
```
Tell the user `moved` (a prefer that was replaced) and `requests`.

**Read each sheet in `read`:** the command writes the facts (shelves, layers, calcs) to `refs/<sheet>.md`; add what to take the trick in a line, what is decoration and stays behind, which variant fits `context/design-rules.md`. Colors and fonts are not taken from here.

A whole book (`whole_books`): `prefer` takes its most frequent covered forms. Its not supported yet sheets are not requested in bulk: name them, and pick those the user wants.

## 5. Layout
A dashboard's layout is its rows and columns in proportion, each block a slot:
```
tb pick-layout profiles/<name>/ L2              # slots: S1.. with kind, what stands there in the book, share
tb pick-layout profiles/<name>/ L2 --spec <spec.json> --map S1=<sheet> --map S2=<sheet> ...
```
Say what each slot held in the book and agree which of the new sheets goes there. Every slot must be filled. KPI cards in a row are one slot (`kpi_cards`): one kpi sheet with that many measures.

- **Not covered:** floating sheets (never carried over), blocks that overlap, more than 6 cells in a row or rows in a column, nesting over 3 levels. `why` says which, and such a layout cannot be picked.
- **Partial:** the tiled tree is carried over, and floating decoration (a button, a logo) is left out.
- The gallery's "Controls and clicks" lists each dashboard's parameters, filters and actions. They have no number and are not carried over: if the user wants one, write it in the spec.
- A grid holds sheets only. Titles come from the spec, and filters, parameters and legends (`left_out`) from its header and filters. Weights are whole numbers 1 to 12: `error_pct` says how far a block moved.
- Then build as usual. A warning D11–D13 means the source's cell is too small for your block: raise that row's weight or the dashboard's height.

## 6. Style
If the user also wants the look of these books: `/copy-style` with the same files. Without it the blocks are drawn in the profile's tokens.
