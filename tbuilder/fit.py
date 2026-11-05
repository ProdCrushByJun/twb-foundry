"""Sheet fit on a dashboard: Standard / Fit Width / Fit Height / Entire View (decisions/068).

The fit is <zoom type='...'/> in the sheet's <viewpoint> of the dashboard window (no <zoom>: Standard). It is chosen
here from the finished XML: the builder writes it (Builder.windows) and the gate recomputes it from the packaged file
(gate.check_fit), both with this one rule.

The rule, from Desktop 2025.1 pictures (tests/fixtures/fit/*.png) and 21 reference books (752 of 803 dashboard sheets
in entire-view, tests/fixtures/fit_survey):
- Entire View fills the zone both ways: it stretches rows and columns, and squeezes them when they do not fit (20
  bars of 9px with overlapping labels, '##' in table cells narrower than their numbers).
- Standard keeps Desktop's own size of a row or column: a short bar list sits at the zone's top with empty space
  under it, a text sheet takes the size of its text and its alignment changes with the field's type.
- Fit Width / Fit Height fill one way and keep the Standard size (and a scrollbar) the other way.
So: a sheet without discrete headers (text, tiles, cards, line, area, scatter, maps, donut) is entire-view. A sheet
with discrete headers is entire-view when its rows and columns at their Standard size fit the zone; fit-width when
the rows do not (a long list scrolls at full width); fit-height when the columns do not; standard when neither does.

The counts of rows and columns come from the data: the combinations of the discrete fields' values in the source
rows (the domain, not the filtered marks: a filter only shortens the list), capped by a Top N on the field, plus
the total rows. A side whose count or size is unknown (a field the counter cannot read) allows both outcomes: the
gate accepts either, the builder takes entire-view.
"""
import re
from dataclasses import dataclass

EV, FW, FH, STD = "entire-view", "fit-width", "fit-height", "standard"
ROW_PX = 20  # a discrete row in Standard (bars 20px apart; REGISTRY_ROW_PX) unless the sheet sets its cell height
COL_PX = 20  # a bar's column in Standard (vertical bars 20px apart)
AXIS_PX = 30  # a horizontal axis: its ticks (bars: 30px under the last row)
AXIS_TITLE_PX = 25  # its title under the ticks ('Sales': 55px under the last row)
AXIS_W_PX = 50  # a vertical axis: its ticks and the gap to the plot
AXIS_TITLE_W_PX = 25  # its title, turned
TITLE_PX = 30  # the worksheet's own title in its zone (a dashboard without block headers)
HEADER_PX = 24  # the column header row of a text table / heatmap (HEATMAP_HEADER_PX)
FIELD_LABEL_PX = 20  # the field label row over the row headers
CELL_PAD_PX = 18  # a text column: its widest number + this (TABLE_CELL_PAD_PX)
SQUEEZE = 0.8  # Entire View may draw a bar's row (or column) this much of its Standard size: bars of 16px keep their
# 9pt labels apart, of 13px they touch (lab squeeze). Numbers on the marks (registry, table, labelled bars) overlap
# at 16px (nulls 'Subtotals'), a row with a height set (theme 30px, two-line 44px) is designed so, and a text
# column turns to '##': those keep their Standard size.
FULL = 100000
HEADER_PT = 9  # Desktop's header label font when the sheet sets none
LABEL_ROW = 1.6  # px of row per pt of its header label font: the font's px (4/3 a pt) and a fifth (lab squeeze: 9pt
# labels touch at 13px, keep apart at 16). Entire View squeezing rows under this overlaps them (golden_actions_v2
# Monthly Sales: 10pt months in ~12px rows, decisions/166); 10pt: 16px = SQUEEZE of ROW_PX, so it binds over 10pt
PLOT_MIN_PX = 20  # a chart's plot beside its axes and titles, at the least: Desktop 2025.1 draws nothing at 5px,
# the axes without marks at 10px, squashed marks at 15px, the marks and a tick label at 20px (decisions/101)

REF = re.compile(r"\[([^\[\]]+)\]\.\[([^\[\]]+)\]")


@dataclass
class Side:
    """One direction of a sheet in its zone: n discrete members (0: no discrete header that way), each unit px in
    Standard, reserve px of headers / axes / title; have: px of the zone inside its margins; squeeze: the share of
    unit Entire View may draw. None: unknown."""
    n: object
    unit: object
    reserve: object
    have: int
    squeeze: float = SQUEEZE

    def need(self):
        return None if None in (self.n, self.unit, self.reserve) else self.n * self.unit * self.squeeze + self.reserve

    def fits(self):
        if self.n == 0:
            return True
        need = self.need()
        return None if need is None else need <= self.have


def decide(rows, cols):
    """The fits allowed for a sheet, {zoom}: one when both sides are known."""
    out = set()
    for h in ([rows.fits()] if rows.fits() is not None else [True, False]):
        for w in ([cols.fits()] if cols.fits() is not None else [True, False]):
            out.add({(True, True): EV, (False, True): FW, (True, False): FH, (False, False): STD}[(h, w)])
    return out


def pick(allowed):
    """The builder's fit: the one allowed, entire-view when a count is unknown."""
    return EV if EV in allowed else sorted(allowed)[0]


def zoom_of(vp):
    z = vp.find("zoom")
    return STD if z is None else z.get("type")


# ---- facts from the XML ------------------------------------------------------------------------------------------
def refs(text):
    """[(datasource, instance)] of a shelf's text."""
    return REF.findall(text or "")


def discrete(ws, inst):
    """A field on a shelf draws headers (discrete), not an axis."""
    if inst == "Multiple Values" or inst.endswith("(generated)") or inst.endswith(":qk"):
        return False
    if inst.endswith(":nk") or inst.endswith(":ok") or inst == ":Measure Names":
        return True
    col = next((c for c in ws.iter("column") if c.get("name") == f"[{inst}]"), None)  # a group: its column itself
    return col is not None and col.get("role") == "dimension"


def _instance(ws, ds, inst):
    """(column, derivation) of an instance on the sheet."""
    for deps in ws.iter("datasource-dependencies"):
        if deps.get("datasource") != ds:
            continue
        for ci in deps.findall("column-instance"):
            if ci.get("name") == f"[{inst}]":
                return ci.get("column"), ci.get("derivation")
    return f"[{inst}]", "None"  # a group on the shelf as its column


def _top(ws, ds, inst, params):
    """N of a Top N filter on the field (the largest value of its parameter), or of a rank filter 1..N computed along
    it (top after the filters, decisions/086, 166); None without one."""
    for flt in ws.iter("filter"):
        if flt.get("column") != f"[{ds}].[{inst}]":
            continue
        end = flt.find("groupfilter[@function='end']")
        if end is not None:
            count = end.get("count", "")
            return int(count) if count.isdigit() else params.get(count)
    along = {f"[{ci.get('name')[1:-1]}]" for ci in ws.iter("column-instance")
             if (tc := ci.find("table-calc")) is not None and tc.get("type") == "Rank"
             and tc.get("ordering-field") == f"[{ds}].[{inst}]"}
    for flt in ws.iter("filter"):
        found = refs(flt.get("column"))
        if found and found[0][0] == ds and f"[{found[0][1]}]" in along:
            ranks = [m.get("member") for m in flt.iter("groupfilter") if m.get("function") == "member"]
            if ranks and all(r.isdigit() for r in ranks):
                return max(int(r) for r in ranks)  # a tie at N keeps more marks; the gate allows a row more or less
    return None


def param_max(root):
    """{'[Parameters].[X]': the largest value of a numeric parameter}: a Top N set by a parameter."""
    out = {}
    for ds in root.iter("datasource"):
        if ds.get("name") != "Parameters":
            continue
        for col in ds.findall("column"):
            values = [m.get("value") for m in col.iter("member")]
            rng = col.find("range")
            if rng is not None:
                values.append(rng.get("max"))
            nums = [float(v) for v in values if v and re.fullmatch(r"-?\d+(\.\d+)?", v)]
            if nums:
                out[f"[Parameters].{col.get('name')}"] = int(max(nums))
    return out


def _measure_names(ws, ds):
    """Members of the sheet's Measure Names filter (a KPI table shows a column each)."""
    for flt in ws.iter("filter"):
        if flt.get("column") == f"[{ds}].[:Measure Names]":
            return len(flt.findall(".//groupfilter[@function='member']"))
    return None


def members(ws, scope, count, params):
    """Discrete members along the rows / cols shelf, the combinations of its discrete fields' values with the total
    rows (a grand total, a subtotal per member of the outer field, decisions/036); 0 without one, None when the
    counter cannot tell."""
    table = ws.find("table")
    shelf = table.find(scope)
    fields = [(ds, inst) for ds, inst in refs(shelf.text if shelf is not None else "") if discrete(ws, inst)]
    if not fields:
        return 0
    totals = 1 if shelf.get("total") == "true" else 0
    for sub in table.findall("subtotals/column"):
        found = refs(sub.text)
        if found and found[0] in fields:
            ds, inst = found[0]
            m = count(ds, [_instance(ws, ds, inst)], [_top(ws, ds, inst, params)])
            if m is None:
                return None
            totals += m
    n, cols, caps = 1, [], []
    for ds, inst in fields:
        if inst == ":Measure Names":
            m = _measure_names(ws, ds)
            if m is None:
                return None
            n *= m
        else:
            cols.append((ds, *_instance(ws, ds, inst)))
            caps.append(_top(ws, ds, inst, params))
    if cols:
        sources = {ds for ds, _, _ in cols}
        got = (count(sources.pop(), [(c, d) for _, c, d in cols], caps, periods=scope == "rows") if len(sources) == 1
               else None)
        if got is None:
            return None
        n *= got
    return n + totals


def _formats(ws, element):
    return ws.findall(f"table/style/style-rule[@element='{element}']/format")


def _set(ws, element, attr, fields, how=max):
    """A size the sheet sets on one of the fields (cell height / width, header width / height), or None."""
    names = {f"[{ds}].[{inst}]" for ds, inst in fields}
    vals = [int(f.get("value")) for f in _formats(ws, element) if f.get("attr") == attr and f.get("field") in names]
    return how(vals) if vals else None


def _axes(ws, shelf):
    """(axes drawn, titles drawn) of the continuous fields along a shelf: an axis each unless hidden."""
    hidden = {f.get("field") for f in _formats(ws, "axis") if f.get("attr") == "display" and f.get("value") == "false"}
    untitled = {f.get("field") for f in _formats(ws, "axis") if f.get("attr") == "title" and f.get("value") == ""}
    shown = [r for r in (f"[{ds}].[{inst}]" for ds, inst in refs(shelf) if not discrete(ws, inst)) if r not in hidden]
    return len(shown), len([r for r in shown if r not in untitled])


def _shown(ws, fields):
    """The fields whose header labels show (a heatmap with a column margin hides its column header, 041)."""
    off = {f.get("field") for f in _formats(ws, "label") if f.get("attr") == "display" and f.get("value") == "false"}
    return [(ds, i) for ds, i in fields if f"[{ds}].[{i}]" not in off]


def _label_pt(ws, fields):
    """pt of the header labels of the fields (the largest a sheet sets), Desktop's own without one."""
    return _set(ws, "label", "font-size", fields) or HEADER_PT


def _field_labels(ws, scope):
    return not any(f.get("attr") == "display-field-labels" and f.get("scope") == scope and f.get("value") == "false"
                   for f in _formats(ws, "worksheet"))


def zone_px(zone, size):
    """(w, h) px of a zone inside its margins; size: the dashboard's (w, h) px."""
    from .gate import _box, _margins, _style
    _, _, w, h = _box(zone)
    m = {k: v or 0 for k, v in _margins(_style(zone)).items()}
    return w * size[0] // FULL - m["left"] - m["right"], h * size[1] // FULL - m["top"] - m["bottom"]


def sides(ws, zone, size, count, params, estimate=None):
    """(rows, cols) Sides of a worksheet in its dashboard zone. count(ds, [(column, derivation)], [Top N caps]) ->
    distinct combinations or None. estimate(sheet name) -> (row header px, column px) of a text sheet whose sizes
    the XML does not set (the builder's numbers), or None (the gate)."""
    have_w, have_h = zone_px(zone, size)
    table = ws.find("table")
    rows_t, cols_t = table.findtext("rows") or "", table.findtext("cols") or ""
    r_fields = [(ds, i) for ds, i in refs(rows_t) if discrete(ws, i)]
    c_fields = [(ds, i) for ds, i in refs(cols_t) if discrete(ws, i)]
    axes_c, titled_c = _axes(ws, cols_t)  # under (and over) the rows
    axes_r, titled_r = _axes(ws, rows_t)  # left (and right) of the columns
    down = (TITLE_PX if zone.get("show-title") != "false" else 0) + axes_c * AXIS_PX + titled_c * AXIS_TITLE_PX
    if _shown(ws, c_fields):
        down += _set(ws, "header", "height", c_fields) or HEADER_PX
    elif r_fields and not c_fields and _field_labels(ws, "rows"):
        down += FIELD_LABEL_PX
    est = estimate(ws.get("name")) if estimate else None
    across = axes_r * AXIS_W_PX + titled_r * AXIS_TITLE_W_PX
    if _shown(ws, r_fields) and c_fields:  # the row headers left of the columns
        head = _set(ws, "header", "width", r_fields, sum)
        across = across + head if head is not None else across + est[0] if est else None
    unit_c = _set(ws, "cell", "width", c_fields)
    bar = unit_c is None and axes_r > 0  # a bar's column; else a text column holding its numbers
    if unit_c is None:
        unit_c = COL_PX if bar else est[1] if est else None
    unit_r = _set(ws, "cell", "height", r_fields)
    labels = any(f.get("attr") == "mark-labels-show" and f.get("value") == "true" for f in ws.iter("format"))
    floor = max(SQUEEZE, _label_pt(ws, r_fields) * LABEL_ROW / (unit_r or ROW_PX))  # the labels keep apart
    rows = Side(members(ws, "rows", count, params), unit_r or ROW_PX, down, have_h,
                1 if unit_r or labels else floor)
    cols = Side(members(ws, "cols", count, params), unit_c, across, have_w, SQUEEZE if bar else 1)
    return rows, cols


def donut_legends(sheets):
    """A donut's legend parts, '<donut> · Dots' and '<donut> · Legend' beside its Pie sheet (decisions/069): they fill
    their zones row for row with each other, entire-view whatever their rows (a dot stays level with its text)."""
    pies = {n for n, w in sheets.items() if any(m.get("class") == "Pie" for m in w.iter("mark"))}
    return {f"{p} · {part}" for p in pies for part in ("Dots", "Legend")} & set(sheets)


def dashboard_fits(root, count, estimate=None):
    """{(dashboard, sheet): allowed fits} of every worksheet zone on a dashboard."""
    sheets = {w.get("name"): w for w in root.iter("worksheet")}
    params = param_max(root)
    legends = donut_legends(sheets)
    out = {}
    for db in root.iter("dashboard"):
        size = db.find("size")
        dims = (int(size.get("maxwidth") or size.get("minwidth")), int(size.get("maxheight") or size.get("minheight")))
        for z in db.find("zones").iter("zone"):
            name = z.get("name")
            if name not in sheets or z.get("type-v2"):
                continue
            allowed = {EV} if name in legends else decide(*sides(sheets[name], z, dims, count, params, estimate))
            key = (db.get("name"), name)
            out[key] = (out[key] & allowed or allowed) if key in out else allowed
    return out


# ---- the height of a chart (decisions/101) -----------------------------------------------------------------------
def chart_need(ws, zone, size):
    """(have, need) px of height of a chart's zone inside its margins: a sheet with an axis (a continuous field on
    rows or columns: line, area, bar, combo, scatter, a KPI card's history); None for another sheet (text, heatmap,
    map). need: what the rows side reserves under and over the plot (axes, their titles, column headers, the
    sheet's title) and PLOT_MIN_PX of plot. In less Desktop draws the axes without marks, or nothing at all
    (decisions/100, 101)."""
    fields = refs(ws.findtext("table/rows")) + refs(ws.findtext("table/cols"))
    if any(i.endswith("(generated)") for _, i in fields) or all(discrete(ws, i) for _, i in fields):
        return None
    if fields and all(_bar_across(ws, ds, i) for ds, i in fields):  # a KPI progress bar (decisions/155)
        return None
    rows, _ = sides(ws, zone, size, lambda *a, **k: None, {})
    return rows.have, rows.reserve + PLOT_MIN_PX


def _bar_across(ws, ds, inst):
    """The field's axis is fixed and hidden, or folded onto such an axis: no ticks or title to reserve, its bar
    drawn across the zone at any height (the pill / marker / progress bars of decisions/063, 155)."""
    ref = f"[{ds}].[{inst}]"
    rule = ws.find("table/style/style-rule[@element='axis']")
    if rule is None:
        return False
    enc = next((e for e in rule.findall("encoding") if e.get("field") == ref), None)
    hidden = any(f.get("attr") == "display" and f.get("field") == ref and f.get("value") == "false"
                 for f in rule.findall("format"))
    return hidden and enc is not None and (enc.get("range-type") == "fixed" or enc.get("fold") == "true")


def short_charts(root):
    """[(dashboard, sheet, have, need)] of the chart zones too short for Desktop to draw them."""
    sheets = {w.get("name"): w for w in root.iter("worksheet")}
    out = []
    for db in root.iter("dashboard"):
        size = db.find("size")
        dims = (int(size.get("maxwidth") or size.get("minwidth")), int(size.get("maxheight") or size.get("minheight")))
        for z in db.find("zones").iter("zone"):
            ws = sheets.get(z.get("name"))
            if ws is None or z.get("type-v2"):
                continue
            got = chart_need(ws, z, dims)
            if got and got[0] < got[1]:
                out.append((db.get("name"), z.get("name"), *got))
    return out


# ---- tails of the rule (decisions/093) ---------------------------------------------------------------------------
MAX_BAR_ROW_PX = 250  # Entire View draws a bar ~75% of its row: over this a few bars become fat slabs (nulls 'Group
# with Other': 2 bars of ~127px); not lab-calibrated: the builder refuses instead of scaling the mark size
MIN_LEGEND_ROW_PX = 16  # a donut legend's row (a 9pt text beside its dot); in less the text overlaps (20 members in
# 250px: 12px a row)
NARROW_NEAR, NARROW_FAR = 1.10, 2.5  # a table needing more than NEAR x its zone's width but less than FAR x: the zone is
# a miss (the builder's widths are estimates, so NEAR is their slack); a matrix far wider is a scroll by design


def _zones(root):
    """[(dashboard, zone, worksheet, (w, h))] of every worksheet zone on a dashboard."""
    sheets = {w.get("name"): w for w in root.iter("worksheet")}
    for db in root.iter("dashboard"):
        size = db.find("size")
        dims = (int(size.get("maxwidth") or size.get("minwidth")), int(size.get("maxheight") or size.get("minheight")))
        for z in db.find("zones").iter("zone"):
            if z.get("name") in sheets and not z.get("type-v2"):
                yield db.get("name"), z, sheets[z.get("name")], dims


def crowded(root, count, estimate=None):
    """[(kind, dashboard, sheet, have, limit)] of the zones where the fit rule's outcome draws badly (decisions/093):
    - 'fat': a bar sheet in Entire View whose bar rows (columns) stretch over MAX_BAR_ROW_PX each; have: px a row;
    - 'legend': a donut legend part whose rows are under MIN_LEGEND_ROW_PX each (Entire View squeezes them);
    - 'narrow': a text table / heatmap whose columns do not fit the zone at their own width, so Fit Height would
      scroll it sideways; have: the zone's px, limit: what the columns need. A bar's columns are not these.
    A side whose count is unknown is not judged."""
    sheets = {w.get("name"): w for w in root.iter("worksheet")}
    params, legends = param_max(root), donut_legends(sheets)
    out = []
    for dash, z, ws, dims in _zones(root):
        name = z.get("name")
        rows, cols = sides(ws, z, dims, count, params, estimate)
        if name in legends:
            if rows.n and rows.reserve is not None and (rows.have - rows.reserve) / rows.n < MIN_LEGEND_ROW_PX:
                out.append(("legend", dash, name, int((rows.have - rows.reserve) / rows.n), MIN_LEGEND_ROW_PX))
            continue
        if cols.fits() is False and cols.squeeze == 1 and cols.n:
            if cols.have * NARROW_NEAR < cols.need() <= cols.have * NARROW_FAR:
                out.append(("narrow", dash, name, cols.have, int(cols.need())))
            continue
        table = ws.find("table")
        if (any(m.get("class") in ("Bar", "Automatic") for m in ws.iter("mark")) and len(table.findall("panes/pane")) == 1
                and EV in decide(rows, cols)):  # a registry has a pane a column
            for side, other, shelf, size in ((rows, cols, "cols", "height"), (cols, rows, "rows", "width")):
                axis = any(not discrete(ws, i) for _, i in refs(table.findtext(shelf)))
                dims_ = [(ds, i) for ds, i in refs(table.findtext("rows" if shelf == "cols" else "cols"))
                         if discrete(ws, i)]
                if (side.n and not other.n and axis and side.reserve is not None
                        and _set(ws, "cell", size, dims_) is None):  # a set cell size is the author's
                    px = (side.have - side.reserve) / side.n
                    if px > MAX_BAR_ROW_PX:
                        out.append(("fat", dash, name, int(px), MAX_BAR_ROW_PX))
    return out


# ---- counting ----------------------------------------------------------------------------------------------------
def combos(rows, getters, caps):
    """Distinct combinations of the values the getters read from each row ('' is the Null member), each field
    capped by its Top N."""
    seen = {tuple(g(r) for g in getters) for r in rows}
    per = [len({k[i] for k in seen}) for i in range(len(getters))]
    capped = [p if c is None else min(p, c) for p, c in zip(per, caps)]
    n = len(seen)
    if capped != per:
        prod = 1
        for p in capped:
            prod *= p
        n = min(n, prod)
    return n


def table_counter(tables):
    """count() over text sources {datasource: (header, rows)} (gate._text_tables): plain columns only."""
    def count(ds, cols, caps, periods=False):
        if ds not in tables or any(d not in ("None", None) for _, d in cols):
            return None
        header, rows = tables[ds]
        names = [c[1:-1] for c, _ in cols]
        if any(n not in header for n in names):
            return None
        return combos(rows, [lambda r, i=header.index(n): r[i] for n in names], caps)
    return count


def builder_counter(b):
    """count() over the builder's data: CSV columns, row-level calcs and groups of its one source."""
    from . import dates
    from .build import TRUNC
    calcs = {c.calc.id: c for c in b.calc_cols.values()}
    levels = {d: p for p, (_, d) in TRUNC.items()}
    ranged = {f["field"] for s in [b.spec, *b.spec["sheets"]] for f in s.get("filters", []) if dates.is_date_filter(f)}
    groups = {g.name: g for g in b.group_cols.values()}
    csv_cols = {c.name for c in b.prof.columns}

    def getter(column):
        name = column[1:-1]
        if name in csv_cols:
            return lambda r: r[name]
        if name in calcs and not (calcs[name].calc.is_agg or calcs[name].calc.uses_view_lod):
            calc = calcs[name].calc.name
            return lambda r: b.calcs.row_value(calc, r)
        if name in groups:
            g = groups[name]
            if g.of_calc:  # a group over a calc (decisions/151)
                return lambda r: g.other if (v := b.calcs.row_value(g.source, r)) in (None, "") else g.value(v)
            return lambda r: g.value(r[g.source])
        return None

    def date_getter(column, derivation):
        """A date's periods (a bar's months, decisions/166); not under a range / relative filter, which cuts them."""
        name = column[1:-1]
        if name not in csv_cols or name in ranged or b.prof.col(name).datatype not in ("date", "datetime"):
            return None
        return lambda r: r[name] and dates.trunc(dates.to_date(r[name]), levels[derivation])

    def count(ds, cols, caps, periods=False):
        """periods: a date's periods count too (rows only: a year heatmap's columns stay unknown, their narrow tail
        of decisions/093 is not lab-checked)."""
        getters = [getter(c) if d in ("None", None) else date_getter(c, d) if periods and d in levels else None
                   for c, d in cols]
        return None if None in getters else combos(b.prof.rows, getters, caps)
    return count


def builder_estimate(b):
    """estimate(): the row header px and the widest number + CELL_PAD_PX of a text sheet (table, heatmap, KPI table)
    from the expected numbers in their formats (decisions/066 sizes text the same way)."""
    from . import design, formats, registry

    def estimate(name):
        s = b.part.get(name)
        if s is None:
            return None
        numbers = [x for v in b.expected.get(name, {}).values()
                   for x in (v.values() if isinstance(v, dict) else [v]) if isinstance(x, (int, float))]
        what = s.get("measure") or (s.get("measures") or [None])[0]  # a KPI table: its first measure's format
        if not (what and numbers):
            return None
        fmt = registry._fmt(b, what, numbers)
        col = max(design.text_px(formats.render(x, fmt), design.FONT["table_header"]) + CELL_PAD_PX for x in numbers)
        rows = s.get("rows")
        labels = b.fields.labels(b.col(rows if isinstance(rows, str) else rows[-1])) if rows else []
        return (design.row_header_fit_px(labels, "") if labels else 0), col
    return estimate
