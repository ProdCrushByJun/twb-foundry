"""The selected member against the benchmark of all members (todo 8.8, decisions/043).

SOC Monitor draws small multiples of 'the selected region vs the organization': the region chosen in a parameter in
the accent color, the average of all regions muted, the last value of each line labelled, a shared legend in the
block header. Spec, on a line sheet:
- benchmark {field, select, against: all, label?}: two lines on one axis (Measure Values, colored by Measure Names):
  - the selected member: select = a value of field ("West"), {parameter: <string parameter over its values>} or
    "filter" (the dashboard filter on field, one value: the measure itself);
  - the benchmark: the measure over all members of field per period, divided by their count (sum), or the average
    of all rows (avg). A FIXED LOD on the period (SOC: { FIXED [date] : AVG([critical_vuln_count]) }), so neither a
    filter on field nor the parameter changes it. EXCLUDE would not do: it is computed after the dimension filters.
    For the same reason every other filter of the dashboard must be a context filter (applied before FIXED), or the
    benchmark would ignore it while the selected line follows it.
- labels: last | ends: the line's last value (SOC: mark-labels-mode line-ends, line-first false) or its first and
  last (Wealth & Banking: line-first true).
- repeat: [measures] (+ columns): small multiples, one copy per measure '<name> · <label>', titled '<title> **<label>**';
  only the first copy keeps the subtitle (the shared legend, in colored words: decisions/016); its dashboard cell
  becomes a group of `columns` cells per row (a 2x2 for four measures), or the copies side by side.
XML forms are SOC's (Line - * Comparison to Org): <filter> on [:Measure Names] with the two measures, [Multiple
Values] on Rows, Measure Names on Color, the labels as mark style formats; the palette map on Measure Names as the
plan sheets of decisions/016 write it.
"""
import copy

from .design import COLOR

AGGS = ("sum", "avg")  # sum: total of all members / their count; avg: the average of all rows
SELECT_FILTER = "filter"


def is_bench(s):
    return s["type"] == "line" and "benchmark" in s


def ends(s):
    """None | 'last' | 'ends'."""
    return s.get("labels") if s["type"] in ("line", "area") else None


def selected_calc(s):
    return f"{s['name']} · Selected"


def bench_calc(s):
    return f"{s['name']} · Benchmark"


def period_calc(s):
    return f"{s['name']} · Period"


def label(s):
    """The benchmark's name in the expected numbers and the reconcile tags ('All regions avg')."""
    bm = s["benchmark"]
    return bm.get("label") or f"All {bm['field']} avg"


def ends_record(name):
    """expected.py key of a sheet's labelled line ends ({series: {first?, last}})."""
    return f"{name} · Ends"


def _sel(s):
    return s["benchmark"]["select"]


def _filter(spec, field):
    return next((f for f in spec.get("filters", []) if f["field"] == field), None)


# ---- small multiples ---------------------------------------------------------------------------------------------
def repeated(s, m):
    return f"{s['name']} · {m.get('label') or m['field']}"


def expand(spec):
    """Line sheets with 'repeat': one copy per measure (see the module doc). -> the spec itself when nothing repeats,
    else an expanded copy (build, expected, reconcile and lint all read it, through registry.expand)."""
    reps = {s["name"]: s for s in spec["sheets"] if s["type"] in ("line", "area") and "repeat" in s}
    if not reps:
        return spec
    out = copy.deepcopy(spec)
    sheets = []
    for s in out["sheets"]:
        if s["name"] not in reps:
            sheets.append(s)
            continue
        where = f"Sheet '{s['name']}'"
        if "measure" in s:
            raise ValueError(f"{where}: 'repeat' gives the measure of each copy; remove 'measure'")
        labels = [m.get("label") or m["field"] for m in s["repeat"]]
        if len(set(labels)) != len(labels):
            raise ValueError(f"{where}: 'repeat' names a measure twice: {labels} (give one a label)")
        base = {k: v for k, v in s.items() if k not in ("repeat", "columns")}
        for i, (m, lab) in enumerate(zip(s["repeat"], labels)):
            title = (base["title"] + " " if base.get("title") else "") + f"**{lab}**"
            copy_ = {**copy.deepcopy(base), "name": repeated(s, m), "measure": m, "title": title}
            if i and "subtitle" in copy_:  # the legend once, in the first block's header
                del copy_["subtitle"]
            sheets.append(copy_)
    out["sheets"] = sheets

    def cell_of(cell, rep):
        names = [repeated(rep, m) for m in rep["repeat"]]
        n = rep.get("columns")
        if not n:
            return [n if isinstance(cell, str) else {**cell, "sheet": n} for n in names]
        group = {"rows": [names[i:i + n] for i in range(0, len(names), n)]}
        if isinstance(cell, dict) and "width" in cell:
            group["width"] = cell["width"]
        return [group]

    def cells(row):
        new = []
        for cell in row:
            name = cell if isinstance(cell, str) else cell.get("sheet")
            if name in reps:
                new += cell_of(cell, reps[name])
            elif isinstance(cell, dict) and "rows" in cell:
                new.append({**cell, "rows": [cells(r) for r in cell["rows"]]})
            else:
                new.append(cell)
        return new

    for d in ([out["dashboard"]] if "dashboard" in out else []) + out.get("dashboards", []):
        d["grid"] = [cells(r) for r in d["grid"]]
    return out


# ---- spec checks (before the calcs are compiled) -----------------------------------------------------------------
def check(spec, prof, params):
    calc_names = {c["name"] for c in spec.get("calcs", [])}
    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        if ends(s) and "table_calc" in s.get("measure", {}):
            raise ValueError(f"{where}: labels on a table calculation are not supported yet")
        if not is_bench(s):
            continue
        bm, m = s["benchmark"], s["measure"]
        if "color" in s:
            raise ValueError(f"{where}: a benchmark colors the lines itself (selected accent, benchmark muted): "
                             f"remove 'color'")
        if m["field"] in calc_names:
            raise ValueError(f"{where}: benchmark of a calculated field is not supported yet; CSV columns only")
        from . import reflines
        if any(r["type"] in ("avg", "median") for r in reflines.lines(s)):
            raise ValueError(f"{where}: an avg / median line over a benchmark's two lines is not supported yet (the "
                             f"benchmark is the comparison); use const, param, date or band")
        if "table_calc" in m:
            raise ValueError(f"{where}: benchmark of a table calculation is not supported yet")
        if m.get("agg", "sum") not in AGGS:
            raise ValueError(f"{where}: benchmark needs agg sum or avg (the average of all members), got "
                             f"'{m.get('agg')}'")
        if prof.col(m["field"]).datatype not in ("integer", "real"):
            raise ValueError(f"{where}: benchmark measure '{m['field']}' is not numeric")
        f = bm["field"]
        if f in calc_names:
            raise ValueError(f"{where}: benchmark field '{f}' is a calculated field; CSV columns only for now")
        col = prof.col(f)
        if col.datatype != "string":
            raise ValueError(f"{where}: benchmark field '{f}' is {col.datatype}; it must be a text dimension")
        sel = bm["select"]
        own = _filter(spec, f)
        if sel == SELECT_FILTER:
            if own is None:
                raise ValueError(f"{where}: select 'filter' needs a dashboard filter on '{f}'")
            if own.get("mode") not in ("single_dropdown", "single_list") or len(own.get("default", [])) != 1 \
                    or own.get("exclude") or own.get("context"):
                raise ValueError(f"{where}: the filter on '{f}' selects the member: it needs mode single_dropdown, "
                                 f"one default value, no exclude and no context (FIXED must not see it)")
        elif isinstance(sel, dict):
            p = params.get(sel["parameter"])
            if p is None:
                raise ValueError(f"{where}: select parameter '{sel['parameter']}' is not a parameter (parameters: "
                                 f"{sorted(params) or 'none'})")
            if p.datatype != "string" or not p.values:
                raise ValueError(f"{where}: select parameter '{p.name}' must be a string parameter with a list of "
                                 f"values")
            missing = [v for v in p.values if v not in col.distinct]
            if missing:
                raise ValueError(f"{where}: select parameter values {missing} are not in '{f}'")
        else:
            if sel not in col.distinct:
                raise ValueError(f"{where}: select '{sel}' is not a value of '{f}' (values: {col.distinct[:12]})")
            if '"' in sel:
                raise ValueError(f"{where}: select values containing '\"' are not verified against Tableau yet")
        if own is not None and sel != SELECT_FILTER:
            raise ValueError(f"{where}: '{f}' has a dashboard filter: it would cut the selected line; select with "
                             f"\"filter\" or remove the filter")
        for other in spec.get("filters", []):
            if other["field"] != f and not other.get("context"):
                raise ValueError(f"{where}: the benchmark is a FIXED LOD, which ignores the filter on "
                                 f"'{other['field']}' while the selected line follows it; make that filter "
                                 f"\"context\": true")


# ---- calcs -------------------------------------------------------------------------------------------------------
def calcs(spec):
    """Calc specs of the benchmark sheets: the period (the FIXED dimension), the selected member, the benchmark."""
    out = []
    for s in spec["sheets"]:
        if not is_bench(s):
            continue
        bm, m = s["benchmark"], s["measure"]
        f, x = bm["field"], m["field"]
        level = s["date"].get("level", "month")
        p = period_calc(s)
        out.append({"name": p, "formula": f"DATETRUNC('{level}', [{s['date']['field']}])"})
        sel = _sel(s)
        if sel != SELECT_FILTER:
            rhs = f"[{sel['parameter']}]" if isinstance(sel, dict) else f'"{sel}"'
            out.append({"name": selected_calc(s), "formula": f"IF [{f}] = {rhs} THEN [{x}] END"})
        if m.get("agg", "sum") == "avg":
            formula = f"{{FIXED [{p}] : AVG([{x}])}}"
        else:
            formula = f"{{FIXED [{p}] : SUM([{x}])}} / {{FIXED [{p}] : COUNTD([{f}])}}"
        out.append({"name": bench_calc(s), "formula": formula})
    return out


def selected_measure(s):
    """The measure spec of the selected line: the generated calc, or under a filter the sheet's own measure."""
    m = s["measure"]
    if _sel(s) == SELECT_FILTER:
        return m
    return {"field": selected_calc(s), "agg": m.get("agg", "sum")}


def bench_measure(s):
    """Every row of a period carries the benchmark (a FIXED value): AVG shows it."""
    return {"field": bench_calc(s), "agg": "avg"}


# ---- sheet shape -------------------------------------------------------------------------------------------------
def encode(b, s, fields, enc):
    """A benchmark line: the selected and the benchmark measures replace the sheet's measure, Measure Names on Color;
    -> the two measures (Measure Values on Rows), else None. Labels of the line ends on Text."""
    from .colors import MEASURE_NAMES
    names = None
    if is_bench(s):
        sel, bench = b._measure(selected_measure(s)), b._measure(bench_measure(s))
        fields[1:2] = [sel, bench]
        enc.append(("color", b.q(MEASURE_NAMES)))
        names = [sel, bench]
    if ends(s):
        if end_member(s):  # 'Suburb 88.0': the series named at its end (decisions/170)
            enc.append(("text", b.q(b._dim(end_member(s)).name)))
        enc.append(("text", b.q("[Multiple Values]") if names else b.q(fields[1].name)))
    return names


def end_member(s):
    """The series field a line's end labels name ahead of the value (decisions/170): a line split by a color dimension
    or a highlighted field; None for one line, a benchmark (its legend names it) and small multiples (the panel)."""
    from .colors import series_field
    from .compareviz import facet
    if s["type"] != "line" or is_bench(s) or facet(s):
        return None
    return series_field(s)


def measure_order(b, view, s, names):
    """The selected line first: drawn on top of the benchmark (Desktop draws the first Measure Names value last)."""
    import xml.etree.ElementTree as ET
    from .colors import MEASURE_NAMES
    if not is_bench(s):
        return
    sort = ET.SubElement(view, "manual-sort", column=b.q(MEASURE_NAMES), direction="ASC")
    d = ET.SubElement(sort, "dictionary")
    for m in names:
        ET.SubElement(d, "bucket").text = f'"{b.q(m.name)}"'


def measures(b):
    """The measures a Measure Names palette maps (Desktop declares them in the datasource)."""
    out = {}
    for s in b.worksheets:
        if is_bench(s):
            for m in (selected_measure(s), bench_measure(s)):
                f = b._measure(m)
                out.setdefault(f.name, f)
    return list(out.values())


def palettes(b):
    """{Measure Names bucket: color}: the selected line accent, the benchmark muted."""
    out = {}
    for s in b.worksheets:
        if is_bench(s):
            out[f'"{b.q(b._measure(selected_measure(s)).name)}"'] = COLOR["accent"]
            # a single grey line next to one accent line: muted text grey, the pale mark grey is too faint at 1px
            out[f'"{b.q(b._measure(bench_measure(s)).name)}"'] = COLOR["muted"]
    return out


def pane_style(pane, s):
    """The line-end labels as SOC (last) and Wealth & Banking (first and last) write them."""
    import xml.etree.ElementTree as ET
    e = ends(s)
    if not e:
        return
    st = pane.find("style")
    if st is None:
        st = ET.SubElement(pane, "style")
    rule = st.find("style-rule[@element='mark']")
    if rule is None:
        rule = ET.SubElement(st, "style-rule", element="mark")
    for attr, value in [("mark-labels-show", "true"), ("mark-labels-mode", "line-ends"),
                        ("mark-labels-line-first", "true" if e == "ends" else "false"),
                        ("mark-labels-cull", "true")]:  # cull: a label that would overlap another is not drawn
        ET.SubElement(rule, "format", attr=attr, value=value)
    if end_member(s):  # one line, 'member value' (compareviz's form): Desktop's default puts each field on its own
        label = ET.Element("customized-label")
        ft = ET.SubElement(label, "formatted-text")
        for i, el in enumerate(pane.findall("encodings/text")):
            ET.SubElement(ft, "run").text = f"{' ' if i else ''}<{el.get('column')}>"
        pane.insert(list(pane).index(st), label)  # before its style, as Desktop writes it


# ---- expected numbers --------------------------------------------------------------------------------------------
def selected_key(s, spec, pars, where=None):
    """The selected member at evaluation: the value, the parameter's value, or the filter's selection."""
    sel = _sel(s)
    if isinstance(sel, dict):
        return str(pars[sel["parameter"]].value)
    if sel == SELECT_FILTER:
        f = s["benchmark"]["field"]
        chosen = (where or {}).get(f) or _filter(spec, f)["default"]
        return str(chosen[0])
    return sel


def marks(s, spec, pars, where, grouped):
    """{period: {selected member: value, benchmark label: value}}; grouped(measure spec) -> {period: value}."""
    sel, bench = grouped(selected_measure(s)), grouped(bench_measure(s))
    k_sel, k_bench = selected_key(s, spec, pars, where), label(s)
    return {k: {k_sel: sel.get(k), k_bench: bench.get(k)} for k in sorted(set(sel) | set(bench))}


def end_values(s, got):
    """{series: {'first'?, 'last'}} of a line's marks ({'period' or 'period | series': value}, or a benchmark's
    {period: {series: value}}), in period order; a null mark is not drawn, so it is not an end."""
    series = {}
    for k in sorted(got):
        v = got[k]
        if isinstance(v, dict):
            for name, x in v.items():
                series.setdefault(name, []).append(x)
        else:
            parts = k.split(" | ")
            name = parts[1] if len(parts) > 1 else s["measure"].get("label") or s["measure"]["field"]
            series.setdefault(name, []).append(v)
    out = {}
    for name, vals in series.items():
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        out[name] = {"first": vals[0], "last": vals[-1]} if ends(s) == "ends" else {"last": vals[-1]}
    return out
