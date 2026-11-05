"""HTML numbers <-> workbook numbers (decisions/024).

Every number visible on the HTML page (outline "texts") is looked up in expected.compute(spec):
  matched    the value the workbook shows for the same thing (same members / measure named next to it)
  mismatch   the workbook shows that thing, but a different value: a wrong binding, an error
  elsewhere  not tied to a mark by the text around it, but the workbook shows that value somewhere
  missing    the workbook does not show this number at all
  format     the workbook shows the value, but in another form: '634.6K' on the page, the field without units K or with
             2 decimals (decisions/032); checked where the spec gives the field a format
  skipped    dates, years, identifiers (XD-0002, B03), axis ticks: not data values
A mismatch or a missing number fails the check unless the case file accepts it with a reason,
so no difference between the HTML and the workbook goes unnoticed.

Case file (JSON, optional):
  {"state": {"<filter field>": ["value", ...]},   the filter selection the HTML page shows
   "parameters": {"<parameter>": "value"},        the parameter values it shows (a metric picked by a button, a
                                                   period tab: decisions/042); default: the spec's defaults
   "accepted": [{"number": "32.3", "context": "per analyst", "reason": "...", "spec": "spec.json"}]}
  An accept with "spec" holds for that spec file of the case only (spec.json lacks what spec_designed.json draws).
  A spec filter with a default (decisions/035) opens the workbook in that selection: the state of its field must
  equal the default (the page and the workbook open alike), so it changes no number; it still holds for the specs
  of the case without a default.
"""
import functools
import json
import re
from pathlib import Path

from . import benchmark, cards, colors, dates, dualaxis, excel, expected, filters, formats, heatmap, insight, kpi2
from . import reflines
from . import reconcile_grid, reconcile_lines, registry, scatter, tables
from .match import SCALES, label_unit, parse_number, unit_suffix

MONTHS = ("jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?"
          "|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")
DAYS = "mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:rs?(?:day)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?"
DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}:\d{2}(?::\d{2})?)?\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{1,2}:\d{2}\b"
    rf"|\b(?:{MONTHS})\.?\s+\d{{1,2}}(?:,?\s+\d{{4}})?\b|\b\d{{1,2}}\s+(?:{MONTHS})\b|\bq[1-4]\b|\b(?:19|20)\d{{2}}\b"
    rf"|\b\d{{1,2}}\s+(?:{DAYS})\b",  # '19 Mon': a day of the month and its weekday (decisions/058)
    re.I)
NUMBER = re.compile(r"[-−]?\d(?:[\d,.  ]*\d)?(?:\s?(?:%|pp|bn|mn|[kKMB])(?![A-Za-z]))?")
WORD = re.compile(r"[^\W\d_]{2,}")
SEP = re.compile(r"[·|•;]")
PCT_CALCS = ("percent_of_total", "percent_difference")
FAILING = ("mismatch", "missing", "format")


def _norm(t):
    """Lower case, one space, every dash a hyphen without spaces around it ('North – Harbor' = 'North-Harbor' = 'north - harbor'),
    one apostrophe (decisions/058)."""
    t = t.replace("−", "-").replace("’", "'")
    return re.sub(r"\s*-\s*", "-", _norm_spaces(t))


def _norm_spaces(t):
    return re.sub(r"\s+", " ", t.replace("–", "-").replace("—", "-").replace(" ", " ")).strip().lower()


def _has_words(t):
    return bool(WORD.search(NUMBER.sub(" ", DATE.sub(" ", t))))


# --- numbers on the page ------------------------------------------------------------------------------------------

def _tokens(text):
    """(token, start, skip reason or None) for every number in a text node."""
    masked, out = text, []
    for m in DATE.finditer(text):
        out.append((m.group(0), m.start(), "date"))
        masked = masked[:m.start()] + " " * len(m.group(0)) + masked[m.end():]
    for m in NUMBER.finditer(masked):
        tok, start, before = m.group(0), m.start(), masked[:m.start()]
        if tok[0] in "-−" and re.search(r"\w$", before):  # a hyphen: 'XD-0002', '1-5'
            tok, start, before = tok[1:], start + 1, masked[:start + 1]
        after = masked[m.end():]
        if re.search(r"[A-Za-z_]$|[A-Za-z][-_/]$", before) or re.match(r"[A-Za-z_]", after):
            out.append((tok, start, "identifier"))
        else:
            out.append((tok.strip(), start, None))
    return sorted(out, key=lambda t: t[1])


def _context(item, start):
    """The words that say what a number is: its table cell headers, its own phrase, its tooltip, its axis label,
    or the nearest enclosing element with words (KPI tile label)."""
    seg = next((s for s in _segments(item["text"]) if s[0] <= start < s[1]), (0, len(item["text"])))
    own = item["text"][seg[0]:seg[1]].strip(" ,.:()")
    if "cell" in item:
        c = item["cell"]
        return f"{c.get('group', '')} {c['row']} {c['col']} {own}".strip()
    if _has_words(own) or _names_null(own):
        return own
    for alt in (item.get("title"), item.get("svg_label") and f"{item['svg_label']} {own}", *item.get("up", [])[1:]):
        if alt and (_has_words(alt) or _names_null(alt)):
            return alt
    return own


def _segments(text):
    cuts = [0] + [m.end() for m in SEP.finditer(text)] + [len(text) + 1]
    return list(zip(cuts, cuts[1:]))


def _lines(group, edge, tol=2):
    """Facts grouped into lines: sorted by the edge, a gap over `tol` px starts a new line. Not a fixed grid of
    buckets: a subpixel shift of the browser's layout (214.4 vs 214.6) must not split one column of ticks in two."""
    out = []
    for f in sorted(group, key=lambda f: edge(f["box"])):
        if out and edge(f["box"]) - edge(out[-1][-1]["box"]) <= tol:
            out[-1].append(f)
        else:
            out.append([f])
    return out


def _axis(facts):
    """Number-only svg texts lined up (left, center or right edge) with evenly spaced values: axis ticks."""
    by_svg = {}
    for f in facts:
        if f.get("svg") is not None and f["status"] is None and not _has_words(f["text"]) and not f.get("cell"):
            by_svg.setdefault(f["svg"], []).append(f)
    for group in by_svg.values():
        for edge in (lambda b: b[0], lambda b: b[0] + b[2] / 2, lambda b: b[0] + b[2],
                     lambda b: b[1] + b[3] / 2):
            for line in _lines(group, edge):
                vals = sorted(f["value"] for f in line)
                steps = {round(b - a, 9) for a, b in zip(vals, vals[1:])}
                if len(line) >= 3 and len(steps) == 1 and steps != {0}:
                    for f in line:
                        f["status"], f["reason"] = "skipped", "axis tick"


def _shown(text, start, tok):
    """The number as the page shows it: with a currency symbol before or after it and the parentheses of a negative,
    '($1.2M)' for the token '1.2M'."""
    end = start + len(tok)
    before = re.search(r"(\(?\s?(?:[-−]?[$€£¥])?\s?|\(?(?<![\w)\]])\+)$", text[:start]).group(1)
    after = re.match(r"(\s?₽)?\)?", text[end:]).group(0)
    if after.endswith(")") != before.startswith("("):  # '(East 12)': a parenthesized phrase, not a negative
        before, after = before.lstrip("("), after.rstrip(")")
    return (before + tok + after).strip()


def _line(item):
    """The sentence around a number in an inline element of its own, '<b>10%</b> cancel': the page's text of its
    parent, for the words next to the number (decisions/200). A grid cell is named by its row and column instead."""
    up = item.get("up", [])
    if item.get("inline") and "cell" not in item and len(up) > 1 and not _has_words(item["text"]) \
            and item["text"] in up[1]:
        return up[1]
    return None


def facts(outline):
    """Every number on the page with what it is about."""
    out = []
    reconcile_grid.annotate(outline)  # heatmap cells get their row and column (decisions/127, 200)
    for item in outline.get("texts", []):
        line = _line(item)
        for tok, start, skip in _tokens(item["text"]):
            parsed = None if skip else parse_number(tok)
            f = {"number": tok, "text": item["text"], "context": _context(item, start), "box": item["box"],
                 "status": "skipped" if skip or not parsed else None, "start": start}
            if "cell" in item:
                f["cell"] = True
            if skip or not parsed:
                f["reason"] = skip or "not a number"
            else:
                f["value"], f["step"], f["suffix"], f["pct"] = parsed
                f["unit"] = unit_suffix(item["text"][start:])  # '40.2 h' (decisions/090)
                f["shown"] = _shown(item["text"], start, tok)
                if f["shown"][0] in "-−":  # a minus before the symbol: -$1.2M
                    f["value"] = -abs(f["value"])
                # '(1,234)': an accounting negative, or a phrase in parentheses ('Sales $1.2M (12.5%)'); the value
                # the workbook shows decides
                f["paren"] = f["shown"].startswith("(") and f["shown"].endswith(")")
            if item.get("svg") is not None:
                f["svg"] = item["svg"]
            if line and line.count(tok) == 1:  # twice in the line: which one is unknown, nothing is guessed
                f["around"] = (line, line.index(tok))
            out.append(f)
    _axis(out)
    return out + _chart_facts(outline) + reconcile_lines.facts(outline, out)


def _chart_facts(outline):
    """The numbers of canvas charts, from the chart's data (decisions/058): each value named by its category label,
    its series and the chart's title and heading, like a table cell by its headers. A canvas whose data the page does
    not expose: one fact 'unverified', its numbers are not checked."""
    out, canvases = [], outline.get("canvases", [])
    for ch in outline.get("charts", []):
        for p in ch["points"]:
            parsed = parse_number(p["value"])
            ctx = " ".join(x for x in (p["label"], p["series"], ch.get("title"), ch.get("heading"), p["value"]) if x)
            f = {"number": p["value"], "text": ctx, "context": ctx, "box": canvases[ch["canvas"]]["box"],
                 "start": None, "data": True, "chart": ch["lib"], "status": None if parsed else "skipped"}
            if parsed:
                f["value"], f["step"], f["suffix"], f["pct"] = parsed
                f["shown"], f["paren"] = p["value"], False
            else:
                f["reason"] = "not a number"
            out.append(f)
    for i, c in enumerate(canvases):
        if c.get("data") is False:
            out.append({"number": "canvas", "text": "", "context": f"canvas {i + 1}", "box": c["box"],
                        "status": "unverified", "reason": "canvas: the page exposes no chart data (a Chart.js or "
                                                          "ECharts instance, data-labels + data-values)"})
    return out


# --- numbers in the workbook --------------------------------------------------------------------------------------

def _is_date(member):
    return bool(re.fullmatch(r"\d{4}(-Q[1-4]|-\d{2}(-\d{2})?)?", member))


def _entry(sheet, key, tags, value, pct=False, part=None, fmt=None):
    members = [m for m in (key.split(" | ") if key else []) if not _is_date(m)]
    e = {"sheet": sheet, "key": key, "members": members, "tags": [t for t in dict.fromkeys(tags) if t],
         "value": value, "pct": pct}
    if part:
        e["part"] = part
    if fmt:
        e["fmt"] = fmt
    return e


def _tags(m):
    return [m.get("label"), m["field"]]


def _pct(m):
    return (m.get("table_calc") or {}).get("type") in PCT_CALCS


def entries(spec, exp):
    """expected.compute output -> flat list of the values the workbook shows, each with what names it and, where the
    spec sets one, the field's number format (decisions/032)."""
    spec = registry.expand(spec)  # the sheets expected.compute named (decisions/039)
    calc_fmt = {c["name"]: c["format"] for c in spec.get("calcs", []) if formats.is_number_format(c.get("format"))}
    field_fmt = {}
    for s in spec["sheets"]:
        for m in formats.measures(s):
            if "format" in m and "per" not in m:
                field_fmt[m["field"]] = m["format"]

    def fmt(m):
        if "per" in m:  # a ratio card measure: its own format, not the field's (decisions/110)
            return m.get("format")
        return calc_fmt.get(m["field"]) or field_fmt.get(m["field"])

    out = []
    for s in spec["sheets"]:
        got, t, name = exp.get(s["name"]), s["type"], s["name"]
        out += insight.entries(s, exp, fmt, _entry)  # insight line, tile notes (decisions/045)
        if got is None:
            continue
        if cards.is_cards(s):
            for m in s["measures"]:
                for part, v in got[cards.label(m)].items():  # the change is the card's own percent
                    out.append(_entry(name, "", _tags(m), v, part=part, fmt=fmt(m) if part != "delta" else None))
                points = exp.get(kpi2.points_record({"name": f"{name} · {cards.label(m)} · History"}), {})
                for part in ("max", "last"):  # the sparkline labels (decisions/037); its min is not labelled
                    if part in points:
                        out.append(_entry(name, "", _tags(m), points[part], part=f"history {part}", fmt=fmt(m)))
        elif t == "kpi":
            for m in s["measures"]:  # keyed as expected._label: SUM(Sales), AGG(<aggregate calc>)
                v = got.get(f"{m.get('agg', 'sum').upper()}({m['field']})", got.get(f"AGG({m['field']})"))
                out.append(_entry(name, "", _tags(m), v, fmt=fmt(m)))
        elif t == "registry":
            for key, cols in got.items():
                for c in s["columns"]:
                    for part, tags, what, pct in registry.parts(s, c):  # rank, share, change: their own form
                        out.append(_entry(name, key, tags, cols[part], pct,
                                          fmt=fmt(what) if isinstance(what, dict) else None))
        elif benchmark.is_bench(s):  # the selected member and the benchmark per period (decisions/043)
            m = s["measure"]
            for key, vals in got.items():
                for series, v in vals.items():
                    out.append(_entry(name, key, [series] + _tags(m), v, part=series, fmt=fmt(m)))
        elif t == "combo":  # both layers (decisions/044)
            for key, vals in got.items():
                (bar, line) = vals.values()
                out += [_entry(name, key, _tags(s["bar"]), bar, fmt=fmt(s["bar"])),
                        _entry(name, key, _tags(s["line"]), line, fmt=fmt(s["line"]))]
        elif t == "pareto":  # the bar and the running share (decisions/157)
            for key, vals in got.items():
                (bar, share) = vals.values()
                out += [_entry(name, key, _tags(s["measure"]), bar, fmt=fmt(s["measure"])),
                        _entry(name, key, ["cumulative", "share"], share, True, part="cumulative")]
        elif t == "scatter":  # x and y of each point, the axis lines (decisions/047)
            out += scatter.entries(s, exp, fmt, _entry, _tags)
        elif t == "donut":  # the slices (legend values), their shares, the total in the centre
            m = s["measure"]
            # The label is the caption under the total ('2 742 / incidents'), not a word naming the slices: as their
            # tag it won 'Email incidents 253' of a bar by category from its own [Email] (decisions/069)
            for key, v in exp.get(dualaxis.legend_name(s), {}).items():
                out += [_entry(name, key, [m["field"]], v["value"], fmt=fmt(m)),
                        _entry(name, key, [m["field"], "share"], v["share"], True, part="share")]
            total = _entry(name, "", _tags(m) + ["total"], exp.get(dualaxis.total_record(s)), part="total",
                           fmt=fmt(m))
            total["whole"] = True  # of all members: a text naming one is not about it
            out.append(total)
        elif t == "bar" and "plan" in s:
            for key, vals in got.items():
                (fact, plan) = vals.values()
                out += [_entry(name, key, _tags(s["measure"]), fact, fmt=fmt(s["measure"])),
                        _entry(name, key, _tags(s["plan"]), plan, fmt=fmt(s["plan"]))]
        else:
            m = s["size"] if t in ("treemap", "bubbles") else s["measure"]  # a treemap's labels show its size (decisions/138)
            f = None if m.get("table_calc") else fmt(m)  # a table calc shows its own numbers
            out += [tables.members(s, _entry(name, key, _tags(m), v, _pct(m), fmt=f)) for key, v in got.items()]
            for p in heatmap.parts(s)[1:] if t == "heatmap" else []:  # marginal totals, by their row / column (200)
                out += [_entry(p["name"], key, _tags(m), v, _pct(m), fmt=f) for key, v in exp.get(p["name"], {}).items()]
            if t == "bar" and colors.series_field(s) and not _pct(m):  # stacked segments: the bar's total too
                totals = {}
                for key, v in got.items():
                    bar = key.split(" | ")[0]
                    totals[bar] = totals.get(bar, 0) + (v or 0)
                out += [_entry(name, bar, _tags(m), v, part="stack total") for bar, v in totals.items()]
        for label, v in exp.get(reflines.record(name), {}).items():  # 'weekday avg 76' (decisions/028)
            out.append(_entry(name, "", [label], v, part="reference line"))
        for series, points in exp.get(benchmark.ends_record(name), {}).items():  # labelled line ends (043)
            for part, v in points.items():
                out.append(_entry(name, "", [series], v, part=f"line {part}", fmt=fmt(s["measure"])))
    return out


# --- matching -----------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def _mention_pattern(name):
    # compiled once per name: `qualified` asks for millions of (value, measure) pairs, more than re's own cache holds
    return re.compile(r"(?<![\w])" + re.escape(_norm(name)) + r"(?![\w])")


def _mentions(context, name):
    return _mention_pattern(str(name)).search(context) is not None


# How a page names the empty member that Tableau shows as 'Null' (decisions/056); an em dash only as a word of its own
NULL_NAMES = ("null", "(null)", "(blank)", "blank", "n/a", "(empty)", "(none)", "(not set)", "not set")
EM_DASH = re.compile(r"(?<!\S)—(?!\S)")


def _names_null(raw):
    """Does a page text name the empty member ('(blank)', 'N/A', a lone em dash)?"""
    return any(_mentions(_norm(raw), n) for n in NULL_NAMES) or EM_DASH.search(raw) is not None


# Members written otherwise (decisions/058): a weekday or a month in any of its spellings
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december")
CALENDAR = {**{w: ("wd", i) for i, n in enumerate(WEEKDAYS) for w in (n, n[:3])},
            **{w: ("m", i + 1) for i, n in enumerate(MONTH_NAMES) for w in (n, n[:3])},
            "tues": ("wd", 1), "thur": ("wd", 3), "thurs": ("wd", 3), "sept": ("m", 9)}
_CAL = "|".join(sorted(CALENDAR, key=len, reverse=True))
_DAY_WORD = re.compile(rf"(\d{{1,2}}) ({_CAL})|({_CAL}) (\d{{1,2}})")


def _spellings(word):
    return {w for w, v in CALENDAR.items() if v == CALENDAR[word]}


def _relaxed(member):
    """Other ways a page writes a member: 'Mon' for 'Monday' and back; 'Mon' for '19 Mon' (the day number left out)."""
    n = _norm(member)
    if n in CALENDAR:
        return _spellings(n) - {n}
    m = _DAY_WORD.fullmatch(n)
    return _spellings(m.group(2) or m.group(3)) if m else set()


class _Names:
    """How the page may write each member of the workbook's marks (decisions/058):
    strong   the member as the workbook shows it, or a data value the spec aliases to it (fields.<f>.aliases, 033);
    relaxed  a weekday or month in another spelling, or without the day number ('Mon' for '19 Mon').
    A name inside a longer name of another member does not count: 'East' in 'East Coast 12' names East only if no
    member is called East Coast. Case, spaces and dashes never matter (_norm)."""

    def __init__(self, spec, ents, prof=None):
        raw = {}
        for props in (spec.get("fields") or {}).values():
            for value, label in (props.get("aliases") or {}).items():
                raw.setdefault(label, set()).add(value)
        members = {m for e in ents for m in e["members"] if m != expected.NULL}
        self.strong = {m: {_norm(m)} | {_norm(v) for v in raw.get(m, ())} for m in members}
        self.relaxed = {m: _relaxed(m) - self.strong[m] for m in members}
        names = {n for s in (*self.strong.values(), *self.relaxed.values()) for n in s if n}
        self.patterns = {n: re.compile(r"(?<![\w])" + re.escape(n) + r"(?![\w])") for n in names}
        # data values of the string fields that no mark shows: a qualifier of a number ('Furniture Sales'), 114
        data = {_norm(v) for col in (prof.columns if prof else ()) if col.datatype == "string" for v in col.distinct}
        self.qualifiers = {n for n in data if len(n) >= 3} - names
        self._qualifiers_in = {}  # {text: the qualifiers it holds}; ID columns make qualifiers tens of thousands
        # names with a number inside ('laptop pro 14', 'iphone 15', a band '0-7'): the number is part of the name, not a
        # value (119, 200)
        self.date_axis = {sh["name"] for sh in spec.get("sheets", []) if sh.get("date")}  # date field on cols
        self.numbered = [re.compile(r"(?<![\w])" + re.escape(n) + r"(?![\w])") for n in sorted(names | data)
                         if re.search(r"\d", n) and not NUMBER.fullmatch(n)]

    def inside_name(self, f):
        """Is the number only a part of a member's / data value's name ('Laptop Pro 14')? The text with the names cut
        out no longer holds it as a word."""
        text = _norm(f["text"])
        tok = re.compile(r"(?<![\w.,])" + re.escape(_norm(f["number"])) + r"(?![\w])")
        if not tok.search(text):
            return False
        for p in self.numbered:
            rest = p.sub(" ", text)
            if rest != text and not tok.search(rest):
                return True
        return False

    def occurrences(self, ctx):
        """{name: [(start, end)]} of every member name in a normalized context."""
        out = {}
        for n, p in self.patterns.items():
            spans = [m.span() for m in p.finditer(ctx)]
            if spans:
                out[n] = spans
        return out

    def qualified(self, ctx, tags):
        """Does the text put a data value right before the measure's name? 'Furniture Sales' is Sales for
        Category = Furniture, not the total of Sales (114). Only the adjacent form: a value elsewhere in the context
        ('resolved' near 'Mean time to resolve') says nothing."""
        measures = [_norm(str(t)) for t in tags]
        # _norm keeps a qualifier as the start of 'q t', so a text without q cannot hold 'q t' (decisions/179)
        if ctx not in self._qualifiers_in:
            self._qualifiers_in[ctx] = [q for q in self.qualifiers if q in ctx]
        return any(_mentions(ctx, f"{q} {t}") for q in self._qualifiers_in[ctx] for t in measures)

    def named(self, member, ctx, raw, occ):
        """'strong', 'relaxed' or None: does the text around a number name this member of a mark?"""
        if member == expected.NULL:
            return "strong" if _names_null(raw) else None
        if member not in self.strong:
            return "strong" if _mentions(ctx, member) else None
        own = self.strong[member] | self.relaxed[member]
        longer = [s for n, spans in occ.items() if n not in own for s in spans]
        for strength, names in (("strong", self.strong[member]), ("relaxed", self.relaxed[member])):
            for n in names:
                for a, b in occ.get(n, ()):
                    if not any(A <= a and b <= B and B - A > b - a for A, B in longer):
                        return strength
        return None


# Dates written on the page (decisions/058): what they say of the date of a mark. Day and month orders of numeric dates
# (05/04) are not guessed: only ISO dates, month names, quarters, years and weekdays count.
_ISO = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
_QUARTER = re.compile(r"\b(?:(\d{4}) ?)?q([1-4])\b(?: (\d{4})\b)?")
_YEAR = re.compile(r"(?<![\d.,-])((?:19|20)\d{2})(?![\d.,-])")
_NAMED = re.compile(rf"(?<![\w])(?:(\d{{1,2}}) )?({_CAL})\.?(?![\w])(?: (\d{{1,2}})(?![\d.,]))?")


def _date_marks(raw):
    """{y, q, m, d, wd: value} the text names; a part named twice with two values is dropped (None)."""
    t, c = _norm_spaces(raw), {}

    def put(k, v):
        if v is not None:
            c[k] = v if c.get(k, v) == v else None
    for m in _ISO.finditer(t):
        put("y", int(m.group(1)))
        put("m", int(m.group(2)))
        put("d", m.group(3) and int(m.group(3)))
    for m in _QUARTER.finditer(t):
        put("q", int(m.group(2)))
        put("y", (m.group(1) or m.group(3)) and int(m.group(1) or m.group(3)))
    for m in _YEAR.finditer(_ISO.sub(" ", t)):
        put("y", int(m.group(1)))
    for m in _NAMED.finditer(t):
        kind, i = CALENDAR[m.group(2)]
        put(kind, i)
        day = m.group(1) or (m.group(3) if kind == "m" else None)  # 'Mon 12' is the Monday bar's 12, not the 12th
        if day and 1 <= int(day) <= 31:
            put("d", int(day))
    return {k: v for k, v in c.items() if v is not None}


def _month_label(marks):
    """The text names a month (maybe with its year / quarter), no weekday or day: a label of a date axis (119)."""
    return "m" in marks and not {"wd", "d"} & marks.keys()


def _date_parts(member):
    """A date member of a key ('2025', '2025-Q2', '2025-05', '2025-05-19') -> ({part: value}, the parts that identify
    it at its level)."""
    y, _, rest = member.partition("-")
    if not rest:
        return {"y": int(y)}, ("y",)
    if rest.startswith("Q"):
        return {"y": int(y), "q": int(rest[1])}, ("y", "q")
    if len(rest) == 2:
        return {"y": int(y), "m": int(rest), "q": (int(rest) - 1) // 3 + 1}, ("y", "m")
    d = dates.to_date(member)
    return {"y": d.year, "m": d.month, "q": (d.month - 1) // 3 + 1, "d": d.day, "wd": d.weekday()}, ("y", "m", "d")


def _date_named(marks, e):
    """None: the text names no date of this mark; False: it names another date; 'strong' (the whole date at its
    level) or 'relaxed' (a part of it: 'May' of 2025-05-19)."""
    got = None
    for member in (m for m in (e["key"].split(" | ") if e["key"] else []) if _is_date(m)):
        parts, level = _date_parts(member)
        common = [k for k in marks if k in parts]
        if not common:
            continue
        if any(marks[k] != parts[k] for k in common):
            return False
        strength = "strong" if all(k in marks for k in level) else "relaxed"
        got = "relaxed" if "relaxed" in (got, strength) else strength
    return got


def _equal(f, e):
    v = e["value"]
    if v is None or isinstance(v, str):
        return False
    if f.get("data") and e["pct"] and abs(v - f["value"]) <= f["step"] / 2 + 1e-9:  # a share as a fraction (canvas)
        return True
    shown = [v * 100] if e["pct"] else [v, v * 100] if f["pct"] else [v / SCALES.get(f["suffix"], 1)]
    page = [f["value"], -f["value"]] if f.get("paren") else [f["value"]]
    return any(abs(x - y) <= f["step"] / 2 + 1e-9 for x in shown for y in page)


def _form(f, e):
    """The page's text of a number for the form check: parentheses only where they stand for the minus."""
    neg = f.get("paren") and e["value"] is not None and e["value"] < 0
    return f["shown"] if neg or not f.get("paren") else f["shown"][1:-1]


def _unit_hits(f, e, ctx):
    """A number with a unit ('40.2 h') and a label that names the same unit after a comma ('Mean time to resolve, h',
    'MTTR (h)'): the page writes the label without it, the unit after the number. The label without its unit named
    in the text and the unit: 2 (decisions/090); a number without a unit: 0, as before."""
    if not f.get("unit"):
        return 0
    for t in e["tags"]:
        base, unit = label_unit(str(t))
        if unit == f["unit"] and not _mentions(ctx, t) and _mentions(ctx, base):
            return 2
    return 0


def _candidates(f, ents, names):
    """(entries, relaxed): the entries the text around the number names: all their members (and the date of the mark,
    when the text names a date), plus their measure for a KPI. Most specific (most names matched) only; on a tie, the
    ones whose measure is named: «Incidents closed 172 · 44% of total» is the tile 'Incidents closed', not the cell
    [Total | Incidents] that only shares words with it (decisions/038); then the ones named as the workbook writes
    them. relaxed: ids of the entries named only in another spelling ('Mon' for '19 Mon', decisions/058)."""
    phrase = [e for e in ents if "phrase" in e and insight.next_to(f, e["phrase"])]
    if phrase:  # an insight / note number with the phrase's words right next to it (decisions/045)
        return phrase, set()
    ctx = _norm(f["context"])
    occ = names.occurrences(ctx)
    marks = _date_marks(f["context"].replace(f["number"], " "))  # the number itself is no year
    scored = []
    for e in ents:
        if "phrase" in e:  # its words only count next to the number
            continue
        if not e["members"] and ((f.get("cell") and occ) or names.qualified(ctx, e["tags"])):
            continue  # 'Furniture Sales' is a row's / a slice's, not a KPI's total (105, 114)
        if e.get("whole") and occ:  # a donut's total: 'Software incidents 787' is a bar's, not the total of
            continue  # 'incidents' (its caption), decisions/069
        dated = False
        how = [names.named(m, ctx, f["context"], occ) for m in e["members"]]
        if not all(how):
            continue
        if marks and (d := _date_named(marks, e)) is not None:
            if d is False:  # the text names another date
                continue
            how.append(d)
            dated = bool(f.get("data")) or (_month_label(marks) and e["sheet"] in names.date_axis)
        hits = sum(_mentions(ctx, t) for t in e["tags"]) + _unit_hits(f, e, ctx)
        if how or hits:
            # a canvas label that names the mark's date ('Jan') outranks the sheets that only share words (105)
            scored.append(((dated, len(how) + hits, hits, how.count("strong")), e, "relaxed" in how))
    if not scored:
        return [], set()
    best = max(s for s, _, _ in scored)
    return [e for s, e, _ in scored if s == best], {id(e) for s, e, r in scored if s == best and r}


def _where(e):
    return f"{e['sheet']}" + (f" [{e['key']}]" if e["key"] else "") + (f" {e['part']}" if e.get("part") else "") \
        + f" = {_fmt(e['value'])}"


def _fmt(v):
    return "null" if v is None else f"{v:.6g}" if isinstance(v, float) else str(v)


def _significant(f):
    """Is a coincidence with some value of the workbook evidence? Not for a number with fewer than 3 significant
    digits (1, 12, 44%, 2.6): a dashboard has many such values, one of them equals it by chance (decisions/058)."""
    return len(re.sub(r"\D", "", f["number"]).lstrip("0")) >= 3


def _plural(word):
    return {word, word + "s", word + "es", word[:-1] + "ies" if word.endswith("y") else word}


def _member_counts(spec, ents, prof):
    """[(field, sheet, count)]: how many members of a field a sheet shows ('12 analysts': the bars of By Analyst).
    A key position of a sheet is the field whose values (or aliases) its members are."""
    by_pos = {}
    for e in ents:
        if e["key"] and not e.get("part") and "phrase" not in e:
            for i, m in enumerate(e["key"].split(" | ")):
                by_pos.setdefault((e["sheet"], i), set()).add(m)
    aliases = {k: v.get("aliases") or {} for k, v in (spec.get("fields") or {}).items()}
    out = []
    for (sheet, _), members in by_pos.items():
        for col in prof.columns:
            shown = {aliases.get(col.name, {}).get(v, v) for v in col.distinct} if col.datatype == "string" else set()
            if members - {expected.NULL} and members - {expected.NULL} <= shown:
                out.append((col.name, sheet, len(members)))
    return out


def _counted(f, counts):
    """The sheet showing as many members of a field as the number says, the field's noun right after the number
    ('12 analysts', '3 teams'), or None. Only a match: a count is too weak to call a different one wrong."""
    if f.get("data") or f["pct"] or f["step"] != 1 or f["suffix"]:
        return None
    word = re.match(r"\s*([^\W\d_]+)", f["text"][f["start"] + len(f["number"]):])
    if not word:
        return None
    w = word.group(1).lower()
    return next((f"{sheet}: {n} members of {field}" for field, sheet, n in counts
                 if n == f["value"] and w in _plural(field.split()[-1].lower())), None)


def _match(fs, ents, names, counts):
    reconcile_lines.match(fs, ents, _where)  # points of lines without labels (decisions/123)
    for f in fs:
        if f["status"]:
            continue
        if not f.get("data") and not f["pct"] and not f["suffix"] and names.inside_name(f):
            f["status"], f["reason"] = "skipped", "part of a name"
            continue
        cands, relaxed = _candidates(f, ents, names)
        equal = [e for e in cands if _equal(f, e)]  # of several equal marks, the one the page's form agrees with (105)
        hit = next((e for e in equal if "fmt" not in e or f.get("data") or formats.same_form(_form(f, e), e["fmt"])),
                   equal[0] if equal else None)
        if hit and "fmt" in hit and not f.get("data") and not formats.same_form(_form(f, hit), hit["fmt"]):
            f["status"], f["workbook"] = "format", _where(hit) + \
                f" shown as {formats.render(hit['value'], hit['fmt'])}"
            continue
        if hit:
            rivals = [e for e in cands if e is not hit and e["sheet"] == hit["sheet"] and e.get("part") == hit.get("part")
                      and e["key"] != hit["key"] and not _equal(f, e)]
            if rivals and (id(hit) in relaxed or any(id(e) in relaxed for e in rivals)):
                f["status"], f["workbook"] = "ambiguous", "; ".join(_where(e) for e in [hit] + rivals[:2])
                f["reason"] = "the text names several marks (in another spelling); one of them equals it"
            else:
                f["status"], f["workbook"] = "matched", _where(hit)
            continue
        counted = None if cands else _counted(f, counts)
        if counted:
            f["status"], f["workbook"] = "matched", counted
            continue
        anywhere = [e for e in ents if _equal(f, e)]
        if f.get("cell") and f["value"] == 0 and not any(" | " in (e["key"] or "") for e in cands):
            # a grid cell of 0 with no mark in the workbook (no rows for the pair): Tableau draws it blank (127)
            f["status"] = "unverified"
            f["reason"] = "the page shows 0 in a grid cell, the workbook has no mark for it (the cell is blank)"
            f["workbook"] = "; ".join(_where(e) for e in cands[:3])
        elif cands:
            f["status"], f["workbook"] = "mismatch", "; ".join(_where(e) for e in cands[:3])
            if anywhere and _significant(f):
                f["note"] = f"this value is in {_where(anywhere[0])}"
        elif anywhere and _significant(f):
            f["status"], f["workbook"] = "elsewhere", _where(anywhere[0])
        elif anywhere:
            f["status"], f["workbook"] = "unverified", _where(anywhere[0])
            f["reason"] = (f"small number: {len(anywhere)} value(s) of the workbook equal it, the text ties it to "
                           f"none of them")
        else:
            f["status"] = "missing"


def _view(spec, csv_path, prof, values, where, view):
    """The facts of one state of the page, matched against the workbook in that state."""
    ents = entries(spec, expected.compute(spec, csv_path, values=values, where=where, prof=prof))
    fs = facts(view)
    _match(fs, ents, _Names(spec, ents, prof), _member_counts(spec, ents, prof))
    return fs


def _summary(fs):
    out = {}
    for f in fs:
        out[f["status"]] = out.get(f["status"], 0) + 1
    return out


def check(spec, spec_dir, outline, case=None, spec_name=None):
    """Reconciliation report: {"facts": [...], "stale": [...], "summary": {...}, "states": [...], "ok": bool}.
    facts and summary: the page as it opens; states: the page after each other option of its controls (filter
    states, decisions/058). spec_name: the spec's file name, for accepts bound to one spec of the case."""
    with formats.shown_in(formats.workbook_locale(spec)):  # 'shown as' in the workbook's marks (decisions/085)
        return _check(spec, spec_dir, outline, case, spec_name)


def _check(spec, spec_dir, outline, case, spec_name):
    case = case or {}
    csv_path = expected.data_path(spec, spec_dir)  # several datasources: the folder, by source (decisions/083)
    state = case.get("state") or {}
    prof = expected.profile(spec, spec_dir)
    _check_state(spec, csv_path, state, prof)
    where = {k: set(v) for k, v in state.items()}
    fs = _view(spec, csv_path, prof, case.get("parameters"), where, outline)
    states = _states(spec, csv_path, prof, case, outline, where)
    accepted = [a for a in case.get("accepted", []) if a.get("spec") in (None, spec_name)]
    stale = _accept(fs + [f for s in states for f in s.get("facts", [])], accepted)
    for s in states:
        if "facts" in s:
            s["summary"] = _summary(s["facts"])
            s["status"] = "fail" if any(f["status"] in FAILING for f in s["facts"]) else "checked"
    summary = _summary(fs)
    return {"state": state, "facts": fs, "stale": stale, "summary": summary, "states": states,
            "ok": not stale and not any(f["status"] in FAILING for f in fs)
            and not any(s["status"] == "fail" for s in states)}


# --- filter states (decisions/058) --------------------------------------------------------------------------------

MAX_STATES = 8  # states checked per page besides the one it opens in; more are reported, not checked
ALL = re.compile(r"\(?all\b")


def _options(spec, prof, case, options):
    """{option text: (kind, name, value)} for the options of one control:
    ('filter', field, [values]) a value of a filter card; ('filter', field, None) its (All);
    ('parameter', name, value) a value of a list parameter (decisions/042);
    ('case', None, {field or parameter: values or None}) the case file's 'options' says so;
    ('no card', column, value) a value of a column the spec has no filter card on;
    ('ambiguous', None, [...]) values of several fields. Options naming nothing are left out."""
    cards_ = {f["field"] for f in spec.get("filters", []) if filters.is_dimension(f)}
    aliases = {k: v.get("aliases") or {} for k, v in (spec.get("fields") or {}).items()}
    labels = {}
    for col in prof.columns:
        if col.datatype == "string":
            for v in col.distinct:
                for n in {_norm(v), _norm(aliases.get(col.name, {}).get(v, v))}:
                    labels.setdefault(n, []).append(("filter" if col.name in cards_ else "no card", col.name, [v]))
    for p in spec.get("parameters", []):
        for v in p.get("values", []):
            labels.setdefault(_norm(str(v)), []).append(("parameter", p["name"], v))
    out, explicit = {}, case.get("options") or {}
    for o in options:
        hits = labels.get(_norm(o), [])
        selectable = [h for h in hits if h[0] != "no card"]
        hits = selectable if len(selectable) == 1 else hits  # 'East' of Region (a card) and of Coast (none)
        if o in explicit:
            out[o] = ("case", None, explicit[o])
        elif len(hits) == 1:
            out[o] = hits[0]
        elif hits:
            out[o] = ("ambiguous", None, [f"{k} {n}" for k, n, _ in hits])
    named = {(k, n) for k, n, _ in out.values() if k in ("filter", "no card")}
    for o in options:
        if o not in out and ALL.match(_norm(o)) and len(named) == 1:
            k, n = next(iter(named))
            out[o] = (k, n, None)
    return out


def _state_of(spec, prof, mapping, where, values):
    """(spec, where, parameter values) of the workbook after the option, or a reason it cannot be checked."""
    kind, name, value = mapping
    pars = {p["name"] for p in spec.get("parameters", []) if "values" in p}
    sel = {name: value} if kind == "filter" else value if kind == "case" else {}
    if kind == "parameter":
        return spec, where, {**(values or {}), name: value}
    spec, where, values = json.loads(json.dumps(spec)), dict(where), dict(values or {})
    cards_ = {f["field"]: f for f in spec.get("filters", []) if filters.is_dimension(f)}
    for k, v in sel.items():
        if k in pars:
            values[k] = v
        elif k not in cards_:
            raise ValueError(f"case options: '{k}' is neither a filter card nor a list parameter of the spec")
        elif v is None:  # (All): the workbook user clears the card, whatever its default
            where.pop(k, None)
            cards_[k].pop("default", None)
            cards_[k].pop("exclude", None)
        else:
            unknown = sorted(set(v) - set(prof.col(k).distinct))
            if unknown:
                raise ValueError(f"case options: {k} has no values {unknown} in the data")
            where[k] = set(v)
    return spec, where, values


def _opening(spec, field, where):
    """The values of a filter card the workbook opens with (None: All)."""
    if field in where:
        return set(where[field])
    f = next(f for f in spec.get("filters", []) if f["field"] == field)
    return set(f["default"]) if f.get("default") and not f.get("exclude") else None


def _states(spec, csv_path, prof, case, outline, where):
    """Each other option of each control of the page (one control at a time, from the state the page opens in):
    checked against the workbook with the same selection; the option a control opens with must be the workbook's."""
    out, maps = [], {}
    for ci, c in enumerate(outline.get("controls", [])):
        maps[ci] = _options(spec, prof, case, c["options"])
        for o in c.get("selected", [])[:1]:
            m = maps[ci].get(o)
            sel = {m[1]: m[2]} if m and m[0] == "filter" else m[2] if m and m[0] == "case" else {}
            cards_ = {f["field"] for f in spec.get("filters", []) if filters.is_dimension(f)}
            for field, values in sel.items():
                opening = _opening(spec, field, where) if field in cards_ else False
                if opening is not False and (set(values) if values else None) != opening:
                    out.append({"control": ci, "option": o, "status": "fail",
                                "reason": f"the page opens with {field} = {sorted(values or ['(All)'])}, the "
                                          f"workbook with {sorted(opening or ['(All)'])}"})
    raw = outline.get("states", [])
    for n, st in enumerate(raw):
        c = outline["controls"][st["control"]]
        rec = {"control": st["control"], "label": c.get("label", ""), "option": st["option"]}
        out.append(rec)
        m = maps[st["control"]].get(st["option"])
        if n >= MAX_STATES:
            rec["status"], rec["reason"] = "not checked", f"more than {MAX_STATES} states on the page"
        elif st.get("error"):
            rec["status"], rec["reason"] = "unverified", f"the page failed to switch: {st['error']}"
        elif st.get("same"):
            rec["status"], rec["reason"] = "static", "the page shows the same numbers: the control does not drive it"
        elif m is None:
            rec["status"], rec["reason"] = "unverified", "the option names no filter value or parameter value; " \
                                                         "map it in the case file ('options')"
        elif m[0] == "ambiguous":
            rec["status"], rec["reason"] = "unverified", f"the option names values of several fields: {m[2]}"
        elif m[0] == "no card":
            rec["status"], rec["reason"] = "fail", f"the page filters by {m[1]} ({c['kind']}), the spec has no " \
                                                   f"filter card on it"
        else:
            spec_, where_, values = _state_of(spec, prof, m, where, case.get("parameters"))
            rec["state"] = {k: sorted(v) for k, v in where_.items()}
            if values:
                rec["parameters"] = values
            view = {"texts": st.get("texts", []), "charts": st.get("charts", []),
                    "canvases": outline.get("canvases", []), "svg_labels": st.get("svg_labels", [])}
            rec["facts"] = _view(spec_, csv_path, prof, values or None, where_, view)
    if outline.get("states_skipped"):
        out.append({"status": "not checked", "option": f"{outline['states_skipped']} more options",
                    "reason": "the page has more states than the outline switches"})
    return out


def _check_state(spec, csv_path, state, prof=None):
    """The state is the HTML page's filter selection. A spec filter with a default (decisions/035) opens the
    workbook in a selection of its own: it must be the page's, else the workbook opens with other numbers."""
    cards_ = {f["field"]: f for f in spec.get("filters", []) if filters.is_dimension(f)}
    prof = prof or (expected.profile(spec, csv_path) if "datasources" in spec  # csv_path: the folder (083)
                    else excel.load(csv_path, spec["datasource"]))
    for field, values in state.items():
        if field not in cards_:
            raise ValueError(f"case state: '{field}' is not a filter card of the spec (the workbook user could not "
                             f"select it); filter cards: {sorted(cards_)}")
        unknown = sorted(set(values) - set(prof.col(field).distinct))
        if unknown:
            raise ValueError(f"case state: {field} has no values {unknown} in the data")
        f = cards_[field]
        if f.get("default") and (f.get("exclude") or set(f["default"]) != set(values)):
            raise ValueError(f"case state: the page shows {field} = {sorted(values)}, the workbook opens with "
                             f"default {'all but ' if f.get('exclude') else ''}{sorted(f['default'])}")


def _accept(fs, accepted):
    """Mark accepted failures; return accept rules that matched nothing (the HTML or the spec changed). A rule
    without 'number' accepts any number in its context: a block the spec does not draw, in every filter state; the
    rules with a number go first."""
    stale = []
    for a in sorted(accepted, key=lambda a: "number" not in a):
        if not a.get("reason"):
            raise ValueError(f"accepted {a}: a reason is required")
        if "number" not in a and not a.get("context"):
            raise ValueError(f"accepted {a}: a rule without a number needs a context")
        used = False
        for f in fs:
            if f["status"] in FAILING and a.get("number", f["number"]) == f["number"] and \
                    _norm(a.get("context", "")) in _norm(f["context"] + " " + f["text"]):
                f["accepted_from"], f["status"], f["reason"] = f["status"], "accepted", a["reason"]
                used = True
        if not used:
            stale.append(a)
    return stale


SHOWN = FAILING + ("accepted", "elsewhere", "unverified", "ambiguous")


def _fact_lines(fs, indent="  "):
    out = []
    for f in fs:
        if f["status"] in SHOWN:
            what = f.get("workbook") or "not in the workbook"
            extra = f" ({f['note']})" if f.get("note") else ""
            reason = f" — accepted: {f['reason']}" if f["status"] == "accepted" else \
                f" — {f['reason']}" if f["status"] in ("unverified", "ambiguous") and f.get("reason") else ""
            out.append(f"{indent}{f['status'].upper():<10} {f['number']:>10}  «{f['context'][:70]}»  → {what}{extra}{reason}")
    return out


def _counts(summary):
    return ", ".join(f"{k} {v}" for k, v in sorted(summary.items()))


def report_text(r):
    lines = []
    if r["state"]:
        lines.append("HTML filter state: " + "; ".join(f"{k} = {', '.join(v)}" for k, v in r["state"].items()))
    lines += _fact_lines(r["facts"])
    for a in r["stale"]:
        lines.append(f"  STALE      accepted {a.get('number', 'any number')} «{a.get('context', '')}» matches nothing on the page")
    for s in r.get("states", []):
        what = "; ".join(f"{k} = {', '.join(v)}" for k, v in s.get("state", {}).items()) or "(All)"
        head = f"state «{s['option']}»" + (f" → {what}" if "facts" in s else "")
        tail = _counts(s["summary"]) if "summary" in s else s.get("reason", "")
        lines.append(f"  {s['status'].upper():<10} {head}: {tail}")
        lines += _fact_lines(s.get("facts", []), "      ")
    lines.append("summary: " + summary_line(r) + (f", stale accepts {len(r['stale'])}" if r["stale"] else "")
                 + (" — OK" if r["ok"] else " — FAIL"))
    return "\n".join(lines)


def summary_line(r):
    """'matched 93, …' of the page as it opens, '; states checked 3 of 3' when it has filter states."""
    checked = sum(1 for s in r.get("states", []) if "facts" in s)
    return _counts(r["summary"]) + (f"; states checked {checked} of {len(r['states'])}" if r.get("states") else "")


def problems(r):
    """One line per reason the check fails: a failing number (of the page as it opens or of a filter state), a stale
    accept, a filter state that cannot be the workbook's."""
    bad = [f"{f['status']} {f['number']} «{f['context'][:40]}»" for f in r["facts"] if f["status"] in FAILING]
    for s in r.get("states", []):
        if s["status"] == "fail":
            bad += [f"state «{s['option'][:30]}»: " + (s.get("reason") or "; ".join(
                f"{f['status']} {f['number']} «{f['context'][:30]}»" for f in s["facts"] if f["status"] in FAILING))]
    return bad + [f"stale accepted {a.get('number', 'any number')} «{a.get('context', '')}»" for a in r["stale"]]


def load_case(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None
