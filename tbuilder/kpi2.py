"""KPI cards v2 (todo 8.2, decisions/037): options of kpi style "cards" from reference set 3 (style-references-3.md).

- delta "abs_pct": the change as "▲ 1 466 | 10,5% MoM": the absolute change with its arrow, then the percent
  (Regional Overview "+0.9M vs PY", RETAIL-POS). Default "pct" is the card of decisions/013.
- delta_style "pill": the change leaves the value text for a pill under it: bold text on a pale fill in the sign's
  color (European / Superstore Performance: a 40px sheet, the bar at 12-25 % opacity, the text bold).
- history "line": a sparkline instead of the bars (Demand Overview); only its max and its last point are labelled,
  history_reference draws the dashed average over it (decisions/028).
- marker "bar": a 4px bar left of the card text in the sign's color (Regional Overview, Help Desk, Wealth & Banking).
- period_line (one cards sheet): "Dec 2025 compared to Nov 2025" once under the dashboard header (RETAIL-POS).
- dashboard.data_as_of <date column>: "Data as of 31 Dec 2025" at the right of the dashboard header (Regional
  Overview, Demand Overview, Customer Support).
- history_points ["max", "min", "last"] (decisions/059): colored dots on the sparkline at its max / min / last period,
  a second layer on the line's axis (dual axis of decisions/044, ER Operation 'KPI Patient - Line'); their values
  next to them unless history_point_labels is false.
Without these keys nothing here changes the output.

XML (forms from Desktop-saved workbooks, not guessed):
- pill and marker: a Bar of the constant MIN(1) on a fixed 0..1 hidden axis (Columns for the pill, Rows for the
  marker: its length is the zone's long side), marks-scaling-off and size 1.989 (its thickness the zone's short
  side), colored by an aggregate boolean flag ([usr:..:nk] with a palette map in the datasource style, as color.good
  of decisions/016); the form of European Superstore 'Sales KPI YTD' (AVG(1) on a fixed 0..1 axis). decisions/063:
  a Square without axes (037) Desktop draws as a dot in the middle of the zone. The pill's palette is the pale fill
  tokens, its label bold in good_text / bad_text, centered in the bar (cell style-rule, Regional Overview).
- sparkline: the history sheet with mark Automatic (a line on a continuous date, as the line sheets), its label a
  generated table calc (WINDOW_MAX / LAST along the date, the form of the history change flag of decisions/028).
- data as of: a fixed-size worksheet zone in the header row's horizontal flow (Regional Overview 'data as of': fixed
  200, show-title false; its text aligned by the pane's cell style-rule); period line: a text worksheet zone in the
  root layout under the header. Both show MIN of a date calc ([min:..:qk], the card's period of decisions/013).
- sparkline points: '(SUM([m]) + [Point Value])' on Rows folded onto one synchronized axis; the line layer Line, the
  points layer Circle colored by a string table calc 'Max' / 'Min' / 'Last' with a palette map (ER: the same two
  calcs, value and kind; the map on a table calc as the history change flag of decisions/028), both computed along
  the date; null-value warning off (the points are null in the other periods).
- status dot (decisions/062): measures[].status {on: value | change, thresholds: [lo, hi]} colors a dot left of the
  card text, level with the number, by thresholds (SOC Monitor: a status dot by the number, its Critical / Warning /
  Healthy legend in the header): a string calc IF [x] >= hi THEN "On track" ELSEIF [x] >= lo THEN "At risk" ELSEIF [x] < lo THEN "Off track"
  END (<= for good 'down') on the Color of a Circle on a sheet without rows and columns (the marker's sheet; the
  Circle with marks-scaling-off and its size in the pane style as the scatter points of decisions/047), its palette
  map in the datasource style (good / warn / bad). The legend: a line of the block header (status_legend 'block') or
  of the dashboard header ('dashboard'), a dot and the label per status, as the inline legend of decisions/045.
- progress (decisions/155): measures[].target {value | field} adds '103% of $15.0K target' to the card text and a
  progress bar under it; the sheet's progress 'bar' (fill over a track of its thickness) or 'thin' (the fill over a
  thin track line). References '1. Normal Progress Chart' / '5. Bar within Bar I', 'Simple
  Progress Bars': the constant (the 100 % track) and the share on Columns as a dual axis, the second axis folded
  onto the first; here the first fixed 0..1 (the pill's axis of decisions/063) and the fill clamped to 0..1, so a
  card over its target shows a full bar in the good color (bad for good 'down': a budget overrun).
"""
import math
import xml.etree.ElementTree as ET

from . import cards, design, formats, strings, theme
from .design import COLOR, FONT, SPACE

KEYS = ("delta", "delta_style", "history", "marker", "period_line", "history_points", "history_point_labels",
        "status_labels", "status_legend", "base_value", "history_points_legend", "history_months", "progress",
        "history_place", "delta_zero", "card_date", "separate_cards", "delta_colors")
PILL, MARKER, PERIOD, AS_OF, STATUS = "card_pill", "card_marker", "period_line", "data_as_of", "card_status"
PROGRESS = "card_progress"  # decisions/155
PARTS = (PILL, MARKER, PERIOD, AS_OF, STATUS, PROGRESS)  # worksheets drawn without a title, filling their zone, no tooltip
FILLER = {"name": None, "type": "filler"}  # a part of _part_boxes that is an empty zone (next to a pill)
BAR_SHELF = {PILL: "cols", MARKER: "rows"}  # the bar's length along the zone's long side (decisions/063)
# bold 10pt in Desktop 2025.1: "▲ 103,1% vs PY" 118px, "▲ 2 | 2,0% MoM" 122px (0.63-0.65 em a char); CHAR_EM 0.6
# clipped them in the bar (decisions/063)
PILL_CHAR_EM = 0.7
BAR_SIZE = "1.989"  # the bar's thickness: the whole zone across (European Superstore 'Sales KPI YTD' pill)
AS_OF_SHEET = "Data As Of"
AS_OF_FORMAT = "*dd mmm yyyy"


def abs_delta(s):
    return s.get("delta") == "abs_pct"


def pill(s):
    return s.get("delta_style") == "pill"


def line(s):
    """A sparkline: history 'line', or 'area' (the line over its pale fill, decisions/088)."""
    return s.get("history") in ("line", "area")


def area(s):
    return s.get("history") == "area"


def marker(s):
    return s.get("marker") == "bar"


# sparkline points (decisions/059): the kinds in the spec's order (a period that is two of them takes the first),
# their value in the color calc ('Max' as ER Operation), their color token by the measure's 'good'
POINT_KIND = {"max": "Max", "min": "Min", "last": "Last", "last_even": "Last Even"}
POINT_SIZE = "1.0"  # the Circle of the points layer: at 0.5 Desktop drew it hardly wider than the line


def spark_points(card):
    """The point kinds of a card's sparkline, [] without points. With delta_colors 'accent' (decisions/178) the last
    point is 'Last' (accent) when the change is worse, else 'Last Even' (the text color)."""
    ks = list(card.get("history_points", [])) if line(card) else []
    if card.get("delta_colors") == "accent" and "last" in ks:
        ks.insert(ks.index("last") + 1, "last_even")
    return ks


def point_labels(card):
    return card.get("history_point_labels", True)


def has_points(p):
    """A card history part drawn as a sparkline with points (two layers)."""
    return p["type"] == "card_history" and bool(spark_points(p["card"]))


def point_value(p):
    return f"{p['name']} · Point Value"


def point_kind(p):
    return f"{p['name']} · Point"


def point_color(kind, m):
    """The color token of a point kind: max good and min bad (swapped when the measure is good down), last accent."""
    if kind == "last":
        return "accent"
    if kind == "last_even":  # the last point of a change not worse (decisions/178)
        return "text"
    up = m.get("good", "up") == "up"
    return "good" if (kind == "max") == up else "bad"


# ---- KPI card v3 (decisions/088, a reference) ----------------------------------------------------------------
AREA_TRANSPARENCY = "64"  # the area's fill at a quarter of its color (reference: a pale #e6e6e6 area under the dots)
MONTH_LETTER = "iLLLLL"  # narrow month 'J F M ...' (reference 'Qty_ (color updated)': label text-format on the month)
BASE_WORD = {"week": "last_week", "month": "last_month", "year": "last_year"}  # '78,038 Last Year' (reference P1)


def base_value(s):
    return bool(s.get("base_value"))


def base_word(s, spec=None):
    return strings.t(spec, BASE_WORD["year" if s.get("compare", "previous") == "year" else cards.level(s)])


def month_letters(s):
    return line(s) and s.get("history_months") == "letter"


def history_date(b, card):
    """The date of a card's history: the continuous month, or with month letters the discrete one, a header under
    the sparkline (reference ER Risk: [mn:..:ok] / [tmn:..:ok] with the letter text-format on its label)."""
    from .build import Field
    d = Field(b.col(card["date"]["field"]), "date", cards.level(card))
    if month_letters(card):
        d.name, d.type = d.name.replace(":qk]", ":ok]"), "ordinal"
    return d


def point_legend(s):
    """[(label, color, glyph)] of a sparkline's points legend, one line over the KPI row (reference '⬤ = Max ⬤ = Min'),
    [] without one. The measures agree on 'good' (check), so one color names each kind."""
    if s.get("history_points_legend") != "block":
        return []
    m = s["measures"][0]
    return [(POINT_KIND[k], COLOR[point_color(k, m)], STATUS_GLYPH) for k in spark_points(s)]


def area_formats(s, color):
    """Mark formats of an area sparkline ([] for a line): the line is the area's stroke in its color, the fill the
    same color at AREA_TRANSPARENCY. Desktop draws no edge on a transparent Area (lab kpi_v3: a flat pale band);
    has-stroke is the Area's border (the reference Business Expense writes it on its areas), in Desktop's format order."""
    if not area(s):
        return []
    return [("has-stroke", "true"), ("stroke-color", color), ("mark-transparency", AREA_TRANSPARENCY),
            ("mark-color", color)]


def history_style(b, style, s, fields):
    """Month letters under a sparkline: the discrete month's label in MONTH_LETTER, upright (as in the reference)."""
    from .colors import _rule
    if s["type"] != "card_history" or not month_letters(s["card"]):
        return
    rule = _rule(style, "label", before=("pane", "table", "worksheet", "refline", "gridline", "zeroline", "table-div"))
    ET.SubElement(rule, "format", attr="text-format", field=b.q(fields[0].name), value=MONTH_LETTER)
    ET.SubElement(rule, "format", attr="text-orientation", field=b.q(fields[0].name), value="0")
    ET.SubElement(_rule(style, "worksheet", before=("refline", "gridline", "zeroline", "table-div")), "format",
                  attr="display-field-labels", scope="cols", value="false")  # no 'Month of Order Date' (reference)


def period_sheet(spec):
    """The cards sheet whose comparison is spelled once under (or in) the header, or None."""
    return next((s for s in spec["sheets"] if cards.is_cards(s) and period_strip(s)), None)


def period_strip(s):
    """period_line true or 'header': its own worksheet; 'card' is a line of each card (decisions/169)."""
    return s.get("period_line") in (True, "header")


def period_in_card(s):
    """period_line 'card': no date above the card's name; the name bold (169)."""
    return s.get("period_line") == "card"


def date_under_name(s):
    """period_line 'card' with card_date: the period's date under each card's name (169); without it, as in the
    mock, the card has no date line: the change line says against what (decisions/177)."""
    return period_in_card(s) and bool(s.get("card_date"))


def separate(s):
    """separate_cards (decisions/178, logistics mock): each measure its own white card with its border, the canvas
    between them; the name, the period line, the number and the change left, the sparkline right of the number."""
    return bool(s.get("separate_cards"))


def accent_deltas(s):
    """delta_colors 'accent' (decisions/178, the mock): a worse change in the accent, a better one and no change in
    dark grey; no green. The last sparkline point: accent when worse, else the text color."""
    return s.get("delta_colors") == "accent"


SEPARATE_FONT = {"kpi_name": 9, "kpi_period": 8, "kpi_delta": 10}  # the mock 13 / 11 / 13px; 9pt: its 13px Source Sans name in one line (178)


# separate_cards: bold="true" alone renders regular in Desktop 2025.1 on these cards (snapshot 178); a Tableau face
# draws the weight: the name bold, the number and the change semibold, as in the mock
SEPARATE_FACE = {"name": "Tableau Bold", "rest": "Tableau Semibold"}


def face(s, attrs, is_name=False):
    """A bold run's attrs with its Tableau face (before fontsize, as Desktop writes it) on separate_cards."""
    if not separate(s) or attrs.get("bold") != "true":
        return attrs
    out = {k: v for k, v in attrs.items() if k != "fontsize"}
    out["fontname"] = SEPARATE_FACE["name" if is_name else "rest"]
    return {**out, **({"fontsize": attrs["fontsize"]} if "fontsize" in attrs else {})}


CARD_KEYS = ("kpi_period", "kpi_name", "kpi_value", "kpi_delta")  # text lines of a KPI card's value sheet


def card_keys(spec, s):
    """The lines of a KPI card's value text: period (in the header row instead: decisions/169), name, value,
    change (on its pill instead: decisions/037). One function for the build and the lint (decisions/182)."""
    keys = [k for k in CARD_KEYS if not (k == "kpi_delta" and pill(s))
            and not (k == "kpi_period" and period_in_header(spec))]
    if period_in_card(s):  # under the name with card_date (decisions/169), else none (decisions/177)
        keys[:2] = ["kpi_name", "kpi_period"] if date_under_name(s) else ["kpi_name"]
    return keys + (["kpi_delta"] if has_progress(s) else [])  # '103% of $15.0K target' (decisions/155)


def separate_min_px(spec, s, font, value_pt):
    """separate_cards: the least px of a card's face (its box less the card's inset) that keeps its text unclipped
    in Desktop (decisions/182): the lines' height less the slack Desktop does not need. The build refuses a card
    under it and the lint's D12 says the same. font: the type scale of the dashboard (theme.font)."""
    font = {**font, **SEPARATE_FONT}
    lines = [(value_pt if k == "kpi_value" else font[k], 1) for k in card_keys(spec, s)]
    return design.header_px(lines, 0, 0) - design.CARD_SEPARATE_SLACK_PX


def card_font(b, s):
    """The card text's sizes: the builder's, the mock's with separate_cards."""
    return {**b.font, **(SEPARATE_FONT if separate(s) else {})}


def goal_text(b, m):
    """'95%' of a measure's goal 0.95 in its format, without the decimals a round goal does not need."""
    f = dict(formats.normalize(m.get("format")) or {"type": "number", "decimals": 0})
    v = m["goal"] * (100 if f.get("type") == "percent" else 1)
    if round(v) == round(v, 6):
        f["decimals"] = 0
    return formats.render(m["goal"], f, strings.locale(b.spec))


def as_of_field(spec):
    return spec["dashboard"].get("data_as_of")


def names(s, m):
    p = f"{s['name']} · {cards.label(m)}"
    return {"diff": f"{p} · Diff", "diff_good": f"{p} · Diff Good", "diff_bad": f"{p} · Diff Bad",
            "sign": f"{p} · Good Sign", "fill": f"{p} · Good Fill"}


def full_name(s):
    """The constant MIN(1) of a cards sheet's pill and marker bars, on their fixed 0..1 axis (decisions/063), and
    of its progress track (decisions/155)."""
    return f"{s['name']} · Full"


def label_calc(p):
    """The sparkline's label (a table calc) of a card history part."""
    return f"{p['name']} · Label"


def base_period(s):
    return f"{s['name']} · Base Period"


def as_of_calc(spec):
    return f"Data as of {as_of_field(spec)}"


def period_name(s):
    return f"{s['name']} · Period Line"


arrow_format = cards.arrow_format  # decisions/169: also the change of a measure with 'delta' abs


# ---- status dot (decisions/062) -------------------------------------------------------------------------------
STATUS_LABELS = ("On track", "At risk", "Off track")  # good, warn, bad
STATUS_TOKENS = ("good", "warn", "bad")
STATUS_GLYPH = "● "  # the legend's swatch: the dot's own shape (SOC: its statuses as circles in the header)
STATUS_SIZE = "1.6"  # the dot's Circle (the size slider; scatter points 1.3)


def status(m):
    return m.get("status")


def has_status(s):
    return cards.is_cards(s) and any(status(m) for m in s["measures"])


def status_name(s, m):
    return f"{s['name']} · {cards.label(m)} · Status"


def status_levels(m):
    """The status tokens a measure can show: good and bad with one threshold, good / warn / bad with two."""
    return ("good", "bad") if len(status(m)["thresholds"]) == 1 else STATUS_TOKENS


def status_label(s, token):
    return s.get("status_labels", STATUS_LABELS)[STATUS_TOKENS.index(token)]


def _num(v):
    return repr(int(v)) if float(v).is_integer() else repr(float(v))


def status_formula(s, m):
    """IF [x] >= hi THEN good ELSEIF [x] >= lo THEN warn ELSEIF [x] < lo THEN bad END on the card's value or change
    (<= / > for good 'down': lower is better); a null value has no status."""
    st, c = status(m), cards.names(s, m)
    x = f"[{c['current' if st['on'] == 'value' else 'delta']}]"
    up = m.get("good", "up") == "up"
    th = [_num(v) for v in st["thresholds"]]
    ladder = list(reversed(th)) if up else th  # the good one first
    op, other = (">=", "<") if up else ("<=", ">")
    branches = [f"{x} {op} {v} THEN \"{status_label(s, k)}\"" for v, k in zip(ladder, status_levels(m))]
    branches.append(f"{x} {other} {ladder[-1]} THEN \"{status_label(s, 'bad')}\"")
    return "IF " + " ELSEIF ".join(branches) + " END"


def dot_offset_px(lines, i=2):
    """How far below the middle of a card text [(pt, 1)] (period, name, value, ...) the middle of its value line
    (lines[i]; 1 without the period line, decisions/169) is: Desktop centers the text in its zone, and the dot's zone
    is cut by twice this at its top to center it on the number."""
    px = [design.line_px(pt) for pt, _ in lines]
    return sum(px[:i]) + px[i] / 2 - sum(px) / 2


def delta_line_px(b, s):
    """Width of a card's change line at its widest: '▼ 100,0 pp to last week' (history_place 'right', 169)."""
    word = cards.base_label(s, b.spec) if not base_value(s) else f"| 100,000 {base_word(s, b.spec)}"
    if cards.date_range(s):  # no base word, a goal after the change (decisions/178)
        word = strings.t(b.spec, "goal").strip() + " 100%"
    return round(design.text_px(f"▼ 100,0 {strings.t(b.spec, 'pp')} {word}", card_font(b, s)["kpi_delta"]))


PERIOD_SAMPLE = {"week": "28 Sep 2025", "month": "Sep 2025", "year": "2025"}  # the widest dates of DATE_FORMAT


def period_header_px(b):
    """Width of the period line in the header row (decisions/169): two bold dates and 'compared to', + slack."""
    s = period_sheet(b.spec)
    date = PERIOD_SAMPLE[cards.level(s)]
    pt = FONT["period_line"]
    return round(2 * design.text_px(date, pt, bold=True) + design.text_px(strings.t(b.spec, "compared_to"), pt)) + 16


def legend_place(s):
    return s.get("status_legend", "block")


def status_items(sheets):
    """[(label, color, glyph)] of the statuses the sheets show, good / warn / bad, each once."""
    out = []
    for token in STATUS_TOKENS:
        for s in sheets:
            item = (status_label(s, token), COLOR[token], STATUS_GLYPH)
            if any(status(m) and token in status_levels(m) for m in s["measures"]) and item not in out:
                out.append(item)
    return out


def block_legend(s):
    """The legend line of a KPI block's header: its statuses (decisions/062), its sparkline points (088); [] without."""
    return (status_items([s]) if has_status(s) and legend_place(s) == "block" else []) + point_legend(s)


def dashboard_legend(b, d):
    """The status legend of a dashboard header: the statuses of its KPI sheets with status_legend 'dashboard'."""
    from .build import _leaves
    names = set(_leaves(d["grid"]))
    return status_items([s for s in b.spec["sheets"] if s["name"] in names and has_status(s)
                   and legend_place(s) == "dashboard"])


def legend_px(items, width_px, pt):
    """Height of a status legend line (wrapped) in a header text, 0 without one."""
    if not items:
        return 0
    text = "".join(g + lab + "    " for lab, _, g in items).rstrip()
    return design.line_px(pt) * design.text_lines(text, pt, width_px)


def _check_status(spec):
    def walk(v, where):  # a measure with a status outside the KPI cards measures
        if isinstance(v, dict):
            if "status" in v and "field" in v:
                raise ValueError(f"{where}: 'status' (a status dot by thresholds) applies to KPI cards measures")
            for x in v.values():
                walk(x, where)
        elif isinstance(v, list):
            for x in v:
                walk(x, where)

    d = spec["dashboard"]
    header = bool(d.get("title") or d.get("subtitle")) and not d.get("sidebar")
    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        if not cards.is_cards(s):
            walk(s, where)
            continue
        walk({k: v for k, v in s.items() if k != "measures"}, where)
        for m in s["measures"]:
            th = (status(m) or {}).get("thresholds", [])
            if any(a >= b for a, b in zip(th, th[1:])):
                raise ValueError(f"{where}: status thresholds {th} of '{cards.label(m)}' are not ascending: a status "
                                 f"between them could never show")
        if not has_status(s):
            extra = [k for k in ("status_labels", "status_legend") if k in s]
            if extra:
                raise ValueError(f"{where}: {extra} describe status dots; give a measure a 'status'")
            continue
        if legend_place(s) == "block" and not ((s.get("title") or s.get("subtitle")) and spec.get("block_headers",
                                                                                                    True)):
            raise ValueError(f"{where}: status_legend 'block' is a line under the block's title: give the sheet a "
                             f"title or subtitle, or set status_legend 'dashboard'")
        if legend_place(s) == "dashboard" and not header:
            raise ValueError(f"{where}: status_legend 'dashboard' is a line of the dashboard header: give the "
                             f"dashboard a title (and no sidebar)")


# ---- progress against a target (decisions/155) ---------------------------------------------------------------
PROGRESS_PX = 8  # the bar's thickness (reference '1. Normal Progress Chart': ~30px rows of a 59px cell; one text line
# under it here, so a band under the card text, not a row of its own)
# the track: the bar's whole thickness in the pale track token (the registry's, 039), or a line under the fill in the
# muted mark color (reference '5. Bar within Bar I': a grey line; at size 0.4 the pale token was a 1px trace in Desktop)
TRACK_SIZE = {"bar": BAR_SIZE, "thin": "0.8"}
TRACK_COLOR = {"bar": "track", "thin": "mark_muted"}
PROGRESS_FORMAT = "pct0"  # '103%' (reference: whole percents at the bar's end)


def target(m):
    return m.get("target")


def has_progress(s):
    return cards.is_cards(s) and any(target(m) for m in s["measures"])


def progress_style(s):
    return s.get("progress", "bar")


def progress_names(s, m):
    p = f"{s['name']} · {cards.label(m)}"
    return {"target": f"{p} · Target", "progress": f"{p} · Progress", "fill": f"{p} · Progress Fill",
            "met": f"{p} · Target Met"}


def met_color(m):
    """The fill's color at or over its target: good, bad for a measure that is good 'down' (a budget overrun)."""
    return "good" if m.get("good", "up") == "up" else "bad"


def _check_progress(spec, prof):
    def walk(v, where):  # a target outside the KPI cards measures
        if isinstance(v, dict):
            if "target" in v and "field" in v:
                raise ValueError(f"{where}: 'target' (a progress bar) applies to KPI cards measures")
            for x in v.values():
                walk(x, where)
        elif isinstance(v, list):
            for x in v:
                walk(x, where)

    for s in spec["sheets"]:
        where = f"Sheet '{s['name']}'"
        if not cards.is_cards(s):
            walk(s, where)
            continue
        walk({k: v for k, v in s.items() if k != "measures"}, where)
        with_target = [cards.label(m) for m in s["measures"] if target(m)]
        if not with_target:
            if "progress" in s:
                raise ValueError(f"{where}: progress draws a bar against a target: give the measures a 'target'")
            continue
        if len(with_target) < len(s["measures"]):
            raise ValueError(f"{where}: only {with_target} have a target: the cards of a row share one progress "
                             f"band, so give every measure a target or the others their own sheet")
        if pill(s):
            raise ValueError(f"{where}: the pill and the progress bar both stand under the card text: drop "
                             f"delta_style 'pill' or the targets")
        for m in s["measures"]:
            t = target(m)
            if "value" in t and t["value"] <= 0:
                raise ValueError(f"{where}: target {t['value']} of '{cards.label(m)}' is not above zero: the share "
                                 f"of it is no progress")
            if "field" in t and prof.col(t["field"]).datatype not in ("integer", "real"):
                raise ValueError(f"{where}: target field '{t['field']}' of '{cards.label(m)}' is not a number")


def progress_calcs(s, m):
    """Target (a constant, or the field over the current period as the card's value), the share of it, the fill
    (the share within 0..1 of the axis) and whether the target is met (the fill's color)."""
    n, c, t = progress_names(s, m), cards.names(s, m), target(m)
    fmt = {"format": m["format"]} if "format" in m else {}
    if "value" in t:
        out = [{"name": n["target"], "formula": f"MIN({_num(t['value'])})", **fmt}]
    else:
        agg = t.get("agg", "sum").upper()
        out = [{"name": n["target"], "formula": f"{agg}(IF [{cards.is_current(s)}] THEN [{t['field']}] END)", **fmt}]
    return out + [{"name": n["progress"], "formula": f"[{c['current']}] / [{n['target']}]", "format": PROGRESS_FORMAT},
                  {"name": n["fill"], "formula": f"MAX(MIN([{n['progress']}], 1), 0)", "format": PROGRESS_FORMAT},
                  {"name": n["met"], "formula": f"[{n['progress']}] >= 1"}]


def progress_runs(b, fields):
    """'103% of $15.0K target' under the change: the share bold in the text color, the target in its format."""
    pct, tgt = (f"<{b.q(f.name)}>" for f in fields)
    size, muted = b.font["kpi_delta"], COLOR["muted"]
    return [(pct, dict(bold="true", fontcolor=COLOR["text"], fontsize=size)), (" of ", dict(fontcolor=muted,
                                                                                            fontsize=size)),
            (tgt, dict(fontcolor=COLOR["text"], fontsize=size)), (" target", dict(fontcolor=muted, fontsize=size))]


def progress_table(b, table_el, style, s, fields):
    """The track and the fill as a dual axis on Columns (reference 'Normal Progress Chart'): the constant first, so
    the fill is drawn over it; its axis fixed 0..1 and hidden, the fill's folded onto it (synchronized); each layer
    a Bar across the zone (marks-scaling-off, the pill's size), the track in its token, the fill by the met flag."""
    full, fill, met = fields
    axis = style.find("style-rule[@element='axis']")
    if axis is None:
        axis = ET.Element("style-rule", element="axis")
        style.insert(0, axis)
    a, f = b.q(full.name), b.q(fill.name)
    for i, el in enumerate([
            ET.Element("encoding", {"attr": "space", "class": "0", "field": a, "field-type": "quantitative",
                                    "max": "1", "min": "0", "range-type": "fixed", "scope": "cols", "type": "space"}),
            ET.Element("encoding", {"attr": "space", "class": "0", "field": f, "field-type": "quantitative",
                                    "fold": "true", "scope": "cols", "synchronized": "true", "type": "space"}),
            ET.Element("format", {"attr": "display", "class": "0", "field": a, "scope": "cols", "value": "false"}),
            ET.Element("format", {"attr": "display", "class": "0", "field": f, "scope": "cols", "value": "false"})]):
        axis.insert(i, el)
    panes = ET.SubElement(table_el, "panes")
    default = ET.SubElement(panes, "pane", {"selection-relaxation-option": "selection-relaxation-allow"})
    ET.SubElement(ET.SubElement(default, "view"), "breakdown", value="auto")
    ET.SubElement(default, "mark", {"class": "Bar"})
    look = progress_style(s["card"])
    layers = [(full, [], [("mark-color", COLOR[TRACK_COLOR[look]]), ("size", TRACK_SIZE[look])]),
              (fill, [("color", met)], [("size", BAR_SIZE)])]
    for i, (ax, encs, fmts) in enumerate(layers, 1):
        pane = ET.SubElement(panes, "pane", {"id": str(i), "selection-relaxation-option": "selection-relaxation-allow",
                                             "x-axis-name": b.q(ax.name)})
        ET.SubElement(ET.SubElement(pane, "view"), "breakdown", value="auto")
        ET.SubElement(pane, "mark", {"class": "Bar"})
        ET.SubElement(pane, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})
        if encs:
            e = ET.SubElement(pane, "encodings")
            for tag, ef in encs:
                ET.SubElement(e, tag, column=b.q(ef.name))
        ET.SubElement(ET.SubElement(pane, "customized-tooltip", {"show-buttons": "false"}), "formatted-text")
        rule = ET.SubElement(ET.SubElement(pane, "style"), "style-rule", element="mark")
        for attr, value in [("mark-labels-show", "false")] + fmts:
            ET.SubElement(rule, "format", attr=attr, value=value)
    ET.SubElement(table_el, "rows")
    ET.SubElement(table_el, "cols").text = f"({a} + {f})"


def under_px(s, inner):
    """Height of the zone under a card's text with its margins: the pill's or the progress bar's, 0 without."""
    if pill(s):
        return design.PILL_PX + 2 * inner
    return PROGRESS_PX + 2 * inner if has_progress(s) else 0


# ---- spec checks --------------------------------------------------------------------------------------------
def _check_v3(spec, s, where):
    """decisions/088: month letters, the points legend."""
    if s.get("history_months") and not (line(s) and cards.level(s) == "month"):
        raise ValueError(f"{where}: history_months 'letter' writes the months of a sparkline as J F M: set history "
                         f"'line' or 'area' and date level 'month'")
    if s.get("history_points_legend"):
        if not s.get("history_points"):
            raise ValueError(f"{where}: history_points_legend names the dots of history_points; set those")
        if len({m.get("good", "up") for m in s["measures"]}) > 1:
            raise ValueError(f"{where}: history_points_legend is one line for the row, but its measures differ in "
                             f"'good' (the max dot is good on one card, bad on another): give the legend-less "
                             f"cards their own sheet")
        if not ((s.get("title") or s.get("subtitle")) and spec.get("block_headers", True)):
            raise ValueError(f"{where}: history_points_legend is a line under the block's title: give the sheet a "
                             f"title or subtitle")


def _check_169(s, where):
    """delta abs, delta_zero neutral, history right (decisions/169): one change per card, as text."""
    for m in s.get("measures", []):
        if cards.is_abs(m) and (cards.is_ratio(m) or abs_delta(s) or pill(s)):
            raise ValueError(f"{where}: measure '{cards.label(m)}' delta 'abs' is its one change as text: not with "
                             f"'per' (percentage points), sheet delta 'abs_pct' or delta_style 'pill'")
        if "delta_format" in m:  # decisions/177
            if not cards.is_abs(m):
                raise ValueError(f"{where}: measure '{cards.label(m)}' delta_format is the format of an absolute "
                                 f"change: give it delta 'abs'")
            formats.normalize(m["delta_format"], f"{where}: delta_format")
    if separate(s) and not (history_right(s) and period_in_card(s) and s.get("arrange", "row") == "row"):
        raise ValueError(f"{where}: separate_cards puts each measure in its own card with the sparkline right of the "
                         f"number: it needs history_place 'right', period_line 'card' and arrange 'row'")
    if s.get("delta_colors") and not cards.neutral_zero(s):
        raise ValueError(f"{where}: delta_colors 'accent' colors a worse change only: it needs delta_zero 'neutral'")
    if cards.date_range(s) and (cards.level(s) != "week" or s.get("compare", "previous") != "previous"):
        raise ValueError(f"{where}: card_date 'range' names a week and the week before: it needs date level 'week' "
                         f"and compare 'previous'")
    for m in s.get("measures", []):
        if "goal" in m and not (isinstance(m["goal"], (int, float)) and history_right(s) and line(s)):
            raise ValueError(f"{where}: measure '{cards.label(m)}' goal is a number drawn as a dashed line on the "
                             f"sparkline: it needs history 'line' and history_place 'right'")
    if s.get("card_date") and not period_in_card(s):
        raise ValueError(f"{where}: card_date puts the date under the card's name: it needs period_line 'card'")
    if cards.neutral_zero(s) and (abs_delta(s) or pill(s)):
        raise ValueError(f"{where}: delta_zero 'neutral' is a grey text change: not with delta 'abs_pct' or "
                         f"delta_style 'pill'")
    if history_right(s) and (marker(s) or pill(s) or has_progress(s) or s.get("history_months")):
        raise ValueError(f"{where}: history_place 'right' stands next to the value: not with a marker, pill, "
                         f"progress or history_months")


def history_right(s):
    return s.get("history_place") == "right"


def period_in_header(spec):
    """period_line 'header': the comparison in the header row; the cards without their date line (decisions/169)."""
    s = period_sheet(spec)
    return bool(s) and s.get("period_line") == "header"


def check(spec, prof):
    d, where_d = spec["dashboard"], f"Dashboard '{spec['dashboard']['name']}'"
    for s in spec["sheets"]:
        if s["type"] != "kpi":
            continue
        where = f"KPI '{s['name']}'"
        if line(s) and s.get("history_color") == "change":
            raise ValueError(f"{where}: history_color 'change' colors bars; a line history has one color")
        if s.get("period_line") and "date" not in s:
            raise ValueError(f"{where}: period_line needs 'date'")
        _check_169(s, where)
        if s.get("history_points") and not line(s):
            raise ValueError(f"{where}: history_points mark periods of a sparkline: set history 'line'")
        if "history_point_labels" in s and not s.get("history_points"):
            raise ValueError(f"{where}: history_point_labels labels the points of history_points; set those")
        _check_v3(spec, s, where)
    _check_status(spec)
    _check_progress(spec, prof)  # decisions/155
    lines = [s["name"] for s in spec["sheets"] if cards.is_cards(s) and period_strip(s)]
    if len(lines) > 1:
        raise ValueError(f"period_line is spelled once under the dashboard header; it is set on {lines}")
    header = bool(d.get("title") or d.get("subtitle")) and not d.get("sidebar")
    if (lines or as_of_field(spec)) and not header:
        raise ValueError(f"{where_d}: period_line and data_as_of stand in and under the dashboard header row; give "
                         f"the dashboard a title (and no sidebar)")
    if as_of_field(spec):
        f = as_of_field(spec)
        if prof.col(f).datatype not in ("date", "datetime"):
            raise ValueError(f"{where_d}: data_as_of '{f}' is not a date column")
        if any(x["name"] == AS_OF_SHEET for x in spec["sheets"]) or d["name"] == AS_OF_SHEET:
            raise ValueError(f"{where_d}: data_as_of adds a sheet named '{AS_OF_SHEET}': rename the sheet or "
                             f"dashboard that has this name")


# ---- generated calcs ----------------------------------------------------------------------------------------
def calcs(spec):
    """Calc specs of the options: the absolute change and its good / bad sides, the sign flags of the marker and
    the pill, the base period of the period line, the date of 'Data as of'."""
    out = []
    for s in spec["sheets"]:
        if not cards.is_cards(s):
            continue
        for m in s["measures"]:
            n, c = names(s, m), cards.names(s, m)
            up = m.get("good", "up") == "up"
            eq = "" if cards.neutral_zero(s) else "="  # zero: the grey '= no change' (decisions/169)
            if abs_delta(s):
                df = cards.delta_format(m)  # decisions/177
                out.append({"name": n["diff"], "formula": f"[{c['current']}] - [{c['previous']}]",
                            **({"format": df} if df else {})})
                out.append({"name": n["diff_good"], "formula": f"IF [{n['diff']}] {'>' if up else '<'}{eq} 0 THEN "
                                                               f"[{n['diff']}] END", "format": arrow_format(m)})
                out.append({"name": n["diff_bad"], "formula": f"IF [{n['diff']}] {'<' if up else '>'} 0 THEN "
                                                              f"[{n['diff']}] END", "format": arrow_format(m)})
            flag = f"[{c['delta']}] {'>=' if up else '<='} 0"
            if marker(s):
                out.append({"name": n["sign"], "formula": flag})
            if pill(s):
                out.append({"name": n["fill"], "formula": flag})
            if status(m):  # decisions/062
                out.append({"name": status_name(s, m), "formula": status_formula(s, m)})
            if target(m):  # decisions/155
                out += progress_calcs(s, m)
        if marker(s) or pill(s) or has_progress(s):  # the bars' length: the whole fixed 0..1 axis (decisions/063)
            out.append({"name": full_name(s), "formula": "MIN(1)"})
        if s.get("period_line"):
            lv = cards.level(s)
            back = "year" if s.get("compare", "previous") == "year" else lv
            out.append({"name": base_period(s), "formula": f"DATEADD('{back}', -1, DATETRUNC('{lv}', "
                                                           f"[{cards.last_date(s)}]))",
                        "format": cards.DATE_FORMAT[lv]})
    if as_of_field(spec):
        out.append({"name": as_of_calc(spec), "formula": f"{{FIXED : MAX([{as_of_field(spec)}])}}",
                    "format": AS_OF_FORMAT})
    return out


def point_test(kind, v, p=None):
    """The table calc condition of a point kind on the measure expression v (of the history part p). With
    delta_colors 'accent' 'last' is the last period when its change against the period before is worse, in the
    card's own rounding (cards.delta_calc), 'last_even' the last period otherwise (decisions/178)."""
    last = "LAST() = 0"
    if kind == "last" and p and accent_deltas(p["card"]):
        d, _ = cards.delta_calc(p["card"], p["measure"], v, f"LOOKUP({v}, -1)")
        last += f" AND {d} {'<' if p['measure'].get('good', 'up') == 'up' else '>'} 0"
    return {"max": f"{v} = WINDOW_MAX({v})", "min": f"{v} = WINDOW_MIN({v})", "last": last,
            "last_even": "LAST() = 0"}[kind]


def table_calcs(b):
    """{caption: Calc} of the sparkline labels: the value at the max and at the last period, null elsewhere. With
    points (decisions/059): the value at each point (the points layer's axis and label) and its kind (its color)."""
    from .formula import calc_id
    from .reflines import TableCalc, _value
    out = {}
    for p in b.worksheets:
        if p["type"] == "card_history" and line(p["card"]):
            m = cards.history_measure(p["card"], p["measure"])  # a ratio: by period (decisions/169)
            v, raw, deps = _value(b, m)
            agg = m.get("agg", "sum")  # the type of the aggregate it shows (cards take CSV columns)
            whole = agg in ("count", "countd") or (agg != "avg" and b.col(m["field"]).datatype == "integer")
            typ, fmt = "integer" if whole else "real", m.get("format", "number")
            kinds = spark_points(p["card"])
            if not kinds:
                name, formula = label_calc(p), f"IF {v} = WINDOW_MAX({v}) OR LAST() = 0 THEN {v} END"
                out[name] = TableCalc(name, formula, None, typ, True, calc_id(name), formula, fmt, sorted(raw), deps)
                continue
            name, formula = point_value(p), f"IF {' OR '.join(point_test(k, v, p) for k in kinds)} THEN {v} END"
            out[name] = TableCalc(name, formula, None, typ, True, calc_id(name), formula, fmt, sorted(raw), deps)
            name = point_kind(p)
            formula = "IF " + " ELSEIF ".join(f'{point_test(k, v, p)} THEN "{POINT_KIND[k]}"' for k in kinds) + " END"
            out[name] = TableCalc(name, formula, None, "string", True, calc_id(name), formula, None, sorted(raw), deps)
    return out


# ---- worksheets ---------------------------------------------------------------------------------------------
def parts(s, m, lab):
    """Physical worksheets of one card measure, in zone order: [marker], [status], value, [pill | progress],
    history."""
    base = f"{s['name']} · {lab}"
    out = []
    if marker(s):
        out.append({"name": f"{base} · Marker", "type": MARKER, "card": s, "measure": m})
    if status(m):
        out.append({"name": f"{base} · Status", "type": STATUS, "card": s, "measure": m})
    out.append({"name": base, "type": "card_value", "card": s, "measure": m})
    if pill(s):
        out.append({"name": f"{base} · Delta", "type": PILL, "card": s, "measure": m})
    if target(m):  # decisions/155
        out.append({"name": f"{base} · Progress", "type": PROGRESS, "card": s, "measure": m})
    out.append({"name": f"{base} · History", "type": "card_history", "card": s, "measure": m})
    return out


def sheets(b):
    """Worksheets of the dashboard header (not in spec.sheets): the period line and 'Data as of'."""
    out = []
    s = period_sheet(b.spec)
    if s:
        out.append({"name": period_name(s), "type": PERIOD, "card": s})
    if as_of_field(b.spec):
        out.append({"name": AS_OF_SHEET, "type": AS_OF})
    return out


def shape(b, s):
    """sheet_shape of a part of this module: fields, rows, cols, encodings, labels, measure_names."""
    from .build import Field
    t = s["type"]
    if t == PROGRESS:  # the track and the fill, colored by the met flag (decisions/155)
        n = progress_names(s["card"], s["measure"])
        fs = [Field(b.col(full_name(s["card"])), "agg", "user"), Field(b.col(n["fill"]), "agg", "user"),
              Field(b.col(n["met"]), "agg", "user", discrete=True)]
        return fs, None, None, [], False, None
    if t == STATUS:  # the status on Color, nothing else (the marker's sheet)
        f = Field(b.col(status_name(s["card"], s["measure"])), "agg", "user", discrete=True)
        return [f], None, None, [("color", b.q(f.name))], False, None
    if t in (PILL, MARKER):
        n, c = names(s["card"], s["measure"]), cards.names(s["card"], s["measure"])
        flag = Field(b.col(n["fill" if t == PILL else "sign"]), "agg", "user", discrete=True)
        fields, enc = [flag], [("color", b.q(flag.name))]
        if t == PILL:
            keys = ((["diff_good", "diff_bad"] if abs_delta(s["card"]) else []) + ["good", "bad"]
                    + (["previous"] if base_value(s["card"]) else []))  # the base as a number (decisions/088)
            for k in keys:
                f = Field(b.col(n[k] if k.startswith("diff") else c[k]), "agg", "user")
                fields.append(f)
                enc.append(("text", b.q(f.name)))
        full = Field(b.col(full_name(s["card"])), "agg", "user")  # a bar over the whole axis (decisions/063)
        fields.append(full)
        rows, cols = (None, full.name) if BAR_SHELF[t] == "cols" else (full.name, None)
        return fields, rows, cols, enc, t == PILL, None
    if t == PERIOD:
        fs = [Field(b.col(cards.period(s["card"])), "agg", "min"), Field(b.col(base_period(s["card"])), "agg", "min")]
        return fs, None, None, [("text", b.q(f.name)) for f in fs], True, None
    f = Field(b.col(as_of_calc(b.spec)), "agg", "min")
    return [f], None, None, [("text", b.q(f.name))], True, None


def history_shape(b, s, d, m):
    """card_history as a sparkline: the date and the measure, its label computed along the date."""
    from .build import Field
    if has_points(s):  # the points layer: its value on the second axis, its kind on Color (decisions/059)
        pv = Field(b.col(point_value(s)), "agg", "user")
        kind = Field(b.col(point_kind(s)), "agg", "user", discrete=True)
        pv.along = kind.along = d
        labels = [("text", b.q(pv.name))] if point_labels(s["card"]) else []
        return [d, m, pv, kind], [("color", b.q(kind.name))] + labels
    lab = Field(b.col(label_calc(s)), "agg", "user")
    lab.along = d  # WINDOW_MAX / LAST over the periods
    return [d, m, lab], [("text", b.q(lab.name))]


def point_layers(b, s, fields):
    """The two layers of a sparkline with points (dualaxis._layers): the line in the muted color without labels, the
    points as dots colored by their kind, labelled with their value; the tooltip of both: period and value."""
    from .ink import _label
    d, m, pv, kind = fields
    tip = [(f"{_label(d)}:\t", {"fontcolor": COLOR["muted"]}), (f"<{b.q(d.name)}>", {"bold": "true"}), ("Æ\n", {}),
           (f"{_label(m)}:\t", {"fontcolor": COLOR["muted"]}), (f"<{b.q(m.name)}>", {"bold": "true"})]
    labels = point_labels(s["card"])
    line_fmts = area_formats(s["card"], COLOR["muted"]) or [("mark-color", COLOR["muted"])]  # area: decisions/088
    return [(m, "Area" if area(s["card"]) else "Line", [], [("mark-labels-show", "false")] + line_fmts, None, tip),
            (pv, "Circle", [("color", kind)] + ([("text", pv)] if labels else []),
             [("size", POINT_SIZE), ("mark-labels-show", "true" if labels else "false")], None, tip)]


def points_style(style, s):
    """No 'N nulls' indicator on a sparkline with points: the points layer is null outside its periods (ER)."""
    from .colors import _rule
    if has_points(s):
        ET.SubElement(_rule(style, "table", before=("worksheet", "refline", "gridline", "zeroline", "table-div")),
                      "format", attr="show-null-value-warning", value="false")


def card_runs(b, s, fields):
    """The change runs of a card text (value sheet or pill): [(text, attrs)] -> abs | pct base, or pct base."""
    font = card_font(b, s["card"])
    on_fill = pill(s["card"])  # bold, in the darker good / bad: the pill's fill is pale
    good = COLOR["good_text"] if on_fill else None
    bad = COLOR["bad_text"] if on_fill else None
    good, bad = good or theme.word_color(b, "good"), bad or theme.word_color(b, "bad")
    style = dict(bold="true") if on_fill else {}
    flat = dict(fontcolor=COLOR["muted"])
    if accent_deltas(s["card"]):  # worse in the accent, the rest dark grey, all bold (decisions/178)
        good, bad, style = COLOR["subtitle"], COLOR["accent"], dict(bold="true")
        flat = dict(bold="true", fontcolor=COLOR["subtitle"])
    size = font["kpi_pill"] if on_fill else font["kpi_delta"]  # the pill's text: 8 bold in the theme (089)
    refs = [f"<{b.q(f.name)}>" for f in fields]
    out = []
    if abs_delta(s["card"]):
        dg, db, refs = refs[0], refs[1], refs[2:]
        out += [(dg, dict(**style, fontcolor=good, fontsize=size)),
                (db, dict(**style, fontcolor=bad, fontsize=size)),
                (" | ", dict(fontcolor=COLOR["muted"], fontsize=size))]
    base = dict(**({} if accent_deltas(s["card"]) else style),
                fontcolor=COLOR["muted"] if not on_fill else COLOR["text"], fontsize=size)
    out += [(refs[0], dict(**style, fontcolor=good, fontsize=size)),
            (refs[1], dict(**style, fontcolor=bad, fontsize=size))]
    if cards.neutral_zero(s["card"]):  # '= no change' in grey (decisions/169)
        out.append((refs[2], dict(**flat, fontsize=size)))
        refs = refs[1:]
    if base_value(s["card"]):  # '▲ 10.5% | $14.0K Last Month': the base as a number (decisions/088, reference P1)
        return out + [(" | ", dict(fontcolor=COLOR["muted"], fontsize=size)), (refs[2], base),
                      (f" {base_word(s['card'], b.spec)}", base)]
    if cards.goal(s["measure"]) is not None:  # '· goal 95%' muted regular (decisions/178)
        out.append((strings.t(b.spec, "goal") + goal_text(b, s["measure"]), base))
    if cards.date_range(s["card"]):  # the period line says against what: 'vs wk 11' (decisions/178)
        return out
    return out + [(f" {cards.base_label(s['card'], b.spec)}", base)]


def label(b, pane, s, fields):
    """customized-label of a pill, the period line and 'Data as of'."""
    ft = ET.SubElement(ET.SubElement(pane, "customized-label"), "formatted-text")

    def run(text, **attrs):
        ET.SubElement(ft, "run", {k: str(v) for k, v in attrs.items()}).text = text

    t = s["type"]
    if t == PILL:
        for text, attrs in card_runs(b, s, fields[1:]):
            run(text, **attrs)
    elif t == PERIOD:
        per, base = (f"<{b.q(f.name)}>" for f in fields)
        fg = COLOR["text"]
        run(per, bold="true", fontcolor=fg, fontsize=FONT["period_line"])
        run(strings.t(b.spec, "compared_to"), fontcolor=COLOR["muted"], fontsize=FONT["period_line"])
        run(base, bold="true", fontcolor=fg, fontsize=FONT["period_line"])
    elif t == AS_OF:
        run(strings.t(b.spec, "data_as_of"), fontcolor=COLOR["muted"], fontsize=FONT["dash_subtitle"])
        run(f"<{b.q(fields[0].name)}>", fontcolor=COLOR["text"], fontsize=FONT["dash_subtitle"])


def status_mark(pane, s):
    """After the <mark> of a status dot (decisions/047) and of a pill / marker bar (decisions/063): no scaling."""
    if s["type"] in (STATUS, PILL, MARKER):
        ET.SubElement(pane, "mark-sizing", {"mark-sizing-setting": "marks-scaling-off"})


def status_style(pane, s):
    """The mark size, the last of its pane's style: the status dot (the scatter points' style), the pill and marker
    bars across their whole zone (decisions/063; the pill's mark rule holds its label formats already)."""
    if s["type"] not in (STATUS, PILL, MARKER):
        return
    st = pane.find("style")
    st = ET.SubElement(pane, "style") if st is None else st
    rule = st.find("style-rule[@element='mark']")
    rule = ET.SubElement(st, "style-rule", element="mark") if rule is None else rule
    ET.SubElement(rule, "format", attr="size", value=STATUS_SIZE if s["type"] == STATUS else BAR_SIZE)


def pane_style(pane_style_el, s):
    """'Data as of' reads from the right edge of the header (cell text-align, Regional Overview); the pill's text
    stands in the middle of its bar (the label alignment, cell style-rule of Regional Overview 'Sales KPI')."""
    if s["type"] == AS_OF or (s["type"] == PERIOD and s["card"].get("period_line") == "header"):
        ET.SubElement(ET.SubElement(pane_style_el, "style-rule", element="cell"), "format", attr="text-align",
                      value="right")
    if s["type"] == PILL:
        rule = ET.SubElement(pane_style_el, "style-rule", element="cell")
        ET.SubElement(rule, "format", attr="text-align", value="center")
        ET.SubElement(rule, "format", attr="vertical-align", value="center")


def axis_style(b, style, s, fields):
    """The pill / marker bar's axis: fixed 0..1, so MIN(1) runs its whole length, and hidden (European Superstore
    'Sales KPI YTD': AVG(1) on a fixed 0..1 axis, display false)."""
    if s["type"] not in (PILL, MARKER):
        return
    axis = style.find("style-rule[@element='axis']")
    if axis is None:
        axis = ET.Element("style-rule", element="axis")
        style.insert(0, axis)
    ref, scope = b.q(fields[-1].name), BAR_SHELF[s["type"]]
    axis.insert(0, ET.Element("encoding", {"attr": "space", "class": "0", "field": ref, "field-type": "quantitative",
                                           "max": "1", "min": "0", "range-type": "fixed", "scope": scope,
                                           "type": "space"}))
    axis.insert(1, ET.Element("format", {"attr": "display", "class": "0", "field": ref, "scope": scope,
                                         "value": "false"}))


def palettes(b):
    """Palette maps of the sign flags: the marker in good / bad, the pill in their pale fills."""
    out = {}
    for p in b.worksheets:
        if p["type"] in (PILL, MARKER):
            col = b.calc_cols[names(p["card"], p["measure"])["fill" if p["type"] == PILL else "sign"]].name
            colors_ = (("good_fill", "bad_fill") if p["type"] == PILL else ("good", "bad"))
            out[f"[usr:{col}:nk]"] = (col, "User", [("true", COLOR[colors_[0]]), ("false", COLOR[colors_[1]])])
        if p["type"] == PROGRESS:  # the fill in the accent, at its target good (bad for good 'down') (155)
            col = b.calc_cols[progress_names(p["card"], p["measure"])["met"]].name
            out[f"[usr:{col}:nk]"] = (col, "User", [("true", COLOR[met_color(p["measure"])]),
                                                    ("false", COLOR["accent"])])
        if p["type"] == STATUS:  # each status the measure can show, in its token (decisions/062)
            c, m = p["card"], p["measure"]
            col = b.calc_cols[status_name(c, m)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [(f'"{status_label(c, k)}"', COLOR[k]) for k in status_levels(m)])
        if has_points(p):  # the sparkline's points by kind (decisions/059); Desktop adds the null kind of the other
            # periods on save (in Tableau orange): muted, as ER's #d3d3d3 (no mark is drawn there, its value is null)
            col = b.calc_cols[point_kind(p)].name
            out[f"[usr:{col}:nk]"] = (col, "User", [(f'"{POINT_KIND[k]}"', COLOR[point_color(k, p["measure"])])
                                                    for k in spark_points(p["card"])]
                                      + [("%null%", COLOR["mark_muted"])])
    return out


def _date(b, p):
    return history_date(b, p["card"])


def along_fields(b, taken=()):
    """The dates the point kinds are computed along: Desktop declares them in the datasource next to the palette
    maps, as for the flags of decisions/028 (names in taken are declared already)."""
    out = {}
    for p in b.worksheets:
        if has_points(p):
            d = _date(b, p)
            if d.name not in taken:
                out.setdefault(d.name, d)
    return [out[k] for k in sorted(out)]


def instance_table_calc(b, ci):
    """A point kind's column-instance in the datasource (its palette map refers to it) carries its compute-using
    along the date, as on the sheet; without it Desktop drops the map (decisions/028)."""
    for p in b.worksheets:
        if has_points(p) and ci.get("column") == f"[{b.calc_cols[point_kind(p)].name}]":
            ET.SubElement(ci, "table-calc", {"ordering-field": b.q(_date(b, p).name), "ordering-type": "Field"})
            return


# ---- layout -------------------------------------------------------------------------------------------------
def pill_px(b, s):
    """Width of a card's pill: its longest text at the delta size (PILL_CHAR_EM, bold) plus the padding."""
    got = b.expected.get(s["name"], {})
    n = 0
    for m in s["measures"]:
        e = got.get(cards.label(m), {})
        change = (f"{formats.render(e.get('delta'), {'type': 'number', 'decimals': 1})} "
                  f"{strings.t(b.spec, 'pp')}" if cards.in_points(m)
                  else formats.render(e.get("delta"), "pct1"))  # a ratio's change: percentage points (decisions/110)
        text = f"▲ {change} {cards.base_label(s, b.spec)}"
        if base_value(s):  # decisions/088
            text = (f"▲ {change} | "
                    f"{formats.render(e.get('previous'), m.get('format', 'number'))} {base_word(s, b.spec)}")
        if abs_delta(s):
            text = f"▲ {formats.render(e.get('diff'), m.get('format', 'number'))} | " + text[2:]
        n = max(n, len(text))
    return math.ceil(n * b.font["kpi_pill"] * 4 / 3 * PILL_CHAR_EM) + 2 * design.PILL_PAD_PX


def text_sheet_px(pt):
    """Height of a one-line text worksheet: its line and the pane's padding (decisions/013: +24px)."""
    return design.line_px(pt) + design.CARD_TEXT_PAD_PX


def period_zone(b, root, box, size):
    """The period line under the dashboard header, on the canvas (its margins = the header's). Returns its
    height in zone units, 0 without one."""
    from . import spacing
    from .build import _sub
    s = period_sheet(b.spec)
    if not s or period_in_header(b.spec):  # in the header row (decisions/169)
        return 0
    x, y, w = box
    edge = b._edge(canvas=True)
    h = b._units(text_sheet_px(FONT["period_line"]) + 2 * edge, size[1])
    z = _sub(root, "zone", h=str(h), id=b._zid(), name=period_name(s), show_title="false", w=str(w), x=str(x),
             y=str(y))
    b._zone_style(z, spacing.margins((x, y, w, h), (x, y, w, h), b.block_headers, edge=edge))
    return h


def dashboard_sheets(b):
    return [p["name"] for p in sheets(b)]


# ---- expected numbers ---------------------------------------------------------------------------------------
def points_record(p):
    """expected.py key of a sparkline's points: {max, min, last}."""
    return f"{p['name']} · Points"


def points(marks):
    """{max, min, last} of a history's values by period (marks in date order)."""
    vals = [v for v in marks.values() if v is not None]
    if not vals:
        return {"max": None, "min": None, "last": None}
    return {"max": max(vals), "min": min(vals), "last": vals[-1]}


def marks_record(p):
    """expected.py key of the periods a sparkline marks with points (decisions/059)."""
    return f"{p['name']} · Point Marks"


def _round(x, d):
    """Tableau's ROUND: half away from zero."""
    q = 10 ** d
    return (1 if x >= 0 else -1) * int(abs(x) * q + 0.5) / q


def last_worse(card, m, vals):
    """The last value's change against the one before is worse, rounded as the card shows it (point_test)."""
    if len(vals) < 2:
        return False
    cur, prev = vals[-1], vals[-2]
    if cards.in_points(m):
        d = _round((cur - prev) * 100, 1)
    elif cards.is_abs(m):
        d = _round(cur - prev, (formats.normalize(cards.delta_format(m)) or {}).get("decimals", 0))
    elif prev == 0:
        return False
    else:
        d = _round((cur - prev) / abs(prev), 3)
    return d < 0 if m.get("good", "up") == "up" else d > 0


def point_marks(card, marks, m=None):
    """{period: {point: 'Max' | 'Min' | 'Last', value}} of the periods with a point (marks in date order), each with
    the first of the card's kinds it is, as the kind calc: ties at the max or min mark every tied period."""
    vals = [v for v in marks.values() if v is not None]
    if not vals:
        return {}
    last = next(k for k in reversed(list(marks)) if marks[k] is not None)
    worse = last_worse(card, m, vals) if m is not None and accent_deltas(card) else True  # decisions/178
    hit = {"max": lambda k, v: v == max(vals), "min": lambda k, v: v == min(vals),
           "last": lambda k, v: k == last and worse, "last_even": lambda k, v: k == last}
    out = {}
    for k, v in marks.items():
        kind = next((x for x in spark_points(card) if v is not None and hit[x](k, v)), None)
        if kind:
            out[k] = {"point": POINT_KIND[kind], "value": v}
    return out


def as_of_record(spec):
    return f"{spec['dashboard']['name']} · Data as of"
