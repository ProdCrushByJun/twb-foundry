"""Design lint: the spec-level rules of context/design-rules.md, checked before the build.

The gate decides whether a file may be handed over (it opens cleanly, the numbers match); this lint says whether the
dashboard follows the house design rules. Each finding names its rule id, so the agent dashboard-designer
(.claude/agents/dashboard-designer.md) can fix the spec and say why.
"""
import math
import re
from dataclasses import dataclass

from . import barlabels, colors, design, fit, kpi2, registry, shell, theme, user_profile
from . import filters as filters_mod
from .design import COLOR, MIN_CONTRAST, TEXT_FLOOR

# D1: sizes of the reference dashboards (reference dashboards: 1900x900, 1000x800, 1600x1200, 1200x700...;
# style-references-3.md: 1250, 1280, 1450, 1500 wide, long reads up to 1666x1450)
WIDTHS = (1000, 1100, 1200, 1250, 1280, 1300, 1400, 1450, 1500, 1600, 1900)
HEIGHTS = (700, 960)
TALL = ((1200, 1666), 1450)  # a long read: width in this range, taller than HEIGHTS up to this
MOBILE = (375, 560)
MAX_BLOCKS = 6  # D4: chart blocks on one dashboard, KPI not counted
# D9 (decisions/101): a chart's cell estimated from the grid's weights: the dashboard's height less its header, less
# the block header over the chart (a title line and a subtitle)
CHART_TYPES = ("line", "area", "bar", "combo", "scatter")
DASH_HEADER_PX, BLOCK_HEADER_PX = 80, 56
CELL_MARGIN_PX = 70  # D11: the cell's margins and padding that the weights estimate does not see (plotly: 66 and 96px off)
CARD_CELL_MARGIN_PX = 54  # D12: what the weights estimate does not see (card padding, the header's real height); bisected
# on specs/theme_cards (the build's own limit: 54px over the need), so the warning never fires on a book that builds
CARD_ADVICE_MARGIN_PX = 96  # D12: the advised weights keep this much (acceptance/table_kpi builds from 95px over the need)
MAX_PALETTE = 5  # C2: values of a categorical color
MAX_LINES = 3  # C3: colored lines
MAX_BARS = 12  # I4
MAX_REFLINES = 1  # I7: reference lines on one sheet (each is always labelled: tbuilder/reflines.py)
MEANING_COLORS = ("good", "bad", "accent")  # C7: what a color on the marks means
MAX_UNSCALED_CELLS = 3  # C10: a heatmap with more cells needs its own color scale (decisions/041)
MAP_MIN_PLACES = 3  # G1: a map of fewer places reads better as bars (decisions/046)
MAX_SPARK_POINTS = 3  # K3: dots on one sparkline (max / min / last; a tie marks more periods, decisions/059)
NEAR_COLOR = 64  # C7: RGB distance under which a brand color reads as a meaning color
HINT = re.compile(r"click|hover|tap", re.I)  # T4
# I3: first three letters of weekday and month names
ORDINAL_EN = {"mon", "tue", "wed", "thu", "fri", "sat", "sun", "jan", "feb", "mar", "apr", "may", "jun", "jul",
              "aug", "sep", "oct", "nov", "dec"}


@dataclass
class Finding:
    rule: str
    level: str  # error | warn | info
    where: str
    text: str

    def __str__(self):
        return f"{self.level:<5} {self.rule:<3} {self.where}: {self.text}"


def _leaves(rows, trail=()):
    """(sheet name, trail): trail holds (row, rows in level, column, cells in row) for each nesting level."""
    for ri, row in enumerate(rows):
        for ci, cell in enumerate(row):
            pos = trail + ((ri, len(rows), ci, len(row)),)
            if isinstance(cell, str):
                yield cell, pos
            elif "sheet" in cell:
                yield cell["sheet"], pos
            else:
                yield from _leaves(cell["rows"], pos)


def _row_shares(rows, weights, share=1.0):
    """(sheet name, share of the grid's height): its row's weight over its level's, down the nesting."""
    total = sum(weights)
    for row, wt in zip(rows, weights):
        for cell in row:
            if isinstance(cell, str):
                yield cell, share * wt / total
            elif "sheet" in cell:
                yield cell["sheet"], share * wt / total
            else:
                yield from _row_shares(cell["rows"], cell.get("row_heights", [1] * len(cell["rows"])),
                                       share * wt / total)


def _short_charts(spec, sheets):
    """D9 (decisions/101): [(sheet, ~px of its cell)] of the line / area / bar / combo / scatter cells whose estimated
    height leaves less than the chart needs: the generator refuses them (fit.short_charts)."""
    from . import fit
    d = spec["dashboard"]
    body = d.get("height", 800) - DASH_HEADER_PX
    need = fit.AXIS_PX + fit.AXIS_TITLE_PX + fit.PLOT_MIN_PX + 2 * 12  # an axis with its title, the plot, margins
    out = []
    for name, share in _row_shares(d["grid"], d.get("row_heights", [1] * len(d["grid"]))):
        s = sheets.get(name)
        if s is None or s["type"] not in CHART_TYPES:
            continue
        px = int(body * share) - (BLOCK_HEADER_PX if s.get("title") or s.get("subtitle") else 0)
        if px < need:
            out.append((name, px, need))
    return out


def _cell_px(spec, sheets):
    """{sheet: ~px of height of its cell under the block header} from the grid's weights, like D9."""
    d = spec["dashboard"]
    body = d.get("height", 800) - DASH_HEADER_PX
    return {name: int(body * share) - (BLOCK_HEADER_PX if sheets[name].get("title") or sheets[name].get("subtitle") else 0)
            for name, share in _row_shares(d["grid"], d.get("row_heights", [1] * len(d["grid"]))) if name in sheets}


def _rows_need(spec, s, cols):
    """D11 (decisions/107): (rows, px) a heatmap / one-dimension registry needs for all its rows, or None when the rows
    are not known (a second dimension, a group, a two-line cell)."""
    if s["type"] == "heatmap":
        field, unit, head = s.get("rows"), fit.ROW_PX, fit.HEADER_PX
    else:
        rows = s.get("rows") or []
        if len(rows) != 1 or any("second" in c for c in s.get("columns", [])):
            return None
        field, head = rows[0], fit.HEADER_PX
        unit = design.TABLE_ROW_CARDS_PX if theme.on(spec) else design.REGISTRY_ROW_PX
    n = _distinct(cols, field, spec) if isinstance(field, str) else None
    top = s.get("top")
    top = top.get("n") if isinstance(top, dict) else top
    if isinstance(top, int) and n:
        n = min(n, top)
    if not n:
        return None
    return n, n * unit + (head if s["type"] == "heatmap" else 0)


def _card_need(spec, s):
    """D12 (decisions/122): px a strip / row of KPI cards needs in its cell (the build's check in
    Builder._part_boxes: value text with its margins and padding, the history strip, the pill), None when the rule
    does not apply (not cards, stacked cards, no card theme: not calibrated)."""
    if s["type"] != "kpi" or s.get("style") != "cards" or s.get("arrange") == "column" or not theme.on(spec):
        return None
    font = theme.font(spec)
    if kpi2.separate(s):  # the build's own rule (decisions/182): the face (cell less the inset) holds the text
        return kpi2.separate_min_px(spec, s, font, design.KPI_VALUE_SEPARATE)
    value = design.KPI_VALUE_WIDE if len(s["measures"]) <= design.KPI_WIDE_MAX else design.KPI_VALUE_DENSE
    pill = s.get("delta_style") == "pill"
    lines = [(font["kpi_period"], 1), (font["kpi_name"], 1), (value, 1)] + ([] if pill else [(font["kpi_delta"], 1)])
    beside = s.get("history_place") == "right"  # the sparkline right of the number, not under it (169, 178)
    return (design.header_px(lines, 0, design.SPACE["zone_margin"]) + design.CARD_TEXT_PAD_PX
            + (0 if beside else design.CARD_HISTORY_MIN_PX)
            + (design.PILL_PX + 2 * design.SPACE["zone_margin"] if pill else 0))


def _row_weights_hint(spec, name, need_px, header_px):
    """D12: the advice for a cell that is too short: row_heights with the sheet's top-level row heavier, or a taller
    dashboard when no weight is enough."""
    d = spec["dashboard"]
    body = d.get("height", 800) - DASH_HEADER_PX
    share = (need_px + header_px) / body  # the row's share of the grid that leaves the sheet need_px
    if share >= 1:
        return f"no weight is enough at height {d.get('height', 800)}: give the dashboard more height"
    weights = list(d.get("row_heights", [1] * len(d["grid"])))
    for i, row in enumerate(d["grid"]):
        if any(c == name or (isinstance(c, dict) and c.get("sheet") == name) for c in row):
            others = sum(weights) - weights[i]
            new = list(weights)
            new[i] = max(weights[i], -(-share * others // (1 - share))) if others else weights[i]
            new[i] = int(new[i]) if float(new[i]).is_integer() else new[i]
            if new != weights:
                return f"row_heights {new} (the row needs {share:.0%} of the grid)"
            return f"the row needs {share:.0%} of the grid: more dashboard height"
    return f"the sheet's row needs {share:.0%} of the grid: raise the weight of its row in row_heights"


def _parts(spec, base_dir):
    """[(sub-spec, profile)] of each data source (decisions/083), [] when the data cannot be read (lint then skips
    data rules)."""
    from . import expected
    try:
        return [(sub, p) for sub, _, p in expected.parts(spec, base_dir)]
    except (OSError, ValueError, KeyError):
        return []


def _columns(parts, sheet=None):
    """Column name -> profile column of the sheet's data source; without a sheet of every source (the first one of a
    name)."""
    out = {}
    for sub, p in parts:
        if sheet is None or any(s["name"] == sheet for s in sub["sheets"]):
            for c in p.columns:
                out.setdefault(c.name, c)
    return out


def _ordinal(col):
    """Weekday or month names: their own order is the meaning, sorting by the measure would hide it."""
    if col is None or col.datatype != "string" or not col.distinct:
        return False
    names = ORDINAL_EN  # a value may carry a number too: '19 Mon', 'Jan 2025'
    return all(any(w[:3] in names for w in re.findall(r"[^\W\d_]+", v.lower()))
               for v in col.distinct)


# I3: the calendar position of a weekday or month name (first three letters)
CALENDAR = [("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
            ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")]


def _calendar_index(v):
    for w in re.findall(r"[^\W\d_]+", v.lower()):
        for names in CALENDAR:
            if w[:3] in names:
                return names.index(w[:3])
    return None


def _alphabet_breaks_calendar(col):
    """Weekday / month values whose alphabetical order (Tableau's default) is not the calendar one: 'Fri, Mon, Sat'.
    '19 Mon', '20 Tue' are fine (the day number leads)."""
    idx = {v: _calendar_index(v) for v in col.distinct}
    if None in idx.values():
        return False
    return sorted(col.distinct) != sorted(col.distinct, key=lambda v: idx[v])


def _distinct(cols, field, spec=None):
    """Values of a text column, or of a group of the spec's fields (decisions/033)."""
    g = (spec or {}).get("fields", {}).get(field, {}).get("group")
    if g:
        src = cols.get(g["field"])
        if src is None:
            return None
        rest = set(src.distinct) - {m for ms in g["bins"].values() for m in ms}
        return len(g["bins"]) + ((1 if rest else 0) if "other" in g else len(rest))
    c = cols.get(field)
    return len(c.distinct) if c is not None and c.datatype == "string" else None


def _opening(parts, field, sheet):
    """Values of a text column in the rows the workbook opens with when a filter has a default (decisions/035):
    a case's opens with the BK teams, 12 analysts of 20. None without a default or when the data cannot be read. The
    sheet's data source and its filters (decisions/083)."""
    for spec, p in parts:
        if not any(s["name"] == sheet for s in spec["sheets"]):
            continue
        if not any(f.get("default") for f in spec.get("filters", [])):
            return None
        try:
            _, rows = filters_mod.split_rows(spec, p)
        except (OSError, ValueError, KeyError):
            return None
        if field not in {c.name for c in p.columns}:
            return None
        return len({r[field] for r in rows if r[field] != ""})
    return None


def _periods(parts, sheet, field, level):
    """D13: the periods of a bar along a date (its months), None without the data or under a date range / relative
    filter (it cuts them)."""
    from . import dates
    for spec, p in parts:
        if not any(s["name"] == sheet for s in spec["sheets"]):
            continue
        col = next((c for c in p.columns if c.name == field), None)
        if (col is None or col.datatype not in ("date", "datetime") or level not in ("year", "quarter", "month", "week", "day")
                or any(f["field"] == field and dates.is_date_filter(f)
                       for s in [spec, *spec["sheets"]] for f in s.get("filters", []))):
            return None
        return len({dates.trunc(dates.to_date(r[field]), level) for r in p.rows if r[field]})
    return None


def _raw_averages(spec):
    """F2: (field, where) of the first AVG of each field on a bar / line / area axis with no format anywhere in the
    spec (a table calc brings its own; registries and tables are not judged)."""
    from . import formats
    done = {m["field"] for s in spec["sheets"] for m in formats.measures(s) if "format" in m}
    done |= {c["name"] for c in spec.get("calcs", []) if c.get("format")}
    for s in spec["sheets"]:
        if s["type"] not in ("bar", "line", "area", "combo"):
            continue
        for m in formats.measures(s):
            if m.get("agg") == "avg" and m.get("field") not in done and "table_calc" not in m:
                done.add(m["field"])
                yield m["field"], f"sheet '{s['name']}'"


def _dimensions(spec):
    """(field, where, sheet | None) of every field the dashboard shows as discrete members: bars, rows and columns,
    colors, places, points, filter cards (no sheet). Continuous date axes are not here (an empty date makes no mark
    there)."""
    for s in spec["sheets"]:
        where, t = f"sheet '{s['name']}'", s["type"]
        names = [s.get("dimension"), None if s.get("date_level") else s.get("cols"), s.get("detail"),
                 s.get("geo", {}).get("field")]  # date_level: periods, not members (decisions/125)
        names += [s["rows"]] if isinstance(s.get("rows"), str) else list(s.get("rows") or [])
        color = s.get("color")
        names += [color] if isinstance(color, str) else [color.get("field")] if isinstance(color, dict) else []
        if t in ("line", "area", "kpi"):
            names = [color] if isinstance(color, str) else []  # their date is an axis
        for n in names:
            if isinstance(n, str):
                yield n, where, s
    for f in spec.get("filters", []):
        if filters_mod.is_dimension(f):
            yield f["field"], f"filter on '{f['field']}'", None


def _code_names(spec):
    """F1: (column, where it is first shown) of the data columns a header or a filter card shows under a name like
    code - snake_case or all lower case ('customer_tier', 'stage') - with no caption (decisions/073). Calcs and groups
    are named by the spec itself."""
    props = spec.get("fields", {})
    named = {c["name"] for c in spec.get("calcs", [])} | {k for k, v in props.items() if "group" in v}
    seen = set()
    for field, where, _ in _dimensions(spec):
        code = "_" in field or (field == field.lower() and any(ch.isalpha() for ch in field))
        if code and field not in named and "caption" not in props.get(field, {}) and field not in seen:
            seen.add(field)
            yield field, where


def _null_members(parts):
    """N1: {data column: (empty values, where it is first shown)} of the columns shown as members (a group: its
    source column), decisions/056. Each source's sheets on its data (decisions/083); a sheet's own filters of values
    first: the rows they leave out draw no Null on it (a case: customer_tier is empty on the region rows only)."""
    out = {}
    for spec, p in parts:
        columns = {c.name for c in p.columns}
        groups = {k: v["group"]["field"] for k, v in spec.get("fields", {}).items() if "group" in v}
        try:
            calc = filters_mod.calc_values(spec, p)
        except ValueError:
            calc = None
        for field, where, s in _dimensions(spec):
            col = groups.get(field, field)
            if col in columns and col not in out:
                try:
                    rows = p.rows if s is None else filters_mod.sheet_rows(s, p.rows, calc)
                except (ValueError, TypeError):  # a calc the lint cannot evaluate: every row
                    rows = p.rows
                n = sum(r[col] == "" for r in rows)
                if n:
                    out[col] = (n, where)
    return out


def _spark_points(spec, base_dir, s):
    """{measure label: periods with a dot} of a cards sheet with history_points, by expected.compute; {} when the data
    cannot be read."""
    from . import cards, expected, kpi2
    try:
        got = expected.compute(spec, expected.data_path(spec, base_dir))
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for m in s["measures"]:
        part = {"name": f"{s['name']} · {cards.label(m)} · History"}
        out[cards.label(m)] = len(got.get(kpi2.marks_record(part), {}))
    return out


def _long_total_bars(spec, base_dir, s):
    """[(column label, total key)] of a registry's total.bar columns whose total, by expected.compute, is longer than
    the longest bar of its rows (all rows for the grand total, its group's for a subtotal): the generator's guard
    draws no bar there (registry.bar_formula, decisions/081)."""
    from . import expected
    cols = [c for c in s.get("columns", []) if registry.guarded(s, c) and registry.total_opts(c).get("bar")]
    if not cols:
        return []
    try:
        marks = expected.compute(spec, expected.data_path(spec, base_dir)).get(s["name"], {})
    except (OSError, ValueError, KeyError):
        return []
    is_total, out = registry.total_keys(s), []
    for c in cols:
        lab = registry.label(c)
        for key, row in marks.items():
            if not is_total(key) or row.get(lab) is None:
                continue
            group = key.rsplit(" | ", 1)[0] + " | " if " | " in key else ""
            bars = [r[lab] for k, r in marks.items() if not is_total(k) and k.startswith(group)
                    and r.get(lab) is not None]
            if bars and row[lab] > max(bars):
                out.append((lab, key))
    return out


def _distance(a, b):
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2 for i in (1, 3, 5)) ** 0.5


def _status_legends(spec, sheets, leaves):
    """K4 (decisions/062): every status a dot shows is named by a legend line drawn on the dashboard: a block's
    (status_legend 'block' under its title) or the dashboard header's; 'none' relies on another block's."""
    from . import kpi2
    d = spec["dashboard"]
    header = bool(d.get("title") or d.get("subtitle")) and not d.get("sidebar")
    shown = [sheets[n] for n, _ in leaves if n in sheets and kpi2.has_status(sheets[n])]
    drawn = set()
    for s in shown:
        place = kpi2.legend_place(s)
        if (place == "block" and (s.get("title") or s.get("subtitle")) and spec.get("block_headers", True)) or \
                (place == "dashboard" and header):
            drawn |= set(kpi2.status_items([s]))
    out = []
    for s in shown:
        missing = [item[0] for item in kpi2.status_items([s]) if item not in drawn]
        if missing:
            out.append(Finding("K4", "error", f"sheet '{s['name']}'",
                               f"status dots {missing} have no legend on the dashboard: set status_legend 'block' "
                               f"(under the block title) or 'dashboard' (in its header)"))
    return out


def lint(spec, base_dir=".", build=False):
    """All findings for a schema-valid spec, errors first. Several dashboards (decisions/040): each is linted, a
    finding of the shared sheets once. build: also what would stop its build, by building it (tbuilder/trial.py); the
    command asks for it, regress builds each book anyway."""
    try:
        profile = user_profile.active(spec)
    except user_profile.ProfileError as e:  # no tokens to judge the book by: only this is known (P1)
        return [Finding("P1", "error", f"profile '{user_profile.resolve(spec)}'", str(e))]
    with design.book_accent(spec):  # the profile's tokens and the book's accent in C7 / C8 (decisions/137, 193)
        out = _lint_all(spec, base_dir) + _lost_actions(spec, base_dir) + _long_titles(spec) + _profile_rules(profile) + _mock_style(profile, base_dir)
    if build:  # decisions/198
        from . import trial
        out += [Finding("BUILD", "error", "build", text) for text in trial.problems(spec, base_dir)]
    for f in out:
        level = profile.get("rules", {}).get(f.rule, {}).get("level")
        if level and f.level != "error":
            f.level = level
    rank = {"error": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda f: rank[f.level])


# P2: the profile's colors, as text. (text, background, min contrast): C8's floor for what must be read, C9's for
# what may be lighter
PROFILE_TEXT = (("text", "card_bg", MIN_CONTRAST), ("text", "canvas", MIN_CONTRAST), ("subtitle", "canvas", MIN_CONTRAST),
                ("muted", "card_bg", None), ("good_text", "card_bg", None), ("bad_text", "card_bg", None))


def _profile_rules(profile):
    """Group P (decisions/193): the paths of the profile (P1), its colors as text (P2), its palette (P3). Run under the
    profile's tokens. A pair the profile does not touch is design.py's, not its finding."""
    where = f"profile '{profile['name']}'"
    out = [Finding("P1", "warn", where, text) for text in user_profile.missing_paths(profile)]
    given = profile["tokens"]["color"]
    for fg, bg, floor in PROFILE_TEXT:
        if fg in given or bg in given:
            ratio = shell.contrast(COLOR[fg], COLOR[bg])
            if ratio < (floor or shell.contrast(TEXT_FLOOR, "#ffffff")):
                out.append(Finding("P2", "error" if floor else "warn", where,
                                   f"'{fg}' {COLOR[fg]} on '{bg}' {COLOR[bg]} has contrast {ratio:.1f}:1"
                                   f" (min {floor or 'as ' + TEXT_FLOOR + ' on white'})"))
    n, top = len(profile.get("palettes", {}).get("categorical", [])), _max_palette(profile)
    if n > top:
        out.append(Finding("P3", "warn", where, f"categorical palette of {n} colors (max {top}, C2): highlight what "
                                                f"matters instead of giving each member a color"))
    return out


def _mock_style(profile, base_dir):
    """P4: the mock was drawn in one profile (outline.json of `tb analyze`) and the book builds in another: without
    spec.profile a styled mock comes out in house, and the two no longer look alike (decisions/195)."""
    import json
    from pathlib import Path
    try:
        mock = json.loads((Path(base_dir) / "outline.json").read_text(encoding="utf-8")).get("profile")
    except (OSError, ValueError):
        return []
    if not mock or mock == profile["name"]:
        return []
    return [Finding("P4", "warn", "profile", f"the mock is drawn in profile '{mock}', the book builds in "
                                             f"'{profile['name']}': set spec.profile, or say why they differ")]


def _max_palette(profile):
    return profile.get("rules", {}).get("C2", {}).get("max_categories", MAX_PALETTE)


# A1: a click in the mock or its notes that names a mark (decisions/174). Buttons and tabs are not actions.
CLICK_NOTE = re.compile(r"click(?:ing)?\s+on\b|on\s*click|cross-?filter|"
                        r"highlight\s+action", re.I)


def _lost_actions(spec, base_dir):
    """A1: the mock reacts to a click on its data (outline.json of `tb analyze`, or a line of *notes*.md next to the
    spec or one folder up) and no dashboard carries `actions`: the click is lost in the book."""
    import json
    from pathlib import Path
    boards = spec.get("dashboards") or [spec.get("dashboard") or {}]
    if any(d.get("actions") for d in boards):
        return []
    base = Path(base_dir)
    lost = []
    try:
        from .html_outline import data_clicks
        o = json.loads((base / "outline.json").read_text(encoding="utf-8"))
        lost += [f"click on {', '.join(g['values'][:4]) or g['tag']} in '{g.get('heading') or g.get('block')}'"
                 for g in data_clicks(o)]
    except (OSError, ValueError):
        pass
    for p in sorted({*base.glob("*notes*.md"), *base.parent.glob("*notes*.md")}):
        for line in p.read_text(encoding="utf-8").splitlines():
            m = CLICK_NOTE.search(line)
            if m:
                s = max(0, m.start() - 40)
                lost.append(f"{p.name}: '…{line[s:m.end() + 60].strip()}…'")
    if not lost:
        return []
    return [Finding("A1", "warn", "dashboard.actions",
                    f"the mock reacts to a click and the book has no actions, the click is lost: {'; '.join(lost[:4])}. "
                    f"Add dashboard.actions (filter / highlight, decisions/017, 160), or list it in gaps.md")]


# T9: a block title is 1-4 words (1-2 in the mock, 4 = T3 "Closures by owner team"), the rest goes to the subtitle
TITLE_WORDS = 4


def _long_titles(spec):
    """T9: a sheet title longer than TITLE_WORDS words (bold marks, {colors} and a one-word unit after the last comma do
    not count): the explanation ('over 120 min, a dot = a delivery') belongs to the block's subtitle."""
    out = []
    for s in spec["sheets"]:
        title = s.get("title")
        if not title or not spec.get("block_headers", True):
            continue
        text = re.sub(r"\{\w+:([^}]*)\}", r"\1", title.replace("**", ""))
        head, _, unit = text.rpartition(",")
        if head and len(unit.split()) <= 1:  # 'Sales by region, %': the unit after the comma is not a word
            text = head
        words = [w for w in text.split() if re.search(r"\w", w)]
        if len(words) > TITLE_WORDS:
            out.append(Finding("T9", "warn", f"sheet '{s['name']}'",
                               f"title '{title}' is {len(words)} words (max {TITLE_WORDS}): keep 1-2 words as the "
                               f"title and move the explanation to the subtitle (second line of the block header)"))
    return out


def _lint_all(spec, base_dir):
    if "dashboards" in spec:
        out = []
        for d in spec["dashboards"]:
            out += [f for f in _lint({**spec, "dashboard": d}, base_dir) if f not in out]
        rank = {"error": 0, "warn": 1, "info": 2}
        return sorted(out, key=lambda f: rank[f.level])
    return _lint(spec, base_dir)


def _lint(spec, base_dir="."):
    from . import registry
    spec = registry.expand(spec)  # a registry template over several dimensions (decisions/039)
    out = []
    add = lambda rule, level, where, text: out.append(Finding(rule, level, where, text))  # noqa: E731
    parts = _parts(spec, base_dir)  # each data source with its data (decisions/083)
    cols = _columns(parts)
    sheets = {s["name"]: s for s in spec["sheets"]}
    d = spec["dashboard"]
    dash = f"dashboard '{d['name']}'"
    max_palette = _max_palette(user_profile.active(spec))

    # Layout and sizes
    w, h = d.get("width"), d.get("height")
    (lo, hi), tall = TALL
    if w and h and not ((w in WIDTHS and HEIGHTS[0] <= h <= HEIGHTS[1]) or (lo <= w <= hi and HEIGHTS[1] < h <= tall)
                        or (w, h) == MOBILE):
        add("D1", "warn", dash, f"size {w}x{h} is not a reference size (width {'/'.join(map(str, WIDTHS))}, "
                                f"height {HEIGHTS[0]}-{HEIGHTS[1]}; a long read {lo}-{hi} x up to {tall})")
    leaves = list(_leaves(d["grid"]))
    for name, trail in leaves:
        s = sheets.get(name)
        if s is None:
            continue
        top = all(ri == 0 for ri, _, _, _ in trail)  # first row at every nesting level
        left = all(ci == 0 for _, _, ci, _ in trail)
        if s["type"] == "kpi" and not (top or left):
            add("D2", "warn", f"sheet '{name}'", "KPI is neither in the top row (archetype B) nor in the left "
                                                 "column (archetype A)")
        if s["type"] == "registry":  # a small crosstab is an ordinary block; a registry closes the dashboard
            ri, n_rows, _, _ = trail[-1]
            if ri != n_rows - 1:
                add("D3", "warn", f"sheet '{name}'", "a registry belongs at the bottom of its column")
    blocks = [n for n, _ in leaves if n in sheets and sheets[n]["type"] not in ("kpi", "buttons")]  # controls: no block
    if len(blocks) > MAX_BLOCKS:
        add("D4", "warn", dash, f"{len(blocks)} chart blocks (max {MAX_BLOCKS}): split the dashboard")
    for name, px, need in _short_charts(spec, sheets):
        add("D9", "warn", f"sheet '{name}'", f"~{px}px of height for the chart (from row_heights and the "
                                             f"dashboard's height), it needs ~{need}px: Desktop draws nothing in a "
                                             f"shorter zone and the build refuses it; give its row more weight")

    # Text
    if not d.get("title"):
        add("T1", "error", dash, "no dashboard title")
    elif not d.get("subtitle"):
        add("T1", "warn", dash, "no dashboard subtitle (source, period, 'Data updated: ...')")
    sources = {a["source"] for a in d.get("actions", [])} | {s["name"] for s in spec["sheets"]
                                                              if s["type"] == "buttons"}  # parameter actions (042)
    for where, title, subtitle, name in [(dash, d.get("title"), d.get("subtitle"), None)] + \
            [(f"sheet '{s['name']}'", s.get("title"), s.get("subtitle"), s["name"]) for s in spec["sheets"]]:
        if title and "**" not in title:
            add("T2", "info", where, "no key word in bold (**Regions** Overview)")
        if subtitle and HINT.search(subtitle) and name not in sources:
            add("T4", "error", where, "subtitle promises an interaction but no dashboard action starts here; "
                                      "add dashboard.actions (the hint is written from it) or drop the words")

    # Brand color: the shell only (decisions/029)
    for part, band in shell.bands(spec):
        where, fg = f"{dash} {part}", shell.text_color(band)
        ratio = shell.contrast(fg, band["color"])
        if ratio < MIN_CONTRAST:
            add("C8", "error", where, f"text {fg} on {band['color']} has contrast {ratio:.1f}:1 (min {MIN_CONTRAST}); "
                                      f"take a darker or lighter brand color")
        for role in MEANING_COLORS:
            if _distance(band["color"], COLOR[role]) < NEAR_COLOR:
                add("C7", "warn", where, f"brand color {band['color']} looks like the '{role}' color {COLOR[role]} "
                                         f"of the marks: the shell would read as a meaning")
    if d.get("sidebar") and not shell.brand(d):  # the grey sidebar in the profile's sidebar_bg (decisions/194): its text is not chosen
        ratio = shell.contrast(COLOR["text"], COLOR["sidebar_bg"])
        if ratio < MIN_CONTRAST:
            add("C8", "error", f"{dash} sidebar", f"text {COLOR['text']} on sidebar_bg {COLOR['sidebar_bg']} has contrast "
                                                  f"{ratio:.1f}:1 (min {MIN_CONTRAST}); a dark panel is a brand sidebar: "
                                                  f"give dashboard.sidebar a color, its text is chosen to read")
    accent = design.given_accent(spec)  # the book's accent (decisions/137): a meaning of its own, apart from good / bad
    for role in ("good", "bad") if accent else ():
        if _distance(accent, COLOR[role]) < NEAR_COLOR:
            add("C7", "warn", dash, f"accent {accent} looks like the '{role}' color {COLOR[role]}: a highlighted mark "
                                    f"would read as {role}")

    # C8 on a registry's header band and its bars (decisions/079): the titles on the band, the white value inside a
    # bar_inside bar
    for s in spec["sheets"]:
        if s["type"] != "registry":
            continue
        where = f"sheet '{s['name']}'"
        fill = registry.header_fill(s)
        pairs = [("header", fill[1], fill[0])] if fill else []
        if ("bar_color" in s or accent) and any(registry.style(c) == "bar_inside" for c in s["columns"]):
            pairs.append(("bar_color" if "bar_color" in s else "accent", COLOR["cell_text"], registry.bar_color(s)))
        for part, fg, bg in pairs:
            ratio = shell.contrast(fg, bg)
            if ratio < MIN_CONTRAST:
                add("C8", "error", where, f"{part}: text {fg} on {bg} has contrast {ratio:.1f}:1 (min {MIN_CONTRAST}); "
                                          f"take a darker or lighter color")

    # I8 (decisions/081): a registry total keeps its bar (total.bar) only where it is no longer than its rows' bars
    for s in spec["sheets"]:
        if s["type"] == "registry":
            for lab, key in _long_total_bars(spec, base_dir, s):
                add("I8", "warn", f"sheet '{s['name']}'",
                    f"column '{lab}': total.bar, but the total '{key}' is longer than its longest row bar: it shows "
                    f"its number without a bar (total.bar suits a ratio or an average, not a sum)")

    # C9: text on white no lighter than TEXT_FLOOR: the colors the spec makes the generator draw as text
    floor = shell.contrast(TEXT_FLOOR, "#ffffff")
    texts = {}  # role -> where it is drawn as text
    for where, sub in [(dash, d.get("subtitle"))] + [(f"sheet '{s['name']}'", s.get("subtitle"))
                                                      for s in spec["sheets"]]:
        for _, role in colors.runs(sub, where) if sub else []:
            if role:
                texts.setdefault(role, where)
    for s in spec["sheets"]:
        if s["type"] == "kpi" and s.get("style") == "cards":  # the change in good / bad
            for role in ("good", "bad"):
                texts.setdefault(role, f"sheet '{s['name']}'")
    for role, where in texts.items():
        color = COLOR[f"{role}_text"] if theme.on(spec) and role in ("good", "bad") else COLOR[role]
        ratio = shell.contrast(color, "#ffffff")
        if ratio < floor:
            add("C9", "info", where, f"'{role}' text {color} on white has contrast {ratio:.1f}:1, lighter than "
                                     f"{TEXT_FLOOR} ({floor:.1f}:1); the card theme draws it in {role}_text")

    # Color, data-ink, KPI
    if spec.get("declutter") is False:
        add("I1", "warn", "spec", "declutter is off: gridlines, zero lines and axis rulers are drawn")
    if spec.get("block_headers") is False:
        add("T7", "warn", "spec", "block_headers is off: Tableau draws the sheet titles itself, without subtitles "
                                  "and outside the spacing system")
    has_date = any(c.datatype in ("date", "datetime") for c in cols.values())
    legends = set()  # C4 once per field: sheets colored by one field share one legend
    cells = _cell_px(spec, {s["name"]: s for s in spec["sheets"]})  # D10 (decisions/093)
    for s in spec["sheets"]:
        where, t, color = f"sheet '{s['name']}'", s["type"], s.get("color")
        cols = _columns(parts, s["name"])  # the sheet's source
        if isinstance(color, str):
            n = _distinct(cols, color, spec)
            if t == "line" and n is not None and n > MAX_LINES:
                add("C3", "warn", where, f"{n} colored lines of '{color}' (max {MAX_LINES}): highlight one or two "
                                         f"series with color: {{field, highlight}}")
            elif n is not None and n > max_palette:
                add("C2", "warn", where, f"categorical palette of {n} values of '{color}' (max {max_palette}): "
                                         f"highlight what matters, the rest muted, or group the rest: "
                                         f"fields.<name>.group = {{field: '{color}', bins: {{...}}, other: 'Other'}} "
                                         f"(decisions/033)")
            elif color not in legends and not s.get("legend"):  # a legend line in the header (045)
                legends.add(color)
                add("C4", "info", where, f"palette of '{color}' needs a legend card; colored words in the subtitle "
                                         f"work only with highlight / good / plan")
        if t in ("heatmap", "registry") and s["name"] in cells:  # D11 (decisions/107)
            need = _rows_need(spec, s, cols)
            if need and need[1] > cells[s["name"]] - CELL_MARGIN_PX:
                add("D11", "warn", where, f"~{cells[s['name']] - CELL_MARGIN_PX}px of cell for {need[0]} rows, they need {need[1]}px "
                                          f"(the sheet would scroll in Desktop): give its row more weight in "
                                          f"row_heights or the dashboard more height")
        need = _card_need(spec, s) if t == "kpi" else None  # D12 (decisions/122)
        sep = t == "kpi" and kpi2.separate(s)  # separate cards: their own inset and no history strip (decisions/182)
        margin = design.CARD_SEPARATE_MARGIN_PX if sep else CARD_CELL_MARGIN_PX
        if need and s["name"] in cells and cells[s["name"]] - margin < need:
            hdr = BLOCK_HEADER_PX if s.get("title") or s.get("subtitle") else 0
            what = "value text" if sep else f"value text + {design.CARD_HISTORY_MIN_PX}px of history"
            add("D12", "warn", where, f"~{cells[s['name']] - margin}px of cell for KPI cards that need "
                                      f"{need}px ({what}): the build refuses it; try "
                                      f"{_row_weights_hint(spec, s['name'], need + (margin if sep else CARD_ADVICE_MARGIN_PX), hdr)}")
        if t == "donut":  # a slice per member, each in its own color (decisions/044)
            n = _distinct(cols, s["dimension"], spec)
            if n is not None and n > max_palette:
                add("C2", "warn", where, f"donut of {n} slices of '{s['dimension']}' (max {max_palette}): angles "
                                         f"of small slices are not comparable; use a lollipop or a bar, or group the "
                                         f"rest: fields.<name>.group (decisions/033)")
            if n and s["name"] in cells and cells[s["name"]] / n < fit.MIN_LEGEND_ROW_PX:  # D10
                add("D10", "warn", where, f"~{cells[s['name']] // n}px a legend row for {n} members (under "
                                          f"{fit.MIN_LEGEND_ROW_PX}px the text overlaps) and the build refuses it; "
                                          f"cut the members (fields.<name>.group with other) or give the row more height")
        if t == "bar" and s.get("dimension"):
            dim = s["dimension"]
            datatype = cols[dim].datatype if dim in cols else None
            ordered = "order" in spec.get("fields", {}).get(dim, {})  # a manual order (decisions/033)
            if s.get("sort", "none") == "none" and datatype not in ("date", "datetime", "integer") and not ordered:
                if not _ordinal(cols.get(dim)):
                    add("I3", "warn", where, f"bars of '{dim}' are not sorted by the measure (sort: desc); an ordinal "
                                             f"field (Low / Medium / High) gets its order in fields.{dim}.order")
                elif _alphabet_breaks_calendar(cols[dim]):
                    add("I3", "warn", where, f"'{dim}' goes in alphabetical order, not the calendar one: "
                                             f"fields.{dim}.order")
            n = _distinct(cols, dim, spec)
            opening = _opening(parts, dim, s["name"])  # the bars of the selection the workbook opens with (045)
            if n is not None and opening is not None:
                n = min(n, opening)
            top = s.get("top", {}).get("n")  # Top N (decisions/020): at most N bars, the parameter's largest N
            if isinstance(top, str):
                p = next((p for p in spec.get("parameters", []) if p["name"] == top), {})
                top = p.get("range", {}).get("max") or max(p.get("values") or [None])  # an integer list (057)
            if n is not None and top is not None:
                n = min(n, top)
            if (n and s.get("orientation", "horizontal") == "horizontal" and s["name"] in cells
                    and (cells[s["name"]] - fit.AXIS_PX) / n > fit.MAX_BAR_ROW_PX):  # D10
                add("D10", "warn", where, f"~{(cells[s['name']] - fit.AXIS_PX) // n}px a bar for {n} members (over "
                                          f"{fit.MAX_BAR_ROW_PX}px the bars are slabs) and the build refuses it; "
                                          f"give the row less height or the chart more members")
            rows = n if n is not None else _periods(parts, s["name"], dim, s.get("date_level"))
            # D13 (decisions/166): a bar's row that keeps its header labels apart; Entire View squeezes rows under it,
            # Fit Width scrolls them
            bar_row_px = math.ceil(fit.LABEL_ROW * design.FONT["bar_header"])
            if (rows and s.get("orientation", "horizontal") == "horizontal" and s["name"] in cells
                    and rows * bar_row_px + fit.AXIS_PX > cells[s["name"]] - CELL_MARGIN_PX):  # D13 (decisions/166)
                add("D13", "warn", where, f"~{cells[s['name']] - CELL_MARGIN_PX}px of cell for {rows} bars, their "
                                          f"{design.FONT['bar_header']}pt labels need {int(rows * bar_row_px)}px and "
                                          f"the axis {fit.AXIS_PX}px: the rows scroll in Desktop (fit-width); give "
                                          f"its row more weight in row_heights, the dashboard more height or fewer "
                                          f"bars (Top N, a coarser date_level)")
            if n is not None and n > MAX_BARS:
                add("I4", "warn", where, f"{n} bars of '{dim}' (max {MAX_BARS}): Top N, or a registry "
                                         f"(a color breakdown then moves to another block)")
            if barlabels.eligible(s) and s.get("labels") == "none" and (n is None or n <= MAX_BARS):
                add("I9", "warn", where, "labels: none keeps the axis: the values at the bar ends read without it "
                                         "(decisions/087); keep the axis only with a reason in the report")
        refs = s.get("reference")
        n_refs = len(refs) if isinstance(refs, list) else int(refs is not None)
        if n_refs > MAX_REFLINES:
            add("I7", "warn", where, f"{n_refs} reference lines (max {MAX_REFLINES}): keep the one the block is "
                                     f"about; another needs a reason in the report")
        if t == "table":
            add("I5", "info", where, "plain text table: a registry with bar-in-cell or a heatmap reads faster")
        scale = color.get("scale") if isinstance(color, dict) else None  # decisions/041
        if t == "heatmap" and scale is None:
            ns = [_distinct(cols, r, spec) for r in ([s["rows"]] if isinstance(s["rows"], str) else s["rows"])]
            n_r = None if None in ns else math.prod(ns)  # two row fields: their pairs (decisions/171)
            n_c = None if s.get("date_level") else _distinct(cols, s["cols"], spec)
            n = n_r * n_c if n_r is not None and n_c is not None else None  # a calc dimension: count unknown
            if n is None or n > MAX_UNSCALED_CELLS:
                add("C10", "warn", where, f"heatmap of {n or 'many'} cells on Tableau's default palette: give it "
                                          f"color: {{scale: sequential}} (or diverging with a center)")
        if scale == "diverging" and "center" not in color:
            add("C11", "error", where, "diverging color scale without 'center': the neutral color lands at the "
                                       "data's midpoint; set the value that means 'even' (0 for a change)")
        if t == "map":  # decisions/046
            g = s["geo"]
            n = _distinct(cols, g["field"], spec)
            if n is not None and n < MAP_MIN_PLACES:
                add("G1", "warn", where, f"map of {n} place(s) of '{g['field']}' (min {MAP_MIN_PLACES}): a sorted "
                                         f"bar compares them better")
            if g.get("role") == "city":  # Desktop placed 3 of the 12 sample cities: Houston, Miami... are in several states
                add("G2", "error", where, f"city names of '{g['field']}' are not checked against Tableau's geocoding "
                                          f"(no offline list of 233 000 names), and a city whose name repeats in "
                                          f"the country is left off the map without its state (9 of 12 sample cities "
                                          f"'unknown' in Desktop): map the states, or the data's latitude / longitude")
        if t == "kpi" and s.get("style", "table") != "cards" and has_date:
            add("K1", "info", where, "the data has a date: KPI cards (style: cards) show the period, change and "
                                     "history")
        if t == "kpi" and s.get("history_points"):  # K3: dots on a sparkline mark at most 3 periods (decisions/059)
            for label, n in _spark_points(spec, base_dir, s).items():
                if n > MAX_SPARK_POINTS:
                    add("K3", "warn", f"{where} {label}", f"{n} periods marked with a dot (max {MAX_SPARK_POINTS}): "
                                                          f"ties at the max / min; drop 'max' or 'min' from "
                                                          f"history_points, or let the line speak")
    out += _status_legends(spec, sheets, leaves)
    relevant = {f["field"] for f in spec.get("filters", []) if f.get("relevant")}
    for field, (n, where) in _null_members(parts).items():
        if where == f"filter on '{field}'" and field in relevant:  # Desktop 2025.1, a case's Division (golden-debt pass)
            add("N1", "warn", where, f"'{field}' has {n} empty value(s), and its card (relevant: true) lists no "
                                     f"'Null' item: those rows count only under (All) and cannot be picked. Fill "
                                     f"them in the data, or filter them out if the HTML leaves these rows out")
            continue
        add("N1", "warn", where, f"'{field}' has {n} empty value(s): Tableau shows them as a mark 'Null' (its own "
                                 f"bar, row, cell, filter item; decisions/056). Fill them in the data, or filter "
                                 f"them out if the HTML leaves these rows out")
    for field, where in _code_names(spec):
        add("F1", "warn", where, f"'{field}' shows under its data name in headers and filter cards: give it "
                                 f"fields.{field}.caption, the name the HTML shows (decisions/073)")
    for field, where in _raw_averages(spec):
        add("F2", "warn", where, f"AVG of '{field}' has no format: Tableau shows it with up to 4 decimals (9.4167, "
                                 f"golden_top_after); give the measure a format (number1) (decisions/166)")
    rank = {"error": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda f: rank[f.level])
