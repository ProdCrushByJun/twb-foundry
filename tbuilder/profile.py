"""CSV profiling: column types and distinct values.

Types are declared in the workbook, so inference must be strict: anything that
is not unambiguously date/datetime/integer/real becomes string, and date columns
whose format cannot be told for sure fail loudly instead of being guessed (tbuilder/dates.py).
Date values are rewritten to ISO in `rows`; the CSV file itself is packaged unchanged.
"""
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import dates

_INT = re.compile(r"^-?\d+$")
_REAL = re.compile(r"^-?\d+\.\d+$")


@dataclass
class Column:
    name: str
    datatype: str  # date | datetime | string | integer | real
    distinct: list = field(default_factory=list)  # sorted, strings only
    date_format: object = None  # dates.DateFormat of a date/datetime column
    date_like: str = ""  # a string column: its first value that looks like a date in an unsupported shape

    @property
    def role(self) -> str:
        return "measure" if self.datatype in ("integer", "real") else "dimension"


@dataclass
class Profile:
    path: Path
    columns: list
    rows: list
    locale: str | None = None  # text-file locale its dates need; None: any, the workbook's is used (decisions/085)

    def col(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise ValueError(f"Field '{name}' not found in {self.path.name}. Available: {[c.name for c in self.columns]}")


def _infer(values: list, name: str):
    """-> (datatype, DateFormat | None)"""
    non_empty = [v for v in values if v != ""]
    if not non_empty:
        return "string", None
    fmt = dates.detect(non_empty, name)
    if fmt:
        return fmt.datatype, fmt
    if all(_INT.match(v) for v in non_empty):
        return "integer", None
    if all(_INT.match(v) or _REAL.match(v) for v in non_empty):
        return "real", None
    return "string", None


def check_names(where, names):
    """Column names of a CSV header or an Excel header row."""
    if len(set(names)) != len(names):
        raise ValueError(f"{where}: duplicate column names")
    for n in names:
        if any(ch in n for ch in "[]'\"<>&"):
            raise ValueError(f"{where}: column name '{n}' contains XML/Tableau-unsafe characters")


def profile_csv(path) -> Profile:
    path = Path(path)
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        names = reader.fieldnames or []
    if not names:
        raise ValueError(f"{path.name}: no header row")
    check_names(path.name, names)
    for r in rows:  # Desktop's text connector drops the spaces around a value ("  Padded  " -> "Padded", decisions/031)
        for n in names:
            if r[n]:
                r[n] = r[n].strip(" ")
    cols = []
    for n in names:
        values = [r[n] for r in rows]
        dt, fmt = _infer(values, n)
        distinct = sorted({v for v in values if v != ""}) if dt == "string" else []
        cols.append(Column(n, dt, distinct, fmt, dates.unparsed(distinct) or "" if dt == "string" else ""))
        if fmt and fmt is not dates.ISO:  # ISO dates are already in the normalized form (and were validated)
            for r in rows:
                if r[n] != "":
                    r[n] = fmt.to_iso(r[n])
    return Profile(path, cols, rows, dates.locale([c.date_format for c in cols]))
