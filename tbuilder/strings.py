"""The generator's own words in a workbook, by the workbook's locale (decisions/169).

Text the generator writes into labels and number formats ('compared to', 'WoW', 'pp', 'Data as of', the action
hints and captions, decisions/177) follows the spec's locale; en_US is the default and the fallback for a key a
locale lacks. Tableau's own UI words ('(All)' of a filter card, 'Week of' of a week header) follow the UI language
of Desktop / Server, not the workbook, and no workbook XML renames them (decisions/177): not here.
"""
STRINGS = {
    "en_US": {
        "compared_to": " compared to ",  # the period line: 'Dec 2025 compared to Nov 2025'
        "pp": "pp",  # percentage points: the change of a ratio measure (decisions/110)
        "no_change": "no change",  # a zero change with delta_zero 'neutral'
        "data_as_of": "Data as of ",
        ("previous", "week"): "WoW", ("previous", "month"): "MoM", ("previous", "year"): "YoY",
        ("year", "week"): "vs PY", ("year", "month"): "vs PY", ("year", "year"): "vs PY",
        "last_week": "Last Week", "last_month": "Last Month", "last_year": "Last Year",
        # action hints after a block's subtitle and the actions' captions (decisions/177)
        ("hint", "filter", "select"): "Click to filter", ("hint", "filter", "hover"): "Hover to filter",
        ("hint", "highlight", "select"): "Click to highlight", ("hint", "highlight", "hover"): "Hover to highlight",
        ("hint", "url", "select"): "Click to open", ("hint", "url", "menu"): "Click for the link",
        ("hint", "parameter", "select"): "Click to select",
        "all": "All",  # an action's caption: 'Source → All' targets every sheet
        "hide_filters": "Hide filters", "show_filters": "Show filters",  # the Show/Hide button (decisions/160)
        # card_date 'range' (decisions/178): 'wk 12 (Oct 19–24) vs wk 11'; a measure's goal: '· target 95%'
        "wk": "wk", "vs_wk": ") vs wk ", "goal": " · target ",
        "months": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    },
}


def locale(spec):
    return (spec or {}).get("locale", "en_US")


def t(spec, key):
    """The text of key in the spec's locale (en_US without one)."""
    return STRINGS.get(locale(spec), {}).get(key, STRINGS["en_US"][key])
