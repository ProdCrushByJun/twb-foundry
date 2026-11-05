"""Number formats (decisions/032): spec format -> Tableau format string, and how Tableau shows a value in it.

A spec format is a preset name ("percent", "currency_k", ...) or an object
  {type: number|currency|percent, decimals: 0-6, units: none|K|M|B, symbol: "$", negative: minus|parentheses,
   plus: true, suffix: "pp"}   (plus: an explicit "+" before a positive number, suffix: the unit after it; both for
type number only: "+92", "+3.2 pp", decisions/124).
The format strings are the ones Desktop's Format -> Numbers dialog writes (Number / Currency (Custom) with Display
Units, Percentage), as found in Desktop-saved reference workbooks:
  n#,##0;-#,##0  n#,##0;(#,##0)  n#,##0,.0K;-#,##0,.0K  n#,##0,,.0M;-#,##0,,.0M
  c"$"#,##0;-"$"#,##0  c"$"#,##0;("$"#,##0)  c"$"#,##0,.0K;-"$"#,##0,.0K  p0.0%
  n"+"#,##0;-#,##0  n"+"#,##0.0" pp";-#,##0.0" pp"   (124)
The format belongs to the field (the column's default-format), so labels, axes, tooltips and KPI text agree.
render() is the text Tableau shows for a value: expected numbers and reconcile compare with it.
"""
import re
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal

TYPES = ("number", "currency", "percent")
UNITS = {"none": (1, ""), "K": (1e3, "K"), "M": (1e6, "M"), "B": (1e9, "B")}
SYMBOLS = {"$": "prefix", "€": "prefix", "£": "prefix", "¥": "prefix", "₽": "suffix"}  # ₽ after the number: 1 234 ₽
NEGATIVE = ("minus", "parentheses")
SUFFIXES = ("pp", "pcs", "min")  # pp: percentage points, a number with a unit (decisions/124); pcs, min: a count
# of pieces and minutes, "12 pcs", "62 min" (decisions/178)
MAX_DECIMALS = 6
PRESETS = {
    "percent": {"type": "percent", "decimals": 1},  # decisions/009, the format of calcs before 032
    "pct0": {"type": "percent", "decimals": 0},
    "pct1": {"type": "percent", "decimals": 1},
    "pct2": {"type": "percent", "decimals": 2},
    "number": {"type": "number", "decimals": 0},
    "number1": {"type": "number", "decimals": 1},
    "number_k": {"type": "number", "decimals": 1, "units": "K"},
    "number_m": {"type": "number", "decimals": 1, "units": "M"},
    "currency": {"type": "currency", "decimals": 0},
    "currency_k": {"type": "currency", "decimals": 1, "units": "K"},
    "currency_m": {"type": "currency", "decimals": 1, "units": "M"},
}
# The workbook shows numbers in its own locale (<workbook locale>, decisions/085; a workbook without one shows them
# in the viewer's): grouping and decimal separators. A spec without "locale" is en_US.
LOCALES = {"en_US": (",", "."), "ru_RU": (" ", ",")}
DEFAULT_LOCALE = "en_US"
_shown_in = [DEFAULT_LOCALE]  # the locale render() uses when given none: the workbook's being built (shown_in)


def workbook_locale(spec):
    """The locale the spec's workbook shows numbers and dates in (decisions/085)."""
    return spec.get("locale", DEFAULT_LOCALE)


@contextmanager
def shown_in(locale):
    """render() without a locale renders in this one inside the block: the build of a workbook in its locale."""
    _shown_in.append(locale)
    try:
        yield
    finally:
        _shown_in.pop()


class FormatError(ValueError):
    pass


def normalize(fmt, where="format"):
    """Spec format -> {type, decimals, units, symbol, negative}; None stays None."""
    if fmt is None:
        return None
    if isinstance(fmt, str):
        if fmt not in PRESETS:
            raise FormatError(f"{where}: unknown format '{fmt}'. Presets: {sorted(PRESETS)}")
        fmt = PRESETS[fmt]
    t = fmt.get("type", "number")
    if t not in TYPES:
        raise FormatError(f"{where}: type '{t}' is not one of {list(TYPES)}")
    d = fmt.get("decimals", 1 if t == "percent" else 0)
    if not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= MAX_DECIMALS:
        raise FormatError(f"{where}: decimals {d!r} must be a whole number 0-{MAX_DECIMALS}")
    units = fmt.get("units", "none")
    if units not in UNITS:
        raise FormatError(f"{where}: units '{units}' is not one of {list(UNITS)}")
    if t == "percent" and units != "none":
        raise FormatError(f"{where}: a percent has no display units")
    symbol = fmt.get("symbol", "$" if t == "currency" else None)
    if t != "currency" and fmt.get("symbol") is not None:
        raise FormatError(f"{where}: 'symbol' applies to type currency only")
    if symbol is not None and symbol not in SYMBOLS:
        raise FormatError(f"{where}: currency symbol '{symbol}' is not one of {list(SYMBOLS)}")
    neg = fmt.get("negative", "minus")
    if neg not in NEGATIVE:
        raise FormatError(f"{where}: negative '{neg}' is not one of {list(NEGATIVE)}")
    plus, suffix = fmt.get("plus", False), fmt.get("suffix")
    if not isinstance(plus, bool):
        raise FormatError(f"{where}: plus {plus!r} must be true or false")
    if suffix is not None and suffix not in SUFFIXES:
        raise FormatError(f"{where}: suffix '{suffix}' is not one of {list(SUFFIXES)}")
    if suffix and t != "number":
        raise FormatError(f"{where}: 'suffix' applies to type number only")
    if plus and t == "currency":
        raise FormatError(f"{where}: 'plus' applies to type number and percent")
    return {"type": t, "decimals": d, "units": units, "symbol": symbol, "negative": neg, "plus": plus,
            "suffix": suffix}


def is_number_format(fmt):
    """A spec number format, not one of the card calcs' own strings ('delta', a '*mmm yyyy' date format)."""
    return isinstance(fmt, dict) or fmt in PRESETS


def is_percent(fmt):
    return is_number_format(fmt) and normalize(fmt)["type"] == "percent"


def measures(s):
    """The measure objects of a sheet, each of which may carry a format."""
    out = list(s.get("measures", []))
    out += [s[k] for k in ("measure", "plan", "bar", "line", "from", "to") if isinstance(s.get(k), dict)]  # bar, line: a combo
    out += [s[k] for k in ("x", "y", "size") if isinstance(s.get(k), dict)]  # a scatter (decisions/047)
    return out + [c["measure"] for c in s.get("columns", []) if isinstance(c, dict) and "measure" in c]


def fields(spec, datatype):
    """{CSV column: normalized format} from the sheets' measures (decisions/032). datatype(name) -> the column's type,
    None for a calc (a calc's format is its own: calcs[].format). A format is the field's default-format, so one field
    has one format; a second look of the same field is a calc copy with its own format."""
    calc_fmt = {c["name"]: c.get("format") for c in spec.get("calcs", [])}
    out, where = {}, {}
    for s in spec["sheets"]:
        for m in measures(s):
            if "format" not in m or "per" in m:  # a ratio card measure: the format is its calcs', not the field's
                continue
            name, here = m["field"], f"Sheet '{s['name']}' measure '{m['field']}'"
            f = normalize(m["format"], here)
            if s["type"] == "kpi" and f["suffix"]:  # a unit is the card's (its calcs carry it), not other sheets' axes
                f = dict(f, suffix=None)
            if name in calc_fmt:
                if calc_fmt[name] is None or normalize(calc_fmt[name]) != f:
                    raise FormatError(f"{here}: a calculated field's format is set in calcs[].format "
                                      f"(there: {calc_fmt[name]!r})")
                continue
            t = datatype(name)
            if t not in ("integer", "real"):
                raise FormatError(f"{here}: a number format needs a numeric field, '{name}' is {t}")
            if name in out and out[name] != f:
                raise FormatError(f"{here}: '{name}' already has another format in {where[name]}; a field has one "
                                  f"format (its default-format): use a calc copy for a second one")
            out[name], where[name] = f, here
    return out


def _quote(text):
    return f'"{text}"' if text else ""


def tableau(fmt):
    """Spec format -> the format string Desktop writes in default-format / text-format."""
    f = normalize(fmt)
    dec = "." + "0" * f["decimals"] if f["decimals"] else ""
    if f["type"] == "percent":
        body = f"0{dec}%"
        if f["plus"]:  # '*+0.0%;-0.0%' as Desktop's custom format (HelpDesk RWFD; polish-26)
            return f"*+{body};" + (f"({body})" if f["negative"] == "parentheses" else f"-{body}")
        return "p" + body + (f";({body})" if f["negative"] == "parentheses" else "")
    commas, unit = "," * {"none": 0, "K": 1, "M": 2, "B": 3}[f["units"]], UNITS[f["units"]][1]
    body = f"#,##0{commas}{dec}{unit}"
    if f["type"] == "currency":
        sym = f["symbol"]
        body = _quote(sym) + body if SYMBOLS[sym] == "prefix" else body + _quote(" " + sym)
    if f["suffix"]:
        body += _quote(" " + f["suffix"])
    neg = f"({body})" if f["negative"] == "parentheses" else f"-{body}"
    return ("c" if f["type"] == "currency" else "n") + (_quote("+") if f["plus"] else "") + f"{body};{neg}"


_PCT = re.compile(r"^p0(?:\.(0+))?%(;\(.*\))?$")
_PCT_PLUS = re.compile(r"^\*\+0(?:\.(0+))?%;(\(?)")
_NUM = re.compile(r'^([nc])(?:"([^"]*)")?#,##0(,*)(?:\.(0+))?([KMB]?)(?:" ([^"]*)")?;(.*)$')


def parse(text):
    """A number format string (default-format / text-format) -> spec format; FormatError when it is not one this
    module writes: an unknown symbol, more than 6 decimals, a hand-made code. The gate reads the workbook with it."""
    m, p, pp = _NUM.match(text), _PCT.match(text), _PCT_PLUS.match(text)
    if pp:
        f = {"type": "percent", "decimals": len(pp.group(1) or ""), "plus": True,
             "negative": "parentheses" if pp.group(2) else "minus"}
    elif p:
        f = {"type": "percent", "decimals": len(p.group(1) or ""),
             "negative": "parentheses" if p.group(2) else "minus"}
    elif m:
        kind, pre, commas, dec, unit, post, neg = m.groups()
        if (len(commas), unit) not in ((0, ""), (1, "K"), (2, "M"), (3, "B")):
            raise FormatError(f"'{text}': display units {unit or 'none'} with {len(commas)} scaling commas")
        f = {"type": "currency" if kind == "c" else "number", "decimals": len(dec or ""),
             "units": unit or "none", "negative": "parentheses" if neg.startswith("(") else "minus"}
        if kind == "c":
            f["symbol"] = pre if pre is not None else post
        else:
            if pre not in (None, "+") or post not in (None, *SUFFIXES):
                raise FormatError(f"'{text}': a number format with a prefix or suffix")
            f["plus"], f["suffix"] = pre == "+", post
    else:
        raise FormatError(f"'{text}': not a number format this builder writes")
    if tableau(f) != text:
        raise FormatError(f"'{text}': not a number format this builder writes (expected {tableau(f)})")
    return normalize(f, f"'{text}'")


def _digits(x, decimals, group, point):
    q = Decimal(repr(x)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    whole, _, frac = f"{abs(q):f}".partition(".")
    whole = re.sub(r"(?<=\d)(?=(\d{3})+$)", group, whole)
    return whole + (point + frac if frac else ""), q < 0


def render(value, fmt, locale=None):
    """The text Tableau shows for value in this format: render(634612, 'number_k', 'en_US') -> '634.6K'."""
    if value is None:
        return ""
    f = normalize(fmt)
    group, point = LOCALES[locale or _shown_in[-1]]
    if f["type"] == "percent":
        text, neg = _digits(value * 100, f["decimals"], "", point)
        text += "%"
    else:
        scale, unit = UNITS[f["units"]]
        text, neg = _digits(value / scale, f["decimals"], group, point)
        text += unit
        if f["suffix"]:
            text += " " + f["suffix"]
        if f["type"] == "currency":
            text = f["symbol"] + text if SYMBOLS[f["symbol"]] == "prefix" else f"{text} {f['symbol']}"
    if not neg:
        return "+" + text if f["plus"] else text
    return f"({text})" if f["negative"] == "parentheses" else "-" + text


# --- HTML -> spec -------------------------------------------------------------------------------------------------
_UNIT = {"k": "K", "K": "K", "m": "M", "M": "M", "mn": "M", "b": "B", "B": "B", "bn": "B"}


def infer(text):
    """The format a number on an HTML page is shown in: '$1.2M' -> currency, M, 1 decimal; '(1,234)' -> negative in
    parentheses; '12.5%' -> percent 1. None when the text does not start with a number. Grouping/decimal marks follow
    match.parse_number ('1,234' is a thousand, '1,5' a decimal)."""
    from .match import parse_number  # not at the top: match imports expected
    t = text.replace(" ", " ").replace(" ", " ").strip()
    parsed = parse_number(t.strip("() "))
    if not parsed:
        return None
    _, step, suffix, is_pct = parsed
    decimals = max(0, -Decimal(repr(step)).normalize().as_tuple().exponent) if step < 1 else 0
    symbol = next((c for c in t if c in SYMBOLS), None)
    if is_pct and suffix != "pp":  # percentage points are a number with a unit
        out = {"type": "percent", "decimals": decimals}
        if t.startswith("+"):
            out["plus"] = True
    else:
        out = {"type": "currency" if symbol else "number", "decimals": decimals, "units": _UNIT.get(suffix, "none")}
        if symbol:
            out["symbol"] = symbol
        elif suffix == "pp":
            out["suffix"] = "pp"
        if t.startswith("+") and not symbol:  # an explicit plus: "+92", "+3.2 pp" (decisions/124)
            out["plus"] = True
    if t.startswith("(") and t.endswith(")"):
        out["negative"] = "parentheses"
    elif t[:1] in "-−":
        out["negative"] = "minus"
    return out


def same_form(shown, fmt):
    """Does the HTML text's form (infer) agree with the field's format? Separators are the workbook's locale and are
    not compared; a minus sign says nothing about the negative style, so only parentheses are. A unit "pp" is
    compared always, a plus sign only for a positive text (a negative one cannot show it)."""
    got, f = infer(shown), normalize(fmt)
    if got is None:
        return True
    g = normalize(got)
    keys = ("type", "decimals", "units", "symbol", "suffix", "negative" if "negative" in got else "plus")
    return all(g[k] == f[k] for k in keys)
