"""Distribution and time blocks (decisions/140): histogram, strip, beeswarm, calendar heatmap, bump chart.

Spec:
- histogram {field, bins: {size} | {count}}: a bar per bin of a numeric column, its height the count of rows;
- strip {measure, detail, dimension?}: a dot per member of detail (a row id) at its measure, a row per dimension
  member, spread up and down by a fixed jitter (INDEX() along detail: the same on every open, not RANDOM());
- beeswarm: a strip with bins {size}: the dots of a bin stack outward from the middle line (0, +1, -1, +2, ...);
- calendar {date, measure}: a square per day, weekday rows under month / week columns, the house sequential scale;
- bump {date: {field, level}, dimension, measure, highlight}: the rank of each member per period (RANK along the
  dimension), a line with a dot per period, rank 1 at the top, the highlighted members accent, the rest muted, the
  member's name at the line's end.

XML (forms from Desktop books):
- bin: <column ... role='dimension' type='ordinal'><calculation class='bin' decimals='0' formula='[X]' peg='0'
  size='N'/></column> on the shelf as [none:X (bin):ok] (HelpDesk RWFD 'DAYS OPEN': bins on Columns, a count on
  Rows, Bar); a bin's range '0–50' as a string calc nested under the hidden bin header, the headers horizontal
  (text-orientation 0), the bars without gaps: marks-scaling-off, size 0.94, a white stroke (HelpDesk 'DAYS OPEN');
- strip: Circle, the measure on Columns, INDEX() on Rows along the dot's id (Enterprise Risk 'Avg Days to Close Dot
  Plot'; RWFD Call Center 'Avg handle time': the id on Detail), the jitter axis hidden;
- calendar: Square with a date part on the shelf, [wd:date:ok] (Data Quality Testing "What's on weekends");
- bump: a reversed axis <encoding attr='space' ... reverse='true' type='space'/> (Data Quality Testing), Line with
  mark-markers-mode (Enterprise Risk, Broker Portfolio), line-end labels (SOC, decisions/043).
"""
import math
import xml.etree.ElementTree as ET

from . import heatmap
from .design import COLOR

HIST, STRIP, SWARM, CAL, BUMP = "histogram", "strip", "beeswarm", "calendar", "bump"
TYPES = (HIST, STRIP, SWARM, CAL, BUMP)
MARK = {HIST: "Bar", STRIP: "Circle", SWARM: "Circle", CAL: "Square", BUMP: "Line"}
SCALE = {"scale": "sequential"}
PHI = 0.618034  # the golden ratio's fraction: INDEX() * PHI mod 1 spreads the dots evenly, never in a column
BEFORE = {"label": ("pane", "table", "worksheet", "gridline", "zeroline", "table-div"),  # Desktop's rule order
          "table": ("worksheet", "refline", "gridline", "zeroline", "table-div"),
          "worksheet": ("gridline", "zeroline", "table-div")}
HEADER_MAX_PX = 220  # a strip's row headers: the longest name whole, up to this (decisions/172)
BAR_SIZE ="0.94453036785125732"  # HelpDesk 'DAYS OPEN': the bins touch, a white stroke between them
RANGE = "–"  # '0–50'
PARTS = {"month": ("mn", "Month"), "week": ("wk", "Week"), "weekday": ("wd", "Weekday")}  # date parts, discrete


def kind(s):
    return s["type"] if s["type"] in TYPES else None


def bin_name(field):
    return f"{field} (bin)"


def jitter_calc(s):
    return f"{s['name']} · Jitter"


def rank_calc(s):
    return f"{s['name']} · Rank"


def label_calc(s):
    return f"{s['name']} · Label"


def range_calc(s):
    return f"{s['name']} · Bin"


def _range_formula(s, bins, prof):
    """'0–50' of a histogram's bin; None for a fractional size or negative values (INT is not the bin's floor)."""
    c = bins[bin_name(s["field"])]
    vals = [float(r[c.source]) for r in prof.rows if r[c.source] not in (None, "")]
    if not isinstance(c.size, int) or min(vals, default=0) < 0:
        return None
    lo = f"INT([{c.source}] / {c.size}) * {c.size}"
    return f'STR({lo}) + "{RANGE}" + STR({lo} + {c.size})'


def has_range(b, s):
    return kind(s) == HIST and range_calc(s) in b.calc_cols


def highlight_calc(s):
    return f"{s['name']} · Highlight"


class BinColumn:
    """A bin of a numeric column, shaped like a profiled CSV column so Field can use it."""
    datatype, role = "integer", "dimension"

    def __init__(self, source, size):
        self.source, self.size, self.name = source, size, bin_name(source)
        self.caption = self.name

    def value(self, raw):
        return None if raw in (None, "") else int(math.floor(float(raw) / self.size) * self.size)


HIST_LABELS_MAX = 12  # more bins: the counts turn on their side over narrow bars (polish-26): none


def n_bins(b, s):
    """The bins a histogram draws: its expected bars (the sheet's filters kept, decisions/144), else from 0 (or the
    minimum) to the maximum of its column."""
    if kind(s) == HIST and b.expected.get(s["name"]):
        return len(b.expected[s["name"]])
    c = b.bin_cols[bin_name(_bin_field(s))]
    vals = [c.value(r[c.source]) for r in b.prof.rows if r[c.source] not in (None, "")]
    return len(set(vals))


def _bins(s):
    return s.get("bins") if kind(s) in (HIST, SWARM) else None


def _bin_field(s):
    return s["field"] if kind(s) == HIST else s["measure"]["field"]


def bin_columns(spec, prof):
    """name -> BinColumn of every histogram and beeswarm; bins {count} -> a round size over the column's range."""
    out = {}
    for s in spec["sheets"]:
        b = _bins(s)
        if not b:
            continue
        field = _bin_field(s)
        col = prof.col(field)
        if col.datatype not in ("integer", "real"):
            raise ValueError(f"Sheet '{s['name']}': bins need a numeric column; '{field}' is {col.datatype}")
        size = b.get("size")
        if size is None:
            vals = [float(r[field]) for r in prof.rows if r[field] not in ("", None)]
            step = (max(vals) - min(0, min(vals))) / b["count"]
            mag = 10 ** math.floor(math.log10(step)) if step > 0 else 1
            size = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= step)
        size = int(size) if float(size).is_integer() else size
        prev = out.get(bin_name(field))
        if prev and prev.size != size:
            raise ValueError(f"Sheet '{s['name']}': '{field}' is binned by {prev.size} elsewhere; one bin size per field")
        out[bin_name(field)] = BinColumn(field, size)
    return out


def column(parent, col):
    """<column> of a bin (HelpDesk 'Days Open (bin)'); None for other columns."""
    if not isinstance(col, BinColumn):
        return None
    el = ET.SubElement(parent, "column", {"aggregation": "None", "caption": col.caption, "datatype": "integer", "name": f"[{col.name}]",
                                          "role": "dimension", "type": "ordinal"})
    ET.SubElement(el, "calculation", {"class": "bin", "decimals": "0", "formula": f"[{col.source}]", "peg": "0",
                                      "size": str(col.size)})
    return el


def check(spec, prof):
    for s in spec["sheets"]:
        k = kind(s)
        if k in (STRIP, SWARM, HIST):
            f = _bin_field(s) if k != STRIP else s["measure"]["field"]
            if prof.col(f).datatype not in ("integer", "real"):
                raise ValueError(f"Sheet '{s['name']}': '{f}' must be a numeric column")
        if k == BUMP:
            col = prof.col(s["dimension"])
            missing = [v for v in s["highlight"] if v not in col.distinct]
            if missing:
                raise ValueError(f"Sheet '{s['name']}': highlight values {missing} are not in '{s['dimension']}'")


def _ref_names(s):
    """The bare <Field> references of a strip's tooltip phrase that are not the sheet's own fields."""
    import re
    own = {s["detail"], s.get("dimension"), s["measure"]["field"]}
    refs = [m.strip() for m in re.findall(r"<([^<>]+)>", s.get("tooltip") or "")]
    return [r for r in dict.fromkeys(refs) if r not in own and not re.match(r"^[A-Z]+\(", r)]


def tooltip_dim(b, s, ref):
    """The ATTR() Field of a tooltip dimension that is not on the strip's sheet (None if ref is not a dimension),
    after checking it is one value per dot (decisions/172). A plain dimension on Tooltip leaves the sheet blank in
    Desktop: its jitter, a table calc, needs it as ATTR([X]) -- [attr:X:nk] -- and runs along the id only
    (decisions/176)."""
    try:
        col = b.col(ref)
    except (ValueError, KeyError):
        return None
    calc = getattr(col, "calc", None)
    if getattr(col, "role", "dimension") != "dimension" or (calc is not None and (calc.is_agg or calc.table_calc)):
        return None

    def raw(c, name):  # the CSV columns a field's value is made of
        k = getattr(c, "calc", None)
        return list(k.raw_deps) if k is not None else [name]

    key, val = raw(b.col(s["detail"]), s["detail"]), raw(col, ref)
    seen = {}
    for r in b.prof.rows:
        if seen.setdefault(tuple(r[c] for c in key), tuple(r[c] for c in val)) != tuple(r[c] for c in val):
            raise ValueError(f"Sheet '{s['name']}' tooltip: <{ref}> has several values per '{s['detail']}': on the "
                             f"Tooltip shelf it would split the dots")
    f = b._dim(ref)
    f.name, f.derivation = f"[attr:{f.col.name}:nk]", "Attribute"
    return f


def calcs(spec, prof=None):
    """The jitter of a strip / beeswarm, the rank and the highlight flag of a bump, a histogram's bin range."""
    out = []
    bins = bin_columns(spec, prof) if prof is not None else {}
    for s in spec["sheets"]:
        k = kind(s)
        f = _range_formula(s, bins, prof) if k == HIST and bins else None
        if f:
            out.append({"name": range_calc(s), "formula": f})
        if k == STRIP:
            out.append({"name": jitter_calc(s), "formula": f"INDEX() * {PHI} - INT(INDEX() * {PHI})",
                        "compute_using": [s["detail"]]})
        elif k == SWARM:  # 1, 2, 3, ... in a bin -> 0, +1, -1, +2, -2, ...
            out.append({"name": jitter_calc(s), "formula": "IIF(INDEX() = 2 * INT(INDEX() / 2), 1, -1) * INT(INDEX() / 2)",
                        "compute_using": [s["detail"]]})
        elif k == BUMP:
            m = s["measure"]
            out += [{"name": rank_calc(s), "formula": f"RANK({m.get('agg', 'sum').upper()}([{m['field']}]))",
                     "compute_using": [s["dimension"]]},
                    {"name": highlight_calc(s),
                     "formula": " OR ".join(f'[{s["dimension"]}] = "{v}"' for v in s["highlight"])},
                    {"name": label_calc(s), "formula": f'IF [{highlight_calc(s)}] THEN [{s["dimension"]}] END'}]
    return out


def palettes(b):
    """A bump's highlight flag: accent / muted (build._palettes)."""
    out = {}
    for s in b.worksheets:
        if kind(s) == BUMP:
            col = b.calc_cols[highlight_calc(s)].name
            out[f"[none:{col}:nk]"] = (col, "None", [("true", COLOR["accent"]), ("false", COLOR["mark_muted"])])
    return out


def _part(b, field, part):
    from .build import Field
    f = Field(b.col(field), "date", "year", discrete=True)
    prefix, f.derivation = PARTS[part]
    f.name = f"[{prefix}:{f.col.name}:ok]"
    return f


def _bin(b, s):
    f = b._dim(bin_name(_bin_field(s)))
    f.name, f.type = f"[none:{f.col.name}:ok]", "ordinal"
    return f


def shape(b, s):
    """-> fields, rows, cols, encodings, labels, measure names (build.sheet_shape); a two-field shelf is written
    by shelves()."""
    from .build import Field
    k = kind(s)
    if k == HIST:
        d, n = _bin(b, s), Field(b.col(s["field"]), "agg", "count")
        fields = [d, n] + ([b._dim(range_calc(s))] if has_range(b, s) else [])
        return fields, n.name, d.name, [], n_bins(b, s) <= HIST_LABELS_MAX, None
    if k in (STRIP, SWARM):
        m = b._measure(s["measure"])
        j = b._measure({"field": jitter_calc(s)})
        det = b._dim(s["detail"])
        fields, enc = [m, j, det], [("lod", b.q(det.name))]
        if k == SWARM:
            bn = _bin(b, s)
            fields.append(bn)
            enc.insert(0, ("lod", b.q(bn.name)))
        if "dimension" in s:
            fields.append(b._dim(s["dimension"]))
        return fields, None, m.name, enc, False, None
    if k == CAL:
        m = b._measure(s["measure"])
        wd, mn, wk = (_part(b, s["date"], p) for p in ("weekday", "month", "week"))
        return [wd, mn, wk, m], wd.name, None, [("color", b.q(m.name))], False, None
    d = Field(b.col(s["date"]["field"]), "date", s["date"].get("level", "year"), discrete=True)
    r = b._measure({"field": rank_calc(s)})
    dim, hl, lab = b._dim(s["dimension"]), b._dim(highlight_calc(s)), b._dim(label_calc(s))
    enc = [("color", b.q(hl.name)), ("lod", b.q(dim.name)), ("text", b.q(lab.name))]
    return [d, r, dim, hl, lab], r.name, d.name, enc, False, None


def shelves(b, s, fields, rows_el, cols_el):
    """(dimension * jitter) on Rows of a strip; (month / week) on Columns of a calendar."""
    k = kind(s)
    if k in (STRIP, SWARM):
        j = b.q(fields[1].name)
        rows_el.text = f"({b.q(fields[3 + (k == SWARM)].name)} * {j})" if "dimension" in s else j  # '*' as Desktop saves it
    elif k == CAL:
        cols_el.text = f"({b.q(fields[1].name)} / {b.q(fields[2].name)})"
    elif has_range(b, s):  # (bin / '0–50'): the range under each bar, in the bins' order
        cols_el.text = f"({b.q(fields[0].name)} / {b.q(fields[2].name)})"


def _axis_rule(style):
    rule = style.find("style-rule[@element='axis']")
    if rule is None:
        rule = ET.Element("style-rule", element="axis")
        style.insert(0, rule)
    return rule


def _hide(style_el, rule, attrs):
    from .colors import _rule
    ET.SubElement(_rule(style_el, rule, before=BEFORE[rule]), "format", attrs)


def style(b, style_el, s, fields):
    """The hidden jitter axis, the reversed rank axis, the calendar's scale; no field labels over the headers (the
    block header names them, as combo 044), no week numbers over the calendar, no 'N nulls' under a bump."""
    k = kind(s)
    if k:
        scopes = {HIST: ("cols",), STRIP: ("rows",), SWARM: ("rows",), CAL: ("rows", "cols"), BUMP: ("cols",)}[k]
        for scope in scopes:
            _hide(style_el, "worksheet", {"attr": "display-field-labels", "scope": scope, "value": "false"})
    if k == HIST:
        ET.SubElement(_axis_rule(style_el), "format", {"attr": "title", "class": "0", "field": b.q(fields[1].name),
                                                       "scope": "rows", "value": "Count"})
        if has_range(b, s):  # the bin's own header hidden; the range horizontal when it fits: fit_zone
            _hide(style_el, "label", {"attr": "display", "field": b.q(fields[0].name), "value": "false"})
            b.hist_ranges[s["name"]] = (style_el, b.q(fields[2].name))
    elif k == CAL:
        _hide(style_el, "label", {"attr": "display", "field": b.q(fields[2].name), "value": "false"})
    elif k == BUMP:
        _hide(style_el, "table", {"attr": "show-null-value-warning", "value": "false"})
    if k in (STRIP, SWARM):
        ET.SubElement(_axis_rule(style_el), "format", {"attr": "display", "class": "0",
                                                       "field": b.q(fields[1].name), "scope": "rows",
                                                       "value": "false"})
        if "dimension" in s:
            _rows_apart(b, style_el, s)
    elif k == BUMP:
        rule = _axis_rule(style_el)
        r = b.q(fields[1].name)
        ET.SubElement(rule, "format", {"attr": "title", "class": "0", "field": r, "scope": "rows", "value": "Rank"})
        ET.SubElement(rule, "encoding", {"attr": "space", "class": "0", "field": r, "field-type": "quantitative",
                                         "reverse": "true", "scope": "rows", "type": "space"})
    elif k == CAL:
        heatmap.encoding(style_el, SCALE, b.q(fields[3].name), *heatmap.palette(SCALE))


def _rows_apart(b, style_el, s):
    """A strip with rows (decisions/172): the names whole in the header (the longest, up to HEADER_MAX_PX) and a
    1px rule between the rows, as the registry's outer groups (table-div level 1)."""
    from .barlabels import header_px
    from .colors import _rule
    dim = b._dim(s["dimension"])
    header = _rule(style_el, "header", before=("label", "mark", "pane", "worksheet", "gridline", "zeroline", "table-div"))
    ET.SubElement(header, "format", attr="width", field=b.q(dim.name), value=str(min(header_px(b, dim), HEADER_MAX_PX)))
    div = _rule(style_el, "table-div", before=())
    for f in div.findall("format[@scope='rows']"):
        div.remove(f)
    for attr, value in [("line-visibility", "on"), ("stroke-size", "1"), ("stroke-color", COLOR["rule"]),
                        ("line-pattern-only", "solid"), ("div-level", "1")]:
        ET.SubElement(div, "format", attr=attr, scope="rows", value=value)


def fit_zone(b, s, zone_w):
    """A histogram's ranges horizontal (HelpDesk text-orientation 0) when the longest fits its bin's column in the
    zone; else Desktop turns them on their side ('100–..' cut at 50px, decisions/144)."""
    if s["name"] not in b.hist_ranges:
        return
    from .design import TABLE_CELL_PAD_PX, text_px
    from .ink import axis
    style_el, ref = b.hist_ranges[s["name"]]
    size = b.bin_cols[bin_name(s["field"])].size
    widest = max(text_px(f"{int(k)}{RANGE}{int(k) + size}", b.font["table_header"]) for k in b.expected[s["name"]])
    n = n_bins(b, s)
    fields = b.shapes[s["name"]][0]
    if n <= HIST_LABELS_MAX and (zone_w - axis(b, s, fields[1]) - 20) / n >= widest + TABLE_CELL_PAD_PX:
        _hide(style_el, "label", {"attr": "text-orientation", "field": ref, "value": "0"})


def mark(pane_el, s):
    """After a histogram's <mark>: no scaling, the bars at their own size (HelpDesk 'DAYS OPEN')."""
    if kind(s) == HIST:
        ET.SubElement(pane_el, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})


def pane_style(pane, s):
    """A bump's dots on every point and its member's name at the line's end; white lines between calendar days and
    between a histogram's bins."""
    k = kind(s)
    if k not in (BUMP, CAL, HIST):
        return
    st = pane.find("style")
    if st is None:
        st = ET.SubElement(pane, "style")
    rule = st.find("style-rule[@element='mark']")
    if rule is None:
        rule = ET.SubElement(st, "style-rule", element="mark")
    formats = ([("mark-labels-show", "true"), ("mark-labels-mode", "line-ends"), ("mark-labels-line-first", "false"),
                ("mark-labels-cull", "true"), ("mark-markers-mode", "all")] if k == BUMP
               else [("size", BAR_SIZE)] * (k == HIST) + [("has-stroke", "true"), ("stroke-color", COLOR["card_bg"])])
    for attr, value in formats:
        ET.SubElement(rule, "format", attr=attr, value=value)


def expected(s, rows, dim, value, grouped, trunc, bins):
    """histogram: bin -> count; strip / beeswarm: (dimension,) id -> measure; calendar: day -> measure;
    bump: (period, member) -> rank (competition, the largest first)."""
    k = kind(s)
    if k == HIST:
        c = bins[bin_name(s["field"])]
        return grouped(rows, [dim(s["field"], lambda v: str(c.value(v)))], value({"field": s["field"], "agg": "count"}))
    if k in (STRIP, SWARM):
        keys = ([dim(s["dimension"])] if "dimension" in s else []) + [dim(s["detail"])]
        return grouped(rows, keys, value(s["measure"]))
    if k == CAL:
        return grouped(rows, [dim(s["date"], lambda v: trunc(v, "day"))], value(s["measure"]))
    level = s["date"].get("level", "year")
    sums = grouped(rows, [dim(s["date"]["field"], lambda v: trunc(v, level)), dim(s["dimension"])],
                   value(s["measure"]))
    period = lambda key: key.split(" | ")[0]  # noqa: E731  marks are keyed 'period | member'
    return {key: 1 + sum(1 for k2, v2 in sums.items() if period(k2) == period(key) and None not in (v, v2) and v2 > v)
            for key, v in sums.items()}
