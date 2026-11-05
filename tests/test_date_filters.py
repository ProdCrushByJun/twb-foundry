"""Period filters (decisions/019): spec, builder XML, expected rows, refusals, gate mutations; datetime and locale XML."""
import copy
import datetime as dt
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from lxml import etree

from tbuilder import dates, design, expected, gate
from tbuilder import spec as spec_mod
from tbuilder.build import build
from tbuilder.formula import CalcSet, FormulaError
from tbuilder.profile import profile_csv
from test_roundtrip import OUT, ROOT, SPECS

DATES = json.loads((SPECS / "dates.json").read_text(encoding="utf-8"))
DATES_US = json.loads((SPECS / "dates_us.json").read_text(encoding="utf-8"))
CSV = ROOT / "data" / "sample" / "sales_dates.csv"
PROF = profile_csv(CSV)


def built(spec, name="date_filters_test"):
    out = build(spec, OUT / f"{name}.twbx", SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(out.stem + ".twb")), out


def spec_with(fn, base=DATES):
    s = copy.deepcopy(base)
    fn(s)
    return s


def dfilter(field, **spec):
    return dates.DateFilter(PROF.col(field), {"field": field, "show_on": "Orders", **spec}, PROF.rows)


class Semantics(unittest.TestCase):
    def test_relative_months_include_the_whole_anchor_month(self):
        """Desktop: 'Last 3 months' anchored 20.07.2025 = 01.05.2025 to 31.07.2025."""
        f = dfilter("Shipped At", mode="relative", period="month", last=3, anchor="2025-07-20")
        self.assertEqual(f.bounds(), (dt.date(2025, 5, 1), dt.date(2025, 7, 31)))

    def test_relative_default_anchor_is_the_latest_date(self):
        f = dfilter("Shipped At", mode="relative", period="month", last=1)
        self.assertEqual(f.anchor, max(dates.to_date(r["Shipped At"]) for r in PROF.rows))

    def test_relative_weeks_quarters_years_days(self):
        anchor = "2025-07-02"  # a Wednesday; weeks start on Monday (date-options)
        cases = {("week", 2): ("2025-06-23", "2025-07-06"), ("quarter", 2): ("2025-04-01", "2025-09-30"),
                 ("year", 1): ("2025-01-01", "2025-12-31"), ("day", 7): ("2025-06-26", "2025-07-02")}
        for (period, last), (a, b) in cases.items():
            with self.subTest(period=period):
                f = dfilter("Order Date", mode="relative", period=period, last=last, anchor=anchor)
                self.assertEqual(f.bounds(), (dt.date.fromisoformat(a), dt.date.fromisoformat(b)))

    def test_range_keeps_bounds_and_drops_nulls(self):
        f = dfilter("Order Date", mode="range", min="2024-07-01", max="2025-06-30")
        self.assertTrue(f.keeps("2024-07-01") and f.keeps("2025-06-30"))
        self.assertFalse(f.keeps("2024-06-30") or f.keeps(""))

    def test_range_over_all_dates_keeps_nulls(self):
        self.assertTrue(dfilter("Order Date", mode="range").keeps(""))

    def test_datetime_range_keeps_the_whole_last_day(self):
        f = dfilter("Shipped At", mode="range", min="2025-01-01", max="2025-03-31")
        self.assertTrue(f.keeps("2025-03-31 23:59:59"))
        self.assertFalse(f.keeps("2025-04-01 00:00:00"))

    def test_expected_applies_all_filters(self):
        """22 258 / 157 is what Desktop showed for the hand-made reference (out/dates_lab, same periods)."""
        e = expected.compute(DATES, SPECS / DATES["datasource"]["path"])
        self.assertEqual(e["KPI"], {"SUM(Sales)": 22258.0, "SUM(Units)": 157.0})


class Xml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root, _ = built(DATES, "date_filters_ru")
        cls.us, _ = built(DATES_US, "date_filters_us")

    def shared(self, root):
        return {f.get("column").split("].")[1]: f for f in root.find("shared-views/shared-view").findall("filter")}

    def test_range_filter(self):
        f = self.shared(self.root)["[none:Order Date:qk]"]
        self.assertEqual((f.get("class"), f.get("included-values"), f.findtext("min"), f.findtext("max")),
                         ("quantitative", "in-range", "#2024-07-01#", "#2025-06-30#"))

    def test_relative_filter_on_datetime(self):
        f = self.shared(self.root)["[none:Shipped At:qk]"]
        self.assertEqual(dict(f.attrib), {"class": "relative-date", "column": f.get("column"), "first-period": "-2",
                                          "include-future": "true", "include-null": "false", "last-period": "0",
                                          "period-anchor": "#2025-07-02 00:00:00#", "period-type-v2": "month"})

    def test_us_filters(self):
        f = self.shared(self.us)
        self.assertEqual(f["[none:Order Date:qk]"].get("period-anchor"), "#2025-06-15 00:00:00#")  # date column
        self.assertEqual(f["[none:Order Date:qk]"].get("first-period"), "-5")
        self.assertEqual((f["[none:Shipped At:qk]"].findtext("min"), f["[none:Shipped At:qk]"].findtext("max")),
                         ("#2025-01-01 00:00:00#", "#2025-03-31 23:59:59#"))
        self.assertEqual(dict(f["[none:Due Date:qk]"].attrib).get("included-values"), "all")
        self.assertEqual(len(f["[none:Due Date:qk]"]), 0)

    def test_manifest_flag_only_with_a_relative_filter(self):
        tags = [c.tag for c in self.root.find("document-format-change-manifest")]
        self.assertEqual(tags[tags.index("ISO8601PeriodTypes") - 1:tags.index("ISO8601PeriodTypes") + 2],
                         ["AutoCreateAndUpdateDSDPhoneLayouts", "ISO8601PeriodTypes", "MarkAnimation"])
        no_relative, _ = built(spec_with(lambda s: s["filters"].pop()), "date_filters_range_only")
        self.assertIsNone(no_relative.find("document-format-change-manifest/ISO8601PeriodTypes"))

    def test_shared_filters_ordered_by_field(self):
        self.assertEqual(list(self.shared(self.root)), ["[none:Order Date:qk]", "[none:Region:nk]",
                                                        "[none:Shipped At:qk]"])

    def test_header_cards(self):
        cards = [z for z in self.root.iter("zone") if z.get("type-v2") == "filter"]
        self.assertEqual([(c.get("fixed-size"), c.get("mode"), c.get("values")) for c in cards],
                         [("142", "checkdropdown", None), (str(design.HEADER_DATE_RANGE_PX), None, "database"),
                          ("142", None, "database")])
        self.assertEqual(list(cards[1].attrib), ["fixed-size", "h", "id", "is-fixed", "name", "param", "type-v2",
                                                 "values", "w", "x", "y"])  # Desktop's attribute order

    def test_no_worksheet_card_for_date_filters(self):
        params = [c.get("param", "") for c in self.root.iter("card") if c.get("type") == "filter"]
        self.assertEqual([p.split("].")[1] for p in params], ["[none:Region:nk]"])

    def test_every_sheet_slices_the_date_filters(self):
        for ws in self.root.iter("worksheet"):
            sl = [c.text.split("].")[1] for c in ws.find("table/view/slices")]
            self.assertEqual(sl, ["[none:Region:nk]", "[none:Order Date:qk]", "[none:Shipped At:qk]"])

    def test_datetime_column(self):
        ds = self.root.find("datasources/datasource")
        rec = next(r for r in ds.iter("metadata-record") if r.findtext("remote-name") == "Shipped At")
        self.assertEqual((rec.findtext("remote-type"), rec.findtext("local-type"), rec.findtext("aggregation")),
                         ("135", "datetime", "Year"))
        col = next(c for c in ds.find("connection/relation/columns") if c.get("name") == "Shipped At")
        self.assertEqual(col.get("datatype"), "datetime")

    def test_locales(self):
        for root, loc, coll, numbers in [(self.root, "ru_RU", "LRU_RRU", True), (self.us, "en_US", "LEN_RUS", False)]:
            with self.subTest(locale=loc):
                ds = root.find("datasources/datasource")
                self.assertEqual({c.get("locale") for c in ds.iter("columns")}, {loc})
                cap = {a.get("name"): a.text for a in ds.find(".//metadata-record[@class='capability']/attributes")}
                self.assertEqual(cap["locale"], f'"{loc}"')
                self.assertEqual("decimal-char" in cap, numbers)
                self.assertEqual({c.get("name") for c in ds.iter("collation")}, {coll})


class Refusals(unittest.TestCase):
    def assertRejects(self, spec, msg):
        with self.assertRaisesRegex(ValueError, msg):
            build(spec, OUT / "date_filters_bad.twbx", SPECS)

    def test_range_on_a_text_field(self):
        self.assertRejects(spec_with(lambda s: s["filters"][0].update(mode="range")), "needs a date column")

    def test_values_on_a_date_field(self):
        self.assertRejects(spec_with(lambda s: s["filters"][1].update(mode="values", min=None) or
                                     [s["filters"][1].pop(k) for k in ("min", "max", "mode")]),
                           "needs mode 'range' or 'relative'")

    def test_unknown_field(self):
        self.assertRejects(spec_with(lambda s: s["filters"][1].update(field="Ship Date")), "not found")

    def test_min_after_max(self):
        self.assertRejects(spec_with(lambda s: s["filters"][1].update(min="2025-07-01")), "is after max")

    def test_needs_the_header_row(self):
        self.assertRejects(spec_with(lambda s: [s["dashboard"].pop(k) for k in ("title", "subtitle")]), "header row")
        self.assertRejects(spec_with(lambda s: s["dashboard"].update(sidebar=True, theme="flat")), "header row")

    def test_one_filter_per_date_field(self):
        self.assertRejects(spec_with(lambda s: s["filters"].append(
            {"field": "Order Date", "show_on": "Orders", "mode": "relative", "period": "year", "last": 1})),
            "repeat the date fields")

    def test_datetime_in_a_formula(self):
        """Datetime columns work in date functions since decisions/051 and in STR since 055; SUM of one is refused."""
        CalcSet([{"name": "D", "formula": "DATETRUNC('month', [Shipped At])"},
                 {"name": "S", "formula": "STR([Shipped At])"}],
                {c.name: c.datatype for c in PROF.columns}, PROF.rows)
        with self.assertRaisesRegex(FormulaError, "SUM needs a number, got datetime"):
            CalcSet([{"name": "D", "formula": "SUM([Shipped At])"}],
                    {c.name: c.datatype for c in PROF.columns}, PROF.rows)


class Schema(unittest.TestCase):
    def assertInvalid(self, filt, msg):
        s = copy.deepcopy(DATES)
        s["filters"] = [{"field": "Order Date", "show_on": "Orders", **filt}]
        with self.assertRaises(spec_mod.SpecError) as e:
            spec_mod.validate(s)
        self.assertIn(msg, str(e.exception))

    def test_relative_needs_period_and_last(self):
        self.assertInvalid({"mode": "relative", "last": 3}, "'period' is a required property")

    def test_range_bounds_come_in_pairs(self):
        self.assertInvalid({"mode": "range", "min": "2024-01-01"}, "'max' is a dependency of 'min'")

    def test_period_only_with_relative(self):
        self.assertInvalid({"mode": "range", "period": "month"}, "filters/0/mode: 'relative' was expected")

    def test_bounds_only_with_range(self):
        self.assertInvalid({"min": "2024-01-01", "max": "2024-02-01"}, "'mode' is a required property")
        self.assertInvalid({"mode": "values", "min": "2024-01-01", "max": "2024-02-01"}, "'range' was expected")

    def test_iso_dates_only(self):
        self.assertInvalid({"mode": "range", "min": "01.07.2024", "max": "2025-06-30"}, "does not match")


class GateCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.path = built(DATES, "date_filters_gate")

    def mutant(self, fn):
        with zipfile.ZipFile(self.path) as src:
            members = {n: src.read(n) for n in src.namelist()}
        name = next(n for n in members if n.endswith(".twb"))
        root = etree.fromstring(members[name])
        fn(root, next(root.iter("shared-view")))
        members[name] = etree.tostring(root, xml_declaration=True, encoding="utf-8")
        path = Path(tempfile.mkdtemp()) / "mutant.twbx"
        with zipfile.ZipFile(path, "w") as z:
            for n, b in members.items():
                z.writestr(n, b)
        return path

    def assertCaught(self, fn, text):
        issues = [str(i) for i in gate.run(self.mutant(fn)) if i.check == "filters"]
        self.assertTrue(any(text in i for i in issues), f"expected [filters] ~ '{text}', got {issues}")

    @staticmethod
    def flt(sv, cls):
        return next(f for f in sv.findall("filter") if f.get("class") == cls)

    def test_generated_passes(self):
        self.assertEqual(gate.run(self.path), [])

    def test_filter_on_a_text_field(self):
        def m(root, sv):
            f = self.flt(sv, "relative-date")
            f.set("column", f.get("column").replace("[none:Shipped At:qk]", "[none:Region:nk]"))
        self.assertCaught(m, "the field is string, not a date")

    def test_filter_on_a_missing_field(self):
        def m(root, sv):
            f = self.flt(sv, "quantitative")
            f.set("column", f.get("column").replace("[none:Order Date:qk]", "[none:Ship Date:qk]"))
        self.assertCaught(m, "not a field of this sheet's datasource")

    def test_min_after_max(self):
        self.assertCaught(lambda root, sv: self.flt(sv, "quantitative").find("min").__setattr__("text", "#2026-01-01#"),
                          "is after max")

    def test_impossible_date(self):
        self.assertCaught(lambda root, sv: self.flt(sv, "quantitative").find("max").__setattr__("text", "#2025-02-30#"),
                          "not a valid date literal")

    def test_relative_filter_without_its_manifest_flag(self):
        """Desktop 2025.1 refused the first candidate: "attribute 'period-type-v2' is not declared"."""
        def m(root, sv):
            man = root.find("document-format-change-manifest")
            man.remove(man.find("ISO8601PeriodTypes"))
        self.assertCaught(m, "needs <ISO8601PeriodTypes/>")

    def test_anchor_without_time_on_a_datetime(self):
        self.assertCaught(lambda root, sv: self.flt(sv, "relative-date").set("period-anchor", "#2025-07-02#"),
                          "not a valid datetime literal")


if __name__ == "__main__":
    unittest.main()
