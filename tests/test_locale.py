"""The workbook's locale (decisions/085): <workbook locale>, the CSV's text-file locale, numbers by it."""
import copy
import json
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from tbuilder import drawn, formats, html_outline, spec as spec_mod
from tbuilder.build import build
from tbuilder.match import parse_number

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "specs"


def built(name, **top):
    """The XML root of specs/<name>.json built with these top-level keys set (None: removed)."""
    spec = copy.deepcopy(spec_mod.load(SPECS / f"{name}.json"))
    for k, v in top.items():
        if v is None:
            spec.pop(k, None)
        else:
            spec[k] = v
    out = Path(tempfile.mkdtemp()) / f"{name}.twbx"
    build(spec, out, SPECS)
    with zipfile.ZipFile(out) as z:
        return ET.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def text_file(root):
    """(<columns locale>, capability attributes {name: value}, string collations) of the CSV source."""
    cols = root.find(".//relation/columns")
    cap = next(r for r in root.iter("metadata-record") if r.get("class") == "capability")
    attrs = {a.get("name"): a.text for a in cap.iter("attribute")}
    colls = {c.get("name") for c in root.iter("collation")}
    return cols.get("locale"), attrs, colls


class Workbook(unittest.TestCase):
    def test_spec_without_locale_is_en_us(self):
        root = built("golden", locale=None)
        self.assertEqual(root.get("locale"), "en_US")
        self.assertEqual(list(root.attrib)[0], "locale")  # as Desktop writes it: attributes by name

    def test_ru_spec(self):
        self.assertEqual(built("golden", locale="ru_RU").get("locale"), "ru_RU")

    def test_schema_takes_two_locales(self):
        spec = spec_mod.load(SPECS / "golden.json")
        for ok in ("en_US", "ru_RU"):
            spec_mod.validate({**spec, "locale": ok})
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.validate({**spec, "locale": "en-US"})


class TextFile(unittest.TestCase):
    """ISO dates (or none) read in any locale: the CSV takes the workbook's; DD.MM keeps ru_RU (decisions/019)."""

    def test_iso_csv_in_an_en_us_book(self):
        loc, attrs, colls = text_file(built("golden"))
        self.assertEqual(loc, "en_US")
        self.assertEqual((attrs["locale"], attrs["collation"]), ('"en_US"', '"en_US"'))
        self.assertFalse({"currency", "decimal-char", "thousands-char"} & set(attrs))  # Desktop's en_US record
        self.assertEqual(colls, {"LEN_RUS"})

    def test_iso_csv_in_a_ru_book(self):
        loc, attrs, colls = text_file(built("golden", locale="ru_RU"))
        self.assertEqual(loc, "ru_RU")
        self.assertEqual((attrs["locale"], attrs["decimal-char"]), ('"ru_RU"', '","'))
        self.assertEqual(colls, {"LRU_RRU"})

    def test_day_first_dates_keep_ru_ru_in_an_en_us_book(self):
        root = built("dates")
        self.assertEqual((root.get("locale"), text_file(root)[0]), ("en_US", "ru_RU"))

    def test_month_first_dates_keep_en_us_in_a_ru_book(self):
        root = built("dates_us", locale="ru_RU")
        self.assertEqual((root.get("locale"), text_file(root)[0]), ("ru_RU", "en_US"))


class Numbers(unittest.TestCase):
    def test_render_in_the_book_being_built(self):
        self.assertEqual(formats.render(27_612_345, "currency_m"), "$27.6M")
        with formats.shown_in("ru_RU"):
            self.assertEqual(formats.render(27_612_345, "currency_m"), "$27,6M")
            self.assertEqual(formats.render(2742, "number"), "2 742")  # a no-break space groups
        self.assertEqual(formats.render(2742, "number"), "2,742")

    def test_parse_by_locale(self):
        self.assertEqual(parse_number("0.179", "en_US")[:2], (0.179, 0.001))
        self.assertEqual(parse_number("0.179")[0], 179.0)  # a guess without one: a thousands point
        self.assertEqual(parse_number("2,742", "en_US")[0], 2742.0)
        self.assertEqual(parse_number("1,234", "ru_RU")[:2], (1.234, 0.001))
        self.assertEqual(parse_number("1 234,5", "ru_RU")[0], 1234.5)
        self.assertEqual(parse_number("$27.6M", "en_US")[:3], (27.6, 0.1, "M"))
        self.assertIsNone(parse_number("1.234,5", "en_US"))
        self.assertIsNone(parse_number("1,234.5", "ru_RU"))

    def test_drawn_reads_by_the_book(self):
        """'$27,6M' is 27.6M only in ru_RU; in en_US it is not a number the book draws."""
        self.assertTrue(drawn.drawn(27_600_000, drawn.numbers(["$27.6M"], "en_US")))
        self.assertTrue(drawn.drawn(27_600_000, drawn.numbers(["$27,6M"], "ru_RU")))
        self.assertFalse(drawn.drawn(27_600_000, drawn.numbers(["$27,6M"], "en_US")))
        self.assertTrue(drawn.drawn(0.179, drawn.numbers(["0.179"], "en_US")))


class Outline(unittest.TestCase):
    def test_lang(self):
        for lang, want in [("en", "en_US"), ("en-GB", "en_US"), ("", "en_US"), ("ru", "ru_RU"), ("ru-RU", "ru_RU"),
                           ("RU", "ru_RU"), ("de", "en_US")]:
            self.assertEqual(html_outline.locale(lang), want, lang)

    def test_outline_carries_it(self):
        raw = {"title": "t", "page": [1, 1], "palette": {}, "fonts": {}, "headings": [], "numbers": [], "svgs": [],
               "canvases": [], "tables": [], "bar_groups": [], "lists": [], "images": [], "controls": [],
               "lang": "ru"}
        out = html_outline.build_outline(raw)
        self.assertEqual((out["lang"], out["locale"]), ("ru", "ru_RU"))
        self.assertEqual(json.loads(json.dumps(out))["locale"], "ru_RU")


if __name__ == "__main__":
    unittest.main()
