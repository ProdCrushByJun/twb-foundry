"""Expected numbers per sheet, computed straight from the CSV or the Excel sheet (independent of the XML).

These are the reference values the workbook must show; the live reconciliation
compares them with what Tableau actually returns for each view.
"""
import contextlib
import copy
import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from . import benchmark, cards, colors, dates, excel, formats, heatmap, interact, kpi2, nav, params, reflines, registry, sparkline
from . import annotate, dualaxis, facetgrid, gantt, insight, maps, scatter, tablecalc, tables, totals, treemap, waterfall, distviz, compareviz, tilegrid, barinbar, pareto, funnel
from . import fields as fields_mod, filters as filters_mod, profile as profile_mod, spec as spec_mod
from .formula import CalcSet, View


def _num(v):
    return None if v == "" else float(v)


def _agg(values, how):
    vals = [v for v in values if v is not None and v != ""]
    if how == "count":
        return len(vals)
    if how == "countd":
        return len(set(vals))
    nums = [float(v) for v in vals]
    if not nums:
        return None
    if how == "median":
        from .compareviz import percentile
        return percentile(nums, 0.5)
    return {"sum": sum, "min": min, "max": max, "avg": lambda x: sum(x) / len(x)}[how](nums)


def _trunc(value, level):
    try:
        d = dates.to_date(value)  # the profiler's ISO date or datetime
    except ValueError:  # the expected values may be computed before the sheet's own date check
        raise ValueError(f"date_level needs a date; got '{value}'") from None
    if level == "year":
        return f"{d.year}"
    if level == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if level == "month":
        return f"{d.year}-{d.month:02d}"
    if level == "week":  # workbook date-options: start-of-week = monday
        return (d - dt.timedelta(days=d.weekday())).isoformat()
    return d.isoformat()


def _label(m, calcs):
    if m["field"] in calcs and calcs[m["field"]].is_agg:
        return f"AGG({m['field']})"  # Tableau's own caption for aggregate calcs
    return f"{m.get('agg', 'sum').upper()}({m['field']})"


NULL = "Null"  # the label of the empty member of a dimension (decisions/056)
_NULL_MEMBER = "\0Null"  # the empty member as a key of the Top N ranking (no data value can equal it)


def axis(fn):
    """Mark a key as a continuous date axis: an empty date makes no mark there (Tableau shows 'N nulls' instead),
    while an empty member of a discrete dimension is a mark of its own, 'Null' (decisions/056)."""
    fn.axis = True
    return fn


def is_mark(r, keys):
    """Does the row make a mark of the sheet? Only an empty date of a continuous axis keeps it out."""
    return not any(getattr(fn, "axis", False) and fn(r) in (None, "") for _, fn in keys)


def _rank_one(fields, name, v):
    """Sort key of one member. Null (Desktop 2025.1, decisions/056): first in the alphabetic order, last after a
    manual order (fields.<name>.order)."""
    if v is None:
        manual = fields and fields.props.get(name, {}).get("order")
        return (1, ()) if manual else (-1, ())
    return (0, fields.rank(name, v) if fields else v)


def _grouped(rows, keys, value, tc=None, fields=None):
    """keys: [(field, row -> str|None)]; value: (mark rows, View) -> number.

    An empty member is a mark of its own, 'Null', placed after the values; an empty date of a continuous axis
    (keys made with axis()) makes no mark (decisions/056). The View (sheet dims + rows) is what
    INCLUDE/EXCLUDE LODs are evaluated against. tc: optional quick table calc on the measure, or a calc with table
    calc functions (type 'formula', tablecalc.expected).
    fields: the spec's field properties (decisions/033): marks in each field's manual order, keyed by the labels
    Tableau shows (aliases); without them, by the values.
    """
    rows = [r for r in rows if is_mark(r, keys)]
    view = View(keys, rows)
    groups = defaultdict(list)
    for r in rows:
        key = tuple(None if v == "" else v for v in (fn(r) for _, fn in keys))
        groups[key].append(r)
    formula = tc and tc["type"] == "formula"  # its value exists only over the partition (decisions/034)
    values = {k: None if formula else value(v, view) for k, v in groups.items()}
    names = [n for n, _ in keys]

    def rank(k):
        return tuple(_rank_one(fields, n, v) for n, v in zip(names, k))
    if tc:
        values = _table_calc(values, groups, names, tc, value, view, rank)

    def shown(k):
        return [NULL if v is None else fields.shown(n, v) if fields else v for n, v in zip(names, k)]
    return {" | ".join(shown(k)): values[k] for k in sorted(groups, key=rank)}


def _zn(v):
    return 0 if v is None else v


def _table_calc(values, groups, names, tc, value, view, rank):
    """Quick table calc over the marks, partitioned by the sheet dims that are not 'along'.

    percent_of_total = SUM/TOTAL(SUM) (TOTAL re-aggregates the partition's rows),
    difference = ZN(SUM) - LOOKUP(ZN(SUM), -1), percent_difference = that / ABS(LOOKUP(...)),
    running_total = RUNNING_SUM(SUM); marks ordered by the 'along' dims within a partition.
    formula: a calc with table calc functions, evaluated over each partition's marks (formula.CalcSet.table_values).
    """
    along = tc.get("along") or names
    a_idx = [names.index(n) for n in along]
    p_idx = [i for i in range(len(names)) if i not in a_idx]
    parts = defaultdict(list)
    for k in values:
        parts[tuple(k[i] for i in p_idx)].append(k)
    out = {}
    for marks in parts.values():
        marks.sort(key=lambda k: tuple(rank(k)[i] for i in a_idx))
        t = tc["type"]
        if t == "formula":
            out.update(zip(marks, tc["values"]([groups[k] for k in marks], view)))
        elif t == "percent_of_total":
            total = value([r for k in marks for r in groups[k]], view)
            for k in marks:
                out[k] = None if values[k] is None or not total else values[k] / total
        elif t == "running_total":
            acc = None
            for k in marks:
                if values[k] is not None:
                    acc = values[k] if acc is None else acc + values[k]
                out[k] = acc
        else:
            prev = None
            for i, k in enumerate(marks):
                if i == 0:
                    out[k] = None
                elif t == "difference":
                    out[k] = _zn(values[k]) - _zn(prev)
                else:
                    out[k] = None if _zn(prev) == 0 else (_zn(values[k]) - _zn(prev)) / abs(_zn(prev))
                prev = values[k]
    return out


def parts(spec, base_dir):
    """[(sub-spec, data path, profile)] of each data source (decisions/083: spec.split); one for a spec with a single
    datasource. base_dir: the spec's folder."""
    base, profs = Path(base_dir), {}

    def load(ds):
        if ds["path"] not in profs:
            profs[ds["path"]] = excel.load(base / ds["path"], ds)
        return profs[ds["path"]]
    return [(sub, base / ds["path"], load(ds))
            for ds, sub in spec_mod.split(spec, lambda ds: [c.name for c in load(ds).columns])]


def profile(spec, base_dir):
    """The data's profile; for several datasources (decisions/083) their columns merged by name, a text column with
    the values it has in any source, and no rows (what reconcile reads: names, values)."""
    ps = [p for _, _, p in parts(spec, base_dir)]
    if len(ps) == 1:
        return ps[0]
    cols = {}
    for p in ps:
        for c in p.columns:
            if c.name not in cols:
                cols[c.name] = profile_mod.Column(c.name, c.datatype, list(c.distinct), c.date_format)
            elif c.datatype == cols[c.name].datatype == "string":
                cols[c.name].distinct = sorted(set(cols[c.name].distinct) | set(c.distinct))
    return profile_mod.Profile(Path(base_dir), list(cols.values()), [], ps[0].locale)


def data_path(spec, base_dir):
    """What compute() takes as csv_path: the data file, or the spec's folder for a spec with several datasources."""
    return Path(base_dir) if "datasources" in spec else Path(base_dir) / spec["datasource"]["path"]


def compute(spec, csv_path, values=None, where=None, prof=None):
    """csv_path: the data (data_path); a spec with several datasources (decisions/083) is computed source by source,
    csv_path its folder, every sheet under its name.
    values: parameter values to compute at ({name: value}); default: each parameter's default.
    where: {filter field: values selected in its card}; default: the selection the workbook opens with (the spec's
    filter default, else (All)).
    prof: the data's profile when the caller already has it (profiling a large CSV twice doubles time and memory).

    Tableau's order of operations: context filters -> FIXED LOD and Top N -> the other filters (decisions/035):
    FIXED and Top N see the context rows, the marks the rows after all filters."""
    with formats.shown_in(formats.workbook_locale(spec)):  # the same numbers whoever asks (decisions/085, 179)
        if _cache is None:
            return _compute(spec, csv_path, values, where, prof)
        key = _key(spec, csv_path, values, where)
        if key not in _cache:
            _cache[key] = _compute(spec, csv_path, values, where, prof)
        return copy.deepcopy(_cache[key])


_cache = None  # {key: numbers} while cached() is on
# what a dashboard has that the numbers do not read: its layout. The grid counts only as the set of its sheets
# (a dashboard's filter applies to its sheets, decisions/071; a switch's card goes where the switch is)
_LAYOUT = ("grid", "row_heights", "height")


@contextlib.contextmanager
def cached():
    """Within it compute() computes a spec once: rebuild checks the same sheets in some 60 layouts (_fit), and the
    numbers do not depend on the layout (_key)."""
    global _cache
    outer = _cache
    _cache = {} if outer is None else outer
    try:
        yield
    finally:
        _cache = outer


def _key(spec, csv_path, values, where):
    from .build import _leaves

    def plain(o):
        return sorted(o, key=str) if isinstance(o, (set, frozenset)) else str(o)

    def dash(d):
        if not isinstance(d, dict) or "grid" not in d:
            return d
        return {**{k: v for k, v in d.items() if k not in _LAYOUT},
                "sheets": sorted({json.dumps(x, sort_keys=True, default=plain) for x in _leaves(d["grid"])})}
    view = dict(spec)
    if "dashboard" in view:
        view["dashboard"] = dash(view["dashboard"])
    if "dashboards" in view:
        view["dashboards"] = [dash(d) for d in view["dashboards"]]
    p = Path(csv_path)
    data = (str(p.resolve()),) + ((p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else ())
    # no selection is the opening one (filters.selection)
    return json.dumps([view, data, values, where or None], sort_keys=True, default=plain)


def _compute(spec, csv_path, values, where, prof):
    if "datasources" in spec:  # each source's sheets on its own data; a filter field's selection in its source
        return {k: v for sub, path, p in parts(registry.expand(spec), csv_path)
                for k, v in compute(sub, path, values, where, p).items()}
    spec = nav.primary(spec)  # several dashboards share the sheets; the shell is the first's (decisions/040)
    spec = registry.expand(spec)  # a registry template over several dimensions (decisions/039)
    prof = prof or excel.load(csv_path, spec["datasource"])  # the same reading as the build
    pars = params.load(spec, {c.name for c in prof.columns}, values, prof)
    # range / relative dates: the dates kept (tbuilder/dates.py), same anchor as the build; a filter of values:
    # the selection, (All) drops the nulls
    fcalc = filters_mod.calc_values(spec, prof, pars)  # filters on calcs (decisions/057)
    context_rows, rows = filters_mod.split_rows(spec, prof, where, fcalc)
    types = {c.name: c.datatype for c in prof.columns}
    aggs = registry.agg_calcs(spec, types, context_rows, pars)
    calcs = CalcSet(spec.get("calcs", []) + cards.calcs(spec) + registry.calcs(spec, aggs) + colors.calcs(spec)
                    + kpi2.calcs(spec) + interact.calcs(spec) + benchmark.calcs(spec) + dualaxis.calcs(spec)
                    + scatter.calcs(spec) + treemap.calcs(spec) + insight.calcs(spec) + waterfall.calcs(spec) + funnel.calcs(spec) + pareto.calcs(spec)
                    + distviz.calcs(spec, prof) + compareviz.calcs(spec, types) + annotate.calcs(spec) + gantt.calcs(spec)
                    + facetgrid.calcs(spec, prof) + tilegrid.calcs(spec) + heatmap.calcs(spec),
                    types, context_rows, pars)  # FIXED ignores other filters
    rows = interact.period_rows(spec, calcs, rows)  # a period switch: a dimension filter (decisions/042)
    fp = fields_mod.Fields(spec, prof)  # aliases, order, groups (decisions/033)

    def dim(name, fn=lambda v: v, on_axis=False):
        """(name, row -> member or None); on_axis: the continuous date axis of a line / area / card history."""
        if name in fp.groups:  # a group: the bin of the member; an empty member goes to Other, else stays Null (056)
            g = fp.groups[name]
            if g.of_calc:  # a group over a calc: the bin of the calc's value (decisions/151)
                return name, lambda r: g.other if (v := calcs.row_value(g.source, r)) in (None, "") else g.value(v)
            return name, lambda r: g.value(r[g.source]) if r[g.source] != "" else g.other
        if name in calcs and calcs[name].datatype == "date":  # a date calc on a date axis: truncated like a column
            key = lambda r: None if (v := calcs.row_value(name, r)) is None else fn(v.isoformat())  # noqa: E731
        elif name in calcs:
            return name, lambda r: _shown(calcs.row_value(name, r))
        else:
            key = lambda r: fn(r[name]) if r[name] != "" else None  # noqa: E731
        return name, axis(key) if on_axis else key

    def top(s, keys):
        """Rows of a bar with a Top N: its top dimension members over the context rows (Tableau ranks them after the
        context filters, before the dimension filters), then the filtered rows of those members."""
        n = params.top_n(s, pars)
        if n is None:
            return rows
        i = params.top_index(s)  # a line's series is its second key (decisions/148)
        member, rank = keys[i][1], value(params.top_by(s)[1])  # a registry: by its first column (decisions/039)
        key = lambda r: _NULL_MEMBER if (v := member(r)) in (None, "") else v  # noqa: E731  Null is ranked too (056)
        if filters_mod.after_filters(s):  # a RANK table calc: the marks after every filter, measure ones too (086)
            shown, groups = filters_mod.measure_rows(s, rows, keys, value), {}
            for r in shown:
                groups.setdefault(key(r), []).append(r)
            keep = filters_mod.rank_members(groups, lambda rs: rank(rs, View(keys[i:i + 1], rs)), n)
            return [r for r in shown if key(r) in keep]
        keep = params.top_members(context_rows, key, lambda rs: rank(rs, View(keys[i:i + 1], rs)), n,
                                  f"Sheet '{s['name']}'", params.bottom(s))
        return [r for r in rows if key(r) in keep]

    def table_calc(m):
        return m.get("table_calc") or tablecalc.expected(calcs, m)

    def value(m):
        name, how = m["field"], m.get("agg", "sum")
        if name in calcs and calcs[name].is_agg:
            return lambda rs, view: calcs.agg_value(name, rs, view)
        if name in calcs and calcs[name].view_lod:  # INCLUDE/EXCLUDE: aggregate the LOD-level values
            return lambda rs, view: _agg(calcs.view_values(name, rs, view), how)
        if name in calcs:
            return lambda rs, view: _agg([calcs.row_value(name, r) for r in rs], how)
        return lambda rs, view: _agg([r[name] for r in rs], how)

    def grouped(*a):
        return _grouped(*a, fields=fp)

    out = {}

    def refs(s, marks):
        """The reference line values of a sheet, a record of their own (tbuilder/reflines.py)."""
        got = reflines.values(s, marks, pars) if reflines.lines(s) else None
        if got:  # a date line alone has no number (decisions/043)
            out[reflines.record(s["name"])] = got

    every = tuple(range(len(spec.get("filters", []))))
    by_filters = {every: rows}

    def dashboard_rows(name):
        """The rows after the filters that apply to the sheet: a dashboard's filter only to its sheets (071)."""
        key = tuple(i for i, f in enumerate(spec.get("filters", [])) if filters_mod.applies(spec, f, name))
        if key not in by_filters:
            by_filters[key] = interact.period_rows(spec, calcs, filters_mod.split_rows(spec, prof, where, fcalc,
                                                                                       name)[1])
        return by_filters[key]

    for s in spec["sheets"]:
        t = s["type"]
        rows = filters_mod.sheet_rows(s, dashboard_rows(s["name"]), fcalc)  # the sheet's own filters (decisions/057)
        mf = lambda rs, ks, s=s: filters_mod.measure_rows(s, rs, ks, value)  # noqa: E731  its measure filters
        if cards.is_cards(s):  # latest period, base period, change (tbuilder/cards.py)
            out[s["name"]] = {cards.label(m): {k: calcs.agg_value(cards.names(s, m)[k], rows)
                                               for k in ("current", "previous", "delta")} for m in s["measures"]}
            if kpi2.abs_delta(s):  # '▲ 1 466 | 10.5%' (decisions/037)
                for m in s["measures"]:
                    out[s["name"]][cards.label(m)]["diff"] = calcs.agg_value(kpi2.names(s, m)["diff"], rows)
            for m in s["measures"]:  # the status dot's color: 'On track' (decisions/062)
                if kpi2.status(m):
                    out[s["name"]][cards.label(m)]["status"] = calcs.agg_value(kpi2.status_name(s, m), rows)
                if kpi2.target(m):  # '103% of $15.0K target' and its bar (decisions/155)
                    n = kpi2.progress_names(s, m)
                    out[s["name"]][cards.label(m)].update({k: calcs.agg_value(n[k], rows) for k in
                                                          ("target", "progress", "fill")})
            keys = [dim(s["date"]["field"], lambda v, lv=cards.level(s): _trunc(v, lv), True)]
            for m in s["measures"]:  # the history part of each card, named as the builder names it
                part = {"name": f"{s['name']} · {cards.label(m)} · History", "type": "card_history", "card": s,
                        "measure": m}
                h = cards.history_measure(s, m)  # a ratio: SUM(field) / SUM(per) by period (decisions/169)
                refs(part, lambda mm, h=h: grouped(rows, keys, value(h if mm is m else mm)))
                if kpi2.line(s):  # the sparkline's max and last are labelled, min is its low point
                    out[kpi2.points_record(part)] = kpi2.points(grouped(rows, keys, value(h)))
                if kpi2.spark_points(s):  # the periods marked with a dot (decisions/059)
                    out[kpi2.marks_record(part)] = kpi2.point_marks(s, grouped(rows, keys, value(h)), m)
            if kpi2.period_strip(s) and rows:  # 'Dec 2025 compared to Nov 2025'
                out[kpi2.period_name(s)] = {k: _iso(calcs.row_value(n, rows[0])) for k, n in
                                            (("period", cards.period(s)), ("base", kpi2.base_period(s)))}
        elif t == "kpi":
            kept = mf(rows, [])
            out[s["name"]] = {_label(m, calcs): value(m)(kept, View([], kept)) for m in s["measures"]}
        elif t == "bar" and "plan" in s:  # dimension value -> {fact label: value, plan label: value}
            keys = [dim(s["dimension"])]
            fact, plan = (grouped(top(s, keys), keys, value(m)) for m in (s["measure"], s["plan"]))
            out[s["name"]] = {k: {_label(s["measure"], calcs): fact[k], _label(s["plan"], calcs): plan[k]}
                              for k in fact}
        elif t == "combo":  # dimension value -> {bar label: value, line label: value} (decisions/044)
            level = dates.bar_level(s)  # a bar per period of a date (decisions/140)
            keys = [dim(s["dimension"], lambda v, lv=level: _trunc(v, lv)) if level else dim(s["dimension"])]
            bar, line = (grouped(rows, keys, value(m)) for m in (s["bar"], s["line"]))
            out[s["name"]] = {k: {_label(s["bar"], calcs): bar[k], _label(s["line"], calcs): line[k]} for k in bar}
        elif t == pareto.TYPE:  # member -> {measure: value, Cumulative: running share}, the vital few (157)
            out[s["name"]], vital = pareto.expected(s, rows, dim, value, grouped, _label(s["measure"], calcs))
            if pareto.highlight(s):
                out[pareto.vital_record(s["name"])] = vital
        elif t == "map":  # place -> value, as a bar (decisions/046)
            keys = [dim(s["geo"]["field"])]
            out[s["name"]] = grouped(rows, keys, value(s["measure"]), table_calc(s["measure"]))
            if maps.second_measure(s):  # the color's own measure: its scale's range is checked on it (decisions/137)
                out[maps.color_record(s["name"])] = grouped(rows, keys, value(maps.second_measure(s)))
        elif t == "scatter":  # point -> {x: v, y: v}, the axis lines (decisions/047)
            out.update(scatter.expected(s, rows, dim, value, grouped))
        elif compareviz.kind(s):  # slope, box plot, waffle (decisions/141); a waffle's share is FIXED: context rows
            if t == compareviz.BOX:  # the quartiles and the median per member (polish-26)
                out[compareviz.box_record(s["name"])] = compareviz.box_stats(s, rows, dim, value, grouped)
            if compareviz.spread(s):  # the labels' positions; the span from both ends, FIXED: context rows (26b)
                ends = grouped(context_rows, [dim(s["period"]), dim(s["dimension"])], value(s["measure"]))
                shown = grouped(rows, [dim(s["period"]), dim(s["dimension"])], value(s["measure"]))
                members = {k.split(" | ")[1] for k in shown}
                kept = [v for k, v in ends.items() if k.split(" | ")[1] in members and k.split(" | ")[0] in
                        {x.split(" | ")[0] for x in shown} and v is not None]
                span = max(kept) - min(min(kept), 0)
                out[compareviz.label_record(s["name"])] = compareviz.label_positions(shown, span)
            if t == compareviz.WAFFLE and s.get("value"):  # the % in the title (polish-26b)
                share = compareviz.expected(s, context_rows, dim, value, grouped)["share"]
                out[compareviz.value_record(s["name"])] = None if share is None else formats.render(share, "pct0")
            out[s["name"]] = compareviz.expected(s, context_rows if t == compareviz.WAFFLE else rows, dim, value,
                                                 grouped)
        elif tilegrid.is_tilegrid(s):  # member -> measure, member -> its tile (decisions/154)
            out[s["name"]] = tilegrid.expected(s, rows, dim, value, grouped)
            out[tilegrid.tiles_record(s["name"])] = tilegrid.tiles(s, rows, out[s["name"]])
        elif treemap.is_treemap(s):  # (group,) label -> size; packed bubbles (decisions/138, 141)
            out[s["name"]] = treemap.expected(s, rows, dim, value, grouped)
        elif distviz.kind(s):  # histogram, strip, beeswarm, calendar, bump (decisions/140)
            out[s["name"]] = distviz.expected(s, rows, dim, value, grouped, _trunc,
                                              distviz.bin_columns(spec, prof))
        elif t == "gantt":  # task -> its days (polish-26)
            out[s["name"]] = gantt.expected(s, rows, dim, value, grouped)
        elif t == "waterfall":  # member -> its step (decisions/139)
            out[s["name"]] = waterfall.expected(s, rows, dim, value, grouped)
        elif t == "funnel":  # stage -> {value, conversion} (decisions/159)
            order = spec.get("fields", {}).get(s["dimension"], {}).get("order")
            out[s["name"]] = funnel.expected(s, rows, dim, value, grouped, order)
        elif t == "dumbbell":  # member -> {from label: value, to label: value} (decisions/139)
            keys = [dim(s["dimension"])]
            a, z = (grouped(rows, keys, value(s[k])) for k in ("from", "to"))
            out[s["name"]] = {k: {_label(s["from"], calcs): a[k], _label(s["to"], calcs): z[k]} for k in a}
            if s.get("zero", True) is False:  # the span the axis covers, not from zero (polish-26b)
                vs = [v for d in (a, z) for v in d.values() if v is not None]
                out[dualaxis.axis_record(s["name"])] = {"min": min(vs), "max": max(vs)} if vs else None
        elif t == "lollipop":
            keys = [dim(s["dimension"])]
            out[s["name"]] = grouped(rows, keys, value(s["measure"]))
        elif t == "donut":  # the slices, the total in the centre, the legend's value (share)
            keys, share = [dim(s["dimension"])], {"field": dualaxis.share_calc(s)}
            slices = grouped(rows, keys, value(s["measure"]))
            shares = grouped(rows, keys, value(share), tablecalc.expected(calcs, share))
            out[s["name"]] = slices
            out[dualaxis.total_record(s)] = value(s["measure"])(rows, View([], rows))
            out[dualaxis.legend_name(s)] = {k: {"value": slices[k], "share": shares[k]} for k in slices}
        elif t == "bar":
            split = colors.series_field(s)  # color dimension or highlighted field: bar segments
            level = dates.bar_level(s)  # a bar per period of a date: its discrete headers (decisions/090)
            keys = [dim(s["dimension"], lambda v, lv=level: _trunc(v, lv)) if level else dim(s["dimension"])]
            keys += [dim(split)] if split else []
            keys += [dim(s["facet"]["field"])] if compareviz.facet(s) else []  # small multiples (decisions/141)
            out[s["name"]] = grouped(mf(top(s, keys), keys), keys, value(s["measure"]), table_calc(s["measure"]))
            if barinbar.on(s):  # the members' totals (decisions/156)
                out[barinbar.total_record(s)] = barinbar.expected(s, rows, dim, value, grouped)
            refs(s, lambda m, ks=keys: grouped(top(s, ks), ks, value(m)))
        elif t in ("line", "area"):
            level = s["date"].get("level", "month")
            keys = [dim(s["date"]["field"], lambda v, l=level: _trunc(v, l), True)]
            split = colors.series_field(s)  # a highlighted series is still one line per value of its field
            keys += [dim(split)] if split else []
            keys += [dim(s["facet"]["field"])] if compareviz.facet(s) else []  # small multiples (decisions/141)
            if benchmark.is_bench(s):  # {period: {selected member: v, benchmark: v}} (decisions/043)
                out[s["name"]] = benchmark.marks(s, spec, pars, where, lambda m, ks=keys: grouped(rows, ks, value(m)))
            else:
                out[s["name"]] = grouped(mf(top(s, keys), keys), keys, value(s["measure"]), table_calc(s["measure"]))
            refs(s, lambda m, ks=keys: grouped(top(s, ks), ks, value(m)))
            if benchmark.ends(s):  # the labelled first / last values
                out[benchmark.ends_record(s["name"])] = benchmark.end_values(s, out[s["name"]])
        elif t == "registry":  # row key -> {column part: value} (registry.parts: decisions/039)
            keys = [dim(r) for r in s["rows"]]
            out[s["name"]] = {}
            for c in s["columns"]:
                for part, _, what, _ in registry.parts(s, c):
                    m = what if isinstance(what, dict) else {"field": what}  # a generated calc by its name
                    shown = mf(top(s, keys), keys)  # Top N rows (decisions/039), the measure filters
                    tc = tablecalc.expected(calcs, m)
                    marks = grouped(shown, keys, value(m), tc)  # rank, share: a table calc
                    # a total mark is a partition of its own: a table calc there over that one mark (decisions/134)
                    total = (lambda rs, view, tc=tc: tc["values"]([rs], view)[0]) if tc else value(m)
                    marks.update(totals.registry(s, shown, keys, total, grouped))  # decisions/036
                    for k, v in marks.items():
                        out[s["name"]].setdefault(k, {})[part] = v
            line = sparkline.line_column(s)
            if line:  # the line's value per row and period (decisions/153)
                sp = line["spark"]
                pk = keys + [dim(sp["date"], lambda v, lv=sp["level"]: _trunc(v, lv))]
                shown = [r for r in mf(rows, keys) if r[sp["date"]] != ""
                         and sparkline.in_periods(line, dates.to_date(r[sp["date"]]))]
                out[sparkline.part_name(s, line)] = grouped(shown, pk, value(line["measure"]))
        elif t in ("table", "heatmap"):
            level = dates.heat_level(s)  # a column per period of a date (decisions/125)
            keys = [dim(r) for r in tables.rows(s)]  # two row fields (decisions/045)
            keys += [dim(s["cols"], lambda v, lv=level: _trunc(v, lv)) if level else dim(s["cols"])]
            shown = top(s, keys)  # Top N of the first row field (decisions/148)
            out[s["name"]] = grouped(mf(shown, keys), keys, value(s["measure"]), table_calc(s["measure"]))
            out[s["name"]].update(totals.table(s, shown, keys, value(s["measure"]), grouped))  # decisions/036
            for p in heatmap.parts(s)[1:]:  # marginal totals: the measure over each row's / column's data rows
                mk = [dim(p["dimension"])] + ([dim(p["inner"])] if "inner" in p else [])  # decisions/186
                out[p["name"]] = grouped(rows, mk, value(p["measure"]))
                refs(p, lambda m, ks=mk: grouped(rows, ks, value(m)))  # their average line
    rows = by_filters[every]  # all filters: the insight lines and the as-of date do not follow a dashboard's (071)
    insight.expected(spec, calcs, rows, out)  # insight lines, tile notes (decisions/045)
    if kpi2.as_of_field(spec) and rows:  # the latest date of the data (FIXED: the context rows)
        out[kpi2.as_of_record(spec)] = _iso(calcs.row_value(kpi2.as_of_calc(spec), rows[0]))
    return out


def by_value(spec, csv_path, name, where=None):
    """{value: compute(...)} at every value of list parameter name (the others at their defaults): a metric selector
    or a switch shows each of them after a click (decisions/042), reconcile can check any."""
    spec_ = nav.primary(spec)
    prof = None if "datasources" in spec else excel.load(csv_path, spec_["datasource"])  # decisions/083
    p = next((p for p in spec_.get("parameters", []) if p["name"] == name), None)
    if p is None or "values" not in p:
        raise ValueError(f"'{name}' is not a list parameter of the spec")
    return {v: compute(spec, csv_path, {name: v}, where, prof) for v in p["values"]}


def _iso(v):
    """A date calc's value as an ISO date (the day of a datetime)."""
    return None if v is None else v.date().isoformat() if isinstance(v, dt.datetime) else v.isoformat()


def _shown(v):
    """Dimension value as Tableau displays it (booleans as True/False)."""
    if v is None:
        return None
    return {True: "True", False: "False"}.get(v, str(v)) if isinstance(v, bool) else str(v)
