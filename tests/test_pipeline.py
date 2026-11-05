"""to-tableau-check (decisions/038): lint + build/gate + reconcile + Desktop, one verdict. Desktop is a stub here."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tbuilder import desktop_check as dc, drawn, gate, html_outline, pipeline, resave
from test_roundtrip import ROOT


try:
    html_outline._chrome()
    HAVE_CHROME = True
except RuntimeError:
    HAVE_CHROME = False


def desktop(status=dc.OK):
    calls = []

    def check(book):
        calls.append(Path(book))
        return dc.Result(str(book), status, "" if status == dc.OK else "an error dialog", 1.0)
    return check, calls


def statuses(rows):
    return {r.stage: r.status for r in rows}


def resaved(left=(), status=dc.OK, sheets=()):
    """A stub of resave.resave: left = the differences by meaning, sheets = [(sheet, dc.Result)]."""
    def run(book, out_dir):
        report = resave.Report("a.twbx", "a.resaved.twbx", list(left), list(left)) if status == dc.OK else None
        return resave.Resave(str(book), status, "" if status == dc.OK else "no Save As", report=report,
                             sheets=list(sheets))
    return run




class Order(unittest.TestCase):
    """The steps without Chrome and Desktop (decisions/179): stubs that note when they run."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.spec, self.order = self.tmp / "s.json", []
        self.spec.write_text("{}", encoding="utf-8")
        self.seen = {"ok": True, "dashboards": [], "groups": []}

    def patches(self, build=True, rec=pipeline.OK, lint=pipeline.OK):
        def build_rows(case, out_dir):
            self.order.append("build")
            book = out_dir / f"{case.name}.twbx"
            if not build:
                return None, [pipeline.Row(case.name, "build", "FAIL", "boom"), pipeline.Row(case.name, "gate", "SKIP")]
            book.write_bytes(b"book")
            return book, [pipeline.Row(case.name, "build", "OK"), pipeline.Row(case.name, "gate", "OK")]

        def reconcile(name, *a):
            self.order.append("reconcile")
            return pipeline.Row(name, "reconcile", rec, "the numbers"), None
        return (mock.patch.object(pipeline, "build_rows", build_rows), mock.patch.object(pipeline, "reconcile_check", reconcile),
                mock.patch.object(pipeline, "lint_row", lambda name, p: pipeline.Row(name, "lint", lint)),
                mock.patch.object(pipeline, "pictures", lambda *a: []))

    def desktop(self, status=dc.OK):
        def check(book):
            self.order.append("desktop")
            return dc.Result(str(book), status, "" if status == dc.OK else "an error dialog", 1.0)
        return check

    def drawn(self, *a):
        self.order.append("drawn")
        return self.seen

    def run_(self, desktop=None, **kw):
        a, b, c, d = self.patches(**kw)
        with a, b, c, d:
            return pipeline.run(self.spec, "p.html", None, self.tmp / "b.twbx", check=desktop or self.desktop(), drawn=self.drawn)

    def test_view_first_reconcile_last(self):
        rows, book, _ = self.run_()
        self.assertEqual(self.order, ["build", "desktop", "drawn", "reconcile"])
        self.assertEqual([r.stage for r in rows], ["lint", "build", "gate", "desktop", "drawn", "reconcile"])
        self.assertEqual(pipeline.verdict(rows), "OK")
        self.assertTrue(book.is_file())

    def test_reconcile_runs_after_a_desktop_failure(self):
        rows, book, _ = self.run_(desktop=self.desktop(dc.ERROR))
        self.assertEqual(self.order, ["build", "desktop", "reconcile"])
        self.assertEqual(statuses(rows)["drawn"], "SKIP")
        self.assertEqual(pipeline.verdict(rows), "FAIL")
        self.assertIsNone(book)
        self.assertFalse((self.tmp / "b.twbx").exists())

    def test_book_of_a_failed_reconcile_exists_for_the_look_then_goes(self):
        existed = []
        self.drawn = lambda *a: existed.append((self.tmp / "b.twbx").is_file()) or self.seen
        rows, book, _ = self.run_(rec=pipeline.FAIL)
        self.assertEqual(existed, [True])
        self.assertEqual(pipeline.verdict(rows), "FAIL")
        self.assertIsNone(book)
        self.assertFalse((self.tmp / "b.twbx").exists())

    def test_no_desktop_on_a_lint_failure_or_without_a_book(self):
        rows, _, _ = self.run_(lint=pipeline.FAIL)
        self.assertEqual(self.order, ["build", "reconcile"])
        self.assertEqual(statuses(rows)["desktop"], "SKIP")
        self.order.clear()
        rows, book, _ = self.run_(build=False)
        self.assertEqual(self.order, ["build", "reconcile"])
        self.assertIsNone(book)

    def test_rows_are_shown_as_they_come(self):
        shown = []
        a, b, c, d = self.patches()
        with a, b, c, d:
            pipeline.run(self.spec, "p.html", None, self.tmp / "b.twbx", check=self.desktop(), drawn=self.drawn,
                         show=lambda r: shown.append((r.stage, list(self.order))))
        self.assertEqual(dict(shown)["desktop"], ["build", "desktop"])  # before reconcile ran

    def preview(self, **kw):
        a, b, c, d = self.patches()
        with a, b, c, d:
            return pipeline.preview(self.spec, self.tmp / "b.twbx", **kw)

    def test_preview_has_no_reconcile_and_no_lint(self):
        rows, book = self.preview(check=self.desktop(), drawn=self.drawn)
        self.assertEqual(self.order, ["build", "desktop", "drawn"])
        self.assertEqual([r.stage for r in rows], ["build", "gate", "desktop", "drawn"])
        self.assertEqual(book.name, "b_preview.twbx")
        self.assertFalse((self.tmp / "b.twbx").exists())  # the place of the book that is handed out stays untouched

    def test_preview_of_a_broken_book_deletes_it(self):
        rows, book = self.preview(check=self.desktop(dc.ERROR), drawn=self.drawn)
        self.assertEqual(pipeline.verdict(rows), "FAIL")
        self.assertIsNone(book)
        self.assertFalse((self.tmp / "b_preview.twbx").exists())

    def test_preview_says_it_is_not_an_acceptance(self):
        a, b, c, d = self.patches()
        with a, b, c, d, mock.patch.object(dc, "find_tableau", return_value="tableau.exe"), \
                mock.patch.object(dc, "check", self.desktop()), mock.patch.object(drawn, "check", self.drawn), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = pipeline.preview_main([str(self.spec), "-o", str(self.tmp / "b.twbx")])
        self.assertEqual(code, 0)
        self.assertIn("NOT AN ACCEPTANCE", out.getvalue())
        self.assertIn("to-tableau-check", out.getvalue())

    def test_check_prints_problems_only_and_logs_everything(self):
        a, b, c, d = self.patches(rec=pipeline.FAIL)
        with a, b, c, d, mock.patch.object(dc, "find_tableau", return_value="tableau.exe"), \
                mock.patch.object(dc, "check", self.desktop()), mock.patch.object(drawn, "check", self.drawn), \
                mock.patch.object(resave, "resave", resaved()), contextlib.redirect_stdout(io.StringIO()) as out:
            code = pipeline.main([str(self.spec), "p.html", "-o", str(self.tmp / "b.twbx")])
        self.assertEqual(code, 1)
        text = out.getvalue()
        self.assertIn("reconcile FAIL: the numbers", text)
        self.assertIn("FAIL: the book is deleted", text)
        self.assertNotIn("desktop OK", text)
        self.assertIn("b_check.log", text)
        log = (self.tmp / "b_check.log").read_text(encoding="utf-8")
        self.assertIn("desktop OK", log)
        self.assertIn("reconcile FAIL", log)


class ResaveStep(unittest.TestCase):
    """decisions/199: what an open does not show stops the book."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.spec = self.tmp / "s.json"
        self.spec.write_text("{}", encoding="utf-8")

    def run_(self, opened=dc.OK, **kw):
        def build_rows(case, out_dir):
            book = out_dir / f"{case.name}.twbx"
            book.write_bytes(b"book")
            return book, [pipeline.Row(case.name, "build", "OK"), pipeline.Row(case.name, "gate", "OK")]
        check, _ = desktop(opened)
        with mock.patch.object(pipeline, "build_rows", build_rows), \
                mock.patch.object(pipeline, "lint_row", lambda n, s: pipeline.Row(n, "lint", "OK")), \
                mock.patch.object(pipeline, "reconcile_check", lambda n, *a: (pipeline.Row(n, "reconcile", "OK"), None)):
            return pipeline.run(self.spec, "p.html", None, self.tmp / "b.twbx", check=check, **kw)

    def test_clean_passes(self):
        rows, book, _ = self.run_(resave=resaved())
        self.assertEqual(statuses(rows)["resave"], "OK")
        self.assertIn("nothing dropped", next(r.reason for r in rows if r.stage == "resave"))
        self.assertTrue(book.is_file())

    def test_a_difference_by_meaning_deletes_the_book(self):
        item = resave.Item(resave.DROPPED, "/workbook/worksheets/worksheet[name=Bar]/filter-group")
        rows, book, _ = self.run_(resave=resaved(left=[item]))
        self.assertEqual(statuses(rows)["resave"], "FAIL")
        self.assertIn("filter-group", next(r.reason for r in rows if r.stage == "resave"))
        self.assertIsNone(book)

    def test_a_sheet_that_does_not_open_deletes_the_book(self):
        bad = dc.Result("copy.twbx", dc.ERROR, "an error dialog", 1.0)
        rows, book, _ = self.run_(resave=resaved(sheets=[("Trend", bad)]))
        self.assertEqual(statuses(rows)["resave"], "FAIL")
        self.assertIsNone(book)

    def test_a_save_that_could_not_run_is_incomplete(self):
        rows, book, _ = self.run_(resave=resaved(status=dc.ERROR))
        self.assertEqual(statuses(rows)["resave"], "SKIP")
        self.assertEqual(pipeline.verdict(rows), "INCOMPLETE")
        self.assertTrue(book.is_file())

        def gone(*a):
            raise RuntimeError("Desktop gone")
        rows, _, _ = self.run_(resave=gone)
        self.assertEqual(statuses(rows)["resave"], "SKIP")

    def test_no_save_of_a_book_that_did_not_open(self):
        calls = []
        rows, book, _ = self.run_(opened=dc.ERROR, resave=lambda *a: calls.append(a))
        self.assertEqual(calls, [])
        self.assertEqual(statuses(rows)["resave"], "SKIP")
        self.assertIsNone(book)

    def test_preview_does_not_save(self):
        def build_rows(case, out_dir):
            book = out_dir / f"{case.name}.twbx"
            book.write_bytes(b"book")
            return book, [pipeline.Row(case.name, "build", "OK"), pipeline.Row(case.name, "gate", "OK")]
        check, _ = desktop()
        seen = {"ok": True, "dashboards": [], "groups": []}
        with mock.patch.object(pipeline, "build_rows", build_rows):
            rows, _ = pipeline.preview(self.spec, self.tmp / "b.twbx", check=check, drawn=lambda *a: seen)
        self.assertNotIn("resave", statuses(rows))


class Verdict(unittest.TestCase):
    def test_verdict(self):
        R = pipeline.Row
        self.assertEqual(pipeline.verdict([R("x", "lint", "WARN"), R("x", "desktop", "OK")]), "OK")
        self.assertEqual(pipeline.verdict([R("x", "lint", "OK"), R("x", "desktop", "SKIP")]), "INCOMPLETE")
        self.assertEqual(pipeline.verdict([R("x", "build", "FAIL"), R("x", "desktop", "SKIP")]), "FAIL")


if __name__ == "__main__":
    unittest.main()
