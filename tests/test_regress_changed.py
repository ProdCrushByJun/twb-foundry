"""regress --desktop --changed (decisions/113): the Desktop cache, with the Desktop check replaced by a fake."""
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tbuilder import desktop_check as dc
from tbuilder import regress
from tbuilder.build import build_file
from test_roundtrip import ROOT


def books_only(rows):
    return {r.case: r for r in rows if not r.case.startswith("desktop-mutant/")}


def edited(src, dst, fn):
    """A copy of the book src with fn applied to the bytes of its .twb."""
    with zipfile.ZipFile(src) as z, zipfile.ZipFile(dst, "w") as o:
        for n in z.namelist():
            o.writestr(n, fn(z.read(n)) if n.endswith(".twb") else z.read(n))
    return dst


class DesktopCache(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.book = self.dir / "a.twbx"
        build_file(ROOT / "specs" / "golden.json", self.book)
        self.opened = []
        self.status = dc.OK
        self.exe = self.dir / "tableau.exe"

    def fake_check(self, path, **_):
        if Path(path).name.startswith(("a", "m", "n")):  # the books of the tests, not the Desktop mutants
            self.opened.append(Path(path).name)
        return dc.Result(path=str(path), status=self.status, seconds=1.0)

    def desktop(self, books, changed, exe=None):
        broken = {n: self.dir / f"{n}.twbx" for n in regress.DESKTOP_MUTANTS}
        tm = mock.Mock(make_broken=mock.Mock(return_value=broken))
        with mock.patch.object(dc, "find_tableau", return_value=exe or self.exe), \
                mock.patch.object(dc, "check", self.fake_check), \
                mock.patch.object(regress, "_tests_module", return_value=tm):
            return books_only(regress.desktop_rows(books, self.dir, changed))

    def test_two_builds_of_one_spec_hash_alike(self):
        other = self.dir / "b.twbx"
        build_file(ROOT / "specs" / "golden.json", other)
        self.assertEqual(regress.book_hash(self.book), regress.book_hash(other))

    def test_changed_content_changes_the_hash(self):
        other = edited(self.book, self.dir / "b.twbx", lambda b: b + b"<!-- x -->")
        self.assertNotEqual(regress.book_hash(self.book), regress.book_hash(other))

    def test_full_run_opens_everything_and_fills_the_cache(self):
        rows = self.desktop([("c", self.book)], changed=False)
        self.assertEqual(self.opened.count("a.twbx"), 1)
        self.assertEqual(rows["c"].status, regress.OK)
        cache = json.loads((self.dir / "desktop-cache.json").read_text(encoding="utf-8"))
        self.assertEqual(cache["books"], {"c": regress.book_hash(self.book)})

    def test_changed_skips_an_unchanged_ok_book(self):
        self.desktop([("c", self.book)], changed=False)
        self.opened.clear()
        rows = self.desktop([("c", self.book)], changed=True)
        self.assertNotIn("a.twbx", self.opened)
        self.assertEqual(rows["c"].status, regress.OK)
        self.assertTrue(rows["c"].reason.startswith("cached"))

    def test_changed_opens_new_and_modified_books(self):
        self.desktop([("c", self.book)], changed=False)
        self.opened.clear()
        new = self.dir / "n.twbx"
        shutil.copy(self.book, new)
        mod = edited(self.book, self.dir / "m.twbx", lambda b: b + b"<!-- x -->")
        rows = self.desktop([("c", mod), ("new", new)], changed=True)
        self.assertEqual(sorted(self.opened), ["m.twbx", "n.twbx"])
        self.assertFalse(any(r.reason.startswith("cached") for r in rows.values()))

    def test_failed_book_is_not_cached_and_reopens(self):
        self.status = dc.ERROR
        rows = self.desktop([("c", self.book)], changed=False)
        self.assertEqual(rows["c"].status, regress.FAIL)
        self.status = dc.OK
        self.opened.clear()
        self.desktop([("c", self.book)], changed=True)
        self.assertEqual(self.opened.count("a.twbx"), 1)

    def test_other_tableau_exe_drops_the_cache(self):
        self.desktop([("c", self.book)], changed=False)
        self.opened.clear()
        self.desktop([("c", self.book)], changed=True, exe=self.dir / "other" / "tableau.exe")
        self.assertEqual(self.opened.count("a.twbx"), 1)

    def test_unreadable_cache_is_an_empty_cache(self):
        (self.dir / "desktop-cache.json").write_text("{not json", encoding="utf-8")
        self.desktop([("c", self.book)], changed=True)
        self.assertEqual(self.opened.count("a.twbx"), 1)


if __name__ == "__main__":
    unittest.main()
