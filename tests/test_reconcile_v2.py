"""Reconcile v2 (decisions/058): members written otherwise, canvas charts, filter states, small numbers."""
import copy
import shutil
import tempfile
import unittest
from pathlib import Path

from tbuilder import html_outline, reconcile
from tbuilder.spec import load
from test_reconcile import FIXTURE, FIXTURE_SPEC, HAVE_CHROME, page, text
from test_roundtrip import ROOT

V2 = ROOT / "tests" / "fixtures" / "reconcile_v2"


def statuses(r):
    return {f["number"] + " " + f["context"]: f["status"] for f in r["facts"] if f["status"] != "skipped"}






class StatesWithoutChrome(unittest.TestCase):
    """Filter states from a synthetic outline: (All), a value of a column without a filter card, the opening option."""

    @classmethod
    def setUpClass(cls):
        cls.spec = load(V2 / "filter_select.json")

    def outline(self, options, selected, states):
        return {"texts": [text("74,957", up=["74,957", "74,957 Total sales"])],
                "controls": [{"kind": "select", "label": "", "options": options, "selected": [selected]}],
                "states": [{"control": 0, "option": o, "same": False, "texts": t, "charts": []} for o, t in states]}

    def test_all_clears_the_default(self):
        o = self.outline(["All", "Furniture", "Office", "Tech"], "Furniture",
                         [("All", [text("224,710", up=["224,710", "224,710 Total sales"])])])
        r = reconcile.check(self.spec, V2, o)
        self.assertTrue(r["ok"], reconcile.report_text(r))
        self.assertEqual([(s["option"], s["status"], s["state"]) for s in r["states"]], [("All", "checked", {})])

    def test_option_of_a_column_without_a_card_fails(self):
        o = self.outline(["East", "North"], "East", [("North", [text("58,483", up=["58,483", "Total sales 58,483"])])])
        r = reconcile.check(self.spec, V2, o)
        self.assertFalse(r["ok"])
        self.assertIn("no filter card", r["states"][0]["reason"])

    def test_the_page_must_open_in_the_workbook_selection(self):
        spec = copy.deepcopy(self.spec)
        spec["filters"][0]["default"] = ["Tech"]
        r = reconcile.check(spec, V2, self.outline(["Furniture", "Office", "Tech"], "Furniture", []))
        self.assertFalse(r["ok"])
        self.assertIn("the page opens with Category = ['Furniture']", reconcile.problems(r)[-1])

    def test_unmapped_and_case_options(self):
        o = self.outline(["Furniture", "Office (was B2)"], "Furniture",
                         [("Office (was B2)", [text("71,178", up=["71,178", "71,178 Total sales"])])])
        r = reconcile.check(self.spec, V2, o)
        self.assertEqual(r["states"][0]["status"], "unverified")
        self.assertTrue(r["ok"])
        r = reconcile.check(self.spec, V2, o, {"options": {"Office (was B2)": {"Category": ["Office"]}}})
        self.assertEqual((r["states"][0]["status"], r["states"][0]["summary"]), ("checked", {"matched": 1}))

    def test_numberless_accept_covers_every_state(self):
        o = self.outline(["Furniture", "Office"], "Furniture",
                         [("Office", [text("71,178", up=["71,178", "71,178 Total sales"]), text("12.5 per order")])])
        o["texts"].append(text("11.1 per order"))
        case = {"accepted": [{"context": "per order", "reason": "not in this spec"}]}
        r = reconcile.check(self.spec, V2, o, case)
        self.assertTrue(r["ok"], reconcile.report_text(r))
        self.assertEqual(r["summary"]["accepted"], 1)
        self.assertEqual(r["states"][0]["summary"]["accepted"], 1)


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class Canvas(unittest.TestCase):
    """canvas.html: three Chart.js charts (offline stand-in, chart_shim.js), one canvas with data-labels +
    data-values, one sketch without data."""

    def test_every_chart_number_is_checked(self):
        r = reconcile.check(load(V2 / "canvas.json"), V2, html_outline.outline(V2 / "canvas.html"))
        self.assertTrue(r["ok"], reconcile.report_text(r))
        data = [f for f in r["facts"] if f.get("data")]
        self.assertEqual(len(data), 4 + 12 + 12 + 3)  # regions, region x category, months, categories
        self.assertTrue(all(f["status"] == "matched" for f in data), [f for f in data if f["status"] != "matched"])
        self.assertEqual({f["chart"] for f in data}, {"chart.js", "data-attributes"})
        self.assertEqual([(f["number"], f["status"]) for f in r["facts"] if f["status"] == "unverified"],
                         [("canvas", "unverified")])  # the hand-drawn sketch: said, not skipped silently
        self.assertEqual(r["summary"], {"matched": 32, "skipped": 1, "unverified": 1})

    def page(self, tmp, html, shim=True):
        if shim:
            shutil.copy(V2 / "chart_shim.js", tmp)
        p = Path(tmp) / "canvas.html"
        p.write_text(html, encoding="utf-8")
        return html_outline.outline(p)

    def test_a_wrong_chart_value_is_a_mismatch(self):
        html = (V2 / "canvas.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("58862.46"), 1)
        with tempfile.TemporaryDirectory() as tmp:
            o = self.page(tmp, html.replace("58862.46", "58000.46"))
        r = reconcile.check(load(V2 / "canvas.json"), V2, o)
        self.assertFalse(r["ok"])
        bad = [f for f in r["facts"] if f["status"] in reconcile.FAILING]
        self.assertEqual([(f["number"], f["status"]) for f in bad], [("58000.46", "mismatch")])
        self.assertIn("Sales by region [South] = 58862.5", bad[0]["workbook"])

    def test_echarts_instance(self):
        """An ECharts page: getInstanceByDom on the chart's container, getOption() as ECharts returns it (arrays of
        axes, series and titles; pie data as {name, value}). A stand-in, as for Chart.js."""
        html = """<!doctype html><html><head><meta charset="utf-8"><script>
        window.echarts = {all: new Map(),
          init(dom) { const c = document.createElement("canvas"); c.width = 400; c.height = 200; dom.appendChild(c);
                      const inst = {o: null, setOption(o) { this.o = o; c.getContext("2d").fillRect(10, 10, 50, 50); },
                                    getOption() { const o = this.o, arr = (v) => v === undefined ? [] : [].concat(v);
                                                  return {title: arr(o.title), xAxis: arr(o.xAxis), yAxis: arr(o.yAxis),
                                                          series: arr(o.series)}; }};
                      this.all.set(dom, inst); return inst; },
          getInstanceByDom(dom) { return this.all.get(dom); }};
        </script></head><body>
        <div id="a" style="width:400px;height:200px"></div><div id="b" style="width:400px;height:200px"></div>
        <script>
        echarts.init(document.getElementById("a")).setOption({title: {text: "Sales by region"},
          xAxis: {type: "category", data: ["East", "North", "South", "West"]}, yAxis: {type: "value"},
          series: [{name: "Sales", type: "bar", data: [52353.59, 58482.58, 58862.46, 55011.05]}]});
        echarts.init(document.getElementById("b")).setOption({title: {text: "Profit by category"},
          series: [{name: "Profit", type: "pie", data: [{name: "Furniture", value: 7585.81},
                   {name: "Office", value: 7211.62}, {name: "Tech", value: 8752.17}]}]});
        </script></body></html>"""
        with tempfile.TemporaryDirectory() as tmp:
            o = self.page(tmp, html, shim=False)
        r = reconcile.check(load(V2 / "canvas.json"), V2, o)
        self.assertTrue(r["ok"], reconcile.report_text(r))
        self.assertEqual(r["summary"], {"matched": 7})
        self.assertEqual({f["chart"] for f in r["facts"]}, {"echarts"})

    def test_no_chart_library_no_check(self):
        """The library did not load: the four Chart.js canvases are 'unverified: canvas', none is matched by chance."""
        with tempfile.TemporaryDirectory() as tmp:
            o = self.page(tmp, (V2 / "canvas.html").read_text(encoding="utf-8"), shim=False)
        r = reconcile.check(load(V2 / "canvas.json"), V2, o)
        self.assertEqual(r["summary"].get("unverified"), 4)
        self.assertEqual(len([f for f in r["facts"] if f.get("data")]), 3)  # data-labels + data-values still read


@unittest.skipUnless(HAVE_CHROME, "Chrome not installed")
class FilterStates(unittest.TestCase):
    """filter_select.html: a <select> of Category re-renders the tiles and bars; the workbook opens with Furniture."""

    def run_(self, html=None):
        spec = load(V2 / "filter_select.json")
        if html is None:
            return reconcile.check(spec, V2, html_outline.outline(V2 / "filter_select.html"))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "filter_select.html"
            p.write_text(html, encoding="utf-8")
            return reconcile.check(spec, V2, html_outline.outline(p))

    def test_every_state_is_checked(self):
        r = self.run_()
        self.assertTrue(r["ok"], reconcile.report_text(r))
        self.assertEqual(r["summary"], {"matched": 6})  # Furniture, as the page opens
        self.assertEqual([(s["option"], s["status"], s["state"], s["summary"]) for s in r["states"]],
                         [("Office", "checked", {"Category": ["Office"]}, {"matched": 6}),
                          ("Tech", "checked", {"Category": ["Tech"]}, {"matched": 6})])

    def test_a_wrong_number_in_one_state_fails_that_state_only(self):
        html = (V2 / "filter_select.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("15632.96"), 1)  # Office, East
        r = self.run_(html.replace("15632.96", "15032.96"))
        self.assertFalse(r["ok"])
        self.assertFalse(any(f["status"] in reconcile.FAILING for f in r["facts"]))
        got = {s["option"]: [(f["number"], f["status"]) for f in s["facts"] if f["status"] in reconcile.FAILING]
               for s in r["states"]}
        self.assertEqual(got, {"Office": [("15,033", "mismatch")], "Tech": []})
        self.assertIn("state «Office»: mismatch 15,033", reconcile.problems(r)[0])

    def test_a_page_the_control_does_not_drive(self):
        """The sales fixture's <select> changes nothing: its states are 'static', the check as before."""
        r = reconcile.check(load(FIXTURE_SPEC), FIXTURE_SPEC.parent, html_outline.outline(FIXTURE))
        self.assertTrue(r["ok"])
        self.assertEqual(r["summary"], {"matched": 18, "elsewhere": 1, "skipped": 2})  # + the sparkline without an axis (decisions/123)
        self.assertEqual([(s["option"], s["status"]) for s in r["states"]],
                         [("East", "static"), ("North", "static"), ("South", "static"), ("West", "static")])


if __name__ == "__main__":
    unittest.main()
