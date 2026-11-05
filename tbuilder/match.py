"""Evidence for binding outline blocks to CSV fields.

KPI numbers: try every aggregation of every field and report which reproduce the
displayed value (at its displayed precision, optionally with a unit scale).
Category blocks (bars, lists, controls): compare their labels with each string
column's distinct values.
The procedure binds a block only to a candidate backed by this evidence.
"""
import re

from . import formats
from .expected import _agg
from .excel import load

SCALES = {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "m": 1e6, "mn": 1e6, "B": 1e9, "b": 1e9, "bn": 1e9, "T": 1e12}
_LEAD = re.compile(r"^([-+−–]?)\s*[$€£₽¥]?\s*(\d[\d ,.]*)(.*)$")
_SUFFIX = re.compile(r"^(%|pp|bn|mn|[kKmMbBT])(?![A-Za-z])")


def parse_number(text, locale=None):
    """'38,226' -> (38226.0, 1, '', False); '74.8%' -> (74.8, 0.1, '%', True); '12 MW' -> (12.0, 1, '', False).

    Returns (value, display step, scale/percent suffix, is_percent) or None if the text does not start with a number.
    locale: the marks of a workbook in that locale (formats.LOCALES; decisions/085): en_US '0.179' is 0.179 and
    '2,742' 2742, ru_RU '1,234' is 1.234; None guesses them from the text (an HTML page: '1,234' a thousand).
    """
    t = text.replace(" ", " ").replace(" ", " ").strip()
    m = _LEAD.match(t)
    if not m:
        return None
    sign, body, rest = m.group(1), m.group(2).rstrip(" ,."), m.group(3)
    rest = t[len(m.group(1)) :].split(body, 1)[1] if body else rest
    sm = _SUFFIX.match(rest.strip())
    suffix = sm.group(1) if sm else ""
    body = body.replace(" ", "")
    if locale:
        group, point = formats.LOCALES[locale]
        g = group.strip()  # ru_RU groups by a space: gone already
        whole, has_point, frac = body.partition(point)
        if not (re.fullmatch(r"\d+", whole) or g and re.fullmatch(r"\d{1,3}(?:" + re.escape(g) + r"\d{3})+", whole)) \
                or not re.fullmatch(r"\d*", frac):
            return None  # not a number of this locale: '1.234,5' in en_US
        body, dec = whole.replace(g, "") if g else whole, None
        if has_point and frac:
            body, dec = f"{body}.{frac}", "."
    elif "," in body and "." in body:  # 1,234.5 or 1.234,5
        dec = "." if body.rfind(".") > body.rfind(",") else ","
    elif "," in body:
        dec = "," if re.search(r",\d{1,2}$", body) else None
    elif "." in body:
        dec = None if re.search(r"^\d{1,3}(\.\d{3})+$", body) else "."
    else:
        dec = None
    digits = body.replace(",", "").replace(".", "") if dec is None else         body.replace("." if dec == "," else ",", "").replace(dec, ".")
    value = float(digits) * (-1 if sign in ("-", "−", "–") else 1)
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    return value, round(10 ** -decimals, decimals), suffix, suffix in ("%", "pp")


def _mentioned_members(label, prof):
    """(column, value) pairs whose value is named in the KPI label, e.g. 'WIND' -> source_type=wind."""
    out = []
    for col in prof.columns:
        if col.datatype == "string" and 1 < len(col.distinct) <= 50:
            for v in col.distinct:
                if _meaningful(v) and re.search(r"(?<![a-z0-9])" + re.escape(v.lower()) + r"(?![a-z0-9])", (label or "").lower()):
                    out.append((col.name, v))
    return out


def _meaningful(v):
    return len(v) >= 3 and not v.replace(".", "").isdigit()


def kpi_candidates(text, prof, label=None, limit=5):
    """Field/agg combos (optionally within one category named in the label) matching the displayed number."""
    parsed = parse_number(text)
    if not parsed:
        return []
    shown, step, suffix, is_pct = parsed
    if is_pct:
        return []  # shares need a calculation; reported, not bound
    scale = SCALES.get(suffix, 1)
    hits = []
    members = _mentioned_members(label, prof)
    scopes = [([], prof.rows)] + [([(c, v)], [r for r in prof.rows if r[c] == v]) for c, v in members]
    if len({c for c, _ in members}) >= 2:  # e.g. table cell "East" x "Furniture": all conditions together
        scopes.append((members, [r for r in prof.rows if all(r[c] == v for c, v in members)]))
    for where, rows in scopes:
        for col in prof.columns:
            aggs = ["count", "countd"] + (["sum", "avg", "min", "max"] if col.role == "measure" else [])
            values = [r[col.name] for r in rows]
            for how in aggs:
                v = _agg(values, how)
                if v is None:
                    continue
                for unit, factor in ((suffix or "", scale), ("÷1000", 1e3 * scale), ("×1000", scale / 1e3)):
                    if abs(v / factor - shown) <= step / 2 + 1e-9:
                        hit = {"field": col.name, "agg": how, "value": v, "unit": unit or None}
                        if where:
                            hit["where"] = " AND ".join(f"{c} = {v}" for c, v in where)
                        hits.append(hit)
    exact = [h for h in hits if h["unit"] in (None, suffix or None)]
    hits = exact or hits
    # most specific evidence first: more conditions, then fewer unit conversions
    return sorted(hits, key=lambda h: -h.get("where", "").count(" = "))[:limit]


NUMBER_TOKEN = re.compile(r"[-+]?\d[\d,.]*\s?(?:%|[kKMB](?![A-Za-z]))?")

MONTHS = {m.lower() for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
                               "January", "February", "March", "April", "June", "July", "August",
                               "September", "October", "November", "December"]}


def axis_candidates(texts, prof):
    """Date columns + the level suggested by axis labels (months, quarters, years, ISO dates)."""
    t = [x.strip().lower() for x in texts if x.strip()]
    if not t:
        return []
    if sum(x in MONTHS for x in t) >= 2:
        level = "month"
    elif sum(bool(re.fullmatch(r"q[1-4]( \d{4})?|\d{4}[- ]?q[1-4]", x)) for x in t) >= 2:
        level = "quarter"
    elif sum(bool(re.fullmatch(r"(19|20)\d{2}", x)) for x in t) >= 2:
        level = "year"
    elif sum(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", x)) for x in t) >= 2:
        level = "day"
    else:
        return []
    dates = [{"field": c.name, "level": level} for c in prof.columns if c.datatype in ("date", "datetime")]
    years = [{"field": c.name, "level": level, "note": "integer year column: not supported as time axis"}
             for c in prof.columns if level == "year" and c.datatype == "integer"
             and all(re.fullmatch(r"(19|20)\d{2}", r[c.name]) for r in prof.rows[:200] if r[c.name])]
    return dates + years


def label_candidates(labels, prof, limit=3):
    """String columns whose distinct values cover the block's labels."""
    words = {w.strip().lower() for l in labels for w in re.split(r"[·|•\n]", l) if w.strip()}
    out = []
    for col in prof.columns:
        if col.datatype != "string" or not col.distinct:
            continue
        vals = {v.lower() for v in col.distinct}
        found = {v for v in vals if _meaningful(v) and any(v == w or re.search(rf"\b{re.escape(v)}\b", w) for w in words)}
        if found:
            out.append({"field": col.name, "matched": sorted(found), "coverage": round(len(found) / len(vals), 2)})
    return sorted(out, key=lambda c: (-len(c["matched"]), -c["coverage"]))[:limit]


def year_candidates(labels, prof):
    """Labels that are 4-digit years (a matrix with a column per year) over a date column whose YEAR gives them
    (decisions/118). Same shape as the 'Year' slicer candidate: date_part."""
    nonempty = [x for x in labels if x.strip()]
    years = {x.strip() for x in nonempty if re.fullmatch(r"(19|20)\d{2}", x.strip())}
    if len(years) < 2 or len(years) < 0.6 * len(nonempty):
        return []
    out = []
    for col in prof.columns:
        if col.datatype in ("date", "datetime"):
            have = {r[col.name][:4] for r in prof.rows if r[col.name]}  # dates are ISO in the profile
            if years <= have:
                out.append({"field": col.name, "matched": sorted(years), "coverage": round(len(years) / len(have), 2),
                            "by": "headers", "date_part": "year"})
    return out


def _norm(name):
    return re.sub(r"[\W_]+", " ", name).strip().lower()


_DATE_PARTS = ("year", "quarter", "month", "week", "day", "date", "period")


def slicer_candidates(c, prof, by_values):
    """Static slicer (decisions/112): its caption names a data column ('Region'), or its values are that column's
    values. A caption that names no column and values that match none (a legend, a note) give no candidate."""
    named = [{"field": col.name, "matched": [], "coverage": 0, "by": "caption"} for col in prof.columns
             if _norm(col.name) == _norm(c.get("label", "")) and _norm(col.name)]
    if not named and _norm(c.get("label", "")) in _DATE_PARTS:  # 'Year' over the data's one date column
        dcols = [col for col in prof.columns if col.datatype in ("date", "datetime")]
        named = [{"field": col.name, "matched": [], "coverage": 0, "by": "caption", "date_part": _norm(c["label"])}
                 for col in dcols] if len(dcols) == 1 else []
    seen = {n["field"] for n in named}
    return named + [dict(v, by="values") for v in by_values if v["field"] not in seen]


def series_color_entries(outline, prof):
    """Colors of chart series (decisions/133): a legend or a chart's series names are values of a column (or the years
    of the data's date) -> the colors as a candidate for the spec's fields.<column>.color. A hint, not a decision."""
    out = []
    for sc in outline.get("series_colors", []):
        names = list(sc["series"])
        cands = []
        for c in label_candidates(names, prof):
            real = {v.lower(): v for col in prof.columns if col.name == c["field"] for v in col.distinct}
            hit = set(c["matched"])
            colors = {real.get(n.lower(), n): sc["series"][n] for n in names if n.lower() in hit}  # legend order, data's spelling
            cands.append(dict(c, color=colors, spec={"fields": {c["field"]: {"color": colors}}}))
        for c in year_candidates(names, prof):
            cands.append(dict(c, color={n: sc["series"][n] for n in names if n in c["matched"]},
                              note="a row-level text calc STR(YEAR([%s])) is the field to color" % c["field"]))
        if sc["source"] == "text" and not cands:  # colored words are a legend only if the data names them
            continue
        out.append({"id": "series_colors", "kind": "series_colors", "source": sc["source"],
                    "series": sc["series"], "candidates": cands})
    return out


def measure_candidates(heading, prof):
    """Numeric columns whose name words all occur in the chart's heading."""
    words = set(_norm(heading or "").split())
    return [{"field": c.name} for c in prof.columns
            if c.role == "measure" and _norm(c.name) and set(_norm(c.name).split()) <= words]


def paint_entries(outline, prof):
    """Mark colors (decisions/135): the color of a single series (no legend) is the measure's; the ends of a color
    scale (heatmap, colorbar) are the low and high of the measure. Evidence only: the spec has no key for them yet."""
    legend = {c.lower() for sc in outline.get("series_colors", []) for c in sc["series"].values()}
    out = []
    for p in outline.get("paints", []):
        cands = measure_candidates(p.get("heading"), prof)
        if p["kind"] == "single":
            if p["source"] in ("svg", "css") and p["color"].lower() in legend:
                continue  # already a series of a legend
            out.append({"id": "measure_color", "kind": "measure_color", "source": p["source"], "color": p["color"],
                        "mark": p.get("mark", ""), "heading": p.get("heading", ""), "series": p.get("name", ""),
                        "candidates": cands})
        else:
            out.append({"id": "color_scale", "kind": "color_scale", "source": p["source"], "colors": p["colors"],
                        "low": p["colors"][0], "high": p["colors"][-1], "mark": p.get("mark", ""),
                        "heading": p.get("heading", ""), "candidates": cands})
    return out


def match(outline, csv_path, sheet=None):
    prof = load(csv_path, sheet)  # a CSV or a sheet of an .xlsx
    report = []
    for b in outline["blocks"]:
        entry = {"id": b["id"], "kind": b["kind"], "heading": b.get("heading")}
        if b["kind"] == "kpi":
            entry.update(text=b["text"], label=b.get("label"), format=formats.infer(b["text"]),  # decisions/032
                         candidates=kpi_candidates(b["text"], prof, b.get("label")))
        elif b["kind"] in ("bars", "list", "table"):
            if b["kind"] == "table":
                entry.update(row_candidates=label_candidates(b["row_labels"], prof) + year_candidates(b["row_labels"], prof),
                             col_candidates=label_candidates(b["headers"][1:], prof) + year_candidates(b["headers"][1:], prof),
                             cell_candidates=[(c, kpi_candidates(c, prof, f"{row[0]} {b['headers'][i]}", 3))
                                              for row in b["sample"][:1] for i, c in enumerate(row)
                                              if i and i < len(b["headers"]) and parse_number(c)])
                labels = b["row_labels"] + b["headers"]
            else:
                labels = b.get("labels") or [" ".join(r) for r in b.get("rows", [])]
            entry.update(labels=labels[:12], candidates=label_candidates(labels, prof))
            if b["kind"] == "list":
                entry["row_numbers"] = [[(c, kpi_candidates(c, prof, " ".join(row), 3)) for c in row if parse_number(c)]
                                        for row in b.get("rows", [])[:3]]
            if b["kind"] == "bars":  # numbers printed next to bars -> the measure behind them
                entry["value_candidates"] = [(n, kpi_candidates(n, prof, l, 3))
                                             for l in labels[:3] for n in NUMBER_TOKEN.findall(l)]
        elif b["kind"] == "svg":
            entry.update(axis=b.get("texts", [])[:12], candidates=axis_candidates(b.get("texts", []), prof))
        else:
            entry["candidates"] = []
        report.append(entry)
    for c in outline.get("controls", []):
        cands = label_candidates(c["options"], prof)
        if c["kind"] == "slicer":  # static markup (decisions/112): a filter only if the data backs it
            cands = slicer_candidates(c, prof, cands)
        report.append({"id": "control", "kind": c["kind"], "options": c["options"][:12], "candidates": cands})
    report.extend(series_color_entries(outline, prof))
    report.extend(paint_entries(outline, prof))
    for entry in report:  # '40.2 h': the unit the tile's number is in (decisions/090)
        if entry["kind"] == "kpi" and unit_suffix(entry["text"]):
            entry["unit"] = unit_suffix(entry["text"])
    return report


# ---- units after a number (decisions/090) -------------------------------------------------------------------------
# '40.2 h', '35 min', '3.5 d', '120 ms', '2.4x', '+1.2 pp': the number is the value as is (no scale), the unit says
# what it measures. A KPI label names the unit after a comma or in parentheses: 'Mean time to resolve, h', 'MTTR (h)'.
UNITS = ("h", "hr", "hrs", "min", "mins", "d", "ms", "s", "sec", "wk", "wks", "mo", "yr", "yrs", "x", "×", "pp")
_UNITS_RE = "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True))
_UNIT = re.compile(rf"^\s?({_UNITS_RE})(?![\w])")
_LABEL_UNIT = re.compile(rf"^(.*?\S)\s*(?:,\s*({_UNITS_RE})|\(({_UNITS_RE})\))\s*$")


def unit_suffix(text):
    """The unit right after the number that starts text ('40.2 h' -> 'h', '2.4x' -> 'x'), None without one."""
    t = text.replace(" ", " ").replace(" ", " ").strip()
    m = _LEAD.match(t)
    if not m:
        return None
    body = m.group(2).rstrip(" ,.")
    rest = t[len(m.group(1)):].split(body, 1)[1] if body else m.group(3)
    u = _UNIT.match(rest)
    return u.group(1) if u else None


def label_unit(label):
    """('Mean time to resolve', 'h') of 'Mean time to resolve, h' or 'MTTR (h)'; (label, None) without a unit."""
    m = _LABEL_UNIT.match(label or "")
    return (m.group(1), m.group(2) or m.group(3)) if m else (label, None)
