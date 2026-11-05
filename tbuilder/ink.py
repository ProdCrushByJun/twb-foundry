"""Data-ink of labels and tooltips (todo 3.7, the design rules): no clipped label, and a tooltip
shows data, not the generated helper fields. Which labels repeat the block header is colors.repeats().

- Row header width: a bar's row field label that stays (the header does not name its field) gets a row header as
  wide as its longest value or the label with its sort indicator. Desktop sizes the column by the values and clips
  the label to 'Man..' / 'Cate..' (golden_colors, golden_actions before 3.7).
- Table columns: a text table whose column headers are longer than its numbers gets columns as wide as the
  headers (Desktop clipped 'Furniture' to 'Furnit..').
- Axis width: a vertical axis without its title is as wide as its longest tick, estimated from the expected
  numbers; at least AXIS_LABEL_W_PX (Desktop narrows it and clips the ticks to '1..', decision 016).
- Tooltips: a registry shows all its numbers on the cells, so its tooltip is empty (the reference's registries); a KPI
  card's value text too. On sheets with helper fields (highlight / good flags, the card's current period and
  latest date) the tooltip lists the data fields only, label grey and value bold as in Desktop's own tooltip.
"""
import math
import xml.etree.ElementTree as ET
from collections import defaultdict

from . import barlabels, colors, dates, formats, reflines
from .design import (AXIS_TITLE_W_PX, COLOR, FONT, SORT_ICON_CHARS, SORT_ICON_PX, TABLE_CELL_PAD_PX,
                     axis_px, field_label_px, row_header_fit_px, row_header_px, text_px)

PERCENT_CALCS = ("percent_of_total", "percent_difference")  # quick table calcs Tableau shows as a percentage
UNITS = ((1e9, "B"), (1e6, "M"), (1e3, "K"))  # Tableau's automatic axis units
AXIS_TICK_PT = 9  # the axis font (design.AXIS_LABEL_W_PX)
AXIS_TICK_PAD_PX = 6  # the tick mark and the gap before the plot, right of the tick text (decisions/170)


# ---- widths ------------------------------------------------------------------------------------------------------
def row_header(b, s, d):
    """px of a bar's row header column that also shows the field label: its longest value and the label with its
    sort indicator whole by the text metric (decisions/066); never narrower than the character estimate before."""
    caption = b.shown(d.col)  # the field label Desktop shows (decisions/073)
    sorted_ = s.get("sort", "none") != "none"
    labels = b.fields.labels(d.col)
    chars = row_header_px(max([len(caption) + (SORT_ICON_CHARS if sorted_ else 0)] + [len(v) for v in labels]))
    values = row_header_fit_px(labels, "", pt=FONT["bar_header"])  # the values at the bar header font (087)
    return max(chars, values, field_label_px(caption, SORT_ICON_PX if sorted_ else 0))


def table_cell(b, s, fields):
    """px of a text table's columns when a column header is longer than the numbers under it (Desktop sizes the
    columns by the numbers and clips the header to 'Furnit..'); None leaves Desktop's width. The header and the
    numbers as Desktop draws them (text metric, the field's format or the automatic one: decisions/066); never
    narrower than the character estimate before it."""
    from .registry import _fmt
    numbers = [x for x in b.expected.get(s["name"], {}).values() if x is not None]
    level = dates.heat_level(s)  # period columns: the header text is the period's (decisions/125)
    heads = (dates.period_labels(level, [r[s["cols"]] for r in b.prof.rows]) if level
             else b.fields.labels(fields[1].col))
    digits = max([len(f"{abs(x):,.1f}") + (x < 0) for x in numbers] or [0])  # generous: '18,840.0'
    header = max(len(v) for v in heads)
    chars = row_header_px(max(header, digits)) if header > digits else None
    fmt = _fmt(b, s["measure"], numbers) if numbers else None
    num_px = max([text_px(formats.render(x, fmt), FONT["table_header"]) + TABLE_CELL_PAD_PX for x in numbers] or [0])
    head_px = max(text_px(v, FONT["table_header"]) + TABLE_CELL_PAD_PX for v in heads)
    fit = head_px if head_px > num_px else None
    return max(chars or 0, fit or 0) or None


def axis_title(b, s, fields):
    """(title, px left of the plot) of a line / area's date axis whose title Desktop shows under the plot, else None.
    Desktop cuts the title to the plot's width ('Month of Orde..', a public book, decisions/066). The vertical axis left of
    the plot: our width when its title is hidden (colors.sheet_style), else its ticks and the title strip."""
    if s["type"] not in ("line", "area"):
        return None
    titles, _ = colors.repeats(b, s, fields)
    hidden = {scope for _, scope in titles}
    if "cols" in hidden:
        return None
    d = fields[0]
    caption = b.shown(d.col)  # the field label Desktop shows (decisions/073)
    level = s["date"].get("level", "month")
    title = f"{level.capitalize()} of {caption}" + year_suffix(b, s, level)
    return title, axis(b, s, fields[1]) + (0 if "rows" in hidden else AXIS_TITLE_W_PX)


def year_suffix(b, s, level):
    """' [2025]': Desktop adds the year to a date axis title below the year level when every mark is in one year
    ('Month of Order Date [2025]', golden_tablecalc_funcs, decisions/094); '' otherwise. The years are the expected
    keys' ('2025-03 | ...')."""
    if level == "year":
        return ""
    years = {key.split(" | ")[0][:4] for key in b.expected.get(s["name"], {})}
    return f" [{years.pop()}]" if len(years) == 1 and next(iter(years)).isdigit() else ""


def check_axis_title(b, s, zone_px):
    """The plot of a line / area holds its date axis title whole, else the build fails naming the sheet ('too narrow':
    rebuild's fitting widens the cell, decisions/060). zone_px: the sheet's zone inside its margins. Run at layout,
    after every sheet is built: the axis width needs the expected numbers."""
    fields = b.axis_fields.get(s["name"])
    t = axis_title(b, s, fields) if fields else None
    if t is None:
        return
    title, left = t
    need = field_label_px(title)
    if zone_px - left < need:
        raise ValueError(f"Sheet '{s['name']}': {zone_px - left}px of plot is too narrow for its axis title '{title}' "
                         f"(needs {need}px; the vertical axis takes {left}px); give the cell more width or name the "
                         f"axis in the block header")


COLUMN_LABEL_SHARE_DEN = 2  # a column narrower than 1/2 of its widest label is refused


def check_column_labels(b, s, zone_px):
    """A vertical bar's column labels (the text dimension's values) each fit their column, else the build fails naming
    the sheet: Tableau turns labels that do not fit on their side, and the block no longer reads at a glance
    (decisions/091). The plot is the zone less the axis and its title strip; a column is its n-th part. Up to half
    the label's width Desktop tilts the labels and they still read (specs/hr.json, test_fit); under half it does not."""
    if s["type"] != "bar" or s.get("orientation", "horizontal") != "vertical" or s.get("date_level"):
        return
    fields = b.shapes[s["name"]][0]
    d, m = fields[0], fields[1]
    if d.col.datatype != "string":
        return
    labels = b.fields.labels(d.col)
    titles, _ = colors.repeats(b, s, fields)
    plot = zone_px - axis(b, s, m) - (0 if any(scope == "rows" for _, scope in titles) else AXIS_TITLE_W_PX)
    column = plot // len(labels)
    need = max(text_px(v, FONT["bar_header"]) for v in labels) + TABLE_CELL_PAD_PX
    if column * COLUMN_LABEL_SHARE_DEN < need:
        widest = max(labels, key=len)
        raise ValueError(f"Sheet '{s['name']}': the columns are {column}px wide, the label '{widest}' needs {need}px; "
                         f"give the cell more width, shorten the label (fields.aliases) or draw the bars horizontally")


def _nice_up(v):
    """The smallest 1, 2 or 5 x 10^k >= v: no fewer digits than the top tick Tableau puts above v."""
    k = 10 ** math.floor(math.log10(v))
    return next(m * k for m in (1, 2, 5, 10) if m * k >= v)


def tick_chars(v, percent):
    """Characters of the longest tick of an axis reaching v (automatic format, one decimal assumed where Tableau
    may write one: '2,5K', '35,0%')."""
    if not v:
        return 1
    a = _nice_up(abs(v))
    if percent:
        text = f"{a * 100:.1f}%"
    else:
        unit = next(((u, n) for u, n in UNITS if a >= u), (1, ""))
        x = a / unit[0]
        text = (f"{x:.1f}" if x < 10 else f"{x:.0f}") + unit[1]
    return len(text) + (v < 0)


def _extent(b, s):
    """(lowest, highest) value of a sheet's axis from the expected numbers; stacked marks add up per position."""
    values = [(key.split(" | ")[0], x) for key, v in b.expected.get(s["name"], {}).items()
              for x in (v.values() if isinstance(v, dict) else [v]) if x is not None]
    if not (s["type"] in ("bar", "area") and colors.kind(s) != "plan" and colors.series_field(s)):
        return min([0] + [x for _, x in values]), max([0] + [x for _, x in values])
    neg, pos = defaultdict(float), defaultdict(float)  # stacked: per position (the key's first part)
    for p, x in values:
        (pos if x > 0 else neg)[p] += x
    return min([0, *neg.values()]), max([0, *pos.values()])


def axis(b, s, measure):
    """px of the sheet's vertical axis without its title."""
    fmt = b.number_format(measure.col)
    percent = formats.is_percent(fmt) or (measure.tc or {}).get("type") in PERCENT_CALCS
    fixed = reflines.axis_range(s)  # a fixed range: no tick beyond its ends (decisions/170)
    lo, hi = fixed or _extent(b, s)
    top = (lambda v: v) if fixed else (lambda v: _nice_up(abs(v)) * (-1 if v < 0 else 1))
    if fmt and not percent and not measure.tc:  # the field's own format (decisions/032)
        ticks = [formats.render(top(v), fmt, "en_US") if v else "0" for v in (lo, hi)]
        # whole by the text metric too: '100.0' is 5 characters but 40px at 9pt, wider than 5 characters' 36 ('10..')
        return max(axis_px(max(len(t) for t in ticks)), max(text_px(t, AXIS_TICK_PT) for t in ticks) + AXIS_TICK_PAD_PX)
    return axis_px(max(tick_chars(lo, percent), tick_chars(hi, percent)))


# ---- tooltips ----------------------------------------------------------------------------------------------------
def helpers(s, fields):
    """Fields of a sheet that only drive its look: meaning-color flags, the card's current flag and latest date, the
    value header of value_column left (the measure again)."""
    if s["type"] == "card_history":
        return fields[2:]
    k = colors.kind(s)
    flags = [f for f in fields if getattr(f.col, "caption", None) in (colors.highlight_calc(s), colors.good_calc(s),
                                                                      colors.below_calc(s))
             ] if k in ("highlight", "good", "below") else []
    value = [f for f in fields if f.name.endswith(":ok]")] if barlabels.value_left(s) else []  # Sales twice (095)
    return flags + reflines.helpers(s, fields) + value  # color vs avg, the measures behind a reference line


def _label(f):
    return getattr(f.col, "caption", f.col.name)


def empty_tooltip(pane):
    """No tooltip (the reference's registries): every number is already on the mark."""
    ET.SubElement(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), "formatted-text")


def tooltip(b, pane, s, fields):
    """A pane's tooltip where Desktop's default would show helper fields; nothing where the default is fine."""
    if s["type"] in ("card_value", "welcome", "card_pill", "card_marker", "period_line", "data_as_of", "button",
                     "insight_line", "card_status"):  # an insight line (decisions/045), a status dot (062)
        # all on the mark (the KPI v2 parts: decisions/037; a button of decisions/042)
        return empty_tooltip(pane)
    hs = helpers(s, fields)
    if not hs:
        return
    ft = ET.SubElement(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), "formatted-text")
    shown = sorted((f for f in fields if f not in hs), key=lambda f: f.kind == "agg")  # dimensions first
    for i, f in enumerate(shown):
        if i:
            ET.SubElement(ft, "run").text = "Æ\n"  # Tableau's line-break run
        ET.SubElement(ft, "run", fontcolor=COLOR["muted"]).text = f"{_label(f)}:\t"
        ET.SubElement(ft, "run", bold="true").text = f"<{b.q(f.name)}>"
