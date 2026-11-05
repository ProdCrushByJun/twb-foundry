---
name: copy-style
description: Fill a user profile (profiles/<name>/) from a workbook the user likes — a local .twbx/.twb, a Tableau Public link, a Server / Cloud workbook, Preferences.tps — or from a brand book in MD. Counts tokens in the XML, writes profile.yaml and tokens.md, asks the user to confirm what the colors mean. Use for "/copy-style", "take the style from this workbook", "make a profile from this workbook", "my style like this dashboard", "here is our brand book", "style from this workbook". Not for building a workbook: that is /to-tableau with --profile.
---

# Style from a workbook

Result: `profiles/<name>/profile.yaml`, `tokens.md` (where each token came from, with counts), the book in `refs/`. A profile only changes values (decisions/193, 194). Everything goes through `python -m tbuilder copy-style`.

## 1. Get the book
- **File** (.twbx, .twb, Preferences.tps): use it as it is.
- **Tableau Public link:** `tableau-public` MCP `download_workbook_twbx` with the workbook's name from the URL, then pass the saved path and `--url <link>`. If download is closed by the author, say so and stop: a picture gives no XML.
- **Server / Cloud:** `tableau` MCP `list-workbooks` or `search-content` to find it, `download-workbook` with `includeExtract: false`, then pass the saved file with `--site <site> --workbook-id <id>`. Style only: read-only, no data of the book is used, and nothing is published.
- **Brand book in MD:** skip to step 4.

## 2. Choose the dashboard
`python -m tbuilder copy-style <book> --list`. More than one dashboard: ask with one AskUserQuestion which to take the style from. Several books are counted whole: no `--dashboard`, the books go to `sources`, not `style_book`.

## 3. Make the profile
```
python -m tbuilder copy-style <book> --dashboard "<name>" --out profiles/<name>/ [--url ... | --site ... --workbook-id ...]
```
What the profile already holds stays (`prefer`, `avoid`, `context_dirs`); the books replace tokens, palette, theme, legend.

Its output lists `confirm`: what a color means is a guess from its hue. Ask one AskUserQuestion with the guesses of accent, good and bad and their alternatives from `tokens.md`. Correct with `--set`:
```
python -m tbuilder copy-style --out profiles/<name>/ --set color.good=#rrggbb
```
Its output lists `moved`: tell the user each one, what the book has and what the profile has instead. Read `tokens.md` sections "Moved from the books" and "In the books, not in the profile" and tell the user what will differ from the book: a text color moved to the contrast floor, card padding raised to half the gap between cards (a book with floating blocks has none), a font without metrics (only Arial), a sidebar or a strip color.

## 4. Brand book
Read the MD, propose tokens (only keys of `tbuilder/design.py`), confirm with one AskUserQuestion, then:
```
python -m tbuilder copy-style --out profiles/<name>/ --brandbook context/brand.md --set color.accent=#rrggbb --set color.good=#rrggbb ...
```
Put the MD in `profiles/<name>/context/` first: `/to-tableau` reads it from there.

## 5. Check and use
`python -m tbuilder lint <spec> --profile <name>`: an error in group P or C8 is a real contrast problem, not to be silenced. A book is built with `--profile <name>` as usual.

An HTML mock in this style: `/draft-style`.
