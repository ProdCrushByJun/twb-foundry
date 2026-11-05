"""Round-trip: a spec describing the golden workbook must rebuild it structurally 1:1.

Run: python -m unittest discover -s tests
"""
import difflib
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from tbuilder.build import build_file

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden" / "golden_2025_1.twb"
GOLDEN_FORMAT = ROOT / "golden" / "golden_format_2025_1.twb"
GOLDEN_CHARTS = ROOT / "golden" / "golden_charts_2025_1.twb"
GOLDEN_DECLUTTER = ROOT / "golden" / "golden_declutter_2025_1.twb"
GOLDEN_CALCS = ROOT / "golden" / "golden_calcs_2025_1.twb"
GOLDEN_LODS = ROOT / "golden" / "golden_lods_2025_1.twb"
GOLDEN_LODS_VIEW = ROOT / "golden" / "golden_lods_view_2025_1.twb"
GOLDEN_TABLECALCS = ROOT / "golden" / "golden_tablecalcs_2025_1.twb"
GOLDEN_HEADERS = ROOT / "golden" / "golden_headers_2025_1.twb"
GOLDEN_CARDS = ROOT / "golden" / "golden_cards_2025_1.twb"
GOLDEN_KPI_LEFT = ROOT / "golden" / "golden_layout_kpi_left_2025_1.twb"
GOLDEN_SIDEBAR = ROOT / "golden" / "golden_layout_sidebar_2025_1.twb"
GOLDEN_REGISTRY = ROOT / "golden" / "golden_registry_2025_1.twb"
GOLDEN_COLORS = ROOT / "golden" / "golden_colors_2025_1.twb"
GOLDEN_ACTIONS = ROOT / "golden" / "golden_actions_2025_1.twb"
OUT = ROOT / "out"

SPECS = ROOT / "specs"


# UI state / volatile parts that Tableau regenerates on open; not part of the contract.
# The phone-layout flag goes with devicelayouts; active = selected zone; a worksheet window's
# empty <viewpoint> exists only once that sheet tab was visited.
DROP_TAGS = {"thumbnails", "devicelayouts", "highlight", "zoom", "active", "AutoCreateAndUpdateDSDPhoneLayouts"}


def normalize(root):
    sources = [d for d in root.find("datasources") if d.get("name") != "Parameters"]  # the data's, not decisions/020's
    ids = {}
    for i, ds in enumerate(sources):  # several data sources (decisions/083): DS, DS2, ... in document order
        k = "" if i == 0 else str(i + 1)
        ids.update({ds.get("name"): f"DS{k}", ds.find(".//named-connection").get("name"): f"CONN{k}",
                    ds.find("object-graph/objects/object").get("id"): f"OBJ{k}"})

    # a nav button opens a window by its simple-id (decisions/040): compare the target's name, not the uuid
    ids.update({w.find("simple-id").get("uuid"): f"WINDOW:{w.get('name')}" for w in root.find("windows")
                if w.find("simple-id") is not None})
    for d in root.iter("dashboard"):  # zone visibility names its dashboard by the simple-id (decisions/042, 082)
        if d.find("simple-id") is not None:
            ids.setdefault(d.find("simple-id").get("uuid"), f"DASHBOARD:{d.get('name')}")

    def sub(v):
        for k, r in ids.items():
            v = v.replace(k, r)
        return v

    for rule in (r for ds in sources for r in ds.iterfind("style/style-rule")):
        # Palette maps are keyed by field; with several of them Desktop writes them in no stable order
        # (golden_colors_2025_1: a different order on each save), so compare them as a set.
        rule[:] = sorted(rule, key=lambda e: (e.tag, e.get("attr", ""), e.get("field", "")))

    def walk(el):
        if el.tag == "zone" and el.get("type-v2") == "layout-flow" and el.get("param") == "vert":
            for z in el.findall("zone[@type-v2='text']"):
                z.set("h", "*")  # a vertical panel (sidebar) sizes its text to Desktop's own text metrics
            if el.find(".//zone[@type-v2='dashboard-object']") is not None:
                # ...and restacks it (decisions/092): every y below follows those heights, the empty spacer takes
                # the rest. Only in panels with buttons (the shell, the nav sidebar), as before for the others
                for z in el.iter("zone"):
                    if z is not el:
                        z.set("y", "*")
                for z in el.findall("zone[@type-v2='empty']"):
                    z.set("h", "*")
        for child in list(el):
            comma_delim = (child.tag == "attribute" and child.get("name") == "field-delimiter"
                           and child.text == '","')  # Desktop writes it with an explicit separator (below)
            # a column's distinct-value estimate: Desktop recomputes it from the data on every open (decisions/080)
            approx_count = el.tag == "metadata-record" and child.tag == "approx-count"
            if (child.tag in DROP_TAGS or comma_delim or approx_count
                    or (el.tag == "window" and child.tag == "viewpoint" and not child.attrib)):
                el.remove(child)
            else:
                walk(child)
        for k in list(el.attrib):
            if k == "uuid" or (el.tag == "zone" and k == "id"):
                el.attrib[k] = "*"
            else:
                el.attrib[k] = sub(el.attrib[k])
        if el.tag == "columns" and el.get("separator") == ",":
            # Explicit comma = what Desktop sniffed for the older goldens (kept as written on save,
            # see a golden); the builder now always writes it.
            del el.attrib["separator"]
        if el.tag == "zone" and el.get("type-v2") in ("color", "filter"):
            el.attrib["h"] = el.attrib["y"] = "*"  # flow-panel heights are recomputed by Tableau
        if el.text and el.text.strip():
            el.text = sub(el.text.strip())
        else:
            el.text = None
        if el.tag == "export-button-action":  # names its dashboard's simple-id (a uuid, like the simple-id itself)
            el.text = re.sub(r'dashboarddoc-id="\{[0-9A-F-]+\}"', 'dashboarddoc-id="*"', el.text)
        el.tail = None
        if el.tag in ("worksheets", "windows"):
            el[:] = sorted(el, key=lambda c: (c.get("class", ""), c.get("name", "")))
        if el.tag in ("shared-views", "datasources", "dashboard"):  # several sources: Desktop orders them by their
            sources_by_name(el)  # random names, compared here by the normalized ones (decisions/083)
        if el.tag in ("node-execution-subgraphs", "nodes"):  # Desktop writes the datagraph's pairs and nodes in no
            # set order: the same 4 nodes under other guids come out in another one (082, 168)
            el[:] = sorted(el, key=lambda c: c.get("node-guid", ""))

    walk(root)
    return root


def sources_by_name(el):
    """The children naming a data source (a shared view, a source of a list, a dependencies block) in the order of
    their names, Parameters first; the others stay in place."""
    def name(c):
        return c.get("name") if c.tag in ("shared-view", "datasource") else c.get("datasource")
    at = [i for i, c in enumerate(el) if c.tag in ("shared-view", "datasource", "datasource-dependencies")
          and name(c) is not None]
    kids = sorted((el[i] for i in at), key=lambda c: (c.tag, name(c) != "Parameters", name(c)))
    for i, c in zip(at, kids):
        el[i] = c


def canon(root):
    lines = []

    def emit(el, depth):
        attrs = " ".join(f'{k}="{v}"' for k, v in sorted(el.attrib.items()))
        lines.append(f"{'  ' * depth}<{el.tag} {attrs}>{el.text or ''}")
        for c in el:
            emit(c, depth + 1)

    emit(root, 0)
    return lines


def read_twbx(path):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith(".twb"))
        return ET.fromstring(z.read(name)), z.namelist()


class RoundTrip(unittest.TestCase):
    def assertRebuilds(self, spec, golden, data="Data/sample/sales.csv"):
        spec = SPECS / spec
        out = build_file(spec, OUT / f"roundtrip_{spec.parent.name}_{spec.stem}.twbx")
        got, names = read_twbx(out)
        self.assertIn(data, names)
        a = canon(normalize(ET.parse(golden).getroot()))
        b = canon(normalize(got))
        diff = "\n".join(difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=2))
        self.assertEqual(a, b, "\n" + diff)

    def test_golden_rebuilds_identically(self):
        self.assertRebuilds("golden.json", GOLDEN)

    def test_format_golden_rebuilds_identically(self):
        """Tiles, computed sort, titles, weighted grid: golden re-saved by Desktop 2025.1."""
        self.assertRebuilds("format.json", GOLDEN_FORMAT)

    def test_charts_golden_rebuilds_identically(self):
        """Area and heatmap (step 5b, wave 1): golden re-saved by Desktop 2025.1."""
        self.assertRebuilds("charts.json", GOLDEN_CHARTS)

    def test_declutter_golden_rebuilds_identically(self):
        """All six sheet types with the default declutter style: golden re-saved by Desktop 2025.1."""
        self.assertRebuilds("declutter.json", GOLDEN_DECLUTTER)

    def test_calcs_golden_rebuilds_identically(self):
        """Calculated fields: aggregate ratio (percent), conditional sum, string dimension calc."""
        self.assertRebuilds("calcs.json", GOLDEN_CALCS)

    def test_lods_golden_rebuilds_identically(self):
        """FIXED LODs: table-scoped, by dimension, share-of-group, LOD-derived dimension, date LOD."""
        self.assertRebuilds("lods.json", GOLDEN_LODS)

    def test_lods_view_golden_rebuilds_identically(self):
        """INCLUDE / EXCLUDE LODs: whole-formula measures, inside aggregates, on a dated line."""
        self.assertRebuilds("lods_view.json", GOLDEN_LODS_VIEW)

    def test_tablecalcs_golden_rebuilds_identically(self):
        """Quick table calcs: % of total (incl. partitioned, AVG), difference, % difference, running total."""
        self.assertRebuilds("tablecalcs.json", GOLDEN_TABLECALCS)

    def test_headers_golden_rebuilds_identically(self):
        """Dashboard and block headers as text zones: all four block combinations, level rows."""
        self.assertRebuilds("headers.json", GOLDEN_HEADERS)

    def test_cards_golden_rebuilds_identically(self):
        """KPI cards: generated date calcs, value text, palette-mapped history with the latest bar labelled."""
        self.assertRebuilds("cards.json", GOLDEN_CARDS, data="Data/sample/sales_2y.csv")

    def test_layout_kpi_left_golden_rebuilds_identically(self):
        """Archetype A: stacked KPI cards in a full-height column next to a nested grid group."""
        self.assertRebuilds("layout_kpi_left.json", GOLDEN_KPI_LEFT, data="Data/sample/sales_2y.csv")

    def test_layout_sidebar_golden_rebuilds_identically(self):
        """Archetype C: grey sidebar with the title, filter dropdowns and the legend."""
        self.assertRebuilds("layout_sidebar.json", GOLDEN_SIDEBAR)

    def test_registry_golden_rebuilds_identically(self):
        """Registry tables: a pane per column (bar / dummy text), highlight palettes, nested sort, titles."""
        self.assertRebuilds("registry.json", GOLDEN_REGISTRY)

    def test_colors_golden_rebuilds_identically(self):
        """Color with meaning: highlight (own dimension, series on Detail), good/bad flag, plan behind the fact
        (Measure Values, stacking off, Size by Measure Names, manual order), colored subtitle words."""
        self.assertRebuilds("colors.json", GOLDEN_COLORS, data="Data/sample/sales_plan.csv")
    def test_actions_golden_rebuilds_identically(self):
        """Filter actions: all targets / all fields, selected field with exclude-on-clear, hover; hints."""
        self.assertRebuilds("actions.json", GOLDEN_ACTIONS)


    def test_dates_us_golden_rebuilds_identically(self):
        """MM/DD/YYYY read in en_US; relative on a date, datetime range, range over all dates."""
        self.assertRebuilds("dates_us.json", ROOT / "golden" / "golden_dates_us_2025_1.twb",
                            data="Data/sample/sales_dates_us.csv")

    def test_params_golden_rebuilds_identically(self):
        """Parameters: metric switch (CASE over a list parameter), Top N by a range parameter and a fixed Top 3,
        period level through DATETRUNC, parameter cards in the header, parameter values in block titles."""
        self.assertRebuilds("params.json", ROOT / "golden" / "golden_params_2025_1.twb",
                            data="Data/sample/sales_products.csv")

    def test_excel_golden_rebuilds_identically(self):
        """Excel source (decisions/025): sheet 'Orders 2025' of sales.xlsx (not the first sheet), date and datetime
        cells, empty Profit cells."""
        self.assertRebuilds("excel.json", ROOT / "golden" / "golden_excel_2025_1.twb", data="Data/sample/sales.xlsx")

    def test_reflines_golden_rebuilds_identically(self):
        """Reference lines (decisions/028): avg / median / const / param, a stacked bar, a line with series, color vs
        avg and the KPI history average with the change colors (table-calc flags)."""
        self.assertRebuilds("reflines.json", ROOT / "golden" / "golden_reflines_2025_1.twb",
                            data="Data/sample/sales_2y.csv")


    def test_formats_golden_rebuilds_identically(self):
        """Number formats (decisions/032): currency K with the card calcs, parentheses, ₽ suffix, B units, percent."""
        self.assertRebuilds("formats.json", ROOT / "golden" / "golden_formats_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    # Golden debt, re-saved by check-desktop --resave (decisions/061)
    def test_benchmark_golden_rebuilds_identically(self):
        """Benchmark (decisions/043): selected vs the average region on Measure Values, 2x2 repeat, line ends, date
        line, bands (a constant edge on Measure Values names the axis, 061)."""
        self.assertRebuilds("benchmark.json", ROOT / "golden" / "golden_benchmark_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_heatmap_v2_golden_rebuilds_identically(self):
        """Heatmap v2 (decisions/041): sequential / diverging / stepped color scales, marginal totals as bar sheets on
        a fixed px grid."""
        self.assertRebuilds("heatmap_v2.json", ROOT / "golden" / "golden_heatmap_v2_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_dual_axis_golden_rebuilds_identically(self):
        """Dual axis (decisions/044): combo bar + line, donut with the total in the hole and a legend sheet, lollipop."""
        self.assertRebuilds("dual_axis.json", ROOT / "golden" / "golden_dual_axis_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_totals_golden_rebuilds_identically(self):
        """Totals and tooltips (decisions/036): grand totals both ways with the 'All' label, registry subtotals,
        custom tooltips."""
        self.assertRebuilds("totals.json", ROOT / "golden" / "golden_totals_2025_1.twb")

    def test_tablecalc_funcs_golden_rebuilds_identically(self):
        """Table calc functions in formulas (decisions/034): RANK / RANK_DENSE, WINDOW_*, LOOKUP, RUNNING_SUM, TOTAL,
        INDEX with an explicit compute-using."""
        self.assertRebuilds("tablecalc_funcs.json", ROOT / "golden" / "golden_tablecalc_funcs_2025_1.twb")

    def test_tablecalc_v2_golden_rebuilds_identically(self):
        """Table calc functions v2 (decisions/147): SIZE, RANK_UNIQUE, RUNNING_*, WINDOW_COUNT / MEDIAN, PREVIOUS_VALUE."""
        self.assertRebuilds("tablecalc_v2.json", ROOT / "golden" / "golden_tablecalc_v2_2025_1.twb",
                            data="Data/sample/tablecalc_v2.csv")

    def test_actions_v2_golden_rebuilds_identically(self):
        """Actions v2 (decisions/160): highlight, URL, parameter action with a value on clearing, Show/Hide button."""
        self.assertRebuilds("actions_v2.json", ROOT / "golden" / "golden_actions_v2_2025_1.twb")

    def test_params_v2_golden_rebuilds_identically(self):
        """Parameters v2 (decisions/148): aliases, Top N / Bottom N on every sheet type, a parameter in a KPI heading."""
        self.assertRebuilds("params_v2.json", ROOT / "golden" / "golden_params_v2_2025_1.twb",
                            data="Data/sample/params_v2.csv")

    def test_fields_golden_rebuilds_identically(self):
        """Field properties (decisions/033): aliases, manual order, a group with Other (its source declared), default
        colors."""
        self.assertRebuilds("fields.json", ROOT / "golden" / "golden_fields_2025_1.twb",
                            data="Data/sample/sales_products.csv")

    def test_fields_v2_golden_rebuilds_identically(self):
        """Field properties v2 (decisions/151): a calc dimension with aliases, order and colors, a group over the calc
        and over a number, a filter by group."""
        self.assertRebuilds("fields_v2.json", ROOT / "golden" / "golden_fields_v2_2025_1.twb",
                            data="Data/sample/sales_products.csv")


    def test_funnel_golden_rebuilds_identically(self):
        """Funnel (decisions/159): centered Gantt bars, stages by value and in process order, conversion table calcs,
        the unseen line that leaves room for the labels."""
        self.assertRebuilds("funnel.json", ROOT / "golden" / "golden_funnel_2025_1.twb", data="Data/sample/funnel.csv")

    def test_nav_golden_rebuilds_identically(self):
        """Navigation (decisions/040): three dashboards, goto buttons as tabs with the accent line, shared sheets, one
        filter card per dashboard."""
        self.assertRebuilds("nav.json", ROOT / "golden" / "golden_nav_2025_1.twb")

    def test_multi_source_golden_rebuilds_identically(self):
        """Several data sources (decisions/083): two CSVs, each sheet on its own, filter cards of both sources on one
        dashboard, an action within its source, Top N by a parameter on the second source."""
        self.assertRebuilds("multi_source.json", ROOT / "golden" / "golden_multi_source_2025_1.twb",
                            data="Data/sample/sales_plan.csv")

    def test_pareto_golden_rebuilds_identically(self):
        """Pareto (decisions/157): bars largest first, the running share on a second axis, the 80 % line, the vital
        few in the accent."""
        self.assertRebuilds("pareto.json", ROOT / "golden" / "golden_pareto_2025_1.twb",
                            data="Data/sample/complaints.csv")

    def test_folders_golden_rebuilds_identically(self):
        """Field folders of the Data pane (decisions/146): multi_source with calcs and columns in folders, each
        source gets the folders of its own fields."""
        self.assertRebuilds("folders.json", ROOT / "golden" / "golden_folders_2025_1.twb",
                            data="Data/sample/sales_plan.csv")

    def test_switch_registry_golden_rebuilds_identically(self):
        """A switch of two registries and a bar (decisions/082): each view in a layout-basic container with zone
        visibility, hidden-by-user on every zone of the hidden ones, the flag calcs in the views' datasource of a book
        with two sources, the radio card on the switch's dashboard."""
        self.assertRebuilds("switch_registry.json", ROOT / "golden" / "golden_switch_registry_2025_1.twb",
                            data="Data/sample/sales_plan.csv")

    def test_interactive_golden_rebuilds_identically(self):
        """Buttons on parameter actions, a period parameter, a radio switching two views by zone visibility
        (decisions/042): Desktop keeps the <datagraph> as written; clicks checked by hand in the golden-debt pass."""
        self.assertRebuilds("interactive.json", ROOT / "golden" / "golden_interactive_2025_1.twb",
                            data="Data/sample/sales_products.csv")

    def test_kpi_v2_nopill_golden_rebuilds_identically(self):
        """KPI v2 (decisions/037) without the pill and the bar marker (Desktop draws them as a small square, 061): abs +
        % delta, history line with labels and average, period line, data as of."""
        self.assertRebuilds("kpi_v2_nopill.json", ROOT / "golden" / "golden_kpi_v2_nopill_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_registry_v2_golden_rebuilds_identically(self):
        """Registry v2 (decisions/039, 065): rank, share with its value, bar inside, track on Measure Values (palette
        instances with the sheet's compute-using), dot scale, tick in the default pane with its base on Detail, change,
        two-line cell, Top 2 per repeated field."""
        self.assertRebuilds("registry_v2.json", ROOT / "golden" / "golden_registry_v2_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_registry_totals_golden_rebuilds_identically(self):
        """Registry totals under bar columns (decisions/081): bars on calcs guarded to the rows (0 on a total), the
        total's number on the first layer of a bar_inside, its own format, a total bar within the rows' (INCLUDE)."""
        self.assertRebuilds("registry_totals.json", ROOT / "golden" / "golden_registry_totals_2025_1.twb")

    def test_registry_spark_pill_golden_rebuilds_identically(self):
        """Registry spark (block glyphs) and pill (level) columns (decisions/096): string calcs as :nk instances."""
        self.assertRebuilds("registry_spark_pill.json", ROOT / "golden" / "golden_registry_spark_pill_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_registry_spark_line_golden_rebuilds_identically(self):
        """Registry line spark (decisions/153): a part sheet right of the registry, an independent axis per row, the
        last period's dot folded onto the line."""
        self.assertRebuilds("registry_spark_line.json", ROOT / "golden" / "golden_registry_spark_line_2025_1.twb",
                            data="Data/sample/sales_2y.csv")

    def test_registry_totals_marks_golden_rebuilds_identically(self):
        """Registry rank / track / dot / tick / highlight under totals (decisions/134): a guarded rank, color and tick
        line, a FIXED-share track, a three-state flag."""
        self.assertRebuilds("registry_totals_marks.json", ROOT / "golden" / "golden_registry_totals_marks_2025_1.twb",
                            data="Data/sample/sales_plan.csv")

    def test_hyper_golden_rebuilds_identically(self):
        """Hyper as the source (decisions/026): specs/dates.json packaged as .hyper; Desktop's approx-count in every
        column record is its own estimate and set aside (decisions/080)."""
        self.assertRebuilds("hyper.json", ROOT / "golden" / "golden_hyper_2025_1.twb",
                            data="Data/sample/sales_dates.hyper")

    def test_filters_v2_golden_rebuilds_identically(self):
        """Filters v2 (decisions/035) with the City column's geographic role Desktop gives it by its name
        (decisions/092)."""
        self.assertRebuilds("filters_v2.json", ROOT / "golden" / "golden_filters_v2_2025_1.twb",
                            data="Data/sample/sales_stores.csv")

    def test_filters_cards_golden_rebuilds_identically(self):
        """Filter cards v2 (decisions/162): single value slider, wildcard, Apply button, a range on a measure."""
        self.assertRebuilds("filters_cards.json", ROOT / "golden" / "golden_filters_cards_2025_1.twb",
                            data="Data/sample/sales_stores.csv")

    def test_filters_cards_panel_golden_rebuilds_identically(self):
        """Filter cards v2 (decisions/162) in the right panel: single value list, a list with an Apply button."""
        self.assertRebuilds("filters_cards_panel.json", ROOT / "golden" / "golden_filters_cards_panel_2025_1.twb",
                            data="Data/sample/sales_stores.csv")

    def test_shell_golden_rebuilds_identically(self):
        """Dashboard shell (decisions/029): brand sidebar with the logo, filters, export buttons and footer, the top
        bar with Welcome; the logo, the button row and Welcome fixed-size in their flows (decisions/092)."""
        self.assertRebuilds("shell.json", ROOT / "golden" / "golden_shell_2025_1.twb")



if __name__ == "__main__":
    unittest.main()
