"""Design tokens: one type scale, spacing and color set for everything the generator draws.

Values are measured in the reference business dashboards (reference dashboards,
the design rules); the type scale is a reference's Dashboard Template: 24 / 14 / 10 / 9.
"""
import contextlib
import math

FONT = {  # pt
    "dash_title": 24,
    "dash_subtitle": 10,
    "block_title": 14,
    "block_subtitle": 9,
    "kpi_value": 24,
    "kpi_period": 9,  # KPI card: period line
    "kpi_name": 12,  # KPI card: measure name, bold
    "kpi_delta": 10,  # KPI card: change against the base period
    "kpi_pill": 10,  # KPI card: the change in its pill, bold (the theme: 8, decisions/089)
    "tile_caption": 10,
    "table_header": 9,  # registry column titles, bold
    "ref_label": 8,  # reference line label 'Average 76' (SOC, Loan Retention, E-Commerce: 8)
    "logo": 20,  # brand sidebar: monogram logo, bold (Call Center "C calls.")
    "topbar_title": 12,  # app top bar: application name, bold
    "shell_label": 10,  # brand sidebar "Download" label, top bar "Welcome, <name>"
    "footer": 9,  # brand sidebar footer: "Created by ...", "Data source: ..."
    "button": 9,  # export button caption, bold
    "nav": 10,  # navigation tab / sidebar button caption (Citizen tabs: 10)
    "toggle": 10,  # a buttons sheet's value (SuperMart period buttons L6M ... All: 10, bold)
    "period_line": 12,  # "Dec 2025 compared to Nov 2025" under the dashboard header (RETAIL-POS: 12 bold)
    "cell_second": 8,  # registry two-line cell: the second line, muted (Data Quality Testing, Wealth & Banking)
    "insight": 10,  # insight line under a block header, its calcs bold (decisions/045; a case's .insight 12px)
    "tile_note": 9,  # note under a KPI tile's number: '44% of total' (decisions/045; a case's .kpi .n 12px)
    "bar_header": 10,  # a horizontal bar's row headers, in the text color (reference Bar Chart Menu: 10pt #333333, 087)
}
COLOR = {
    "muted": "#898989",  # subtitles, hints (label color in 151 reference sheets)
    "good": "#3ea8a6",  # change in the good direction (as in the reference)
    "bad": "#ff5c60",  # change in the bad direction (as in the reference)
    # between good and bad (decisions/062): a KPI status at risk. Amber, the hue between the two, as light as bad so
    # the three status dots weigh the same (SOC Critical / Warning / Healthy, a traffic light). A mark and legend
    # swatch only: as text it fails C9
    "warn": "#f2a93b",
    "mark_muted": "#d4d4d4",  # history marks (mark-color in 133 reference sheets)
    "sidebar_bg": "#f5f5f5",  # sidebar panel (dashboard background in 31 of 79 reference dashboards)
    "cell_bar": "#e6e6e6",  # registry bar-in-cell (references)
    "cell_text": "#ffffff",  # registry text cell background
    "cell_bad": "#ffb3b3",  # registry cell flagged by a highlight (reference tables)
    "rule": "#e6e6e6",  # thin rule between registry row groups (as in the reference)
    "accent": "#4e79a7",  # the current period among muted history (Tableau 10 blue, as plain bars)
    "shell_light": "#ffffff",  # text on a dark brand sidebar / top bar
    "shell_dark": "#333333",  # text on a light brand color (SOC title color)
    "button_bg": "#ffffff",  # export button face on the brand color; its caption is in the brand color
    # card theme (decisions/030, reference books: 12 of 12 reference workbooks)
    "canvas": "#f5f5f5",  # dashboard background under the cards
    "card_bg": "#ffffff",  # card face (11 of 12)
    "card_border": "#e6e6e6",  # card border, 1px (#dee1e6 / #e6e6e6 / #e9ecef in 9 of 12)
    "text": "#333333",  # titles and numbers (no pure black in the references)
    "subtitle": "#666666",  # dashboard subtitle (#555555..#78798c in the references)
    "history": "#e6e6e6",  # KPI card history in the theme; mark_muted keeps the plan (decisions/016)
    "good_text": "#2f8f8d",  # good / bad as text on white: the mark colors darkened to the contrast floor (C9)
    "bad_text": "#e0484c",
    # KPI pill (decisions/037): good / bad at 20 % on white, the references' 12-25 % opacity as solid colors
    "good_fill": "#d8eeed",
    "bad_fill": "#ffdedf",
    "track": "#edeff4",  # registry track column: the 100 % behind the share bar (Help Desk #edeff4 / #f3f5fa)
    "dot_low": "#f1f1f1",  # registry dot column: the light end of its scale (ER Referrals)
    # continuous color scale (decisions/041): the light end of a sequential scale (ER heatmap, Citizen, Customer
    # Support: #f1f1f1 in 14 of 16 custom sequential palettes) and the neutral middle of a diverging one (#d9d9d9 in
    # 61 of 62 custom diverging palettes of the 27 reference books)
    "scale_low": "#f1f1f1",
    "scale_mid": "#d9d9d9",
    # reference band (decisions/043): a pale fill between two values (SOC fills above its lines #f8fae5 / #e9f3f2:
    # tints this light), here the track's grey-blue so it reads as background, not as a mark
    "band": "#edeff4",
}


def given_accent(spec):
    """dashboard.accent (decisions/137): the book's own accent, None for the house one. One value for all
    dashboards (nav.SHELL_KEYS)."""
    if not spec:
        return None
    d = spec["dashboards"][0] if "dashboards" in spec else spec.get("dashboard", {})
    return d.get("accent", "").lower() or None


@contextlib.contextmanager
def book_accent(spec):
    """The tokens of the spec's profile (decisions/193) and on them COLOR["accent"], the book's accent, while a build, a
    gate or a lint of the spec runs (decisions/137): every module reads the tokens at build time, so highlight, scales,
    KPI, nav, reflines and maps all follow them."""
    from . import user_profile  # it validates a profile against the tokens here
    with apply(user_profile.active(spec)):
        before = COLOR["accent"]
        COLOR["accent"] = given_accent(spec) or before
        try:
            yield
        finally:
            COLOR["accent"] = before


@contextlib.contextmanager
def apply(profile):
    """A loaded profile (user_profile.load) over the tokens while the block runs (decisions/193). Only what it sets is
    touched and put back. A font size holds in both type scales: a profile names one size for a block title."""
    tokens = profile.get("tokens", {})
    changes = [(COLOR, k, v) for k, v in tokens.get("color", {}).items()]
    changes += [(SPACE, k, v) for k, v in tokens.get("space", {}).items()]
    for k, v in tokens.get("font", {}).items():
        changes += [(BOOK, "theme_font", v)] if k == "family" else [(FONT, k, v)] + [(FONT_CARDS, k, v)] * (k in FONT_CARDS)
    if "theme" in profile:
        changes.append((BOOK, "theme", profile["theme"]))
    saved = [(d, k, d[k]) for d, k, _ in changes]
    for d, k, v in changes:
        d[k] = v
    try:
        yield
    finally:
        for d, k, v in saved:
            d[k] = v


# What a spec's dashboard may leave out and a profile may set (decisions/193)
BOOK = {"theme": "cards", "theme_font": None}
ZONE = object()  # a margin argument's default: zone_margin when the call runs (None already means no margin)
TEXT_FLOOR = "#898989"  # C9: text on white is never lighter than this (book 8 with #9c9c9c reads badly)
CARD_BORDER_PX = 1
SPACE = {  # px
    "zone_margin": 4,  # between the parts of one block (1120 of 1789 margins in the references)
    "outer_margin": 8,  # dashboard edge
    "panel_padding": 12,  # inside the sidebar (references: padding 8-12)
    "block_margin": 12,  # outer sides of a block: blocks 2 x 12 = 24px apart, 8 + 12 = 20px from the dashboard
    # edge (reference Reports Usage: margin-top 24 between two blocks on one card, dashboard padding 20)
    "header_gap": 12,  # under a block header; the zone below it has margin-top 0 (reference: margin-bottom 12)
    # card theme (decisions/030, 070, 187): outer = a card's margin, cards 2 x 6 = 12px apart and 6 + 6 = 12px from
    # the dashboard edge, one number (user: 20 reads too loose, over the references' median 20); inner = its
    # padding, by the card's weight and at least half the gap (card_margin)
    "card_margin": 6,
    "card_padding": 16,  # a chart / table card
    "card_padding_kpi": 12,  # a KPI card
    "theme_edge": 6,  # root zone margin in the theme: edge = gap, keep equal to card_margin (187)
    "rule_margin": 8,  # each side of a 1px divider (RETAIL-POS: margin 8)
}
# Card theme type scale (style-references-3.md): the keys of FONT it changes
FONT_CARDS = {"dash_title": 18, "dash_subtitle": 11, "block_title": 12, "kpi_name": 11, "tile_caption": 11,
              "table_header": 8, "kpi_pill": 8}  # decisions/089: title 18, column titles and pill 8
# decisions/089: a chart's own text (axes, mark labels, headers) in the theme: the worksheet's style-rule
# (reference: worksheet font-size 8, color #898989 in 74 sheets)
SHEET_TEXT_PT = 8
KPI_VALUE_WIDE, KPI_VALUE_DENSE = 24, 18  # theme KPI number: up to KPI_WIDE_MAX side by side, else (and stacked)
KPI_WIDE_MAX = 3  # refs4 T5: 3 side by side 24, 4 already 18 (decisions/089)
CARD_VALUE_W_CARDS_PX = 150  # stacked KPI card's value text in the theme (references: 145-150)
TABLE_HEADER_CARDS_PX = 28  # registry column titles in the theme (references: 28-32)
TABLE_ROW_CARDS_PX = 30  # table and registry row height in the theme (references: 30-34)
MARKER_PX = 4  # KPI card sign bar left of the text (Wealth & Banking: 4px; Regional Overview: the bar itself)
PILL_PX = 24  # KPI pill's fill height: one 10pt bold line (Superstore Performance: a ~40px sheet with its margins)
PILL_PAD_PX = 8  # each side of the pill's text inside its fill
STATUS_PX = 16  # KPI status dot (decisions/062): its zone left of the card text, inside its margins (SOC: a ~12px
# dot by the number; at size 1.6 Desktop draws ~13px)
DATA_AS_OF_PX = 200  # "Data as of 31 Dec 2025" at the right of the dashboard header (Regional Overview: fixed 200)
REGISTRY_ROW_TWO_LINE_PX = 44  # registry rows with a two-line cell (references: 41-54)
TICK_STROKE_PX = 2  # registry tick column: the base (previous period, plan) across the bar
REF_STROKE_PX = 1  # reference line, dashed (ER, SOC, E-Commerce)
SCALE_SEQ_COLORS = 11  # custom sequential palette: 11 colors, as Desktop writes it (16 of 16 in the references)
SCALE_DIV_SIDE = 6  # custom diverging palette: 6 + the middle + 6 = 13 colors (27 of 62 in the references; the
# rest 11 + 1 + 11)
MARGIN_BAR_PX = 80  # marginal total bars beside a heatmap: the bar length (ER Operation: 83px panes)
HEATMAP_HEADER_PX = 24  # a heatmap's column header row when the marginal bars at its right align to its rows
# (BonusProject heatmap: 32; one 9pt line is 21)
HEATMAP_CELL_MIN_PX = 16  # the smallest heatmap cell side that still holds a 9pt number
PLAN_FACT_SIZE = 0.5  # plan behind the fact: the fact bar's width relative to the plan bar (Size by Measure Names)
AXIS_LABEL_W_PX = 36  # a vertical axis without its title: 5-character ticks ('100K') at the 9pt axis font; Desktop
# sized it for '5K' and clipped '10K' to '1..' (references: 36 and 48px)
AXIS_LABEL_CHARS = 5  # ticks that AXIS_LABEL_W_PX fits; a longer tick ('100,0%') widens the axis in proportion
ROW_HEADER_PAD_PX = 16  # a row header column: its longest text at 9pt plus this (registry, as in the reference)
SORT_ICON_CHARS = 2  # the sort indicator after a sorted field's label takes about two characters
SIDE_PANEL_PX = 160  # legends and filter cards
SIDEBAR_PX = 240  # left sidebar: title, filters, legends (reference: 240px)
LEGEND_LINE_PX = 23  # one legend / filter-card line
HEADER_FILTER_PX = 142  # filter dropdown card in the dashboard header row (reference: fixed 142px)
HEADER_FILTER_H_PX = 60  # its height: field name + dropdown (reference: 60px)
LINE_HEIGHT = 1.7  # text line = font px * this; Desktop 2025.1 clips a title + subtitle at 1.5 (default font)
CHAR_EM = 0.6  # conservative average glyph width: overestimates, so wrapped text is never clipped
MAX_TEXT_LINES = 3  # a header text that wraps more is too long for its block
TILE_TEXT_PAD_PX = 8  # pane padding around a KPI tile's caption and value: 90px inside its margins hold them
# (a golden), 76px got a scrollbar in Desktop (3.7)
CARD_HISTORY_MIN_PX = 40  # a KPI card's history strip below its value text
CARD_TEXT_PAD_PX = 24  # worksheet text sits inside pane padding: 130px clipped the 4 card lines
CARD_VALUE_W_PX = 200  # stacked KPI cards: value text left of the history (reference: 145px); fits a 24pt value of
# ~9 characters; 170px clipped the text in Desktop
CARD_HISTORY_MIN_W_PX = 60
CARD_SPARK_RIGHT_PX = (104, 40)  # history_place 'right': the sparkline right of the value (logistics mock 104x40, 169)
CARD_SPARK_GAP_PX = 8  # separate_cards: at least this between the number and its sparkline (178)
CARD_SEPARATE_SLACK_PX = 0  # separate_cards: px of the text lines' estimate Desktop does not need; measured: face 113 draws, 106 draws "####" (182)
CARD_SEPARATE_MARGIN_PX = 50  # separate_cards: a cell less its card's inset = the face (lint D12; 182; 58 less the 8 px of card_margin 6, 187)
KPI_VALUE_SEPARATE = 22  # separate_cards: the mock's number (29px, Source Sans) next to a 104px sparkline (178)
REGISTRY_HEADER_PX = 20  # strip of column titles above a registry (reference: 20px)
# Registry columns (decisions/064, Desktop 2025.1 labs): Desktop draws the panes of a registry equally wide whatever
# their minwidth/maxwidth say, and a pane narrower than REGISTRY_PANE_MIN_PX is widened to it: the sheet scrolls
# sideways and the numbers are cut at its edge without '..' (text 99px held, 98 scrolled; bar 100 / 98). A vertical
# scrollbar takes SCROLLBAR_PX more. A label longer than its pane is cut at the pane's edge, also without '..'.
REGISTRY_PANE_MIN_PX = 100
SCROLLBAR_PX = 17
REGISTRY_MIN_ROWS = 3  # a registry shows at least this many rows (all when fewer) without scrolling (decisions/066)
REGISTRY_ROW_PX = 20  # a registry row at the 9pt default font (19.5px measured); the theme's is TABLE_ROW_CARDS_PX
# a two-dimension registry's rows, set: Desktop 2025.1 draws no label on a mark alone in its outer group at its
# automatic height nor at 20-21px, and draws every one from 22px (a two-dimension registry, decisions/075)
REGISTRY_ROW_NESTED_PX = 22
REGISTRY_DIM_PX = (60, 240)  # row header width bounds; inside: longest value at 9pt + ROW_HEADER_PAD_PX
# Text that must fit (decisions/064): text_px() + these. Labels start ~2px into their pane; a header or a column
# title Desktop shortens to 'Cent..' when narrower (labs: row header 'Central' held at 60px, '..' at 55)
LABEL_PAD_PX = 4
HEADER_TEXT_PAD_PX = 10
TITLE_PAD_PX = 2
# Field labels over row headers and axis titles (decisions/066): Desktop draws them bold-like ('Sub-Cate..' 77px of
# ink, 'Month of Order Date' 143: wider than the regular metric) and cuts them to '..' like a row header. The sort
# indicator after a sorted field's label: 10px of ink 5px after the text, and Desktop keeps ~21px free right of it
# (label ink + 36 px: 'Sub-Category' 95 + 36 held at 131 in a public book, 'Product' cut to 'Produ..' at 87 in
# golden_params_filters_v3); with HEADER_TEXT_PAD_PX that is bold metric + 36, a few px to spare
SORT_ICON_PX = 26
# A vertical axis with its title shown: Desktop sizes it itself, the title strip left of the ticks (a public book area:
# 70px between the zone's margin and the pane for '120K' ticks, axis_px 36 + 34)
AXIS_TITLE_W_PX = 34
# Text in a text table's column (its header and its numbers) takes more than a row header: 'Furniture' (text_px 63)
# was cut to 'Furnitu..' in a 73px column (golden_totals, decisions/066) and held whole at 81 (golden_headers, 3.7);
# '215 129' (57) became '#####' in a 64px column (golden_dates_v2, decisions/066)
TABLE_CELL_PAD_PX = 18
# A Pie with marks-scaling-off (a donut's ring and hole, decisions/069) is this many px across per unit of its size,
# whatever its pane or zoom (Desktop 2025.1 lab, 120 dpi: 0.6 / 1.0 / 1.4 / 1.8 / 2.2 / 2.6 -> 47 / 79 / 111 / 143 /
# 175 / 207px; 1.6 -> 128 in 346 x 453, 345 x 453 and 693 x 151 zones)
PIE_PX_PER_SIZE = 80
HINT_SEPARATOR = " | "  # action hint after a block subtitle (reference: "Views | Click to filter")
HEADER_DATE_RANGE_PX = 242  # date range card in the header row: both dates and the slider on one line (reference Ads
# Campaigns: fixed 242px); a relative date card is a dropdown like a values card (HEADER_FILTER_PX)
LOGO_IMAGE_PX = 48  # brand sidebar logo picture height (Citizen: 58px logo in an 86px header)
BUTTON_PX = 28  # export button height (ER: 48px icons, Admissions: 48px; a text button needs less)
NAV_BUTTON_PX = 28  # navigation button inside its margins (Citizen tab: 25px at 10pt)
NAV_UNDERLINE_PX = 3  # the current tab's accent line under its caption (Citizen: 5px)
NAV_TAB_MIN_PX = 96  # narrowest tab, its margins excluded (Citizen: ~107px tabs, equal widths)
NAV_TAB_PAD_PX = 16  # each side of the longest caption inside a tab
WELCOME_PX = 240  # "Welcome, <name>" sheet at the right of the top bar (SOC: 152px for a placeholder)
MIN_CONTRAST = 4.5  # WCAG AA: text on the brand sidebar and the top bar
HEADER_DATETIME_RANGE_PX = 300  # the same for a datetime field: '31.03.2025 23:59:59' at both ends overlapped at 242px


def line_px(pt):
    """Height of one text line in px (1pt = 4/3 px at 96 dpi)."""
    return math.ceil(pt * 4 / 3 * LINE_HEIGHT)


def text_lines(text, pt, width_px):
    """Lines a text needs when wrapped in width_px (estimate)."""
    chars_per_line = max(1, int(width_px // (pt * 4 / 3 * CHAR_EM)))
    return math.ceil(len(text) / chars_per_line)


def row_header_px(chars):
    """Width of a row header column whose longest text has chars characters (9pt), within REGISTRY_DIM_PX."""
    lo, hi = REGISTRY_DIM_PX
    return min(hi, max(lo, round(chars * FONT["table_header"] * 4 / 3 * CHAR_EM) + ROW_HEADER_PAD_PX))


def axis_px(chars):
    """Width of a vertical axis without its title whose longest tick has chars characters."""
    return max(AXIS_LABEL_W_PX, math.ceil(AXIS_LABEL_W_PX * chars / AXIS_LABEL_CHARS))


def header_px(lines, top=ZONE, bottom=ZONE):
    """Height of a text block: lines = [(pt, count)], plus its zone's margins above and below."""
    top, bottom = (SPACE["zone_margin"] if m is ZONE else m for m in (top, bottom))
    return top + bottom + sum(line_px(pt) * n for pt, n in lines)

# ---- text metrics (decisions/064) -------------------------------------------------------------------------
# Advance widths in 1/1000 em of Arial and Arial Bold (GDI on Windows). Desktop's Tableau Book draws the same
# widths as Arial within 1-3 px on a label of 5-10 characters, its bold is narrower than Arial Bold (measured,
# decisions/064), so the table is the metric of both fonts. A character not in it counts as 1 em.
GLYPHS = ("".join(map(chr, range(32, 127))) + "\xa0\u202f\u25b2\u25bc\u2013\u2014\u2026\u20bd\u20ac\xa3\xa5\xb7\xd7\xb1\xb0"
          + "".join(map(chr, range(0x410, 0x450))) + "\u0401\u0451")  # ASCII, nbsp, signs, Cyrillic
GLYPH_EM = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
    556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
    556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
    556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
    500, 500, 500, 334, 260, 334, 584, 278, 200, 990, 990, 556, 1000, 1000, 556, 556, 556, 556, 333, 584, 549, 400,
    667, 656, 667, 542, 677, 667, 923, 604, 719, 719, 583, 656, 833, 722, 778, 719, 667, 722, 611, 635, 760, 667,
    740, 667, 917, 938, 792, 885, 656, 719, 1010, 722, 556, 573, 531, 365, 583, 556, 669, 458, 559, 559, 438, 583,
    688, 552, 556, 542, 556, 500, 458, 500, 823, 500, 573, 521, 802, 823, 625, 719, 521, 510, 750, 542, 667, 556,
)
GLYPH_EM_BOLD = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
    556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722,
    611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556,
    611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778,
    556, 556, 500, 389, 280, 389, 584, 278, 200, 990, 990, 556, 1000, 1000, 556, 556, 556, 556, 333, 584, 549, 400,
    722, 719, 722, 567, 712, 667, 904, 626, 719, 719, 610, 702, 833, 722, 778, 719, 667, 722, 611, 622, 854, 667,
    730, 703, 1005, 1019, 870, 979, 719, 711, 1031, 719, 556, 618, 615, 417, 635, 556, 709, 497, 615, 615, 500, 635,
    740, 604, 611, 604, 611, 556, 490, 556, 875, 556, 615, 581, 833, 844, 729, 854, 615, 552, 854, 583, 669, 556,
)
# Desktop draws text at the system DPI (120 here: Windows at 125 %) while dashboard and pane px stay 1:1, so 9pt is
# 15px; Tableau Book is up to TEXT_SCALE wider than Arial ('-1 234 567 890,12': 126px drawn, 121.8 by the table)
TEXT_DPI = 120
TEXT_SCALE = 1.04
_GLYPH = {c: i for i, c in enumerate(GLYPHS)}


def text_px(text, pt, bold=False):
    """Width in px of one line of text as Desktop draws it at pt (decisions/064); an unknown character is 1 em."""
    table = GLYPH_EM_BOLD if bold else GLYPH_EM
    em = sum(table[_GLYPH[c]] if c in _GLYPH else 1000 for c in text)
    return math.ceil(em / 1000 * pt * TEXT_DPI / 72 * TEXT_SCALE)


def row_header_fit_px(labels, title, pt=None):
    """Width of a row header column (registry, two-field table): row_header_px as before, wider when its longest
    label (regular) or its column title (bold, a text zone over it) would be cut to '..' (decisions/064). Not capped:
    a header wider than REGISTRY_DIM_PX shows its text whole instead of cutting it silently."""
    pt = FONT["table_header"] if pt is None else pt
    need = max([text_px(v, pt) + HEADER_TEXT_PAD_PX for v in labels] + [text_px(title, pt, bold=True) + TITLE_PAD_PX])
    return max(row_header_px(max(len(v) for v in list(labels) + [title])), need)


def field_label_px(text, extra_px=0, pt=None):
    """Width a field label (over row headers) or an axis title needs whole, extra_px for the sort indicator after
    it (decisions/066)."""
    pt = FONT["table_header"] if pt is None else pt
    return text_px(text, pt, bold=True) + extra_px + HEADER_TEXT_PAD_PX
