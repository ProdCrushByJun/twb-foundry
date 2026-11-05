"""Registry tables (sheet type "registry"): one worksheet, a pane per column (references; decisions/015, 039).

Rows are 1-2 dimensions; each column is a pane on Columns. Column styles:
- bar: the measure itself, a grey bar with its value on it;
- text: a dummy MIN(1) axis whose full-width bar is the cell background, labelled with the measure;
  'second': a second line under the value, 8pt muted (Data Quality Testing, Wealth & Banking);
- rank: a text cell with RANK(agg) along the inner row dimension (within the outer group, as the nested sort;
  ties competition 1, 2, 2, 4: decisions/034);
- share: a text cell with agg / TOTAL(agg) over the whole table, percent; 'with_value' -> "**21 %** (230)" (Help Desk);
- bar_inside: the measure as an accent bar with its value inside in white bold (ER Referrals); a bar too short for
  its value has it outside, right of its end, in the text color: a dual axis on the measure, the second layer a
  transparent bar labelled outside (decisions/077);
- track: the share as an accent bar on a 100 % track: Measure Values stacked [share, 1 - share] on a fixed 0..1 axis
  (no dual axis), one per registry;
- dot: a dot colored by the measure on a sequential scale, its value right of it (ER Referrals waiting time);
  shape "sign" (decisions/139): a status mark instead, Tableau's own filled triangle up / down or circle by the sign
  of the measure, good / bad / muted (citizeenservicerequests 'increase / decrease / stay');
- tick: the measure as a bar with a tick at 'base' (the previous period, a plan): a per-cell reference line
  (DemandCapacity, RETAIL-POS form) in the default pane, the base on Detail of the column's pane (decisions/065);
- delta: the change of the measure against 'base', "▲ 12.3%" in the good / bad color (two calcs, as KPI cards),
  right of a 0 bar at the cell's left edge (inside a bar Desktop drew it black, decisions/164);
- spark: a mini-trend in the row, the measure over the last 'count' periods of a date as a string of block glyphs
  "▁▃▅█" (one calc per period, scaled between the lowest and the highest; decisions/096);
- pill: a status pill, the measure's level (low / ok / high ...) as a label on a pale fill, centred in the cell
  (the card pill's fills, decisions/063; decisions/096).
A highlight colors the bar of the cells below/above a threshold (bar and text). The builder and expected.py take the
calcs from here.

A registry with a total row (decisions/036, 081): a bar or bar_inside column draws its bar from a calc guarded to the
rows (every row dimension one member, COUNTD <= 1), 0 on a total row: the total's mark keeps its label but draws no
bar, so it does not stretch the column; 'total': {"bar": true} keeps the total's bar where it is no longer than the
longest row bar (an INCLUDE max of the rows); 'total': {"format"} shows the total in its own format (25.1 % under 52 %).
"""
import math
import xml.etree.ElementTree as ET

from . import design, formats
from .design import COLOR, FONT, REGISTRY_ROW_TWO_LINE_PX, TICK_STROKE_PX

STYLES = ("bar", "text", "rank", "share", "bar_inside", "track", "dot", "tick", "delta", "spark", "pill")
TEXT_CELL = ("text", "rank", "share", "delta", "dot", "spark", "pill")  # a dummy MIN(1) axis per column
STRINGS = ("spark", "pill")  # the column shows a string calc, not a number
# a text cell whose label stands right of a 0 bar, at the cell's left edge (decisions/164): inside a bar Desktop drew
# the '▲ 12.3%' run black, its good / bad color lost; outside a bar a run keeps its color
OUTSIDE_CELL = ("delta",)
# spark (decisions/096): block glyphs from the lowest to the highest bar; the periods a trend can take
SPARK_GLYPHS = "▁▂▃▄▅▆▇█"
SPARK_LEVELS = ("day", "month", "quarter", "year")
SPARK_COUNT = (2, 12)
SPARK_LINE_COUNT = (2, 60)  # a line spark (decisions/153): one calc for all periods, not one per period
# pill (decisions/096): level colors -> the fill behind the label (the text color on all of them, contrast >= 4.5); a
# bar of MIN(1) on the fixed axis 0..1 fills the cell (Desktop rewrites a wider range back to 0..1 on re-save)
def pill_fill():
    return {"good": COLOR["good_fill"], "bad": COLOR["bad_fill"], "neutral": COLOR["track"], "warn": "#fdecc8"}


PILL_MARGIN = 0
BASED = ("tick", "delta")  # need 'base'
TOTAL_TEXT = ("delta", "share")  # text-like columns a registry total takes (decisions/109)
TOTAL_BARS = ("bar", "bar_inside")  # bar columns a registry total takes (decisions/081)
GUARDED = TOTAL_BARS + ("tick",)  # their bar 0 on a total row; a tick's line none there (decisions/134)
TOTAL_MARKS = ("rank", "track", "dot", "tick")  # take a total by their own rule (decisions/134)
DOT_RANGE = 10  # the dot's axis runs 0..DOT_RANGE, the dot at 1: near the left edge, its label right of it
# bar_inside (decisions/077): Desktop clips a label inside a bar at the bar's end. A value goes inside when its bar is
# at least INSIDE_FIT (its widest label + a pad each side) long. The bar's length is the value / its column's
# WINDOW_MAX times the longest bar; labels outside make Desktop keep room right of the longest bar: measured 171px pane,
# '52%' (32px) -> longest bar 125px, '52,0%' (45px) -> 113px; 250px pane -> 207px. LABEL_ROOM_PX is the room beyond
# the widest label, rounded up (measured 11-14px): the estimated bar is never longer than the drawn one.
LABEL_ROOM_PX = 20
INSIDE_K0 = "0.5"  # the share of the longest bar from which a value goes inside, until the pane's width is known
# A filled header (decisions/079): the column titles on a band of the HTML's th color. The band is the title zones
# themselves (margin 0, side by side), each with the fill and a padding: a text on its own fill keeps off its edge
# (decisions/070). The strip is one 9pt bold line (15px at 120 DPI) + the padding above and below, as the HTML's th
# (11.5px bold + 7px padding each side = 28px; the references' table headers 28-32).
HEADER_FILL_PX = 28


def is_registry(s):
    return s["type"] == "registry"


def repeated(s, dim):
    return f"{s['name']} · {dim}"


def expand(spec):
    """A registry with 'repeat': [dims] is a template (NovaCart Top 3 by channel / payment / country, Cutest Financial
    region / category / segment): one registry per dimension, '<name> · <dim>' with rows [dim] and the title
    '<title> **<dim>**'; its dashboard cell becomes a cell per dimension in the same row, each as wide. -> the spec
    itself when nothing repeats, else an expanded copy (build, expected, reconcile and lint all read this one). A
    spark without 'form' gets its form here (spark_forms)."""
    import copy
    from . import benchmark
    spec = benchmark.expand(spec)  # small multiples of a line over several measures (decisions/043)
    reps = {s["name"]: s for s in spec["sheets"] if is_registry(s) and "repeat" in s}
    if not reps:
        return spark_forms(spec)
    out = copy.deepcopy(spec)
    sheets = []
    for s in out["sheets"]:
        if s["name"] not in reps:
            sheets.append(s)
            continue
        if "rows" in s:
            raise ValueError(f"Registry '{s['name']}': 'repeat' gives the rows of each copy; remove 'rows'")
        if len(set(s["repeat"])) != len(s["repeat"]):
            raise ValueError(f"Registry '{s['name']}': 'repeat' names a dimension twice: {s['repeat']}")
        base = {k: v for k, v in s.items() if k != "repeat"}
        for d in s["repeat"]:
            title = (base["title"] + " " if base.get("title") else "") + f"**{d}**"
            sheets.append({**copy.deepcopy(base), "name": repeated(s, d), "rows": [d], "title": title})
    out["sheets"] = sheets

    def cells(row):
        new = []
        for cell in row:
            name = cell if isinstance(cell, str) else cell.get("sheet")
            if name in reps:
                new += [repeated(reps[name], d) if isinstance(cell, str) else {**cell, "sheet": repeated(reps[name], d)}
                        for d in reps[name]["repeat"]]
            elif isinstance(cell, dict) and "rows" in cell:
                new.append({**cell, "rows": [cells(r) for r in cell["rows"]]})
            else:
                new.append(cell)
        return new
    out["dashboard"]["grid"] = [cells(r) for r in out["dashboard"]["grid"]]
    return spark_forms(out)


def spark_forms(spec):
    """A spark without 'form' is a line where its registry takes one (decisions/164, the user's choice: a real mini
    chart; 153's rules: the last column, one row dimension, no totals or Top N), else block glyphs, the fallback
    (decisions/096). -> the spec itself when every spark has its form, else a copy with the forms written."""
    import copy
    from . import sparkline
    todo = [(i, j) for i, s in enumerate(spec["sheets"]) if is_registry(s)
            for j, c in enumerate(s.get("columns", [])) if style(c) == "spark" and "form" not in c.get("spark", {"form": 0})]
    if not todo:
        return spec
    out = copy.deepcopy(spec)
    for i, j in todo:
        s = out["sheets"][i]
        s["columns"][j]["spark"]["form"] = "line" if sparkline.can_line(s, j) else "glyphs"
    return out


def style(c):
    return c.get("style", "bar")


def header_fill(s):
    """(band color, title color) of a registry whose column titles stand on a band (decisions/079), else None. The
    title color is the spec's, otherwise white or dark, whichever contrasts more (as the shell's, decisions/029)."""
    from .shell import text_color  # shell -> colors -> registry
    h = s.get("header")
    return (h["color"].lower(), text_color(h).lower()) if h else None  # Desktop writes colors in lower case


def header_px(b, s):
    """Height of the strip of column titles: the theme's or the plain 20px; a filled one 28px (decisions/079)."""
    from . import theme
    px = theme.registry_header_px(b)
    return max(px, HEADER_FILL_PX) if header_fill(s) else px


def title_pad_px(s):
    """Width a column title needs beyond its text: Desktop's 2px, and the padding each side on a band."""
    return design.TITLE_PAD_PX + (2 * design.SPACE["zone_margin"] if header_fill(s) else 0)


def title_style(b, s):
    """(run attrs, zone-style kwargs) of a column title zone: on a band its fill, padding and contrasting color;
    otherwise the theme's title color (decisions/030) and no fill."""
    from . import theme
    fill = header_fill(s)
    if fill:
        return {"fontcolor": fill[1]}, {"padding": design.SPACE["zone_margin"], "background": fill[0]}
    return ({"fontcolor": theme.title_color(b)} if b.theme else {}), {}


def bar_color(s):
    """The registry's own bar color (bar_inside bars, the track's share) or the accent (decisions/079)."""
    return s.get("bar_color", COLOR["accent"]).lower()


def label(c):
    return c.get("label", c["measure"]["field"])


def _name(s, c, part):
    return f"{s['name']} · {label(c)} · {part}"


def cell_calc(s, c):
    return _name(s, c, "Cell")


def flag_calc(s, c):
    return _name(s, c, "Flag")


def rank_calc(s, c):
    return _name(s, c, "Rank")


def share_calc(s, c):
    return _name(s, c, "Share")


def rest_calc(s, c):
    return _name(s, c, "Track")


def inside_calc(s, c):
    return _name(s, c, "Inside")


def outside_calc(s, c):
    return _name(s, c, "Outside")


def pill_calc(s, c):
    return _name(s, c, "Pill")


def sign_calc(s, c):
    return _name(s, c, "Sign")


# shape "sign" (decisions/139): Tableau's built-in filled shapes, no image of ours (citizeenservicerequests)
SIGN_SHAPES = {"up": ":filled/triangle", "down": ":filled/down-triangle", "flat": ":filled/circle"}


def spark_calc(s, c):
    return _name(s, c, "Spark")


def spark_period_calc(s, c, i):
    return _name(s, c, f"Period {i + 1}")


def _inside_fit(a, k):
    return f"{a} > 0 AND {a} >= {k} * WINDOW_MAX({a})"


# ---- a total row under bar columns (decisions/081) -------------------------------------------------------------------
def totalled(s):
    """A registry with a total row: grand or subtotals (decisions/036)."""
    return bool(s.get("totals"))


def bar_calc(s, c):
    return _name(s, c, "Bar")


def row_calc(s, c):
    return _name(s, c, "Row")


def total_calc(s, c):
    return _name(s, c, "Total")


def guarded(s, c):
    """The column draws its bar from a row-guarded calc: a bar or tick column of a registry with a total row."""
    return totalled(s) and style(c) in GUARDED


def total_opts(c):
    return c.get("total", {})


def own_total_label(s, c):
    """The total row's number is a calc of its own (decisions/081): always on a bar_inside (its labels are calcs per
    row), on a bar when the total has its own format."""
    return guarded(s, c) and (style(c) == "bar_inside" or "format" in total_opts(c))


def color_calc(s, c):
    return _name(s, c, "Color")


def base_calc(s, c):
    return _name(s, c, "Base")


FLAG_STATES = ("Flagged", "Row", "Total")  # a highlight's flag under a total row (decisions/134)


def flag_formula(s, c, a):
    """A highlight's flag: true where the value crosses the threshold. Under a total row a string of three states,
    the total never flagged and colored apart (its shading, decisions/134): the flag on the total's value (a sum of
    rows) would compare it with a per-row threshold. A total that keeps its bar (total.bar) is a row's color."""
    op, x = threshold(c)
    if not totalled(s):
        return f"{a} {op} {x}"
    flagged, row, total = FLAG_STATES
    guard = bar_guard(s, c, a)
    kept = f'ELSEIF NOT ({is_row(s)}) THEN "{row}" ' if guard != is_row(s) else ""
    return f'IF NOT ({guard}) THEN "{total}" {kept}ELSEIF {a} {op} {x} THEN "{flagged}" ELSE "{row}" END'


def flag_buckets(s, c):
    """[(bucket, color)] of a highlight's flag: flagged in the 'bad' background, the rest in the column's own color;
    under a total row the total in its shading: a text cell's white bar would cover the pane's (decisions/072), a
    bar's 0 would draw a 1px line at the total's number (decisions/164)."""
    base = COLOR["cell_bar"] if style(c) == "bar" else COLOR["cell_text"]
    if not totalled(s):
        return [("true", COLOR["cell_bad"]), ("false", base)]
    flagged, row, total = FLAG_STATES
    return [(f'"{flagged}"', COLOR["cell_bad"]), (f'"{row}"', base), (f'"{total}"', COLOR["rule"])]


def fill_calc(s, c):
    return _name(s, c, "Fill")


def zero_filled(s, c):
    """A guarded bar without a highlight: colored by a fill calc, its 0 on a total row in the total's shading. Desktop
    draws a 0 bar as a 1px line of the bar's color, right at the total's number (decisions/081 tail, 164)."""
    return guarded(s, c) and "highlight" not in c


SUBTOTAL = "Subtotal"  # a fill calc's subtotal row: no shading there (totals.style), its 0 bar white


def _subtotalled(s):
    from . import totals
    return bool(totals.subs(s))


def fill_formula(s, c, a):
    _, row, total = FLAG_STATES
    sub = f'ELSEIF COUNTD([{s["rows"][0]}]) <= 1 THEN "{SUBTOTAL}" ' if _subtotalled(s) else ""
    return f'IF {bar_guard(s, c, a)} THEN "{row}" {sub}ELSE "{total}" END'


def fill_buckets(s, c):
    """[(bucket, color)] of a fill calc: a row the column's bar color, a 0 total the total's shading, a 0 subtotal
    the white of its unshaded row."""
    _, row, total = FLAG_STATES
    base = bar_color(s) if style(c) == "bar_inside" else COLOR["cell_bar"]
    return [(f'"{row}"', base)] + ([(f'"{SUBTOTAL}"', COLOR["cell_text"])] if _subtotalled(s) else []) + [
        (f'"{total}"', COLOR["rule"])]


def is_row(s):
    """True on a mark of one row, false on a total (grand or subtotal): every row dimension is one member there. A
    Null member counts 0 (COUNTD skips Nulls): still a row. A total over one member equals that row."""
    return " AND ".join(f"COUNTD([{d}]) <= 1" for d in s["rows"])


def bar_guard(s, c, a):
    """Where a guarded column draws its bar: on rows; with total.bar also a total no longer than the longest row bar."""
    r = is_row(s)
    if total_opts(c).get("bar"):
        dims = ", ".join(f"[{d}]" for d in s["rows"])
        r = f"({r}) OR {a} <= MAX({{INCLUDE {dims} : {a}}})"
    return r


def bar_formula(s, c, a):
    """The bar of a guarded column: the measure on rows, 0 on a total (its label stays, the column is not stretched);
    with total.bar the total keeps its bar when it is no longer than the longest row bar."""
    return f"IF {bar_guard(s, c, a)} THEN {a} ELSE 0 END"


def share_formula(a):
    """The measure over its grand total: a FIXED LOD sees every row of the source (context filters only), so neither a
    Top N nor a dimension filter changes the denominator (decisions/109). MAX of the single value makes it an aggregate."""
    return f"{a} / MAX({{FIXED : {a}}})"


def delta_calcs(s, c):
    return {"delta": _name(s, c, "Change"), "good": _name(s, c, "Change Good"), "bad": _name(s, c, "Change Bad")}


def base_label(c):
    b = c["base"]
    return b.get("label", b["field"])


def second_label(c):
    m = c["second"]
    return m.get("label", m["field"])


def threshold(c):
    """('<' | '>', number) of a highlighted column."""
    h = c["highlight"]
    return ("<", h["below"]) if "below" in h else (">", h["above"])


def agg(m, aggs):
    """The aggregate expression of a measure in a generated formula: SUM([Sales]), or [Calc] of an aggregate calc."""
    if m["field"] in aggs:
        return f"[{m['field']}]"
    return f"{m.get('agg', 'sum').upper()}([{m['field']}])"


def spark_periods(c):
    """The start dates of a spark's periods: 'count' of them from 'from', a day / month / quarter / year apart."""
    import datetime
    sp = c["spark"]
    d0 = datetime.date.fromisoformat(sp["from"])
    step = {"day": None, "month": 1, "quarter": 3, "year": 12}[sp["level"]]
    out = []
    for i in range(sp["count"]):
        if step is None:
            out.append(d0 + datetime.timedelta(days=i))
        else:
            m = d0.month - 1 + step * i
            out.append(datetime.date(d0.year + m // 12, m % 12 + 1, 1))
    return out


def spark_formulas(s, c, aggs):
    """[(name, formula)] of a spark column, in dependency order (decisions/096): a calc per period (the measure's
    aggregate over that period, 0 where it has no rows), the highest and the lowest of them, then the string: per
    period the glyph at (value - lowest) / (highest - lowest) of the glyph scale; all equal -> the middle glyph."""
    m, sp = c["measure"], c["spark"]
    if m["field"] in aggs:
        raise ValueError(f"Registry '{s['name']}', column '{label(c)}': a spark takes a field, not the aggregate "
                         f"calc '{m['field']}' (it is summed per period)")
    fn, cut = m.get("agg", "sum").upper(), f"DATETRUNC('{sp['level']}', [{sp['date']}])"
    out, names = [], []
    for i, d in enumerate(spark_periods(c)):
        names.append(spark_period_calc(s, c, i))
        out.append((names[-1], f"ZN({fn}(IF {cut} = #{d.isoformat()}# THEN [{m['field']}] END))"))
    ref = [f"[{n}]" for n in names]

    def extreme(name, op):  # IF p1 >= p2 AND p1 >= p3 ... THEN p1 ELSEIF ... ELSE p_last END
        branches = [f"{' AND '.join(f'{a} {op} {b}' for b in ref if b != a)} THEN {a}" for a in ref[:-1]]
        return name, "IF " + " ELSEIF ".join(branches) + f" ELSE {ref[-1]} END"
    hi, lo = extreme(_name(s, c, "Highest"), ">="), extreme(_name(s, c, "Lowest"), "<=")
    out += [hi, lo]
    top, bottom, n = f"[{hi[0]}]", f"[{lo[0]}]", len(SPARK_GLYPHS) - 1
    glyphs = " + ".join(
        f'MID("{SPARK_GLYPHS}", IIF({top} = {bottom}, {n // 2 + 1}, INT({n} * ({p} - {bottom}) / ({top} - {bottom}) '
        f'+ 0.5) + 1), 1)' for p in ref)
    out.append((spark_calc(s, c), glyphs))
    return out


def pill_formula(s, c, a):
    """IF a >= hi THEN "High" ELSEIF a >= mid THEN "OK" ELSE "Low" END: the levels from the highest; a null value is
    in no 'from' range, so it takes the lowest level."""
    lv = c["levels"]
    top = [f'{a} >= {_num(x["from"])} THEN "{x["label"]}"' for x in reversed(lv[1:])]
    return "IF " + " ELSEIF ".join(top) + f' ELSE "{lv[0]["label"]}" END'


def _num(v):
    return repr(int(v)) if float(v).is_integer() else repr(float(v))


def along(s):
    """compute_using of a rank (the inner row dimension: within the outer group; with Top N the rows are one list,
    decisions/144) and of a track's share (all rows)."""
    return (list(s["rows"]) if "top" in s else [s["rows"][-1]]), list(s["rows"])


def agg_calcs(spec, types, rows, params):
    """Names of the spec's aggregate calcs that a registry column shows (they are referenced as [Calc])."""
    from .formula import CalcSet
    used = {m["field"] for s in spec["sheets"] if is_registry(s) for c in s["columns"]
            for m in [c["measure"]] + [c[k] for k in ("base", "second") if k in c]}
    specs = spec.get("calcs", [])
    if not used & {c["name"] for c in specs}:
        return frozenset()
    cs = CalcSet(specs, types, rows, params)
    return frozenset(n for n in used if n in cs.calcs and cs.calcs[n].is_agg)


def _check_spark(col, c):
    import datetime
    sp = c["spark"]
    lo, hi = SPARK_LINE_COUNT if sp.get("form") == "line" else SPARK_COUNT  # a line: periods by a filter (153)
    if not lo <= sp["count"] <= hi:
        raise ValueError(f"{col}: spark.count {sp['count']} is outside {lo}..{hi} periods")
    try:
        d = datetime.date.fromisoformat(sp["from"])
    except ValueError:
        raise ValueError(f"{col}: spark.from '{sp['from']}' is not a date YYYY-MM-DD") from None
    start = {"day": True, "month": d.day == 1, "quarter": d.day == 1 and d.month % 3 == 1,
             "year": d.day == 1 and d.month == 1}[sp["level"]]
    if not start:
        raise ValueError(f"{col}: spark.from {sp['from']} is not the start of a {sp['level']} (it is the first "
                         f"period; DATETRUNC compares with period starts)")


def _check_levels(col, levels):
    if len(levels) < 2:
        raise ValueError(f"{col}: a pill needs at least 2 levels, got {len(levels)}")
    if "from" in levels[0]:
        raise ValueError(f"{col}: the lowest level has no 'from' (it takes everything below the next one)")
    froms = [x.get("from") for x in levels[1:]]
    if None in froms or froms != sorted(set(froms)):
        raise ValueError(f"{col}: every level above the lowest has 'from', strictly ascending, got {froms}")
    labels = [x["label"] for x in levels]
    if len(set(labels)) != len(labels):
        raise ValueError(f"{col}: pill levels need distinct labels, got {labels}")
    for x in levels:
        if x["color"] not in pill_fill():
            raise ValueError(f"{col}: pill color '{x['color']}' is not one of {', '.join(pill_fill())}")


def check(s):
    """Column options that belong to other styles, a missing base: errors with the column named."""
    where = f"Registry '{s['name']}'"
    if "top" in s and len(s["rows"]) != 1 and s.get("totals"):
        raise ValueError(f"{where}: Top N with a second row dimension takes no totals")
    tracks = [label(c) for c in s["columns"] if style(c) == "track"]
    if len(tracks) > 1:
        raise ValueError(f"{where}: one track column per registry (Measure Values is one per sheet), got {tracks}")
    for c in s["columns"]:
        st, col = style(c), f"{where}, column '{label(c)}'"
        if "highlight" in c and st not in ("bar", "text"):
            raise ValueError(f"{col}: highlight applies to bar and text columns, not {st}")
        if st in BASED and "base" not in c:
            raise ValueError(f"{col}: style '{st}' needs 'base' (the measure it compares with)")
        if "base" in c and st not in BASED:
            raise ValueError(f"{col}: 'base' applies to {', '.join(BASED)} columns, not {st}")
        if "of" in c and (st != "track" or totalled(s)):
            raise ValueError(f"{col}: 'of' applies to a track column without totals")
        if "with_value" in c and st != "share":
            raise ValueError(f"{col}: 'with_value' applies to share columns")
        if "second" in c and st != "text":
            raise ValueError(f"{col}: 'second' (a second line) applies to text columns")
        if "good" in c and st not in ("delta", "dot"):
            raise ValueError(f"{col}: 'good' applies to delta and dot columns")
        if "shape" in c and (st != "dot" or totalled(s)):
            raise ValueError(f"{col}: 'shape' applies to dot columns of a registry without totals")
        if "total" in c and not (totalled(s) and st in TOTAL_BARS):  # decisions/081
            raise ValueError(f"{col}: 'total' (the total row's bar and format) applies to {' and '.join(TOTAL_BARS)} "
                             f"columns of a registry with 'totals'")
        if total_opts(c).get("bar") and st == "bar_inside":  # decisions/081: golden snapshot, dark on the bar
            raise ValueError(f"{col}: a bar_inside total shows its number without a bar (on a total bar it would be "
                             f"dark on the bar color, or clipped white on a short one); total.bar is for bar columns")
        for opt, only in (("spark", "spark"), ("levels", "pill")):
            if opt in c and st != only:
                raise ValueError(f"{col}: '{opt}' applies to {only} columns, not {st}")
            if opt not in c and st == only:
                raise ValueError(f"{col}: style '{st}' needs '{opt}'")
        if st == "spark":
            _check_spark(col, c)
        if st == "pill":
            _check_levels(col, c["levels"])
        for m in [c["measure"]] + [c[k] for k in ("base", "second") if k in c]:
            if "table_calc" in m:
                raise ValueError(f"{col}: table calculations in registry columns are not supported yet")
    from . import sparkline
    sparkline.check(s, where)  # a line spark: the last column, one row dimension (decisions/153)


def calcs(spec, aggs=frozenset()):
    """Calc specs for every registry sheet: a dummy axis per text-like column, a flag per highlighted column, the
    rank, share and change calcs. aggs: names of the spec's aggregate calcs (referenced as [Calc])."""
    from . import sparkline
    spec, out = expand(spec), []
    for s in spec["sheets"]:
        if not is_registry(s):
            continue
        rank_along, share_along = along(s)
        for c in s["columns"]:
            st, m = style(c), c["measure"]
            a = agg(m, aggs)
            if sparkline.is_line(c):  # drawn on a sheet of its own (decisions/153)
                out += sparkline.calcs(s, c)
                continue
            if st in TEXT_CELL:
                out.append({"name": cell_calc(s, c), "formula": "MIN(0)" if st in OUTSIDE_CELL else "MIN(1)"})
            if "highlight" in c:
                out.append({"name": flag_calc(s, c), "formula": flag_formula(s, c, a)})
            elif zero_filled(s, c):  # a 0 total bar in the total's shading (decisions/164)
                out.append({"name": fill_calc(s, c), "formula": fill_formula(s, c, a)})
            fmt = _measure_format(spec, m)
            if guarded(s, c):  # the bar 0 on a total row (decisions/081)
                out.append({"name": bar_calc(s, c), "formula": bar_formula(s, c, a)})
            if st == "bar_inside":  # the value inside its bar or outside it, in the measure's format (decisions/077)
                fit = _inside_fit(f"[{bar_calc(s, c)}]" if guarded(s, c) else a, INSIDE_K0)
                row = f"{is_row(s)} AND " if guarded(s, c) else ""  # a total's number is its own calc (081)
                for name, cond in ((inside_calc(s, c), fit), (outside_calc(s, c), f"NOT ({fit})")):
                    out.append({"name": name, "formula": f"IF {row}{cond} THEN {a} END",
                                "compute_using": share_along, **({"format": fmt} if fmt else {})})
            if own_total_label(s, c):
                if st == "bar":  # the rows' number without the total's
                    out.append({"name": row_calc(s, c), "formula": f"IF {is_row(s)} THEN {a} END",
                                **({"format": fmt} if fmt else {})})
                tfmt = total_opts(c).get("format", fmt)
                out.append({"name": total_calc(s, c), "formula": f"IF NOT ({is_row(s)}) THEN {a} END",
                            **({"format": tfmt} if tfmt else {})})
            if st == "spark":
                out += [{"name": n, "formula": f} for n, f in spark_formulas(s, c, aggs)]
            if st == "pill":
                out.append({"name": pill_calc(s, c), "formula": pill_formula(s, c, a)})
            if st == "rank":  # blank on a total row: a total is not ranked among its rows (decisions/134)
                rank = f"IF {is_row(s)} THEN RANK({a}) END" if totalled(s) else f"RANK({a})"
                out.append({"name": rank_calc(s, c), "formula": rank, "compute_using": rank_along,
                            "format": "number"})
            if st == "share":  # of the whole source, not of the visible top N (decisions/109)
                out.append({"name": share_calc(s, c), "formula": share_formula(a), "format": "pct0"})
            if st == "track" and totalled(s):  # a total is its share of the source, 100 % on the grand (134)
                out.append({"name": share_calc(s, c), "formula": share_formula(a), "format": "pct0"})
                out.append({"name": rest_calc(s, c), "formula": f"1 - {share_formula(a)}", "format": "pct0"})
            elif st == "track":  # of the rows' total, or of the largest row (of: max, decisions/144)
                whole = f"WINDOW_MAX({a})" if c.get("of") == "max" else f"TOTAL({a})"
                out.append({"name": share_calc(s, c), "formula": f"{a} / {whole}", "compute_using": share_along,
                            "format": "pct0"})
                out.append({"name": rest_calc(s, c), "formula": f"1 - {a} / {whole}",
                            "compute_using": share_along, "format": "pct0"})
            if st == "dot" and "shape" in c:  # the sign as the status mark's shape and color (decisions/139)
                out.append({"name": sign_calc(s, c),
                            "formula": f'IF {a} > 0 THEN "up" ELSEIF {a} < 0 THEN "down" ELSE "flat" END'})
            if st == "dot" and totalled(s):  # the color scale of the rows: no color on a total (decisions/134)
                out.append({"name": color_calc(s, c), "formula": f"IF {is_row(s)} THEN {a} END",
                            **({"format": fmt} if fmt else {})})
            if st == "tick" and totalled(s):  # the line on the rows only (decisions/134)
                b_fmt = _measure_format(spec, c["base"])
                out.append({"name": base_calc(s, c), "formula": f"IF {is_row(s)} THEN {agg(c['base'], aggs)} END",
                            **({"format": b_fmt} if b_fmt else {})})
            if st == "delta":
                n, b = delta_calcs(s, c), agg(c["base"], aggs)
                up = c.get("good", "up") == "up"
                out.append({"name": n["delta"], "formula": f"({a} - {b}) / ABS({b})", "format": "percent"})
                out.append({"name": n["good"], "formula": f"IF [{n['delta']}] {'>=' if up else '<='} 0 THEN "
                                                         f"[{n['delta']}] END", "format": "delta"})
                out.append({"name": n["bad"], "formula": f"IF [{n['delta']}] {'<' if up else '>'} 0 THEN "
                                                        f"[{n['delta']}] END", "format": "delta"})
    return out


def _measure_format(spec, m):
    """The number format a measure is shown in: its calc's own (calcs[].format), else the field's (decisions/032);
    None for Tableau's automatic one."""
    calc_fmt = {c["name"]: c.get("format") for c in spec.get("calcs", [])}
    if m["field"] in calc_fmt:
        return calc_fmt[m["field"]]
    return formats.fields(spec, lambda _: "real").get(m["field"])


def parts(s, c):
    """What a column shows, for expected.py and reconcile: [(key, tags, measure spec or calc name, pct)].

    key: the column's entry in expected (the label; '<label> · <base>' for a tick's base, ...); the value is the
    measure's aggregate (a spec measure dict) or a generated calc's value (its name)."""
    st, lab, m = style(c), label(c), c["measure"]
    if st == "rank":
        return [(lab, [lab, "rank"], rank_calc(s, c), False)]
    if st in ("share", "track"):
        out = [(lab, [lab, m["field"], "share"], share_calc(s, c), True)]
        if c.get("with_value"):
            out.append((f"{lab} · value", [m.get("label"), m["field"]], m, False))
        return out
    if st == "delta":
        return [(lab, [lab, m["field"], "change"], delta_calcs(s, c)["delta"], True)]
    from . import sparkline
    if sparkline.is_line(c):  # the last period's value, the dot at the line's end (decisions/153)
        return [(lab, [lab, m["field"], "last"], sparkline.last_calc(s, c), False)]
    if st in STRINGS:  # the string the cell shows; a spark's period values are checked in its test
        return [(lab, [lab, m["field"], st], (spark_calc if st == "spark" else pill_calc)(s, c), False)]
    out = [(lab, [lab, m["field"]], m, False)]
    if st == "tick":  # under a total row the line's calc: none on a total (decisions/134)
        out.append((f"{lab} · {base_label(c)}", [base_label(c), c["base"]["field"]],
                    base_calc(s, c) if totalled(s) else c["base"], False))
    if "second" in c:
        out.append((f"{lab} · {second_label(c)}", [second_label(c), c["second"]["field"]], c["second"], False))
    return out


# ---- workbook (build.py) -------------------------------------------------------------------------------------------
def column(b, s, c):
    """A column's pane: {spec, style, x (Field on Columns, None for Measure Values), measure, flag, fields (for the
    dependencies), enc [(tag, Field)], label [(Field | str, run attrs)] or None, mark, color (mark-color) or None,
    names (Measure Values of a track) or None, axis (fixed min, max) or None, base (a tick's Field) or None}."""
    from .build import Field  # build imports this module
    from .tablecalc import is_table_calc
    st = style(c)
    m = b._measure(c["measure"])
    for f in [m] + [b._measure(c[k]) for k in ("base", "second") if k in c]:
        if is_table_calc(f.col):
            raise ValueError(f"Registry '{s['name']}', column '{label(c)}': '{f.col.calc.name}' is a table "
                             f"calculation; registry columns take other measures (rank and share are styles)")

    def calc(name, discrete=False):
        return Field(b.col(name), "agg", "user", discrete=discrete)

    cell = calc(cell_calc(s, c)) if st in TEXT_CELL else None
    col = dict(spec=c, style=st, x=cell or m, measure=m, flag=None, enc=[], label=None, mark="Bar",
               color=COLOR["cell_text"] if cell else COLOR["cell_bar"], names=None, axis=None, base=None,
               outside=None)
    if "highlight" in c:
        col["flag"] = calc(flag_calc(s, c), discrete=True)
        col["enc"].append(("color", col["flag"]))
    elif zero_filled(s, c):  # no 1px line of a 0 bar at the total's number (decisions/164)
        col["flag"] = calc(fill_calc(s, c), discrete=True)
        col["enc"].append(("color", col["flag"]))
    total = calc(total_calc(s, c)) if own_total_label(s, c) else None
    if guarded(s, c):  # the bar 0 on a total row; the number a label of its own (decisions/081)
        col["x"] = calc(bar_calc(s, c))
        if st == "bar" and total:  # the rows' number, then the total's in its format
            row = calc(row_calc(s, c))
            col["enc"] += [("text", row), ("text", total)]
            col["label"] = [(row, {}), (total, {})]
        elif st in ("bar", "tick"):
            col["enc"].append(("text", m))
    if st == "text":
        col["enc"].append(("text", m))
        if "second" in c:  # value, line break, the second measure 8pt muted (Data Quality Testing)
            sec = b._measure(c["second"])
            col["enc"].append(("text", sec))
            col["label"] = [(m, {}), ("Æ\n", {}), (sec, {"fontcolor": COLOR["muted"],
                                                        "fontsize": str(FONT["cell_second"])})]
    elif st == "rank":
        col["enc"].append(("text", calc(rank_calc(s, c))))
    elif st == "share":
        share = calc(share_calc(s, c))
        col["enc"].append(("text", share))
        if c.get("with_value"):  # "**21 %** (230)": the space ends the bold run (a run of a space alone is dropped)
            col["enc"].append(("text", m))
            col["label"] = [(share, {"bold": "true", "suffix": " "}), (m, {"fontcolor": COLOR["muted"],
                                                                           "prefix": "(", "suffix": ")"})]
    elif st == "bar_inside":  # the bar and the values that fit in it; the rest on a second layer (decisions/077)
        inside, outside = calc(inside_calc(s, c)), calc(outside_calc(s, c))
        col["enc"].append(("text", inside))
        col["color"] = bar_color(s)
        col["label"] = [(inside, {"bold": "true", "fontcolor": COLOR["cell_text"]})]
        if total:  # the total's number on its 0 bar, dark (081): on the second layer Desktop would keep room for it
            col["enc"].append(("text", total))
            col["label"].append((total, {"bold": "true", "fontcolor": COLOR["text"]}))
        col["outside"] = [outside]
    elif st == "track":  # the share and the rest to 100 %, stacked on one axis (no dual axis)
        col["x"], col["names"] = None, [calc(share_calc(s, c)), calc(rest_calc(s, c))]
        col["enc"].append(("color", "[:Measure Names]"))
        # Measure Values of real shares: Desktop writes the fixed axis as '0.0' .. '1.0' (decisions/065)
        col["color"], col["axis"] = None, (0.0, 1.0)
    elif st == "dot" and "shape" in c:  # a status mark: shape and color by the sign (decisions/139)
        sg = calc(sign_calc(s, c), discrete=True)
        col["enc"] += [("color", sg), ("shape", sg)]  # no label: Desktop draws a shape's on it; a text column says it
        col["mark"], col["color"], col["axis"] = "Shape", None, (0, 2)
    elif st == "dot":  # a dot near the left edge, colored by the measure, its value right of it (ER Referrals)
        col["enc"] += [("color", calc(color_calc(s, c)) if totalled(s) else m), ("text", m)]
        col["mark"], col["color"], col["axis"] = "Circle", None, (0, DOT_RANGE)
    elif st == "tick":
        # the line's value column on Detail: a measure on no shelf is dropped by Desktop, and the line with it
        # (decisions/065)
        col["base"] = calc(base_calc(s, c)) if totalled(s) else b._measure(c["base"])
        col["enc"].append(("lod", col["base"]))
    elif st == "delta":  # its label outside a 0 bar on a fixed 0..1 axis: at the left edge, in its color (164)
        col["axis"] = (0, 1)
        n = delta_calcs(s, c)
        good, bad = calc(n["good"]), calc(n["bad"])
        col["enc"] += [("text", good), ("text", bad)]
        col["label"] = [(good, {"fontcolor": COLOR["good_text"]}), (bad, {"fontcolor": COLOR["bad_text"]})]
    elif st == "spark":  # the glyph string in the accent color (the mark stays white)
        sp = calc(spark_calc(s, c), discrete=True)  # a string: Desktop writes [usr:...:nk], a :qk text stays empty
        col["enc"].append(("text", sp))
        col["label"] = [(sp, {"fontcolor": COLOR["accent"]})]
    elif st == "pill":  # the level's label on its fill: the bar of MIN(1) is the pill, colored by the level
        pl = calc(pill_calc(s, c), discrete=True)
        col["enc"] += [("color", pl), ("text", pl)]
        col["label"] = [(pl, {"bold": "true", "fontcolor": COLOR["text"], "fontsize": str(b.font["kpi_pill"])})]  # 8 in the card theme (089)
        col["color"], col["axis"] = None, (-PILL_MARGIN, 1 + PILL_MARGIN)
    shown = [col["x"], m if (st in ("bar", "text", "bar_inside", "tick", "dot") or c.get("with_value"))
             and not guarded(s, c) else None, col["flag"]]  # a guarded bar shows its calcs (decisions/081)
    col["fields"] = [f for f in shown if f] + [f for _, f in col["enc"] if not isinstance(f, str)] \
        + (col["names"] or []) + ([col["base"]] if col["base"] else []) + (col["outside"] or [])
    return col


def widths(cols, px):
    """Column widths in px: equal. Desktop draws the panes of one registry equally wide whatever their widths say
    (decisions/064: a narrower rank column put the titles off their columns), so the titles get the same widths."""
    return [px // len(cols)] * len(cols)


def row_header_px(b, d, s):
    """A row header column: its longest label and its bold title whole (decisions/064), the title on a band with
    its padding (decisions/079)."""
    title = b.shown(d.col)
    return max(design.row_header_fit_px(b.fields.labels(d.col), title),
               design.text_px(title, FONT["table_header"], bold=True) + title_pad_px(s))


# ---- what a column shows, for its width (decisions/064) -------------------------------------------------------------
def automatic(values):
    """The format Tableau's automatic one shows a column of numbers in, as a spec format (an upper bound): whole numbers
    from 100 up or when all are whole (a public book: 501 240, 828, 2 022), 4 decimals below 1 (0,1793, -0,0022), else 2."""
    big = max((abs(v) for v in values), default=0)
    d = 0 if big >= 100 or all(float(v).is_integer() for v in values) else 2 if big >= 1 else 4
    return {"type": "number", "decimals": d}


def _fmt(b, what, values):
    from .build import CalcColumn
    col = b._measure(what).col if isinstance(what, dict) else b.col(what)
    fmt = b.number_format(col)
    if fmt is None and isinstance(col, CalcColumn) and col.calc.fmt in ("percent", "delta", "delta_plain"):
        fmt = "percent"
    return fmt or automatic(values)


def total_keys(s):
    """The expected keys of a registry's total rows: the grand total's label, '<outer> | Total' (totals.registry)."""
    from . import totals
    grand = totals.label(s) if totalled(s) and totals.grand(s)[0] else None
    sub = totalled(s) and bool(totals.subs(s))
    return lambda key: key == grand or (sub and key.endswith(f" | {totals.SUB_LABEL}"))


def label_runs(b, s, c, rows_only=False):
    """Per row of the column, the label as Desktop draws it: [[(text, pt, bold)] per line]; [] for a track (no
    labels on its segments). A total row in its own format (decisions/081); rows_only: without the total rows."""
    st = style(c)
    if st == "track":
        return []
    marks = b.expected.get(s["name"], {})
    is_total = total_keys(s)
    shown = {key: what for key, _, what, _ in parts(s, c)}
    fmts = {key: _fmt(b, what, [r[key] for r in marks.values() if r.get(key) is not None])
            for key, what in shown.items() if st not in STRINGS}
    tfmt = total_opts(c).get("format") if own_total_label(s, c) else None
    lab, out = label(c), []
    for key_, row in marks.items():
        if rows_only and is_total(key_):
            continue
        own = tfmt if is_total(key_) else None

        def text(key, f=None):
            v = row.get(key)
            return "" if v is None else formats.render(v, f or (own if key == lab and own else fmts[key]))
        if st in STRINGS:  # the calc's string as it is
            line = [(row.get(lab) or "", st == "pill")]
        elif st == "delta":  # '▲ 12.3%': the sign glyph, then the change without its minus
            v = row.get(lab)
            line = [] if v is None else [(("▲ " if v >= 0 else "▼ ") + formats.render(abs(v), fmts[lab]), False)]
        elif st == "share" and c.get("with_value"):  # '**21%** (230)'
            line = [(text(lab) + " ", True), (f"({text(f'{lab} · value')})", False)]
        else:
            line = [(text(lab), st == "bar_inside")]
        lines = [[(t, b.font["kpi_pill"] if st == "pill" else FONT["table_header"], bold) for t, bold in line]]
        if "second" in c:
            lines.append([(text(f"{lab} · {second_label(c)}"), FONT["cell_second"], False)])
        out.append(lines)
    return out


def need_px(b, s, c):
    """(px, why) the narrowest pane that shows the column whole: Desktop's narrowest pane, the longest label, the
    bold title over it (decisions/064). A dot's label starts right of its dot (at 1 on its 0..10 axis)."""
    best = (design.REGISTRY_PANE_MIN_PX, f"Desktop's narrowest pane {design.REGISTRY_PANE_MIN_PX}px")
    title = label(c)
    t = design.text_px(title, FONT["table_header"], bold=True) + title_pad_px(s)
    if t > best[0]:
        best = (t, f"its title '{title}'")
    for lines in label_runs(b, s, c):
        for line in lines:
            w = sum(design.text_px(text, pt, bold) for text, pt, bold in line) + design.LABEL_PAD_PX
            if style(c) == "dot":
                w = math.ceil(w * DOT_RANGE / (DOT_RANGE - 1)) + design.STATUS_PX
            if w > best[0]:
                best = (w, f"its value '{''.join(text for text, _, _ in line)}'")
    return best


# a title run's fontalignment per cell text-align; never right (decisions/164: the user's rule, titles at the left,
# rarely centred)
TITLE_ALIGN = {"left": "0", "center": "1"}


def align(c):
    """The text-align of a column's cell, its title's too: a pill sits centred, everything else at the left
    (decisions/096, 164). A number right-aligned (126) stood right of a text cell's MIN(1) bar, which Desktop then
    shortened to keep room for it: the number off the column's right edge and its title, a highlight's fill left of
    it, not under it."""
    return "center" if style(c) == "pill" else "left"


def cell_align(c):
    """The text-align the cell rule writes, None for none: a dot's label then stands right of the dot, where Desktop
    puts a circle's label ('left' drew it centred on the dot, the dot over the number: '35●17'); a delta's right of
    its 0 bar, at the cell's left edge (decisions/164)."""
    return None if style(c) in ("dot",) + OUTSIDE_CELL else align(c)


def pill_palettes(b):
    """The color palettes of the registries' pills: level label -> fill (the card pill's way, kpi2.palettes)."""
    out = {}
    for s in b.worksheets:
        for c in s["columns"] if is_registry(s) else []:
            if style(c) == "pill":
                col = b.calc_cols[pill_calc(s, c)].name  # the datasource's own name of the calc (Calculation_...)
                out[f"[usr:{col}:nk]"] = (col, "User", [
                    (f'"{x["label"]}"', pill_fill()[x["color"]]) for x in c["levels"]])
    return out


def sign_palettes(b):
    """The status marks' colors (decisions/139): up good with good 'up' (bad with 'down'), down the other, flat muted."""
    out = {}
    for s in b.worksheets:
        for c in s["columns"] if is_registry(s) else []:
            if style(c) == "dot" and "shape" in c:
                col = b.calc_cols[sign_calc(s, c)].name
                up, down = (("good", "bad") if c.get("good", "up") == "up" else ("bad", "good"))
                out[f"[usr:{col}:nk]"] = (col, "User", [('"up"', COLOR[up]), ('"down"', COLOR[down]),
                                                         ('"flat"', COLOR["mark_muted"])])
    return out


def shape_maps(b):
    """{instance: [(bucket, shape)]} of the status marks: the datasource style's shape encodings."""
    out = {}
    for s in b.worksheets:
        for c in s["columns"] if is_registry(s) else []:
            if style(c) == "dot" and "shape" in c:
                col = b.calc_cols[sign_calc(s, c)].name
                out[f"[usr:{col}:nk]"] = [(f'"{k}"', v) for k, v in SIGN_SHAPES.items()]
    return out


def row_height_px(b, s, cols):
    """A registry row's height: a two-line cell 44px, the theme's 30px, a two-dimension registry's 22px (Desktop draws
    no label on a mark alone in its outer group lower, decisions/075), else Desktop's automatic 20px (not written)."""
    if any("second" in c["spec"] for c in cols):
        return REGISTRY_ROW_TWO_LINE_PX
    from . import sparkline
    if b.theme or sparkline.line_column(s):  # a line needs the height to show a shape (decisions/153)
        return design.TABLE_ROW_CARDS_PX
    return design.REGISTRY_ROW_NESTED_PX if len(s.get("rows", [])) == 2 else design.REGISTRY_ROW_PX


def scrollbar_px(b, s, cols, sheet_h_px):
    """SCROLLBAR_PX when the sheet's rows do not fit its height (it scrolls vertically), else 0."""
    return design.SCROLLBAR_PX if len(b.expected.get(s["name"], {})) * row_height_px(b, s, cols) > sheet_h_px else 0


def check_top_rows(b, s):
    """Top N keeps members of the first row dimension; a second one is a text beside it ('Type' of a 'Plant'): one
    member per first member in the data, else the top N rows would be more than N (decisions/144)."""
    if "top" not in s or len(s["rows"]) != 2:
        return
    first, second = s["rows"]
    value = lambda f, r: b.calcs.row_value(f, r) if f in b.calcs.calcs else r[f]  # noqa: E731  a row calc or a column
    seen = {}
    for r in b.prof.rows:
        k, v = value(first, r), value(second, r)
        if seen.setdefault(k, v) != v:
            raise ValueError(f"Registry '{s['name']}': Top N needs one row dimension (the members it keeps), or a "
                             f"second one with one value per '{first}': '{k}' has '{seen[k]}' and '{v}' of '{second}'")


def check_widths(b, s, cols, col_px, dim_px, sheet_h_px):
    """Every column holds its text in the width Desktop gives it, else the build fails naming the column: no
    horizontal scroll, no number cut at a pane's edge (decisions/064). A sheet whose rows do not fit its height
    scrolls vertically: its scrollbar takes SCROLLBAR_PX of the width, which the panes leave free (decisions/120:
    col_px is already the width less the scrollbar, divided equally)."""
    rows = len(b.expected.get(s["name"], {}))
    row_px = row_height_px(b, s, cols)
    shown = min(rows, design.REGISTRY_MIN_ROWS)  # decisions/066: a public book's State Wise got 10px, only its titles drew
    if sheet_h_px < shown * row_px:
        raise ValueError(f"Registry '{s['name']}': {sheet_h_px}px under its titles is too short for {shown} row(s) "
                         f"(needs {shown * row_px}px); give the cell more height")
    bar = scrollbar_px(b, s, cols, sheet_h_px)
    for c, px in zip(cols, col_px):
        if c["style"] == "bar_inside":
            inside_k(b, s, c["spec"], px)
        need, why = need_px(b, s, c["spec"])
        if px < need:
            raise ValueError(
                f"Registry '{s['name']}': {px}px per column is too narrow for column '{label(c['spec'])}' "
                f"(needs {need}px: {why}" + (f"; {bar}px go to the vertical scrollbar of {rows} rows" if bar else "")
                + f"; row headers {sum(dim_px)}px); give the cell more width or use fewer columns")


def inside_k(b, s, c, pane_px):
    """The share of the longest bar from which a bar_inside value fits in its bar (decisions/077), kept for
    thresholds(): its widest label + LABEL_PAD_PX each side over the longest bar, which is the pane less the room
    Desktop keeps for a label outside (the widest label + LABEL_ROOM_PX). A sheet in several zones keeps the largest."""
    label = max((sum(design.text_px(t, pt, bold) for t, pt, bold in line)
                 for lines in label_runs(b, s, c, rows_only=True) for line in lines), default=0)  # a total: outside
    longest = pane_px - label - LABEL_ROOM_PX
    k = (label + 2 * design.LABEL_PAD_PX) / longest if longest > 0 else 1.0
    k = min(1.0, math.ceil(k * 1000) / 1000)  # 1: only the longest bar's value inside, and only when it fits
    ks = b.__dict__.setdefault("registry_inside_k", {})
    ks[inside_calc(s, c)] = ks[outside_calc(s, c)] = max(k, ks.get(inside_calc(s, c), 0))
    return k


def thresholds(b, wb):
    """Each bar_inside calc's formula gets its column's share (inside_k) in place of INSIDE_K0, in the datasource and
    in every sheet's dependencies: the pane's width is known only once the dashboard is laid out, after the calcs are
    written."""
    ks = getattr(b, "registry_inside_k", {})
    for col in wb.iter("column"):
        k = ks.get(col.get("caption"))
        calc = col.find("calculation")
        if k is None or calc is None:
            continue
        old = f">= {INSIDE_K0} * WINDOW_MAX("
        calc.set("formula", calc.get("formula").replace(old, f">= {k:g} * WINDOW_MAX("))


def ref(b, f):
    return b.q(f) if isinstance(f, str) else b.q(f.name)


def x_ref(b, col):
    return b.q("[Multiple Values]") if col["x"] is None else b.q(col["x"].name)


def single_pane(cols):
    """One column on one axis (no bar_inside's second layer): Desktop keeps a single pane, id 1 without x-axis-name,
    no default pane and no width of its own; it filled the sheet right of the row headers (decisions/099)."""
    return len(cols) == 1 and not cols[0]["outside"]


def pane(b, pane_el, col, i):
    """Encodings of one column's pane (XSD order: encodings, customized-tooltip, customized-label, style)."""
    if col["enc"]:
        e = ET.SubElement(pane_el, "encodings")
        for tag, f in col["enc"]:
            ET.SubElement(e, tag, column=ref(b, f))


def shelf(b, col):
    """The column on Columns: its field, twice for a bar_inside (the second time the outside layer, decisions/077)."""
    return [x_ref(b, col)] * (2 if col["outside"] else 1)


def fold_axis(b, axis, cols):
    """A bar_inside's dual axis in the sheet's axis rule, as Desktop re-saved it (decisions/077): the fold (encoding
    class 1, synchronized: one field) before the other rules, the second axis hidden next to the first."""
    for col in cols:
        if not col["outside"]:
            continue
        f = x_ref(b, col)
        at = len(axis.findall("encoding"))
        axis.insert(at, ET.Element("encoding", {"attr": "space", "class": "1", "field": f,
                                                "field-type": "quantitative", "fold": "true", "scope": "cols",
                                                "synchronized": "true", "type": "space"}))
        first = next(e for e in axis.iterfind("format[@attr='display']") if e.get("field") == f)
        axis.insert(list(axis).index(first) + 1, ET.Element("format", {"attr": "display", "class": "1", "field": f,
                                                                       "scope": "cols", "value": "false"}))


def outside_pane(b, panes, col, pane_id):
    """The second layer of a bar_inside (x-index 1): a transparent bar labelled, at Desktop's automatic place right of
    its end, with the values too long for their bars in the text color (decisions/077). Its width follows the first
    layer's (the lab drew it the same without one). -> the next pane id."""
    if not col["outside"]:
        return pane_id
    from .ink import empty_tooltip
    pane_id += 1
    pane = ET.SubElement(panes, "pane", {"id": str(pane_id), "selection-relaxation-option":
                                         "selection-relaxation-allow", "x-axis-name": x_ref(b, col), "x-index": "1"})
    ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
    ET.SubElement(pane, "mark", {"class": "Bar"})
    enc = ET.SubElement(pane, "encodings")
    for f in col["outside"]:  # the short bars' values, a total's number (decisions/081)
        ET.SubElement(enc, "text", column=ref(b, f))
    empty_tooltip(pane)
    write_label(b, pane, {"label": [(f, {"bold": "true", "fontcolor": COLOR["text"]}) for f in col["outside"]]})
    mark = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", element="mark")
    for attr, value in [("mark-labels-show", "true"), ("mark-color", COLOR["cell_text"]), ("mark-transparency", "0")]:
        ET.SubElement(mark, "format", attr=attr, value=value)
    return pane_id


def reference_lines(b, default, cols):
    """The ticks: a per-cell line at the base on the column's axis (one mark per cell, its average is the base
    itself), in the sheet's default pane (after its mark), where Desktop keeps the lines of every axis
    (decisions/065: it moved one written in the column's pane there)."""
    z = 0
    for i, col in enumerate(cols, 1):
        if col["base"] is not None:
            z += 1
            ET.SubElement(default, "reference-line", {
                "axis-column": x_ref(b, col), "enable-instant-analytics": "true", "formula": "average",
                "id": f"refline{i}", "label-type": "none", "probability": "95", "scope": "per-cell",
                "value-column": b.q(col["base"].name), "z-order": str(z)})


def write_label(b, pane_el, col):
    """The column's own label: runs of fields (<[ds].[instance]>) and text, as Desktop's label editor writes them."""
    if not col["label"]:
        return
    ft = ET.SubElement(ET.SubElement(pane_el, "customized-label"), "formatted-text")
    for item, attrs in col["label"]:
        attrs = dict(attrs)
        pre, post = attrs.pop("prefix", ""), attrs.pop("suffix", "")
        text = item if isinstance(item, str) else f"<{b.q(item.name)}>"
        ET.SubElement(ft, "run", attrs).text = f"{pre}{text}{post}"


def measure_order(b, view, s, names):
    """A track's Measure Names sorted by hand, the rest first, the share last (decisions/016 form). Desktop stacks the
    first member on top, at the far end of the bar: the share last starts from zero (decisions/065 snapshot)."""
    if not is_registry(s):
        return
    sort = ET.SubElement(view, "manual-sort", column=b.q("[:Measure Names]"), direction="ASC")
    d = ET.SubElement(sort, "dictionary")
    for m in reversed(names):
        ET.SubElement(d, "bucket").text = f'"{b.q(m.name)}"'


def _scale(low, high, n=11):
    """n colors from low to high, as Desktop writes a custom sequential palette (ER Referrals: 11)."""
    a, z = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (low, high))
    return ["#" + "".join(f"{round(x + (y - x) * k / (n - 1)):02x}" for x, y in zip(a, z)) for k in range(n)]


def sheet_style(b, style, s, dims, cols):
    """Sheet rules of the v2 columns, in Desktop's order: two-line rows (cell height), the dot's color scale (mark),
    the tick's look (refline)."""
    from .colors import _rule
    two = any("second" in c["spec"] for c in cols)  # taller rows for the value and its second line
    from . import sparkline
    if two or (len(dims) == 2 and not b.theme) or (sparkline.line_column(s) and not b.theme):  # theme: 30px already
        rule = _rule(style, "cell", before=("header", "label", "mark", "pane", "worksheet", "gridline", "zeroline",
                                            "table-div"))
        h = rule.find(f"format[@attr='height'][@field='{b.q(dims[-1].name)}']")
        if h is None:
            h = ET.Element("format", attr="height", field=b.q(dims[-1].name))
            rule.insert(0, h)
        h.set("value", str(row_height_px(b, s, cols)))
    for c in cols:
        if c["style"] == "dot" and "shape" not in c["spec"]:  # ER Referrals: a custom ordered-sequential palette on the measure
            rule = _rule(style, "mark", before=("pane", "worksheet", "gridline", "zeroline", "table-div"))
            high = COLOR["good"] if c["spec"].get("good", "up") == "up" else COLOR["bad"]
            on = next(f for tag, f in c["enc"] if tag == "color")  # the measure, its row-guarded calc (134)
            enc = ET.SubElement(rule, "encoding", attr="color", field=b.q(on.name), type="custom-interpolated")
            pal = ET.SubElement(enc, "color-palette", custom="true", name="", type="ordered-sequential")
            for color in _scale(COLOR["dot_low"], high):
                ET.SubElement(pal, "color").text = color
    ticks = [(i, c) for i, c in enumerate(cols, 1) if c["base"] is not None]
    if ticks:
        rule = _rule(style, "refline", before=("gridline", "zeroline", "table-div"))
        for i, _ in ticks:
            for attr, value in [("fill-above", "#00000000"), ("fill-below", "#00000000"),
                                ("stroke-size", str(TICK_STROKE_PX)), ("line-visibility", "on"),
                                ("line-pattern-only", "solid"), ("stroke-color", COLOR["text"])]:
                ET.SubElement(rule, "format", attr=attr, id=f"refline{i}", value=value)


def palettes(b):
    """The track's Measure Names colors: share accent, the rest the track color (a workbook-wide map, as plan
    sheets): {bucket: color}."""
    out = {}
    for s in b.worksheets:
        if not is_registry(s):
            continue
        for c in s["columns"]:
            if style(c) == "track":
                out[f'"{b.q(_instance(b, share_calc(s, c)))}"'] = bar_color(s)
                out[f'"{b.q(_instance(b, rest_calc(s, c)))}"'] = COLOR["track"]
    return out


def _instance(b, name):
    from .build import Field
    return Field(b.col(name), "agg", "user").name


def _tracks(b):
    return [(s, c) for s in b.worksheets if is_registry(s) for c in s["columns"] if style(c) == "track"]


def measures(b):
    """Fields Desktop declares in the datasource for the track's Measure Names palette: the share and the rest, and
    the row dimensions they are computed along (decisions/065)."""
    from .build import Field
    out = [Field(b.col(n), "agg", "user") for s, c in _tracks(b) for n in (share_calc(s, c), rest_calc(s, c))]
    return out + [b._dim(d) for s, _ in _tracks(b) if not totalled(s) for d in along(s)[1]]


def instance_table_calc(b, ci):
    """The datasource column-instance of a track's share or rest carries its compute-using on the sheet (all rows):
    an instance without it is the default (Rows) one, and Desktop renames the sheet's to [usr:...:qk:1], which the
    palette does not map (decisions/065; the form of reflines.instance_table_calc)."""
    for s, c in _tracks(b):
        if totalled(s):  # a FIXED share, no table calc (decisions/134)
            continue
        if ci.get("column") in {f"[{b.col(n).name}]" for n in (share_calc(s, c), rest_calc(s, c))}:
            dims = [b.q(b._dim(d).name) for d in along(s)[1]]
            attrs = {"ordering-field": dims[0]} if len(dims) == 1 else {}
            tc = ET.SubElement(ci, "table-calc", {**attrs, "ordering-type": "Field"})
            if len(dims) > 1:
                for d in dims:
                    ET.SubElement(tc, "order", field=d)
            return
