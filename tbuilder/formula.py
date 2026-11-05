"""Tableau calculated fields: a strict formula subset we can both emit and evaluate.

Every spec formula is parsed and type-checked here before anything is written, so the
generator never emits a formula Tableau would flag, and expected.py recomputes each
calculated field independently of the XML.

Subset: numbers, "strings", [Field] references (CSV columns or other calcs), + - * /,
= == <> != < <= > >=, AND OR NOT, TRUE FALSE, IF ... THEN ... ELSEIF ... ELSE ... END,
aggregates SUM AVG MIN MAX COUNT COUNTD, functions ZN ABS ROUND, FULLNAME() (the viewer's name, a constant string),
DATETRUNC('level', date) and DATEADD('level', integer, date) with level year|quarter|month|week|day,
FIXED level-of-detail expressions {FIXED [Dim], ... : AGG(...)} / {FIXED : AGG(...)} / {AGG(...)}.
FIXED is evaluated over the full dataset, as Tableau computes it before dimension filters.
CASE subject WHEN literal THEN value ... [ELSE value] END. Parameters (tbuilder/params.py): [Parameters].[Name] or
a bare [Name] that is no column or calc; a parameter is a constant (mixes with aggregate and row-level values) and is
evaluated at its current value (the default, unless expected.py overrides it); a string parameter whose values are
all date levels may be the level of DATETRUNC/DATEADD.
Dates (rewritten to ISO 'YYYY-MM-DD' by the profiler, tbuilder/dates.py) evaluate to datetime.date, datetime
columns ('YYYY-MM-DD HH:MM:SS') to datetime.datetime (decisions/051). Weeks start on Monday, as the
workbook's date-options declare, and DATEADD clamps to the month end (Jan 31 + 1 month = Feb 28).
Levels 'hour' and 'minute' (DATETRUNC, DATEADD, DATEDIFF, DATEPART, DATENAME) need datetime arguments; on a datetime
a date level truncates to midnight, and DATEDIFF counts the level boundaries crossed (10:59 -> 11:00 is 1 hour).
STR of a datetime prints 'YYYY-MM-DD HH:MM:SS' (decisions/055); comparing a date with a datetime is refused (not
checked in Desktop).

Functions v2 (decisions/031; each checked against Desktop 2025.1, tests/fixtures/funcs_lab):
logical IIF(cond, then, else [, unknown]), IFNULL(x, y), ISNULL(x), subject IN (literal, ...); MAX(a, b) / MIN(a, b)
of two numbers: the larger / smaller, NULL when either is (polish-26b: a slope's label positions);
dates DATEDIFF('level', start, end [, 'weekday']) (level boundaries crossed), DATEPART / DATENAME('level', date
[, 'weekday']) with level year|quarter|month|week|weekday|dayofyear|day, YEAR QUARTER MONTH WEEK DAY. As Desktop:
'weekday' is Sunday = 1 whatever the week start, WEEK() counts Sunday-started weeks, DATEPART('week') follows the
workbook (Monday), DATENAME names are English in any workbook locale;
conversion STR (a real prints 17 significant digits: STR(0.1) = "0.10000000000000001", STR(1.0) = "1"; a date
prints YYYY-MM-DD), INT (truncates; a string that is no number -> NULL), FLOAT;
strings CONTAINS STARTSWITH ENDSWITH (case-sensitive), LEFT RIGHT MID (1-based), UPPER LOWER (Unicode, ß -> SS),
REPLACE, LEN, TRIM, and + between strings.

Functions v3 (decisions/055; each checked against Desktop 2025.1, tests/fixtures/funcs_v3): date literals
#YYYY-MM-DD# (date) and #YYYY-MM-DD HH:MM:SS# (datetime), strictly (no 24:00:00, no T, no locale forms);
MAKEDATE(y, m, d) (a month / day out of range rolls over), MAKETIME(h, m, s) (carries, wraps at 24 h on 1899-12-30),
MAKEDATETIME(date, time), DATEPARSE("ICU pattern", string) -> datetime (no match or no such date -> NULL),
DATE of a date / datetime, DATETIME of a datetime (of a string both are refused: Desktop guesses month-first),
ISOYEAR ISOQUARTER ISOWEEK ISOWEEKDAY, SPLIT(string, "delimiter", +-token literal), FIND(string, substring [, start]),
FINDNTH(string, substring, n >= 1 literal) (1-based, 0 = not found, no overlaps); INT / FLOAT read "1,234.5"
(comma groups thousands) but not "1,5"; a date branch next to a datetime one (IF / CASE / IIF / IFNULL) makes the
result a datetime (IFNULL of two dates stays a date: Desktop, golden_calcs_v4).

Functions v4 (decisions/149; each checked against Desktop 2025.1, golden_calcs_v4): DATEPARSE patterns MMM / MMMM
(English month names, case-insensitive: a full name or its first 3 letters, "Sept" is NULL), yy (exactly 2 digits: < 70 ->
20yy, else 19yy; other lengths = the literal year), hh / h with a (12-hour, valid only 1..12 with am/pm in any case,
otherwise NULL); yyyy / M / d read 1-4 / 1-2 digit numbers ("2024-1-5").

Table calculation functions (decisions/034): RANK RANK_DENSE (expr [, 'asc'|'desc'], competition / dense ranks,
nulls unranked), WINDOW_SUM WINDOW_AVG WINDOW_MAX WINDOW_MIN (expr [, start, end]; offsets are integer literals or
FIRST() / LAST()), LOOKUP(expr, offset literal), RUNNING_SUM, TOTAL (the expression over the partition's rows),
INDEX() FIRST() LAST() SIZE(); v2 (decisions/147): RANK_UNIQUE (ties by position), RUNNING_AVG / MIN / MAX / COUNT,
WINDOW_COUNT / WINDOW_MEDIAN, PREVIOUS_VALUE(seed) (this calc at the previous mark, the seed at the first). NULL marks
are skipped by RUNNING_* and WINDOW_*; SIZE counts them. They are aggregate-level and evaluated over the marks of one partition (table_values): the
calc's compute_using lists the sheet dimensions it runs along (required: no default direction), the other sheet
dimensions partition it. Not inside an aggregate or a LOD, and a calc does not reference another table calc.
"""
import calendar
import datetime as dt
import hashlib
import math
import re
from dataclasses import dataclass, field

from . import formats

AGGREGATES = {"SUM", "AVG", "MIN", "MAX", "COUNT", "COUNTD", "MEDIAN", "PERCENTILE"}  # PERCENTILE(x, p): decisions/144
FUNCTIONS = {"ZN": (1, 1), "ABS": (1, 1), "ROUND": (1, 2), "DATETRUNC": (2, 2), "DATEADD": (3, 3), "FULLNAME": (0, 0),
             # logical (decisions/031)
             "IIF": (3, 4), "IFNULL": (2, 2), "ISNULL": (1, 1),
             # dates
             "DATEDIFF": (3, 4), "DATEPART": (2, 3), "DATENAME": (2, 3),
             "YEAR": (1, 1), "QUARTER": (1, 1), "MONTH": (1, 1), "WEEK": (1, 1), "DAY": (1, 1),
             # type conversion
             "STR": (1, 1), "INT": (1, 1), "FLOAT": (1, 1),
             # strings
             "CONTAINS": (2, 2), "STARTSWITH": (2, 2), "ENDSWITH": (2, 2), "LEFT": (2, 2), "RIGHT": (2, 2),
             "MID": (2, 3), "UPPER": (1, 1), "LOWER": (1, 1), "REPLACE": (3, 3), "LEN": (1, 1), "TRIM": (1, 1),
             # functions v3 (decisions/055)
             "MAKEDATE": (3, 3), "MAKETIME": (3, 3), "MAKEDATETIME": (2, 2), "DATEPARSE": (2, 2), "DATE": (1, 1),
             "DATETIME": (1, 1), "ISOYEAR": (1, 1), "ISOQUARTER": (1, 1), "ISOWEEK": (1, 1), "ISOWEEKDAY": (1, 1),
             "SPLIT": (3, 3), "FIND": (2, 3), "FINDNTH": (3, 3)}
# table calculation functions (decisions/034): name -> (min args, max args)
# v2 (decisions/147): SIZE, RANK_UNIQUE, RUNNING_AVG / MIN / MAX / COUNT, WINDOW_COUNT / MEDIAN, PREVIOUS_VALUE
TABLE_CALCS = {"RANK": (1, 2), "RANK_DENSE": (1, 2), "RANK_UNIQUE": (1, 2), "WINDOW_SUM": (1, 3),
               "WINDOW_AVG": (1, 3), "WINDOW_MAX": (1, 3), "WINDOW_MIN": (1, 3), "WINDOW_COUNT": (1, 3),
               "WINDOW_MEDIAN": (1, 3), "LOOKUP": (2, 2), "RUNNING_SUM": (1, 1), "RUNNING_AVG": (1, 1),
               "RUNNING_MIN": (1, 1), "RUNNING_MAX": (1, 1), "RUNNING_COUNT": (1, 1), "TOTAL": (1, 1),
               "PREVIOUS_VALUE": (1, 1), "INDEX": (0, 0), "FIRST": (0, 0), "LAST": (0, 0), "SIZE": (0, 0)}
FULLNAME_VALUE = "<Full Name>"  # the signed-in user's name in Tableau; a stand-in for evaluation
DATE_LEVELS = ("year", "quarter", "month", "week", "day")
PART_LEVELS = DATE_LEVELS + ("weekday", "dayofyear")  # DATEPART / DATENAME
TIME_LEVELS = ("hour", "minute")  # datetime arguments only (decisions/051)
DATES = ("date", "datetime")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
START_OF_WEEK = "monday"  # the workbook's date-options (build.py)
DATE_PARTS = {"YEAR": "year", "QUARTER": "quarter", "MONTH": "month", "WEEK": "week", "DAY": "day"}
# DATENAME names: English in Desktop 2025.1 whatever the workbook locale (none, ru_RU, en_US: out/funcs_lab, decisions/031)
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
NUMERIC = ("integer", "real")

_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+(?:\.\d+)?)
  | (?P<str>"(?:[^"]|"")*"|'(?:[^']|'')*')
  | (?P<date>\#[^\#\n]*\#)
  | (?P<param>\[Parameters\]\.\[[^\[\]]+\])
  | (?P<field>\[[^\[\]]+\])
  | (?P<op><=|>=|<>|!=|==|[-+*/()=<>,{}:])
  | (?P<word>[A-Za-z_][A-Za-z_0-9]*)
""", re.X)


class FormulaError(ValueError):
    pass


@dataclass
class Tok:
    kind: str
    text: str
    start: int
    end: int


def tokenize(src):
    toks, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            hint = " (a date literal #...# is not closed)" if src[pos] == "#" else ""
            raise FormulaError(f"unexpected character {src[pos]!r} at position {pos}{hint}")
        if m.lastgroup != "ws":
            text = m.group()
            kind = m.lastgroup
            if kind == "word":
                text = text.upper()
            toks.append(Tok(kind, text, m.start(), m.end()))
        pos = m.end()
    return toks


# ---- AST ----------------------------------------------------------------------------------
@dataclass
class Num:
    value: object


@dataclass
class Str:
    value: str


@dataclass
class Bool:
    value: bool


@dataclass
class DateLit:
    """#YYYY-MM-DD# (a date) or #YYYY-MM-DD HH:MM:SS# (a datetime), decisions/055."""
    value: object  # datetime.date | datetime.datetime


_DATE_LITERAL = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}):(\d{2}))?")


def date_literal(text):
    """'#2024-01-31#' -> date, '#2024-01-31 09:00:00#' -> datetime; anything else is a FormulaError.

    Strict on purpose: Python 3.11+ fromisoformat reads 24:00:00 as the next midnight and accepts forms Desktop
    may read otherwise (2024-01-31T09:00, 20240131), so every field is checked here."""
    m = _DATE_LITERAL.fullmatch(text[1:-1])
    if not m:
        raise FormulaError(f"date literal {text} must be #YYYY-MM-DD# or #YYYY-MM-DD HH:MM:SS# (24-hour time)")
    y, mo, d = (int(x) for x in m.groups()[:3])
    try:
        day = dt.date(y, mo, d)
    except ValueError:
        raise FormulaError(f"date literal {text}: {y:04d}-{mo:02d}-{d:02d} is not a calendar date") from None
    if m.group(4) is None:
        return day
    h, mi, s = (int(x) for x in m.groups()[3:])
    if h > 23 or mi > 59 or s > 59:
        raise FormulaError(f"date literal {text}: time must be 00:00:00 .. 23:59:59")
    return dt.datetime(y, mo, d, h, mi, s)


@dataclass
class Ref:
    name: str
    start: int
    end: int


@dataclass
class Unary:
    op: str
    arg: object


@dataclass
class Bin:
    op: str
    left: object
    right: object


@dataclass
class Func:
    name: str
    args: list


@dataclass
class If:
    branches: list  # [(cond, value)]
    otherwise: object  # node or None


@dataclass
class Lod:
    kind: str  # FIXED | INCLUDE | EXCLUDE
    dims: list  # [Ref]
    body: object  # aggregate expression


@dataclass
class Param:
    """[Parameters].[Name]: a parameter by its spec name."""
    name: str
    start: int
    end: int


@dataclass
class Case:
    subject: object
    branches: list  # [(literal node, value)]
    otherwise: object  # node or None


class _Parser:
    def __init__(self, src):
        self.toks = tokenize(src)
        self.i = 0

    def peek(self, *texts):
        t = self.toks[self.i] if self.i < len(self.toks) else None
        return t if t and (not texts or t.text in texts) else None

    def take(self, *texts):
        t = self.peek(*texts)
        if not t:
            got = self.toks[self.i].text if self.i < len(self.toks) else "end of formula"
            raise FormulaError(f"expected {' or '.join(texts) or 'a value'}, got {got!r}")
        self.i += 1
        return t

    def parse(self):
        node = self.expr()
        if self.i != len(self.toks):
            raise FormulaError(f"unexpected {self.toks[self.i].text!r} after the end of the expression")
        return node

    def expr(self):
        node = self.and_()
        while self.peek("OR"):
            self.i += 1
            node = Bin("OR", node, self.and_())
        return node

    def and_(self):
        node = self.not_()
        while self.peek("AND"):
            self.i += 1
            node = Bin("AND", node, self.not_())
        return node

    def not_(self):
        if self.peek("NOT"):
            self.i += 1
            return Unary("NOT", self.not_())
        return self.cmp()

    def cmp(self):
        node = self.add()
        if self.peek("IN"):
            return self.in_(node)
        t = self.peek("=", "==", "<>", "!=", "<", "<=", ">", ">=")
        if t:
            self.i += 1
            op = {"==": "=", "!=": "<>"}.get(t.text, t.text)
            node = Bin(op, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while self.peek("+", "-"):
            op = self.take().text
            node = Bin(op, node, self.mul())
        return node

    def mul(self):
        node = self.unary()
        while self.peek("*", "/"):
            op = self.take().text
            node = Bin(op, node, self.unary())
        return node

    def unary(self):
        if self.peek("-"):
            self.i += 1
            return Unary("-", self.unary())
        return self.primary()

    def primary(self):
        t = self.peek()
        if t is None:
            raise FormulaError("formula ends unexpectedly")
        if t.kind == "num":
            self.i += 1
            return Num(float(t.text) if "." in t.text else int(t.text))
        if t.kind == "str":
            self.i += 1
            q = t.text[0]
            return Str(t.text[1:-1].replace(q + q, q))
        if t.kind == "date":
            self.i += 1
            return DateLit(date_literal(t.text))
        if t.kind == "field":
            self.i += 1
            return Ref(t.text[1:-1], t.start, t.end)
        if t.kind == "param":
            self.i += 1
            return Param(t.text[len("[Parameters].["):-1], t.start, t.end)
        if t.text == "(":
            self.i += 1
            node = self.expr()
            self.take(")")
            return node
        if t.text in ("TRUE", "FALSE"):
            self.i += 1
            return Bool(t.text == "TRUE")
        if t.text == "IF":
            return self.if_()
        if t.text == "CASE":
            return self.case()
        if t.text == "{":
            return self.lod()
        if t.kind == "word":
            self.i += 1
            if t.text not in AGGREGATES and t.text not in FUNCTIONS and t.text not in TABLE_CALCS:
                raise FormulaError(f"function {t.text} is not supported (allowed: "
                                   f"{', '.join(sorted(AGGREGATES | set(FUNCTIONS) | set(TABLE_CALCS)))})")
            self.take("(")
            args = [] if self.peek(")") else [self.expr()]
            while args and self.peek(","):
                self.i += 1
                args.append(self.expr())
            self.take(")")
            return Func(t.text, args)
        raise FormulaError(f"unexpected {t.text!r}")

    def in_(self, subject):
        """subject IN (literal, ...): a Func("IN", [subject, literals...]); the list takes literals only."""
        self.take("IN")
        self.take("(")
        values = [self._literal("IN (...)")]
        while self.peek(","):
            self.i += 1
            values.append(self._literal("IN (...)"))
        self.take(")")
        return Func("IN", [subject] + values)

    def _literal(self, where):
        """A literal value: a number (optionally negative), "text", TRUE, FALSE or #date#."""
        neg = self.peek("-") is not None
        self.i += neg
        lit = self.primary()
        if not isinstance(lit, (Num, Str, Bool, DateLit)):
            raise FormulaError(f"{where} takes a literal value (a number, \"text\", TRUE, FALSE or #YYYY-MM-DD#)")
        if neg:
            if not isinstance(lit, Num):
                raise FormulaError(f"{where}: '-' needs a number")
            lit = Num(-lit.value)
        return lit

    def if_(self):
        self.take("IF")
        branches = [(self.expr(), self._then())]
        while self.peek("ELSEIF"):
            self.i += 1
            branches.append((self.expr(), self._then()))
        otherwise = None
        if self.peek("ELSE"):
            self.i += 1
            otherwise = self.expr()
        self.take("END")
        return If(branches, otherwise)

    def _then(self):
        self.take("THEN")
        return self.expr()

    def case(self):
        """CASE subject WHEN literal THEN value ... [ELSE value] END; WHEN takes literals only."""
        self.take("CASE")
        subject, branches = self.expr(), []
        while self.peek("WHEN"):
            self.i += 1
            branches.append((self._literal("CASE ... WHEN"), self._then()))
        if not branches:
            raise FormulaError("CASE needs at least one WHEN ... THEN ...")
        otherwise = None
        if self.peek("ELSE"):
            self.i += 1
            otherwise = self.expr()
        self.take("END")
        return Case(subject, branches, otherwise)

    def lod(self):
        """{FIXED [a], [b] : AGG(...)}, {FIXED : AGG(...)} or the shorthand {AGG(...)}."""
        self.take("{")
        kind, dims = "FIXED", []
        if self.peek("FIXED", "INCLUDE", "EXCLUDE"):
            kind = self.take().text
            if not self.peek(":"):
                dims.append(self.expr())
                while self.peek(","):
                    self.i += 1
                    dims.append(self.expr())
            self.take(":")
        body = self.expr()
        self.take("}")
        return Lod(kind, dims, body)


def parse(src):
    return _Parser(src).parse()


# ---- calculated fields --------------------------------------------------------------------
def calc_id(name):
    """Deterministic Tableau-style internal name: Calculation_<19 digits>."""
    n = int(hashlib.sha1(name.encode("utf-8")).hexdigest(), 16) % (9 * 10 ** 18) + 10 ** 18
    return f"Calculation_{n}"


@dataclass
class Calc:
    name: str  # caption shown in Tableau
    formula: str  # as written in the spec
    node: object
    datatype: str  # integer | real | string | boolean | date
    is_agg: bool  # aggregate calc (SUM([x])/SUM([y])) vs row-level
    id: str  # internal column name, Calculation_...
    xml_formula: str  # formula with calc references replaced by internal names
    fmt: object  # None | "percent"
    raw_deps: list  # CSV columns referenced, transitively
    calc_deps: list  # other calcs referenced, transitively
    view_lod: bool = False  # the whole formula is an INCLUDE/EXCLUDE LOD (a view-dependent measure)
    uses_view_lod: bool = False  # INCLUDE/EXCLUDE anywhere (here or in referenced calcs)
    params: list = field(default_factory=list)  # parameters referenced, transitively (spec names)
    table_calc: bool = False  # uses table calculation functions (decisions/034)
    compute_using: list = field(default_factory=list)  # the sheet dimensions a table calc runs along


@dataclass
class View:
    """The sheet an INCLUDE/EXCLUDE LOD is evaluated in."""
    dims: list  # [(field name, row -> key)] for every dimension on the sheet (date fields truncated)
    rows: list  # sheet rows after dimension filters


def _unify(types, where):
    types = [t for t in types if t is not None]
    if not types:
        return None
    if all(t in NUMERIC for t in types):
        return "real" if "real" in types else "integer"
    if set(types) == set(DATES):  # a date branch next to a datetime one: datetime (decisions/055)
        return "datetime"
    if len(set(types)) == 1:
        return types[0]
    raise FormulaError(f"{where}: incompatible types {sorted(set(types))}")


class CalcSet:
    """All calculated fields of a spec, checked against the CSV columns."""

    def __init__(self, specs, column_types, rows=None, params=None):
        self.column_types = dict(column_types)  # CSV column -> integer|real|string|date
        self.rows = rows  # full dataset: FIXED LODs aggregate over it, before dimension filters
        self.params = dict(params or {})  # spec name -> params.Parameter (datatype, values, value, ref)
        self._lod_cache = {}
        self._lod_depth = 0  # type check: inside a LOD body (no table calcs there)
        self._tc_root = None
        self._tc = None  # evaluation: (marks of the partition, current position) of a table calc
        self._as_datetime = set()  # id() of IF / CASE / IIF / IFNULL nodes whose date branch is shown as a datetime
        self.calcs = {}
        names = [c["name"] for c in specs]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise FormulaError(f"duplicate calculated field names: {dup}")
        for n in names:
            if n in self.column_types:
                raise FormulaError(f"calculated field '{n}' has the same name as a CSV column")
        nodes = {}
        for c in specs:
            try:
                nodes[c["name"]] = parse(c["formula"])
            except FormulaError as e:
                raise FormulaError(f"calculated field '{c['name']}': {e}") from None
        self._specs = {c["name"]: c for c in specs}
        self._nodes = nodes
        self._visiting = []
        for c in specs:
            self._compile(c["name"])

    def __contains__(self, name):
        return name in self.calcs

    def __getitem__(self, name):
        return self.calcs[name]

    # -- compile / type-check --
    def _compile(self, name):
        if name in self.calcs:
            return self.calcs[name]
        if name in self._visiting:
            raise FormulaError(f"calculated fields reference each other in a cycle: "
                               f"{' -> '.join(self._visiting + [name])}")
        self._visiting.append(name)
        spec, node = self._specs[name], self._nodes[name]
        raw, calcs = set(), set()
        try:
            dtype, level = self._check(node, raw, calcs, in_agg=False)
            uses_view_lod = self._view_lod_positions(node, allowed=True, inside_lod=False)
        except FormulaError as e:
            raise FormulaError(f"calculated field '{name}': {e}") from None
        self._visiting.pop()
        if dtype is None:
            raise FormulaError(f"calculated field '{name}': formula has no value type")
        fmt = spec.get("format")
        if formats.is_number_format(fmt) and dtype not in NUMERIC:  # decisions/032
            raise FormulaError(f"calculated field '{name}': {fmt if isinstance(fmt, str) else 'number'} format needs "
                               f"a numeric result, got {dtype}")
        tc = _table_calc_funcs(node)
        cu = spec.get("compute_using")
        if tc and not cu:
            raise FormulaError(f"calculated field '{name}': {tc[0]}(...) is a table calculation: set compute_using to "
                               f"the sheet dimensions it runs along, e.g. \"compute_using\": [\"Region\"] (Tableau's "
                               f"default direction is not assumed)")
        if cu and not tc:
            raise FormulaError(f"calculated field '{name}': compute_using applies only to table calculations "
                               f"({', '.join(sorted(TABLE_CALCS))})")
        if cu and len(set(cu)) != len(cu):
            raise FormulaError(f"calculated field '{name}': compute_using repeats a dimension: {cu}")
        src = spec["formula"]
        refs = sorted(_refs(node), key=lambda r: r.start, reverse=True)
        xml, params = src, set()
        for r in refs:
            p = self._param_of(r)
            if p is not None:  # Tableau stores a parameter by its internal name: [Parameters].[Parameter 1]
                xml = xml[:r.start] + p.ref + xml[r.end:]
                params.add(r.name)
            elif r.name in self._specs:
                xml = xml[:r.start] + f"[{calc_id(r.name)}]" + xml[r.end:]
                params.update(self.calcs[r.name].params)
        self.calcs[name] = Calc(name, src, node, dtype, level == "agg", calc_id(name), xml,
                                spec.get("format"), sorted(raw), sorted(calcs),
                                view_lod=self._as_view_lod(node) is not None, uses_view_lod=uses_view_lod,
                                params=sorted(params), table_calc=bool(tc), compute_using=list(cu or []))
        return self.calcs[name]

    def _param_of(self, node):
        """The parameter a node stands for: [Parameters].[X], or a bare [X] that is no column or calc."""
        if isinstance(node, Param):
            if node.name not in self.params:
                raise FormulaError(f"unknown parameter [Parameters].[{node.name}] (parameters: "
                                   f"{sorted(self.params) or 'none'})")
            return self.params[node.name]
        if isinstance(node, Ref) and node.name not in self.column_types and node.name not in self._specs:
            return self.params.get(node.name)
        return None

    def _date_level(self, node, levels=DATE_LEVELS):
        """A date level: a literal, or a string parameter whose every value is a level."""
        if isinstance(node, Str):
            return node.value in levels
        p = self._param_of(node)
        return p is not None and p.datatype == "string" and bool(p.values) and set(p.values) <= set(levels)

    def _as_view_lod(self, node):
        """The INCLUDE/EXCLUDE node behind `node` (itself, or a calc whose whole formula is one)."""
        if isinstance(node, Lod) and node.kind != "FIXED":
            return node
        if isinstance(node, Ref) and node.name in self.calcs and self.calcs[node.name].view_lod:
            return self.calcs[node.name].node
        return None

    def _view_lod_positions(self, node, allowed, inside_lod):
        """INCLUDE/EXCLUDE only as the whole formula or the direct argument of an aggregate.

        Their value depends on the sheet's dimensions; anywhere else (row-level arithmetic,
        inside another LOD) the result is not defined by our evaluator. -> uses INCLUDE/EXCLUDE?
        """
        if self._as_view_lod(node) is not None:
            if inside_lod:
                raise FormulaError("INCLUDE/EXCLUDE inside another LOD expression is not supported")
            if not allowed:
                raise FormulaError("INCLUDE/EXCLUDE must be the whole formula or the direct argument "
                                   "of SUM/AVG/MIN/MAX/COUNT/COUNTD")
            if isinstance(node, Lod):
                self._view_lod_positions(node.body, allowed=False, inside_lod=True)
            return True
        if isinstance(node, Ref):
            return node.name in self.calcs and self.calcs[node.name].uses_view_lod
        if isinstance(node, Func):
            arg_ok = node.name in AGGREGATES and len(node.args) == 1  # MAX(a, b) is not an aggregate
            return any([self._view_lod_positions(a, arg_ok, inside_lod) for a in node.args])
        if isinstance(node, Lod):  # FIXED
            for d in node.dims:
                self._view_lod_positions(d, False, True)
            return self._view_lod_positions(node.body, False, True)
        children = []
        if isinstance(node, Unary):
            children = [node.arg]
        elif isinstance(node, Bin):
            children = [node.left, node.right]
        elif isinstance(node, If):
            children = [x for b in node.branches for x in b] + ([node.otherwise] if node.otherwise else [])
        elif isinstance(node, Case):
            children = [node.subject] + [v for _, v in node.branches] + ([node.otherwise] if node.otherwise else [])
        return any([self._view_lod_positions(c, False, inside_lod) for c in children])

    def _check(self, node, raw, calcs, in_agg):
        """-> (datatype, level) with level in const | row | agg."""
        if isinstance(node, Num):
            return ("integer" if isinstance(node.value, int) else "real"), "const"
        if isinstance(node, Str):
            return "string", "const"
        if isinstance(node, Bool):
            return "boolean", "const"
        if isinstance(node, DateLit):
            return ("datetime" if isinstance(node.value, dt.datetime) else "date"), "const"
        if isinstance(node, Ref):
            if node.name in self.column_types:
                raw.add(node.name)
                return self.column_types[node.name], "row"
            if node.name in self._specs:
                c = self._compile(node.name)
                if c.table_calc:  # its compute_using would be a second, nested addressing (decisions/034)
                    raise FormulaError(f"[{node.name}] is a table calculation: referencing it from another "
                                       f"calculation is not supported yet (write its expression inline)")
                calcs.add(c.name)
                calcs.update(c.calc_deps)
                raw.update(c.raw_deps)
                if c.is_agg and in_agg:
                    raise FormulaError(f"[{node.name}] is already aggregated; it cannot be inside another aggregate")
                return c.datatype, ("agg" if c.is_agg else "row")
            if node.name in self.params:
                return self.params[node.name].datatype, "const"  # one value for the whole view
            raise FormulaError(f"unknown field [{node.name}]")
        if isinstance(node, Param):
            return self._param_of(node).datatype, "const"
        if isinstance(node, Func):
            if node.name in TABLE_CALCS:
                return self._check_table_calc(node, raw, calcs, in_agg)
            if node.name in ("MAX", "MIN") and len(node.args) == 2:  # the larger / smaller of two
                checked = [self._check(a, raw, calcs, in_agg) for a in node.args]
                if any(t not in NUMERIC for t, _ in checked):
                    raise FormulaError(f"{node.name}(a, b) needs two numbers, got {checked[0][0]} and {checked[1][0]}")
                level = _level([lv for _, lv in checked], node.name)
                return ("integer" if all(t == "integer" for t, _ in checked) else "real"), level
            if node.name in AGGREGATES:
                if in_agg:
                    raise FormulaError(f"nested aggregation {node.name}(...) inside another aggregate")
                if node.name == "PERCENTILE":  # PERCENTILE(expression, p): p a number 0..1, as Tableau's
                    if len(node.args) != 2 or not (isinstance(node.args[1], Num)
                                                   and 0 <= float(node.args[1].value) <= 1):
                        raise FormulaError("PERCENTILE takes an expression and a number from 0 to 1: PERCENTILE([x], 0.9)")
                elif len(node.args) != 1:
                    raise FormulaError(f"{node.name} takes exactly one argument")
                t, _ = self._check(node.args[0], raw, calcs, in_agg=True)
                if node.name in ("SUM", "AVG", "MEDIAN", "PERCENTILE") and t not in NUMERIC:
                    raise FormulaError(f"{node.name} needs a number, got {t}")
                if node.name in ("COUNT", "COUNTD"):
                    return "integer", "agg"
                if node.name in ("AVG", "MEDIAN", "PERCENTILE"):
                    return "real", "agg"
                return t, "agg"
            if node.name == "IN":  # subject IN (literal, ...), built by the parser
                checked = [self._check(a, raw, calcs, in_agg) for a in node.args]
                st = checked[0][0]
                for lit, (lt, _) in zip(node.args[1:], checked[1:]):
                    if not ((st in NUMERIC and lt in NUMERIC) or st == lt):
                        raise FormulaError(f"IN compares a {st} with the {lt} value {lit.value!r}")
                return "boolean", checked[0][1]
            lo, hi = FUNCTIONS[node.name]
            if not lo <= len(node.args) <= hi:
                raise FormulaError(f"{node.name} takes {lo}{'' if lo == hi else f'-{hi}'} argument(s), "
                                   f"got {len(node.args)}")
            if node.name == "FULLNAME":
                return "string", "const"  # one value for the whole view, like a parameter
            checked = [self._check(a, raw, calcs, in_agg) for a in node.args]
            level = _level([lv for _, lv in checked], node.name)
            return self._func_type(node, [t for t, _ in checked]), level
        if isinstance(node, Unary):
            t, lv = self._check(node.arg, raw, calcs, in_agg)
            if node.op == "-" and t not in NUMERIC:
                raise FormulaError(f"cannot negate {t}")
            if node.op == "NOT" and t != "boolean":
                raise FormulaError(f"NOT needs a boolean, got {t}")
            return t, lv
        if isinstance(node, Bin):
            lt, ll = self._check(node.left, raw, calcs, in_agg)
            rt, rl = self._check(node.right, raw, calcs, in_agg)
            level = _level([ll, rl], node.op)
            op = node.op
            if op in ("AND", "OR"):
                if lt != "boolean" or rt != "boolean":
                    raise FormulaError(f"{op} needs booleans, got {lt} and {rt}")
                return "boolean", level
            if op in ("=", "<>", "<", "<=", ">", ">="):
                if not ((lt in NUMERIC and rt in NUMERIC) or lt == rt):
                    raise FormulaError(f"cannot compare {lt} with {rt}")
                return "boolean", level
            if op == "+" and lt == "string" and rt == "string":
                return "string", level
            if lt not in NUMERIC or rt not in NUMERIC:
                hint = " (STR() turns a number into text)" if op == "+" and "string" in (lt, rt) else ""
                raise FormulaError(f"'{op}' needs numbers, got {lt} and {rt}{hint}")
            if op == "/":
                return "real", level
            return ("real" if "real" in (lt, rt) else "integer"), level
        if isinstance(node, If):
            levels, types = [], []
            for cond, value in node.branches:
                ct, cl = self._check(cond, raw, calcs, in_agg)
                if ct != "boolean":
                    raise FormulaError(f"IF condition must be boolean, got {ct}")
                vt, vl = self._check(value, raw, calcs, in_agg)
                levels += [cl, vl]
                types.append(vt)
            if node.otherwise is not None:
                ot, ol = self._check(node.otherwise, raw, calcs, in_agg)
                levels.append(ol)
                types.append(ot)
            return self._branches(node, types, "IF branches"), _level(levels, "IF")
        if isinstance(node, Case):
            st, sl = self._check(node.subject, raw, calcs, in_agg)
            levels, types, whens = [sl], [], []
            for lit, value in node.branches:
                lt, _ = self._check(lit, raw, calcs, in_agg)
                if not ((st in NUMERIC and lt in NUMERIC) or st == lt):
                    raise FormulaError(f"CASE compares a {st} with the {lt} WHEN value {lit.value!r}")
                whens.append(lit.value)
                vt, vl = self._check(value, raw, calcs, in_agg)
                levels.append(vl)
                types.append(vt)
            if node.otherwise is not None:
                ot, ol = self._check(node.otherwise, raw, calcs, in_agg)
                levels.append(ol)
                types.append(ot)
            p = self._param_of(node.subject)
            if p is not None and p.values:  # a switch over a list parameter: every option has its branch
                typos = [w for w in whens if w not in p.values]
                if typos:
                    raise FormulaError(f"CASE [{node.subject.name}]: WHEN {typos} is not a value of the parameter "
                                       f"(values: {p.values})")
                missing = [v for v in p.values if v not in whens]
                if missing and node.otherwise is None:
                    raise FormulaError(f"CASE [{node.subject.name}] has no WHEN for {missing} and no ELSE: the view "
                                       f"would be empty for that choice")
            return self._branches(node, types, "CASE branches"), _level(levels, "CASE")
        if isinstance(node, Lod):
            self._lod_depth += 1
            try:
                for d in node.dims:
                    if not isinstance(d, Ref):
                        raise FormulaError(f"{node.kind} dimensions must be field references like [Region]")
                    _, lv = self._check(d, raw, calcs, in_agg=False)
                    if lv == "agg":
                        raise FormulaError(f"{node.kind} dimension [{d.name}] is an aggregate calculation")
                t, lv = self._check(node.body, raw, calcs, in_agg=False)  # own aggregation scope
            finally:
                self._lod_depth -= 1
            if lv != "agg":
                raise FormulaError("the part after ':' in a LOD must be an aggregate, e.g. SUM([Sales])")
            return t, "row"  # LOD values are disaggregated: aggregate them again in the view
        raise FormulaError(f"unsupported expression {node!r}")

    def _branches(self, node, types, where):
        """The common type of the values a node picks from; a date among datetimes becomes a datetime at midnight."""
        t = _unify(types, where)
        if t == "datetime" and "date" in types:
            self._as_datetime.add(id(node))
        return t

    def _picked(self, node, v):
        return dt.datetime.combine(v, dt.time()) if id(node) in self._as_datetime and type(v) is dt.date else v

    def _check_table_calc(self, node, raw, calcs, in_agg):
        """Type of a table calculation function (decisions/034): aggregate level, over aggregate arguments."""
        name, args = node.name, node.args
        if in_agg:
            raise FormulaError(f"table calculation {name}(...) cannot be inside an aggregate")
        if self._lod_depth:
            raise FormulaError(f"table calculation {name}(...) cannot be inside a LOD expression {{...}}")
        lo, hi = TABLE_CALCS[name]
        if not lo <= len(args) <= hi or (name.startswith("WINDOW_") and len(args) == 2):
            want = "1 or 3 (expression, start, end)" if name.startswith("WINDOW_") else \
                f"{lo}{'' if lo == hi else f'-{hi}'}"
            raise FormulaError(f"{name} takes {want} argument(s), got {len(args)}")
        if not args:  # INDEX() FIRST() LAST() SIZE()
            return "integer", "agg"
        t, lv = self._check(args[0], raw, calcs, in_agg=False)
        if name == "PREVIOUS_VALUE":  # the seed may be a constant: PREVIOUS_VALUE(0) + SUM([Sales])
            if lv == "row":
                raise FormulaError("PREVIOUS_VALUE needs an aggregate or a constant seed, got a row-level value")
            if _table_calc_funcs(args[0]):
                raise FormulaError("PREVIOUS_VALUE takes an aggregate or a constant, not another table calculation")
            if t not in NUMERIC:
                raise FormulaError(f"PREVIOUS_VALUE needs a number, got {t}")
            return t, "agg"
        if lv != "agg":
            raise FormulaError(f"{name} needs an aggregate expression, e.g. {name}(SUM([Sales])"
                               f"{', -1' if name == 'LOOKUP' else ''}), got a {'constant' if lv == 'const' else 'row-level value'}")
        if name == "TOTAL" and _table_calc_funcs(args[0]):
            raise FormulaError("TOTAL takes an aggregate, not another table calculation")
        if name != "LOOKUP" and t not in NUMERIC:
            raise FormulaError(f"{name} needs a number, got {t}")
        if name == "LOOKUP" and not _is_offset(args[1], ()):
            raise FormulaError("LOOKUP offset must be an integer literal, e.g. LOOKUP(SUM([Sales]), -1)")
        if name.startswith("WINDOW_") and not all(_is_offset(a, ("FIRST", "LAST")) for a in args[1:]):
            raise FormulaError(f"{name} start and end must be integer literals or FIRST() / LAST(), e.g. "
                               f"{name}(SUM([Sales]), -2, 0)")
        if name.startswith("RANK"):
            if len(args) == 2 and not (isinstance(args[1], Str) and args[1].value in ("asc", "desc")):
                raise FormulaError(f"{name} order must be 'asc' or 'desc'")
            return "integer", "agg"
        if name in ("WINDOW_AVG", "WINDOW_MEDIAN", "RUNNING_AVG"):
            return "real", "agg"
        if name in ("WINDOW_COUNT", "RUNNING_COUNT"):
            return "integer", "agg"
        return t, "agg"

    def _func_type(self, node, types):
        """Result type of a non-aggregate function from its argument types; a FormulaError names the mismatch."""
        name, args = node.name, node.args

        def need(i, *allowed, what):
            if types[i] not in allowed:
                raise FormulaError(f"{name} needs {what}, got {types[i]}")

        def level_arg(levels, dates):
            """The level literal / parameter; 'hour' / 'minute' need datetime arguments (decisions/051)."""
            if not (self._date_level(args[0], levels) or (isinstance(args[0], Str) and args[0].value in TIME_LEVELS)):
                raise FormulaError(f"{name} level must be a string literal, one of "
                                   f"{', '.join(repr(lv) for lv in levels + TIME_LEVELS)}, or a string parameter "
                                   f"whose values are all levels")
            for i in dates:
                need(i, *DATES, what="a date")
                if isinstance(args[0], Str) and args[0].value in TIME_LEVELS and types[i] != "datetime":
                    raise FormulaError(f"{name} level '{args[0].value}' needs a datetime, got {types[i]}")

        if name in ("DATETRUNC", "DATEADD"):
            if name == "DATEADD" and types[1] != "integer":
                raise FormulaError(f"DATEADD amount must be an integer, got {types[1]}")
            level_arg(DATE_LEVELS, [len(args) - 1])
            return types[-1]  # a date stays a date, a datetime a datetime
        if name == "IIF":
            if types[0] != "boolean":
                raise FormulaError(f"IIF condition must be boolean, got {types[0]}")
            return self._branches(node, types[1:], "IIF values")
        if name == "IFNULL":
            return self._branches(node, types, "IFNULL arguments")
        if name == "ISNULL":
            return "boolean"
        if name in ("DATEDIFF", "DATEPART", "DATENAME") or name in DATE_PARTS:
            # YEAR([d]) .. DAY([d]); DATEDIFF(level, start, end [, week start]); DATEPART/DATENAME(level, d [, ws])
            dates, week = ([0], None) if name in DATE_PARTS else ([1, 2], 3) if name == "DATEDIFF" else ([1], 2)
            if name not in DATE_PARTS:
                level_arg(DATE_LEVELS if name == "DATEDIFF" else PART_LEVELS, dates)
            for i in dates:
                need(i, *DATES, what="a date")
            if week is not None and len(args) > week and not (isinstance(args[week], Str)
                                                                and args[week].value in WEEKDAYS):
                raise FormulaError(f"{name} start of week must be a string literal, one of "
                                   f"{', '.join(repr(d) for d in WEEKDAYS)}")
            return "string" if name == "DATENAME" else "integer"
        # functions v3 (decisions/055)
        if name in ("MAKEDATE", "MAKETIME"):
            for i in range(3):
                need(i, "integer", what="integer year, month, day" if name == "MAKEDATE" else
                     "integer hour, minute, second")
            return "date" if name == "MAKEDATE" else "datetime"
        if name == "MAKEDATETIME":
            need(0, *DATES, what="a date first")
            need(1, "datetime", what="a time (a datetime: MAKETIME(...) or a datetime field) second")
            return "datetime"
        if name == "DATEPARSE":
            if not isinstance(args[0], Str):
                raise FormulaError("DATEPARSE format must be a string literal, e.g. DATEPARSE(\"dd.MM.yyyy\", [Text])")
            date_format(args[0].value)  # an unsupported pattern letter is an error here
            need(1, "string", what="a string to parse")
            return "datetime"
        if name in ("DATE", "DATETIME"):
            if types[0] == "string":  # Desktop guesses the order month-first, whatever the locale (decisions/055)
                raise FormulaError(f"{name} of a string guesses its format (Desktop 2025.1 read '1.2.2024' as "
                                   f"January 2 and '31.01.2024' as NULL in a ru_RU workbook): use DATEPARSE with the "
                                   f"format, e.g. DATEPARSE(\"dd.MM.yyyy\", [Text])")
            if name == "DATETIME" and types[0] == "date":  # lab DT: LEN(STR(DATETIME([Day]))) = 10, not 19
                raise FormulaError("DATETIME of a date stays a date in Desktop (STR prints no time): use "
                                   "MAKEDATETIME(date, time)")
            need(0, *DATES, what="a date or a datetime")
            return name.lower()
        if name in ISO_PARTS:
            need(0, *DATES, what="a date")
            return "integer"
        if name == "SPLIT":
            need(0, "string", what="a string first")
            if not (isinstance(args[1], Str) and args[1].value):
                raise FormulaError("SPLIT delimiter must be a non-empty string literal")
            tok = args[2].arg if isinstance(args[2], Unary) and args[2].op == "-" else args[2]
            if not (isinstance(tok, Num) and isinstance(tok.value, int) and tok.value != 0):
                raise FormulaError("SPLIT token must be a non-zero integer literal (1 = first, -1 = last)")
            return "string"
        if name in ("FIND", "FINDNTH"):
            need(0, "string", what="strings")
            need(1, "string", what="strings")
            if name == "FIND" and len(args) == 3:
                need(2, "integer", what="an integer start")
            if name == "FINDNTH" and not (isinstance(args[2], Num) and isinstance(args[2].value, int)
                                          and args[2].value > 0):
                # Desktop: 0 gives 1 and a negative n counts from the end in a way not modelled here
                # (FINDNTH("--", "-", -2) = 2), decisions/055
                raise FormulaError("FINDNTH occurrence must be a positive integer literal (1 = the first)")
            return "integer"
        if name == "STR":
            need(0, "integer", "real", "string", *DATES, what="a number, a string or a date")
            return "string"
        if name in ("INT", "FLOAT"):
            need(0, "integer", "real", "string", "boolean", what="a number, a string or a boolean")  # TRUE = 1 (060)
            return "integer" if name == "INT" else "real"
        if name in ("CONTAINS", "STARTSWITH", "ENDSWITH", "REPLACE", "UPPER", "LOWER", "TRIM", "LEN"):
            for i in range(len(args)):
                need(i, "string", what="strings")
            return {"CONTAINS": "boolean", "STARTSWITH": "boolean", "ENDSWITH": "boolean",
                    "LEN": "integer"}.get(name, "string")
        if name in ("LEFT", "RIGHT", "MID"):
            need(0, "string", what="a string first")
            for i in range(1, len(args)):
                need(i, "integer", what="integer positions / lengths")
            return "string"
        for i in range(len(args)):  # ZN ABS ROUND
            need(i, *NUMERIC, what="numbers")
        if name == "ROUND":
            if len(args) == 2 and not (isinstance(args[1], Num) and isinstance(args[1].value, int)):
                raise FormulaError("ROUND decimals must be an integer literal")
            return "real"
        return types[0]

    # -- evaluate --
    def _value(self, column, raw):
        if raw is None or raw == "":
            return None
        t = self.column_types[column]
        if t == "integer":
            return int(raw)
        if t == "real":
            return float(raw)
        if t == "date":
            return dt.date.fromisoformat(raw)
        if t == "datetime":
            return dt.datetime.fromisoformat(raw)
        return raw

    def row_value(self, name, row):
        """Row-level calc evaluated on one CSV row (dict of raw strings)."""
        c = self.calcs[name]
        if c.is_agg or c.uses_view_lod:
            raise ValueError(f"'{name}' is not a row-level calculation")
        return self._eval(c.node, row, None, None)

    def agg_value(self, name, rows, view=None):
        """Aggregate calc evaluated over the rows of one mark; `view` is needed for INCLUDE/EXCLUDE."""
        c = self.calcs[name]
        if not c.is_agg:
            raise ValueError(f"'{name}' is a row-level calculation")
        if c.table_calc:
            raise ValueError(f"'{name}' is a table calculation: evaluate it over its partition (table_values)")
        return self._eval(c.node, None, rows, view)

    def table_values(self, name, marks, view=None):
        """Values of a table calculation for the marks of one partition (decisions/034).

        marks: the CSV rows of each mark, in the order of the calc's compute_using dimensions. -> [value per mark]
        """
        c = self.calcs[name]
        if not c.table_calc:
            raise ValueError(f"'{name}' is not a table calculation")
        memo = {}  # (node, position) -> value: RANK and WINDOW_* read every mark of the partition
        self._tc_root = c.node  # PREVIOUS_VALUE reads this calc at the previous mark
        out = []
        for i in range(len(marks)):
            self._tc = (marks, i, memo)
            try:
                out.append(self._eval(c.node, None, marks[i], view))
            finally:
                self._tc = None
        return out

    def _at(self, j, node, view):
        """`node` evaluated at mark j of the current partition."""
        marks, i, memo = self._tc
        key = (id(node), j)
        if key not in memo:
            self._tc = (marks, j, memo)
            try:
                memo[key] = self._eval(node, None, marks[j], view)
            finally:
                self._tc = (marks, i, memo)
        return memo[key]

    def _eval_table_calc(self, node, view):
        if self._tc is None:
            raise ValueError(f"{node.name}() needs the marks of its partition (CalcSet.table_values)")
        marks, i, _ = self._tc
        n, name, args = len(marks), node.name, node.args
        if name == "INDEX":
            return i + 1
        if name == "FIRST":  # offset to the first mark
            return -i
        if name == "LAST":
            return n - 1 - i
        if name == "LOOKUP":
            j = i + self._eval(args[1], None, None, view)
            return self._at(j, args[0], view) if 0 <= j < n else None  # outside the partition: NULL
        if name == "TOTAL":  # the aggregate over all rows of the partition, not a sum of the marks
            return self._eval(args[0], None, [r for m in marks for r in m], view)
        if name == "PREVIOUS_VALUE":  # this calc at the previous mark; at the first one, its seed
            return self._eval(args[0], None, marks[i], view) if i == 0 else self._at(i - 1, self._tc_root, view)
        if name == "SIZE":  # marks of the partition, NULL ones too
            return n
        if name.startswith("RUNNING_"):  # marks 0..i, NULL skipped (a fold of none is NULL)
            vals = [v for v in (self._at(j, args[0], view) for j in range(i + 1)) if v is not None]
            return _fold(name[8:], vals)
        if name.startswith("WINDOW_"):
            lo, hi = 0, n - 1
            if len(args) == 3:  # offsets from the current mark, clipped to the partition
                lo = max(lo, i + self._eval(args[1], None, None, view))
                hi = min(hi, i + self._eval(args[2], None, None, view))
            vals = [v for v in (self._at(j, args[0], view) for j in range(lo, hi + 1)) if v is not None]
            return _fold(name[7:], vals)
        # RANK (competition: 1, 2, 2, 4) / RANK_DENSE (1, 2, 2, 3) / RANK_UNIQUE (1, 2, 3, 4: ties by position);
        # NULL is not ranked and does not count
        vals = [self._at(j, args[0], view) for j in range(n)]
        v = vals[i]
        if v is None:
            return None
        desc = len(args) < 2 or args[1].value == "desc"
        ahead = [w for w in vals if w is not None and (w > v if desc else w < v)]
        if name == "RANK_UNIQUE":
            return 1 + len(ahead) + sum(1 for w in vals[:i] if w == v)
        return 1 + (len(set(ahead)) if name == "RANK_DENSE" else len(ahead))

    def view_values(self, name, rows, view):
        """Values of a calc whose whole formula is INCLUDE/EXCLUDE, for one mark.

        The sheet then aggregates these values (one per LOD-level group), not the CSV rows.
        """
        c = self.calcs[name]
        if not c.view_lod:
            raise ValueError(f"'{name}' is not an INCLUDE/EXCLUDE calculation")
        return self._view_lod_values(c.node, rows, view)

    def _view_lod_values(self, lod, rows, view):
        if view is None:
            raise ValueError("INCLUDE/EXCLUDE needs the sheet context (View)")
        if not rows:
            return []
        names = {d.name for d in lod.dims}
        if lod.kind == "INCLUDE":
            # view dims are constant within the mark: split it further by the included dims
            extra = [d for d in lod.dims if d.name not in {n for n, _ in view.dims}]
            groups = {}
            for r in rows:
                groups.setdefault(tuple(self._eval(d, r, None, None) for d in extra), []).append(r)
            return [self._eval(lod.body, None, g, None) for g in groups.values()]
        # EXCLUDE: the mark's value at the view level minus the excluded dims, over all sheet rows
        keep = [fn for n, fn in view.dims if n not in names]
        key = tuple(fn(rows[0]) for fn in keep)
        peers = [r for r in view.rows if tuple(fn(r) for fn in keep) == key]
        return [self._eval(lod.body, None, peers, None)]

    def _eval(self, node, row, rows, view):
        if isinstance(node, (Num, Str, Bool, DateLit)):
            return node.value
        if isinstance(node, Param):
            return self.params[node.name].value
        if isinstance(node, Ref):
            if node.name in self.column_types:
                return self._value(node.name, row.get(node.name))
            if node.name not in self.calcs:
                return self.params[node.name].value
            c = self.calcs[node.name]
            return self._eval(c.node, None if c.is_agg else row, rows, view)
        if isinstance(node, Func):
            if node.name in TABLE_CALCS:
                return self._eval_table_calc(node, view)
            if node.name in ("MAX", "MIN") and len(node.args) == 2:
                a, b = (self._eval(x, row, rows, view) for x in node.args)
                return None if a is None or b is None else (max if node.name == "MAX" else min)(a, b)
            if node.name in AGGREGATES:
                lod = self._as_view_lod(node.args[0])
                if lod is not None:
                    vals = self._view_lod_values(lod, rows, view)
                else:
                    vals = [self._eval(node.args[0], r, None, None) for r in rows]
                vals = [v for v in vals if v is not None]
                if node.name == "COUNT":
                    return len(vals)
                if node.name == "COUNTD":
                    return len(set(vals))
                if not vals:
                    return None
                if node.name == "SUM":
                    return sum(vals)
                if node.name == "AVG":
                    return sum(vals) / len(vals)
                if node.name in ("MEDIAN", "PERCENTILE"):  # linear between the closest ranks, as Tableau's
                    from .compareviz import percentile
                    return percentile(vals, 0.5 if node.name == "MEDIAN" else float(node.args[1].value))
                return min(vals) if node.name == "MIN" else max(vals)
            if node.name in ("IIF", "IFNULL", "ISNULL", "IN"):  # null-aware: they decide on a missing value
                v = self._eval(node.args[0], row, rows, view)
                if node.name == "IIF":  # TRUE -> then, FALSE -> else, NULL -> unknown (or NULL without it)
                    i = 1 if v is True else 2 if v is False else 3
                    return self._picked(node, self._eval(node.args[i], row, rows, view)) if i < len(node.args) else None
                if node.name == "IFNULL":
                    return self._picked(node, v if v is not None else self._eval(node.args[1], row, rows, view))
                if node.name == "ISNULL":
                    return v is None
                return None if v is None else any(v == lit.value for lit in node.args[1:])
            args = [self._eval(a, row, rows, view) for a in node.args]
            if node.name == "FULLNAME":
                return FULLNAME_VALUE
            if node.name == "ZN":
                return 0 if args[0] is None else args[0]
            if any(a is None for a in args):
                return None
            if node.name in ("DATETRUNC", "DATEADD"):
                return _datetrunc(*args) if node.name == "DATETRUNC" else _dateadd(*args)
            if node.name == "DATENAME":
                return _datename(*args)
            if node.name in SCALAR:
                return SCALAR[node.name](*args)
            if node.name == "ABS":
                return abs(args[0])
            digits = args[1] if len(args) == 2 else 0
            scaled = abs(args[0]) * 10 ** digits  # Tableau rounds half away from zero
            return math.copysign(math.floor(scaled + 0.5) / 10 ** digits, args[0])
        if isinstance(node, Unary):
            v = self._eval(node.arg, row, rows, view)
            if v is None:
                return None
            return -v if node.op == "-" else (not v)
        if isinstance(node, Bin):
            a, b = self._eval(node.left, row, rows, view), self._eval(node.right, row, rows, view)
            op = node.op
            if op == "AND":
                return False if a is False or b is False else (None if a is None or b is None else True)
            if op == "OR":
                return True if a is True or b is True else (None if a is None or b is None else False)
            if a is None or b is None:
                return None
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                return None if b == 0 else a / b
            return {"=": a == b, "<>": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        if isinstance(node, If):
            for cond, value in node.branches:
                if self._eval(cond, row, rows, view) is True:
                    return self._picked(node, self._eval(value, row, rows, view))
            return None if node.otherwise is None else self._picked(node, self._eval(node.otherwise, row, rows, view))
        if isinstance(node, Case):
            v = self._eval(node.subject, row, rows, view)
            for lit, value in node.branches:
                if v is not None and v == lit.value:
                    return self._picked(node, self._eval(value, row, rows, view))
            return None if node.otherwise is None else self._picked(node, self._eval(node.otherwise, row, rows, view))
        if isinstance(node, Lod):
            if node.kind != "FIXED":
                raise ValueError("INCLUDE/EXCLUDE is evaluated through its aggregate or view_values()")
            groups = self._lod_cache.get(id(node))
            if groups is None:
                if self.rows is None:
                    raise ValueError("FIXED LOD needs the full dataset: pass rows to CalcSet")
                members = {}
                for r in self.rows:
                    members.setdefault(tuple(self._eval(d, r, None, None) for d in node.dims), []).append(r)
                groups = {k: self._eval(node.body, None, rs, None) for k, rs in members.items()}
                self._lod_cache[id(node)] = groups
            return groups.get(tuple(self._eval(d, row, None, None) for d in node.dims))
        raise ValueError(node)


def _day(d):
    """The calendar day of a date or a datetime: date levels count days, not times of day."""
    return d.date() if isinstance(d, dt.datetime) else d


def _datetrunc(level, d):
    if isinstance(d, dt.datetime):  # hour / minute keep the day; a date level truncates to midnight
        if level in TIME_LEVELS:
            return d.replace(minute=0 if level == "hour" else d.minute, second=0, microsecond=0)
        return dt.datetime.combine(_datetrunc(level, d.date()), dt.time())
    if level == "year":
        return d.replace(month=1, day=1)
    if level == "quarter":
        return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    if level == "month":
        return d.replace(day=1)
    if level == "week":  # workbook date-options: start-of-week = monday
        return d - dt.timedelta(days=d.weekday())
    return d


def _dateadd(level, n, d):
    if level in TIME_LEVELS:
        return d + dt.timedelta(hours=n) if level == "hour" else d + dt.timedelta(minutes=n)
    if isinstance(d, dt.datetime):  # the time of day stays
        return dt.datetime.combine(_dateadd(level, n, d.date()), d.time())
    if level in ("week", "day"):
        return d + dt.timedelta(days=n * (7 if level == "week" else 1))
    y, m = divmod(d.year * 12 + d.month - 1 + n * {"year": 12, "quarter": 3, "month": 1}[level], 12)
    return dt.date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))  # Tableau clamps to the month end


def _week_start(d, start_of_week):
    return d - dt.timedelta(days=(d.weekday() - WEEKDAYS.index(start_of_week)) % 7)


def _datepart(level, d, start_of_week=START_OF_WEEK):
    """As Desktop 2025.1 computes it (out/funcs_lab): only 'week' depends on the start of week."""
    if level in TIME_LEVELS:
        return d.hour if level == "hour" else d.minute
    d = _day(d)
    if level == "year":
        return d.year
    if level == "quarter":
        return (d.month - 1) // 3 + 1
    if level == "month":
        return d.month
    if level == "day":
        return d.day
    if level == "dayofyear":
        return d.timetuple().tm_yday
    if level == "weekday":  # Sunday = 1 ... Saturday = 7, even with start of week 'monday' (workbook or argument)
        return (d.weekday() + 1) % 7 + 1
    # week: week 1 is the (possibly partial) week of January 1st, weeks start on start_of_week
    return (_week_start(d, start_of_week) - _week_start(dt.date(d.year, 1, 1), start_of_week)).days // 7 + 1


def _datename(level, d, start_of_week=START_OF_WEEK):
    if level in ("month", "weekday"):
        return MONTH_NAMES[d.month - 1] if level == "month" else WEEKDAY_NAMES[d.weekday()]
    return str(_datepart(level, d, start_of_week))


def _datediff(level, start, end, start_of_week=START_OF_WEEK):
    """Level boundaries crossed from start to end (negative when end is earlier)."""
    if level in TIME_LEVELS:  # 10:59 -> 11:00 crosses one hour; 10:00 -> 10:59 none
        step = 3600 if level == "hour" else 60
        return int((_datetrunc(level, end) - _datetrunc(level, start)).total_seconds()) // step
    start, end = _day(start), _day(end)
    if level == "day":
        return (end - start).days
    if level == "week":
        return (_week_start(end, start_of_week) - _week_start(start, start_of_week)).days // 7
    months = {"year": 12, "quarter": 3, "month": 1}[level]
    return (end.year * 12 + end.month - 1) // months - (start.year * 12 + start.month - 1) // months


_NUMBER_TEXT = re.compile(r"\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\s*")


# a comma groups thousands, a point is the decimal mark, whatever the workbook locale: Desktop 2025.1 in ru_RU read
# "1,234.5" as 1234.5, "1,234e2" as 123400 and "1,5" / "-2,75" / "1 000" / "1.234,5" / "0,000.5" / "12,34,567" as
# NULL (decisions/055)
_GROUPED_TEXT = re.compile(r"\s*[-+]?[1-9]\d{0,2}(?:,\d{3})+(?:\.\d*)?(?:[eE][-+]?\d+)?\s*")


def _to_float(v):
    if isinstance(v, str):
        if _GROUPED_TEXT.fullmatch(v):
            return float(v.replace(",", ""))
        return float(v) if _NUMBER_TEXT.fullmatch(v) else None  # not a number -> NULL, as in Tableau
    return float(v)


def _str(v):
    if isinstance(v, float):
        return f"{v:.17g}"  # Desktop: 17 significant digits, STR(0.1) = "0.10000000000000001"; STR(1.0) = "1"
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


# ---- functions v3 (decisions/055) ----------------------------------------------------------
ISO_PARTS = ("ISOYEAR", "ISOQUARTER", "ISOWEEK", "ISOWEEKDAY")
TIME_ZERO = dt.date(1899, 12, 30)  # the day of a time-only datetime (MAKETIME), Tableau's day zero
# DATEPARSE pattern letters (ICU) -> (field, regex); repeated letters as in the pattern. Other letters are refused.
_FORMAT_FIELDS = {"yyyy": ("year", r"\d{1,4}"), "MM": ("month", r"\d{1,2}"), "M": ("month", r"\d{1,2}"),
                  "dd": ("day", r"\d{1,2}"), "d": ("day", r"\d{1,2}"), "HH": ("hour", r"\d{1,2}"),
                  "H": ("hour", r"\d{1,2}"), "mm": ("minute", r"\d{1,2}"), "m": ("minute", r"\d{1,2}"),
                  "ss": ("second", r"\d{1,2}"), "s": ("second", r"\d{1,2}"),
                  # decisions/149: English month names, a two-digit year, 12-hour time with AM/PM
                  "MMM": ("monthname", r"[A-Za-z]+"), "MMMM": ("monthname", r"[A-Za-z]+"), "yy": ("year2", r"\d{1,4}"),
                  "hh": ("hour12", r"\d{1,2}"), "h": ("hour12", r"\d{1,2}"), "a": ("ampm", r"[A-Za-z]{2}")}


def date_format(fmt):
    """An ICU date pattern of DATEPARSE -> compiled regex with named groups; FormulaError on what is not supported."""
    out, seen, i = [], set(), 0
    while i < len(fmt):
        ch = fmt[i]
        if ch == "'":  # 'quoted literal', '' = a quote
            j = fmt.find("'", i + 1)
            if j < 0:
                raise FormulaError(f"DATEPARSE format {fmt!r}: unclosed quote")
            out.append(re.escape(fmt[i + 1:j] or "'"))
            i = j + 1
            continue
        if ch.isascii() and ch.isalpha():
            j = i
            while j < len(fmt) and fmt[j] == ch:
                j += 1
            letters = fmt[i:j]
            if letters not in _FORMAT_FIELDS:
                raise FormulaError(f"DATEPARSE format {fmt!r}: pattern {letters!r} is not supported (supported: "
                                   f"{', '.join(_FORMAT_FIELDS)}, separators and 'quoted text')")
            field_name, rx = _FORMAT_FIELDS[letters]
            if field_name in seen:
                raise FormulaError(f"DATEPARSE format {fmt!r}: {field_name} appears twice")
            seen.add(field_name)
            out.append(f"(?P<{field_name}>{rx})")
            i = j
            continue
        out.append(re.escape(ch))
        i += 1
    if not ({"year", "year2"} & seen and {"month", "monthname"} & seen and "day" in seen):
        raise FormulaError(f"DATEPARSE format {fmt!r} needs a year (yyyy, yy), a month (MM, MMM, MMMM) and a day (dd)")
    if "hour" in seen and "hour12" in seen:
        raise FormulaError(f"DATEPARSE format {fmt!r}: HH and hh in one pattern")
    if "ampm" in seen and "hour12" not in seen:
        raise FormulaError(f"DATEPARSE format {fmt!r}: AM/PM (a) needs the 12-hour hh")
    return re.compile("".join(out))


def _dateparse(fmt, s):
    """A string read with an ICU pattern -> datetime; a string that does not match, or no such date -> NULL."""
    m = date_format(fmt).fullmatch(s)
    if not m:
        return None
    g = m.groupdict()
    p = {k: int(v) for k, v in g.items() if k not in ("monthname", "ampm", "year2")}
    if "monthname" in g:
        p["month"] = _month_by_name(g["monthname"])
        if not p["month"]:
            return None
    if "year2" in g:
        p["year"] = _year_of_two_digits(g["year2"])
    if "hour12" in p:
        p["hour"] = _hour_of_12(p["hour12"], g.get("ampm"))
        if p["hour"] is None:
            return None
    try:
        return dt.datetime(p["year"], p["month"], p["day"], p.get("hour", 0), p.get("minute", 0), p.get("second", 0))
    except ValueError:
        return None


def _month_by_name(name):
    n = name.lower()
    hits = [i + 1 for i, full in enumerate(MONTH_NAMES) if full.lower() == n or full[:3].lower() == n]
    return hits[0] if hits else 0


def _year_of_two_digits(text):
    """Desktop 2025.1 (golden_calcs_v4): exactly two digits 00-69 -> 2000-2069, 70-99 -> 1970-1999; one, three or
    four digits are the year itself ('5' -> year 5, '2024' -> 2024). The pivot is fixed, not a window from today."""
    y = int(text)
    if len(text) == 2:
        return 2000 + y if y < 70 else 1900 + y
    return y


def _hour_of_12(h, ampm):
    """With 'a': hours 1-12 only (0 and 13 are NULL), am/pm in any case; without 'a' the hour is a 24-hour one."""
    if ampm is None:
        return h
    pm = {"am": False, "pm": True}.get(ampm.lower())
    if pm is None or not 1 <= h <= 12:
        return None
    return h % 12 + (12 if pm else 0)


def _to_datetime(v):
    return v if isinstance(v, dt.datetime) else dt.datetime.combine(v, dt.time())


def _makedate(y, m, d):
    """Desktop rolls a month or day out of range over (2023-02-29 -> 2023-03-01, month 13 -> January of the next
    year, day 0 -> the last day of the month before); a year before 1 is NULL (MAKEDATE(0, 1, 1), lab r14)."""
    yy, mm = divmod(y * 12 + m - 1, 12)
    if yy < 1:
        return None
    if yy > 9999:  # Desktop shows 10000-01-01 (lab); Python dates end at 9999: refuse rather than guess
        raise ValueError(f"MAKEDATE({y}, {m}, {d}): a year after 9999 cannot be computed here")
    first = dt.date(yy, mm + 1, 1)
    try:
        return first + dt.timedelta(days=d - 1)
    except OverflowError:
        raise ValueError(f"MAKEDATE({y}, {m}, {d}): outside the years 1..9999") from None


def _maketime(h, m, s):
    """As Desktop (lab MkT1-5): seconds and minutes carry over (MAKETIME(1, 60, 0) = 02:00:00), the time wraps at
    24 hours on the same day (MAKETIME(24, 0, 0) = 1899-12-30 00:00:00), a negative hour is NULL."""
    if min(h, m, s) < 0:
        return None
    return dt.datetime.combine(TIME_ZERO, dt.time()) + dt.timedelta(seconds=(h * 3600 + m * 60 + s) % 86400)


def _isopart(name, d):
    y, w, wd = _day(d).isocalendar()
    return {"ISOYEAR": y, "ISOWEEK": w, "ISOWEEKDAY": wd, "ISOQUARTER": min((w - 1) // 13 + 1, 4)}[name]


def _split(s, delim, token):
    parts = s.split(delim)
    i = token - 1 if token > 0 else len(parts) + token
    return parts[i] if 0 <= i < len(parts) else ""


def _find(s, sub, start=None):
    """1-based position of sub in s (0 = not found); start: ignore what begins before it."""
    return s.find(sub, max(start, 1) - 1 if start is not None else 0) + 1


def _findnth(s, sub, n):
    """Position of the n-th occurrence, n >= 1 (1-based, 0 = none). As Desktop (lab): occurrences do not overlap,
    FINDNTH("aaa", "aa", 2) = 0."""
    step, pos = max(len(sub), 1), -max(len(sub), 1)
    for _ in range(n):
        pos = s.find(sub, pos + step)
        if pos < 0:
            return 0
    return pos + 1


def _mid(s, start, length=None):
    i = max(start - 1, 0)  # 1-based
    return s[i:] if length is None else s[i:i + max(length, 0)]


SCALAR = {
    "DATEPART": _datepart,
    "DATEDIFF": _datediff,
    **{f: (lambda d, lv=lv: _datepart(lv, d)) for f, lv in DATE_PARTS.items()},
    "WEEK": lambda d: _datepart("week", d, "sunday"),  # WEEK() ignores the workbook's week start (golden_calcs_v2)
    "STR": _str,
    "INT": lambda v: None if (f := _to_float(v)) is None else int(f),  # truncates toward zero
    "FLOAT": _to_float,
    "CONTAINS": lambda s, sub: sub in s,
    "STARTSWITH": lambda s, sub: s.startswith(sub),
    "ENDSWITH": lambda s, sub: s.endswith(sub),
    "LEFT": lambda s, n: s[:max(n, 0)],
    "RIGHT": lambda s, n: s[len(s) - min(max(n, 0), len(s)):],
    "MID": _mid,
    "UPPER": str.upper,
    "LOWER": str.lower,
    "REPLACE": lambda s, sub, new: s.replace(sub, new) if sub else s,
    "LEN": len,
    "TRIM": lambda s: s.strip(" "),
    # functions v3 (decisions/055)
    "MAKEDATE": _makedate,
    "MAKETIME": _maketime,
    "MAKEDATETIME": lambda d, t: dt.datetime.combine(_day(d), t.time()),
    "DATEPARSE": _dateparse,
    "DATE": _day,
    "DATETIME": _to_datetime,
    **{f: (lambda d, f=f: _isopart(f, d)) for f in ISO_PARTS},
    "SPLIT": _split,
    "FIND": _find,
    "FINDNTH": _findnth,
}


def _level(levels, where):
    real = {lv for lv in levels if lv != "const"}
    if real == {"row", "agg"}:
        raise FormulaError(f"cannot mix aggregate and non-aggregate values in {where} "
                           f"(wrap the row-level part in SUM/AVG/... or remove the aggregate)")
    return real.pop() if real else "const"


def _children(node):
    if isinstance(node, Unary):
        return [node.arg]
    if isinstance(node, Bin):
        return [node.left, node.right]
    if isinstance(node, Func):
        return list(node.args)
    if isinstance(node, If):
        return [x for b in node.branches for x in b] + ([node.otherwise] if node.otherwise is not None else [])
    if isinstance(node, Case):
        return ([node.subject] + [x for b in node.branches for x in b]
                + ([node.otherwise] if node.otherwise is not None else []))
    if isinstance(node, Lod):
        return list(node.dims) + [node.body]
    return []


def _fold(kind, vals):
    """RUNNING_* / WINDOW_* over the non-NULL values of the span; of none every fold is NULL, COUNT too (Desktop draws
    nothing at RUNNING_COUNT over no value, decisions/147)."""
    if not vals:
        return None
    if kind == "COUNT":
        return len(vals)
    if kind == "MEDIAN":
        from .compareviz import percentile
        return percentile(vals, 0.5)
    return {"SUM": sum, "AVG": lambda x: sum(x) / len(x), "MAX": max, "MIN": min}[kind](vals)


def _table_calc_funcs(node):
    """Names of the table calculation functions in a formula, in source order (decisions/034)."""
    own = [node.name] if isinstance(node, Func) and node.name in TABLE_CALCS else []
    return own + [n for c in _children(node) for n in _table_calc_funcs(c)]


def _is_offset(node, funcs):
    """An integer literal (optionally negative), or FIRST() / LAST() when allowed."""
    if isinstance(node, Unary) and node.op == "-":
        node = node.arg
    if isinstance(node, Num):
        return isinstance(node.value, int)
    return isinstance(node, Func) and node.name in funcs and not node.args


def _refs(node):
    """Field and parameter references of a formula (they carry their position in the source)."""
    if isinstance(node, (Ref, Param)):
        yield node
    elif isinstance(node, Case):
        yield from _refs(node.subject)
        for _, v in node.branches:
            yield from _refs(v)
        if node.otherwise is not None:
            yield from _refs(node.otherwise)
    elif isinstance(node, Unary):
        yield from _refs(node.arg)
    elif isinstance(node, Bin):
        yield from _refs(node.left)
        yield from _refs(node.right)
    elif isinstance(node, Func):
        for a in node.args:
            yield from _refs(a)
    elif isinstance(node, If):
        for c, v in node.branches:
            yield from _refs(c)
            yield from _refs(v)
        if node.otherwise is not None:
            yield from _refs(node.otherwise)
    elif isinstance(node, Lod):
        for d in node.dims:
            yield from _refs(d)
        yield from _refs(node.body)
