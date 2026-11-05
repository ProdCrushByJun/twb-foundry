"""KPI cards (kpi style "cards"): the calculated fields behind a card, generated from the spec.

A card shows, per measure, the value for the latest period in the data, the change against the previous
period (or the same period a year back) and a history of the measure by period. The builder and
expected.py both take these definitions, so the workbook and the reference numbers use one formula.
"""
from . import formats, strings

LEVELS = ("week", "month", "year")
DATE_FORMAT = {"week": "*dd mmm yyyy", "month": "*mmm yyyy", "year": "*yyyy"}  # period shown on the card
DELTA_FORMAT = "*▲ 0.0%;▼ 0.0%"  # the reference's change format: arrow and absolute percent
DELTA_PP_FORMAT = '*▲ 0.0" pp";▼ 0.0" pp"'  # the change of a ratio measure: percentage points, not a percent (decisions/110)
DELTA_PLAIN_FORMAT = "*0.0%;0.0%"  # the percent after an absolute change (decisions/037): the arrow is on that one
# Short bases as the references write them ("MoM", "vs PY"); a longer text wrapped in a
# stacked card's value column. In the spec's locale: tbuilder/strings.py (decisions/169).


def is_cards(s):
    return s["type"] == "kpi" and s.get("style") == "cards"


def label(m):
    return m.get("label", m["field"])


def heading(m):
    """The tile's name line: 'heading' (may say a [Parameter], decisions/148) else the label."""
    return m.get("heading", label(m))


def is_ratio(m):
    """A ratio measure ('per'): SUM(field) / SUM(per) of a period, or per_agg of per (decisions/198); its change is in
    percentage points unless it says delta 'pct'."""
    return "per" in m


def in_points(m):
    """The change of a ratio in percentage points (decisions/110); delta 'pct' asks for a percent (decisions/198): an
    average order value of 80 against 100 is -20%, not -2000 pp."""
    return is_ratio(m) and m.get("delta") != "pct"


def per_agg(m):
    """How a ratio's 'per' adds up (decisions/198): COUNTD of invoices under an average order value."""
    return m.get("per_agg", "sum").upper()


def is_abs(m):
    """A measure whose change is absolute ('delta': 'abs', decisions/169): '▲ 3' of a count, not '▲ 12.5%'."""
    return m.get("delta") == "abs"


def neutral_zero(s):
    """delta_zero 'neutral' (decisions/169): no change is grey '= no change', neither good nor bad."""
    return s.get("delta_zero") == "neutral"


def names(s, m):
    """Calc captions of one card measure; prefixed with the card name so two cards never collide."""
    p = f"{s['name']} · {label(m)}"
    return {"current": f"{p} · Current", "previous": f"{p} · Previous", "delta": f"{p} · Change",
            "good": f"{p} · Change Good", "bad": f"{p} · Change Bad", "flat": f"{p} · Change Flat",
            "ratio": f"{p} · Ratio"}


def history_measure(s, m):
    """The measure a card's history shows by period: a ratio as SUM(field) / SUM(per) of each period (the calc
    'Ratio'), not SUM(field) alone (decisions/169, L4)."""
    if not is_ratio(m):
        return m
    return {**{k: v for k, v in m.items() if k not in ("field", "per", "agg")}, "field": names(s, m)["ratio"]}


def pp_format(spec):
    """The change of a ratio measure: percentage points, not a percent (decisions/110), 'pp' in the locale."""
    pp = strings.t(spec, "pp")
    return f'*▲ 0.0" {pp}";▼ 0.0" {pp}"'


ADDITIVE = ("sum", "count", "countd")  # whole counts: their change keeps the measure's decimals


def delta_format(m):
    """The format of an absolute change (decisions/177): 'delta_format' if given; of an average-like 'delta': 'abs'
    measure one decimal more than its format (1.9 min, not 2: the change of averages is finer than they are);
    else the measure's own format (None: '#,##0')."""
    if "delta_format" in m:
        return m["delta_format"]
    fmt = m.get("format")
    if not is_abs(m) or m.get("agg", "sum") in ADDITIVE:
        return fmt
    base = dict(formats.PRESETS[fmt]) if isinstance(fmt, str) else dict(fmt or {})
    return {**base, "decimals": min(formats.normalize(base)["decimals"] + 1, formats.MAX_DECIMALS)}


def arrow_format(m):
    """The absolute change with the card's arrows ('*▲ 0.0%;▼ 0.0%', decisions/013) in its number format
    (delta_format): the first section without the type letter; Tableau shows the negative section without the
    minus."""
    df = delta_format(m)
    body = formats.tableau(df)[1:].split(";")[0] if df else "#,##0"
    return f"*▲ {body};▼ {body}"


def flat_format(spec):
    """A zero change, grey (decisions/169): only the zero section of the format has text."""
    return f'*;;"= {strings.t(spec, "no_change")}"'


def delta_calc(s, m, cur, prev):
    """(formula, format) of a card measure's change from the expressions cur and prev: a ratio in percentage points
    (13.1% against 11.5% is +1.6 pp, not +13.9%: decisions/110), 'delta': 'abs' its difference in its own precision
    ('▲ 1.9', not '▲ 2' of an average: decisions/177), else the percent change; rounded as it reads with
    delta_zero 'neutral' (decisions/169). Also the last sparkline point's color of delta_colors 'accent' (178)."""
    shown = lambda x, d: f"ROUND({x}, {d})" if neutral_zero(s) else x  # noqa: E731
    if in_points(m):
        return shown(f"({cur} - {prev}) * 100", 1), {"type": "number", "decimals": 1}
    if is_abs(m):
        df = delta_format(m)
        return shown(f"{cur} - {prev}", (formats.normalize(df) or {}).get("decimals", 0)), df
    return shown(f"({cur} - {prev}) / ABS({prev})", 3), "percent"


def last_date(s):
    return f"Last {s['date']['field']}"


def period(s):
    return f"{s['name']} · Period"


def period_text(s):
    return f"{s['name']} · Period Text"


def date_range(s):
    """card_date 'range' (decisions/178, logistics mock): 'wk 12 (Oct 19-24) vs wk 11' under the card's name,
    the week's number from the data's first week and its days up to the last date in the data."""
    return s.get("card_date") == "range"


def period_text_formula(s, spec):
    """The text of card_date 'range': the week's number, its first and last day (the last date in the data when
    the week is not over), the month once when both days are in it, and the week it is compared to."""
    d, p = s["date"]["field"], f"[{period(s)}]"
    months = strings.t(spec, "months")
    mon = lambda x: "CASE MONTH(" + x + ") " + " ".join(f'WHEN {i} THEN "{m}"' for i, m in enumerate(months, 1))         + " END"  # noqa: E731
    end = f"IIF(DATEADD('day', 6, {p}) < DATE([{last_date(s)}]), DATEADD('day', 6, {p}), DATE([{last_date(s)}]))"
    n = f"DATEDIFF('week', DATETRUNC('week', {{FIXED : MIN([{d}])}}), {p}) + 1"
    return (f'"{strings.t(spec, "wk")} " + STR({n}) + " (" + STR(DAY({p})) + IIF(MONTH({p}) = MONTH({end}), "", " " '
            f'+ {mon(p)}) + "–" + STR(DAY({end})) + " " + {mon(end)} + "{strings.t(spec, "vs_wk")}" + STR({n} - 1)')


def goal(m):
    """A measure's goal (decisions/178): '· goal 95%' after its change, a dashed line on its sparkline."""
    return m.get("goal")


def is_current(s):
    return f"{s['name']} · Is Current"


def level(s):
    return s["date"].get("level", "month")


def base_label(s, spec=None):
    return strings.t(spec, (s.get("compare", "previous"), level(s)))


def own_formats(spec):
    """A row-level calc under a card without a format of its own takes the card's, as a CSV column does: the labels of
    the card's history show it (decisions/198). A unit stays the card's (formats.fields)."""
    own = {c["name"]: c for c in spec.get("calcs", [])}
    found = {}
    for s in spec["sheets"]:
        for m in s["measures"] if is_cards(s) else ():
            if "format" in m and not is_ratio(m) and m["field"] in own and own[m["field"]].get("format") is None:
                found.setdefault(m["field"], dict(formats.normalize(m["format"]), suffix=None))
    return {**spec, "calcs": [{**c, "format": found[c["name"]]} if c["name"] in found else c for c in spec["calcs"]]} if found else spec


def calcs(spec):
    """Calc specs ({name, formula, format?}) for every cards sheet of the spec."""
    out, seen = [], set()

    def add(name, formula, fmt=None):
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "formula": formula, **({"format": fmt} if fmt else {})})

    for s in spec["sheets"]:
        if not is_cards(s):
            continue
        d, lv = s["date"]["field"], level(s)
        add(last_date(s), f"{{FIXED : MAX([{d}])}}")
        this = f"DATETRUNC('{lv}', [{last_date(s)}])"
        if s.get("anchor") == "last_complete":  # the latest whole period: a part-filled one is left out (polish-26)
            this = f"DATEADD('{lv}', -1, DATETRUNC('{lv}', DATEADD('day', 1, [{last_date(s)}])))"
        back = "year" if s.get("compare", "previous") == "year" else lv
        prev = f"DATEADD('{back}', -1, {this})"
        row = f"DATETRUNC('{lv}', [{d}])"
        add(period(s), this, DATE_FORMAT[lv])
        add(is_current(s), f"{row} = {this}")
        if date_range(s):
            add(period_text(s), period_text_formula(s, spec))
        for m in s["measures"]:
            n, agg = names(s, m), m.get("agg", "sum").upper()
            ratio = is_ratio(m)

            def of(when):  # the measure over the rows of one period; a ratio: SUM(field) / SUM(per) of them
                part = lambda f, how=agg: f"{how}(IF {row} = {when} THEN [{f}] END)"  # noqa: E731
                return f"{part(m['field'])} / {part(m['per'], per_agg(m))}" if ratio else part(m["field"])

            add(n["current"], of(this), m.get("format"))  # decisions/032
            add(n["previous"], of(prev), m.get("format"))
            add(n["delta"], *delta_calc(s, m, f"[{n['current']}]", f"[{n['previous']}]"))
            if ratio:
                add(n["ratio"], f"{agg}([{m['field']}]) / {per_agg(m)}([{m['per']}])", m.get("format"))  # its history
            up = m.get("good", "up") == "up"
            fmt = "delta_plain" if s.get("delta") == "abs_pct" else "delta"  # decisions/037
            if in_points(m):
                fmt = "delta_pp" if strings.locale(spec) == "en_US" else pp_format(spec)
            elif is_abs(m):
                fmt = arrow_format(m)
            eq = "" if neutral_zero(s) else "="  # neutral: zero is neither side (decisions/169)
            add(n["good"], f"IF [{n['delta']}] {'>' if up else '<'}{eq} 0 THEN [{n['delta']}] END", fmt)
            add(n["bad"], f"IF [{n['delta']}] {'<' if up else '>'} 0 THEN [{n['delta']}] END", fmt)
            if neutral_zero(s):
                add(n["flat"], f"IF [{n['delta']}] = 0 THEN 0 END", flat_format(spec))
    return out
