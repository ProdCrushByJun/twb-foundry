"""Dates in the CSV: which formats we read, how Tableau reads them, and date filters.

Formats. A column is a date (or datetime) only when every non-empty value has one of the shapes below;
the day/month order of DD/MM/YYYY vs MM/DD/YYYY is decided by the data (a value > 12 in one position) and
an undecidable column fails loudly instead of being guessed. The profiler rewrites the values to ISO
('YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS'), so expected.py and formula.py compute on the parsed dates; the
packaged CSV stays as it is and Tableau parses it with the text-file locale returned by locale(), or the
workbook's locale when any locale reads it (ISO or no dates; decisions/085).

Filters. A spec filter with mode 'range' (min..max, or every date) or 'relative' (the last N periods up to an
anchor, by default the latest date in the data) becomes a shared quantitative / relative-date filter on the exact
date [none:<date>:qk] and a card in the dashboard header row; expected.py keeps the same rows (DateFilter.keeps).
All XML shapes are the ones Desktop 2025.1 saved (decisions/019).
"""
import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from . import design

TEMPLATE_LOCALE = "ru_RU"  # the capability record template's: Desktop 2025.1 on this machine (Windows ru-RU)
# What Desktop writes for a text file in each locale (Text File Properties -> Locale, then Save As):
# the capability record's collation and its number attributes, and a string column's collation.
LOCALES = {
    "ru_RU": dict(collation="ru", string_collation="LRU_RRU", numbers=True),
    "en_US": dict(collation="en_US", string_collation="LEN_RUS", numbers=False),  # no currency/decimal/thousands
}


class DateFormatError(ValueError):
    pass


@dataclass(frozen=True)
class DateFormat:
    label: str  # as messages and the CLI show it
    datatype: str  # date | datetime
    locale: str | None  # text-file locale Tableau reads it with; None = any locale
    pattern: re.Pattern
    order: str  # positions of year, month, day in the pattern groups

    def to_iso(self, raw):
        """'15.03.2024' -> '2024-03-15'; datetimes -> 'YYYY-MM-DD HH:MM:SS'. Raises on impossible dates."""
        g = self.pattern.fullmatch(raw).groups()
        ymd = {k: int(v) for k, v in zip(self.order, g[:3])}
        d = dt.date(ymd["y"], ymd["m"], ymd["d"])
        if self.datatype == "date":
            return d.isoformat()
        h, mi, s = int(g[3]), int(g[4]), int(g[5] or 0)
        return dt.datetime(d.year, d.month, d.day, h, mi, s).isoformat(sep=" ")


_ISO_DAY = r"(\d{4})-(\d{2})-(\d{2})"
_ISO_TIME = r"(\d{2}):(\d{2})(?::(\d{2}))?"
# Non-ISO shapes: day, month and hour with or without a leading zero ('5.1.2024 9:30' and '05.01.2024 09:30'),
# as spreadsheets export them (decisions/051). Desktop 2025.1 read all of them (golden_dates_v2*).
_DOT_DAY, _SLASH_DAY = r"(\d{1,2})\.(\d{1,2})\.(\d{4})", r"(\d{1,2})/(\d{1,2})/(\d{4})"
_TIME = r" (\d{1,2}):(\d{2})(?::(\d{2}))?"
ISO = DateFormat("YYYY-MM-DD", "date", None, re.compile(_ISO_DAY), "ymd")
ISO_DATETIME = DateFormat("YYYY-MM-DD HH:MM[:SS]", "datetime", None, re.compile(_ISO_DAY + " " + _ISO_TIME), "ymd")
ISO_T = DateFormat("YYYY-MM-DDTHH:MM[:SS]", "datetime", None, re.compile(_ISO_DAY + "T" + _ISO_TIME), "ymd")
# Desktop 2025.1 picks a text column's day/month order from the first rows and, when they are ambiguous,
# from the text-file locale (out/dates_lab, decisions/019): ru_RU read '02/01/2024' as 2 January, en_US as
# 1 February. So the locale must match the order: day-first -> ru_RU, month-first -> en_US.
DMY_DOT = DateFormat("DD.MM.YYYY", "date", "ru_RU", re.compile(_DOT_DAY), "dmy")
DMY_DOT_TIME = DateFormat("DD.MM.YYYY HH:MM[:SS]", "datetime", "ru_RU", re.compile(_DOT_DAY + _TIME), "dmy")
DMY_SLASH = DateFormat("DD/MM/YYYY", "date", "ru_RU", re.compile(_SLASH_DAY), "dmy")
MDY_SLASH = DateFormat("MM/DD/YYYY", "date", "en_US", DMY_SLASH.pattern, "mdy")
DMY_SLASH_TIME = DateFormat("DD/MM/YYYY HH:MM[:SS]", "datetime", "ru_RU", re.compile(_SLASH_DAY + _TIME), "dmy")
MDY_SLASH_TIME = DateFormat("MM/DD/YYYY HH:MM[:SS]", "datetime", "en_US", DMY_SLASH_TIME.pattern, "mdy")
FORMATS = (ISO, ISO_DATETIME, ISO_T, DMY_DOT, DMY_DOT_TIME, DMY_SLASH, MDY_SLASH, DMY_SLASH_TIME, MDY_SLASH_TIME)
# one per pattern: slash dates (day-first in the shape) are resolved by _slash()
_SHAPES = (ISO, ISO_DATETIME, ISO_T, DMY_DOT, DMY_DOT_TIME, DMY_SLASH, DMY_SLASH_TIME)
_MONTH_FIRST = {DMY_SLASH: MDY_SLASH, DMY_SLASH_TIME: MDY_SLASH_TIME}
# Looks like a date but is none of the shapes (1-digit ISO parts, AM/PM, a time zone, fractions of a second):
# fail, never a string.
_DATE_LIKE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}([ T]\d|$)|\d{1,2}[./]\d{1,2}[./]\d{4}( |$)")


def _slash(fmt, values, name):
    """DD/MM/YYYY or MM/DD/YYYY (with or without a time), decided by a value > 12 in the day position."""
    firsts = {int(fmt.pattern.fullmatch(v).group(1)) for v in values}
    seconds = {int(fmt.pattern.fullmatch(v).group(2)) for v in values}
    day_first, month_first = max(firsts) > 12, max(seconds) > 12
    if day_first and month_first:
        raise DateFormatError(f"Column '{name}': dates have values > 12 both before and after the first '/', "
                              f"so they are neither DD/MM/YYYY nor MM/DD/YYYY")
    if not (day_first or month_first):
        raise DateFormatError(f"Column '{name}': dates like '{values[0]}' are ambiguous: no value has a day > 12, "
                              f"so DD/MM/YYYY and MM/DD/YYYY read them differently; export the column as "
                              f"YYYY-MM-DD")
    return fmt if day_first else _MONTH_FIRST[fmt]


def detect(values, name):
    """The DateFormat of a column, or None when it is not a date column.

    values: the non-empty raw strings. All of them in one date shape -> that format; all dates but in several
    shapes, a shape with impossible dates or an undecidable day/month order -> DateFormatError.
    """
    if not values:
        return None
    shapes = set()
    for v in values:  # stops at the first value of no shape: a non-date column costs one value, not all of them
        shapes.add(next((f for f in _SHAPES if f.pattern.fullmatch(v)), None))
        if None in shapes:
            break
    if None in shapes:
        odd = next((v for v in values if _DATE_LIKE.match(v) and not any(f.pattern.fullmatch(v) for f in _SHAPES)),
                   None)
        if odd is not None and any(f.pattern.fullmatch(v) for v in values for f in _SHAPES):
            # a real date column with a stray value of another shape: a typo, never silently a string
            raise DateFormatError(f"Column '{name}': '{odd}' looks like a date in a format not supported yet "
                                  f"(supported: {', '.join(f.label for f in FORMATS)}; outside ISO the day, "
                                  f"month and hour may have one digit; times are 24-hour)")
        return None  # a text column; one in no supported shape at all (2024-1-5, AM/PM) is for DATEPARSE, see unparsed()
    if len(shapes) > 1:
        raise DateFormatError(f"Column '{name}': mixed date formats {sorted(f.label for f in shapes)}; "
                              f"Tableau reads one format per column")
    fmt = shapes.pop()
    if fmt in _MONTH_FIRST:
        fmt = _slash(fmt, values, name)
    for v in values:
        try:
            fmt.to_iso(v)
        except ValueError:
            raise DateFormatError(f"Column '{name}': '{v}' is not a valid {fmt.label} date") from None
    return fmt


def unparsed(values):
    """The first value of a text column that looks like a date but fits no supported shape (2024-1-5,
    3/15/2024 2:30 PM, 2024-03-15T14:30Z), else None. Such a column is a string for DATEPARSE (decisions/149)."""
    return next((v for v in values if _DATE_LIKE.match(v)), None)


def locale(formats):
    """Text-file locale the CSV's date formats need; None when any locale reads them (ISO, or no dates), and the
    CSV is then read in the workbook's locale (decisions/085)."""
    need = {f.locale for f in formats if f and f.locale}
    if len(need) > 1:
        raise DateFormatError(f"Date columns need different locales {sorted(need)}: Tableau reads a CSV in one "
                              f"locale; export the dates as YYYY-MM-DD")
    return need.pop() if need else None


def localize_capability(cap, loc):
    """The capability record template (written by Desktop in ru_RU) for the text-file locale `loc`."""
    if loc == TEMPLATE_LOCALE:
        return
    attrs = cap.find("attributes")
    for a in list(attrs):
        name = a.get("name")
        if name in ("currency", "decimal-char", "thousands-char") and not LOCALES[loc]["numbers"]:
            attrs.remove(a)
        elif name == "collation":
            a.text = f'"{LOCALES[loc]["collation"]}"'
        elif name == "locale":
            a.text = f'"{loc}"'


def to_date(iso):
    """A normalized value ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS') -> its calendar date."""
    return dt.datetime.fromisoformat(iso).date()


# ---- date filters (spec filters with mode range | relative) ------------------------------------------------
def is_date_filter(f):
    """range / relative on a date; a range with numeric bounds filters a measure (filters.py, decisions/162)."""
    return f.get("mode", "values") in ("range", "relative") and not isinstance(f.get("min"), (int, float))


class DateFilter:
    """A range / relative filter on a date column, shaped like build.Field for the dependency writer:
    the exact date as a continuous instance, [none:<date>:qk]."""
    derivation, type, tc, kind = "None", "quantitative", None, "date_filter"

    def __init__(self, col, spec, rows):
        where = f"Filter on '{col.name}'"
        if col.datatype not in ("date", "datetime"):
            raise ValueError(f"{where}: mode '{spec['mode']}' needs a date column, '{col.name}' is {col.datatype}")
        self.col, self.spec, self.mode = col, spec, spec["mode"]
        self.name = f"[none:{col.name}:qk]"
        values = [r[col.name] for r in rows if r[col.name] != ""]
        if not values:
            raise ValueError(f"{where}: the column has no dates")
        self.data_last = to_date(max(values))  # ISO strings sort as dates
        if self.mode == "range" and "min" in spec:
            timed = [b for b in (spec["min"], spec["max"]) if len(b) > 10]
            if timed and col.datatype != "datetime":
                raise ValueError(f"{where}: bound '{timed[0]}' has a time of day, '{col.name}' is a date column "
                                 f"(times only on a datetime column)")
            first, last = self.moments()
            if first > last:
                raise ValueError(f"{where}: min {spec['min']} is after max {spec['max']}")

    @property
    def anchor(self):
        """relative: the date the periods count back from; default the latest date in the data."""
        return dt.date.fromisoformat(self.spec["anchor"]) if "anchor" in self.spec else self.data_last

    def bounds(self):
        """(first, last) calendar dates kept, inclusive; None = every row (range without min/max)."""
        if self.mode == "range":
            s = self.spec
            return (dt.date.fromisoformat(s["min"][:10]), dt.date.fromisoformat(s["max"][:10])) if "min" in s else None
        period, n = self.spec["period"], self.spec["last"]
        end = trunc(self.anchor, period)
        return add(end, -(n - 1), period), add(add(end, 1, period), -1, "day")

    def moments(self):
        """range: (first, last) moments kept, inclusive, as datetimes. A bound may carry a time of day on a datetime
        column ('2024-03-01 08:00'); a max without one keeps its whole day (23:59:59, decisions/019, 051)."""
        s = self.spec
        first = dt.datetime.fromisoformat(s["min"])
        last = dt.datetime.fromisoformat(s["max"]) if len(s["max"]) > 10 else dt.datetime.combine(
            dt.date.fromisoformat(s["max"]), dt.time(23, 59, 59))
        return first, last

    def keeps(self, value):
        """Does the filter keep a row with this (ISO) value? Nulls drop out unless nothing is filtered."""
        b = self.bounds()
        if b is None:
            return True
        if value == "":
            return False
        if self.mode == "range" and self.col.datatype == "datetime":
            first, last = self.moments()
            return first <= dt.datetime.fromisoformat(value) <= last
        return b[0] <= to_date(value) <= b[1]

    def literal(self, moment):
        """A range bound as Desktop writes it for this column: #2024-07-03# (date), #2025-03-31 23:59:59# (datetime)."""
        if self.col.datatype == "date":
            return f"#{moment.date().isoformat()}#"
        return f"#{moment.isoformat(sep=' ')}#"

    def write(self, parent, column):
        """The shared filter element, in the shapes Desktop 2025.1 saved (out/dates_lab, decisions/019)."""
        if self.mode == "range":
            b = self.bounds()
            el = ET.SubElement(parent, "filter", {"class": "quantitative", "column": column,
                                                  "included-values": "all" if b is None else "in-range"})
            if b is not None:  # a datetime column keeps the whole last day, unless max has a time of day
                for tag, moment in zip(("min", "max"), self.moments()):
                    ET.SubElement(el, tag).text = self.literal(moment)
            return el
        return ET.SubElement(parent, "filter", {
            "class": "relative-date", "column": column, "first-period": str(1 - self.spec["last"]),
            "include-future": "true", "include-null": "false", "last-period": "0",
            # the anchor is a datetime even on a date column (Desktop rewrote #2025-06-15# so, golden_dates_us)
            "period-anchor": f"#{self.anchor.isoformat()} 00:00:00#", "period-type-v2": self.spec["period"]})


def manifest_flags(manifest, filters):
    """Desktop 2025.1 reads a relative date filter's period-type-v2 only under ISO8601PeriodTypes: without the flag
    it refused the file ("attribute 'period-type-v2' is not declared for element 'filter'"). Range filters do not
    need it (reference workbooks with date ranges have no such flag). The manifest is in alphabetical order."""
    if any(isinstance(f, DateFilter) and f.mode == "relative" for f in filters):
        tags = [c.tag for c in manifest]
        manifest.insert(next((i for i, t in enumerate(tags) if t > "ISO8601PeriodTypes"), len(tags)),
                        ET.Element("ISO8601PeriodTypes"))


def check_filters(spec):
    """One filter per date field; date cards only in the dashboard header row, the placement checked in Desktop."""
    fields = [f["field"] for f in spec.get("filters", [])]
    dup = sorted({f["field"] for f in spec.get("filters", []) if is_date_filter(f) and fields.count(f["field"]) > 1})
    if dup:
        raise ValueError(f"Filters repeat the date fields {dup}: Tableau keeps one filter per field")
    d = spec["dashboard"]
    if any(is_date_filter(f) for f in spec.get("filters", [])) and (
            d.get("sidebar") or not (d.get("title") or d.get("subtitle"))):
        raise ValueError(f"Dashboard '{d['name']}': date filter cards go in the header row (decisions/019); give "
                         f"the dashboard a title and no sidebar")


def card_px(f):
    """Fixed width of a filter card in the dashboard header row (without its margins)."""
    if isinstance(f, DateFilter) and f.mode == "range":
        return design.HEADER_DATETIME_RANGE_PX if f.col.datatype == "datetime" else design.HEADER_DATE_RANGE_PX
    return design.HEADER_FILTER_PX


def trunc(d, period):
    if period == "year":
        return d.replace(month=1, day=1)
    if period == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    if period == "month":
        return d.replace(day=1)
    if period == "week":  # workbook date-options: start-of-week = monday
        return d - dt.timedelta(days=d.weekday())
    return d


def add(d, n, period):
    """d + n periods; d is the start of a period (any day for day/week)."""
    if period in ("day", "week"):
        return d + dt.timedelta(days=n * (7 if period == "week" else 1))
    months = d.year * 12 + d.month - 1 + n * {"year": 12, "quarter": 3, "month": 1}[period]
    return d.replace(year=months // 12, month=months % 12 + 1)


# ---- a bar along a date (decisions/090) ---------------------------------------------------------------------------
# A bar sheet with 'date_level' puts its date dimension on the shelf as a discrete truncation [tmn:<date>:ok]
# (derivation Month-Trunc, type ordinal): one header per period, the bars stacked by the color field, as Desktop
# 2025.1 writes it (reference books: EnterpriseRiskDashboard 2025.1.2, SuperMartSalesOverview 2025.2.2). A month
# header is labelled with the label style text-format '*mmm' ('Jan'; RWFD-TwitterDashboard), '*mmm yyyy' when the
# data spans more than one year.
BAR_UNSUPPORTED = ("plan", "top", "reference")  # not drawn along a date yet: no golden pattern


def bar_level(s):
    """The date level of a bar along a date, None for a bar of members."""
    return s.get("date_level") if s.get("type") in ("bar", "combo") else None  # combo along a date: 140


def _text_hint(col):
    return (f" (its values like '{col.date_like}' are in no date shape the CSV reader supports; make a date with "
            f"DATEPARSE or export YYYY-MM-DD)") if getattr(col, "date_like", None) else ""


def check_bar(s, col):
    """A bar with date_level: its dimension is a date column; the bar's options that need members are refused."""
    where = f"Sheet '{s['name']}'"
    if col.datatype not in ("date", "datetime"):
        raise ValueError(f"{where}: date_level needs a date dimension; '{s['dimension']}' is {col.datatype}{_text_hint(col)}")
    bad = [k for k in BAR_UNSUPPORTED if k in s]
    c = s.get("color", "")
    if not isinstance(c, str) and not ("highlight" in c and c.get("field")):  # a highlighted series is stacked (111)
        bad.append("color {field, ...} other than {field, highlight}")
    if bad:
        raise ValueError(f"{where}: {', '.join(bad)} on a bar along a date (date_level) is not supported yet")


def heat_level(s):
    """The date level of a heatmap's columns, None for columns of members."""
    return s.get("date_level") if s.get("type") == "heatmap" else None


def check_heat(s, col):
    """A heatmap with date_level: its cols is a date column and has no column margin (the margin is a bar sheet over
    the members of the field)."""
    where = f"Sheet '{s['name']}'"
    if col.datatype not in ("date", "datetime"):
        raise ValueError(f"{where}: date_level needs a date in cols; '{s['cols']}' is {col.datatype}{_text_hint(col)}")
    if "cols" in s.get("margins", {}):
        raise ValueError(f"{where}: a column margin on date columns (date_level) is not supported yet")


def period_labels(level, values):
    """The header texts of the periods of a date column as Desktop shows them with bar_label_format (month: 'Jan'),
    the truncation's own text otherwise (the widths only)."""
    from . import expected
    if level == "month":
        return sorted({dt.date(2000, expected._trunc(v, level) and int(expected._trunc(v, level)[5:7]), 1).strftime("%b")
                       for v in values if v})
    return sorted({expected._trunc(v, level) for v in values if v})


def bar_label_format(level, values):
    """The header text-format of a bar's date periods (values: the column's ISO dates), None for Tableau's own."""
    if level in ("week", "day"):  # 'Mar 2', not 'March 2, 2026' (polish-26)
        return "*mmm d"
    if level != "month":
        return None
    years = {v[:4] for v in values if v}
    return "*mmm" if len(years) <= 1 else "*mmm yyyy"
