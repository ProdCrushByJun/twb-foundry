"""to-tableau-check (todo 5.1, decisions/038): the last gate of /to-tableau, one report and one exit code.

  python -m tbuilder to-tableau-check <spec.json> <page.html> [--case reconcile.json] [-o out.twbx] [--no-desktop]
                                      [--profile name]

Steps, each a row "step | OK/FAIL/WARN/SKIP | reason" (the rows and stages of regress, decisions/027):
  lint       design rules: error -> FAIL, warn -> WARN (each warn needs a reason in the report to the user)
  build      spec -> .twbx; the gate runs inside the build
  gate       the written book passes the gate
  desktop    the book opens cleanly in Tableau Desktop 2025.1 (decisions/022); only when everything before is clean
  drawn      every number of its KPIs, registries and tables is on screen, each dashboard opened (decisions/076):
             FAIL = a registry column drew nothing; WARN = a group unread (OCR) or not on screen; SKIP = could not run
  resave     Desktop saves a copy, nothing dropped or changed by meaning, every sheet opens (decisions/054, 199):
             FAIL = a difference or a sheet that does not open; SKIP = the save could not run
  reconcile every number of the HTML page is in the book or accepted with a reason (decisions/024); runs last, so what
             the book looks like is known first, and whatever Desktop said (decisions/179)

Verdict: OK (exit 0) = no FAIL and no SKIP; FAIL (exit 1) = a step failed, the book is deleted (it is not handed
out); INCOMPLETE (exit 2) = nothing failed but a step did not run (--no-desktop, no Chrome, no OCR): not ready to
hand out.
The Desktop queue (out/desktop-queue.md) is not managed here: whoever runs the check takes it.
Printed: each row that is not OK as soon as it is known, the verdict, the time of each step, the path of the picture.
All of it, with the reconcile report, is in <book dir>/<book>_check.log.

  python -m tbuilder to-tableau-preview <spec.json> [-o out.twbx] [--profile name]

A look at the book while its layout is being fixed (decisions/179): build, gate, desktop, drawn. No lint, no reconcile:
NOT an acceptance. The book goes to <name>_preview.twbx, never where to-tableau-check writes the book it hands out.
"""
import argparse
import sys
import time
from pathlib import Path

from . import design_lint, expected, spec as spec_mod, user_profile
from .regress import FAIL, OK, SKIP, WARN, Case, Row, build_rows, reconcile_check, table

VERDICT_EXIT = {"OK": 0, "FAIL": 1, "INCOMPLETE": 2}


def lint_row(name, spec_path):
    findings = design_lint.lint(spec_mod.load(spec_path), Path(spec_path).parent)
    errors = [f for f in findings if f.level == "error"]
    warns = [f for f in findings if f.level == "warn"]
    if errors:
        return Row(name, "lint", FAIL, "; ".join(f"{f.rule} {f.where}: {f.text}" for f in errors))
    return Row(name, "lint", WARN if warns else OK, "; ".join(f"{f.rule} {f.where}: {f.text}" for f in warns))


def desktop_row(name, book, check=None):
    from . import desktop_check as dc
    if check is None:
        if dc.find_tableau() is None:
            return Row(name, "desktop", FAIL, f"tableau.exe not found ({dc.TABLEAU_EXE}; set TABLEAU_EXE)")
        check = dc.check
    r = check(book)
    return Row(name, "desktop", OK if r.status == dc.OK else FAIL,
               f"{r.status} in {r.seconds} s" + (f": {r.message}" if r.status != dc.OK else ""), r.seconds)


def drawn_row(name, book, spec_path, check=None):
    """What Desktop drew (decisions/076); out/<book dir>/drawn_<name>/ keeps the pictures and drawn.json."""
    from . import drawn
    try:
        r = (check or drawn.check)(book, spec_path, Path(book).parent / f"drawn_{name}")
    except Exception as e:  # no Windows OCR, Desktop gone: the pictures were not read, not a defect of the book
        return Row(name, "drawn", SKIP, f"{type(e).__name__}: {e}")
    gs = r["groups"]
    status = FAIL if not r["ok"] else WARN if any(g["status"] in (drawn.UNREAD, drawn.UNCHECKED) for g in gs) else OK
    return Row(name, "drawn", status, drawn.summary(r))


def resave_row(name, book, check=None):
    """What an open does not show: Desktop's first save (decisions/199); out/<book dir>/resave_<name>/ keeps its files."""
    from . import desktop_check as dc, resave
    try:
        r = (check or resave.resave)(book, Path(book).parent / f"resave_{name}")
    except Exception as e:  # Desktop gone, no menu: the save did not run, not a defect of the book
        return Row(name, "resave", SKIP, f"{type(e).__name__}: {e}")
    status = OK if r.clean else FAIL if r.status == dc.OK else SKIP
    return Row(name, "resave", status, "; ".join(line.strip() for line in r.text().splitlines()))


def verdict(rows):
    if any(r.status == FAIL for r in rows):
        return "FAIL"
    return "INCOMPLETE" if any(r.status == SKIP for r in rows) else "OK"


class Steps:
    """The rows so far. Each is given to show as soon as it is known; the first row of a step gets the step's time."""

    def __init__(self, show=None):
        self.rows, self.show, self.started = [], show or (lambda row: None), time.perf_counter()

    def add(self, *rows):
        rows[0].seconds = time.perf_counter() - self.started
        for r in rows:
            self.rows.append(r)
            self.show(r)
        self.started = time.perf_counter()


def book_steps(steps, name, spec_path, out, desktop, check, drawn):
    """build, gate, desktop, drawn -> the book or None. Desktop only for a book clean so far."""
    book, built = build_rows(Case(name, spec_path), out.parent)
    steps.add(*built)
    if not desktop:
        steps.add(Row(name, "desktop", SKIP, "--no-desktop"))
    elif book is None or any(r.status == FAIL for r in steps.rows):
        steps.add(Row(name, "desktop", SKIP, "an earlier step failed"))
    else:
        steps.add(desktop_row(name, book, check))
        if drawn is not None or check is None:
            steps.add(drawn_row(name, book, spec_path, drawn) if steps.rows[-1].status == OK
                      else Row(name, "drawn", SKIP, "Desktop did not open the book cleanly"))
    return book


def book_path(spec_path, out):
    return Path(out or Path("out") / (Path(spec_path).stem + ".twbx"))


def run(spec_path, html, case_path=None, out=None, desktop=True, check=None, drawn=None, show=None, resave=None):
    """-> (rows, book or None, reconcile report or None). check: desktop_check.check, drawn: drawn.check, resave:
    resave.resave (stubs in tests; with a Desktop stub and no stub of its own the drawn or resave step is left out).
    show: called with each row when known."""
    spec_path = Path(spec_path)
    out = book_path(spec_path, out)
    out.parent.mkdir(parents=True, exist_ok=True)
    name = out.stem
    steps = Steps(show)
    with expected.cached():  # lint, build, drawn and reconcile ask for the same numbers (decisions/179)
        try:
            steps.add(lint_row(name, spec_path))
        except Exception as e:  # unreadable or schema-invalid spec: the build below says the same, with its own row
            steps.add(Row(name, "lint", FAIL, f"{type(e).__name__}: {e}"))
        book = book_steps(steps, name, spec_path, out, desktop, check, drawn)
        if desktop and (resave is not None or check is None):
            opened = any(r.stage == "desktop" and r.status == OK for r in steps.rows)
            steps.add(resave_row(name, book, resave) if opened and not any(r.status == FAIL for r in steps.rows)
                      else Row(name, "resave", SKIP, "an earlier step failed"))
        rec_row, rec = reconcile_check(name, spec_path, html, case_path)
        steps.add(rec_row)
    if book and verdict(steps.rows) == "FAIL":
        book.unlink(missing_ok=True)  # zero errors: a book that failed a step is not handed out
        book = None
    return steps.rows, book, rec


def preview_path(spec_path, out):
    out = book_path(spec_path, out)
    return out.with_name(out.stem + "_preview.twbx")


def preview(spec_path, out=None, check=None, drawn=None, show=None):
    """-> (rows, book or None): a look at the book, no lint and no reconcile; not an acceptance (decisions/179)."""
    spec_path = Path(spec_path)
    out = preview_path(spec_path, out)
    out.parent.mkdir(parents=True, exist_ok=True)
    steps = Steps(show)
    with expected.cached():
        book = book_steps(steps, out.stem, spec_path, out, True, check, drawn)
    if book and verdict(steps.rows) == "FAIL":
        book.unlink(missing_ok=True)
        book = None
    return steps.rows, book


def pictures(rows, spec_path, out):
    """The dashboards' pictures of this run: none when drawn did not run."""
    if not any(r.stage == "drawn" and r.status != SKIP for r in rows):
        return []
    from . import drawn
    spec = spec_mod.load(spec_path)
    found = (out.parent / f"drawn_{out.stem}" / f"{drawn._safe(d['name'])}.png"
             for d in spec.get("dashboards") or [spec["dashboard"]])
    return [p for p in found if p.is_file()]


def times(rows):
    """'lint 2 s, build 9 s, ...' of the steps that ran; build holds the gate."""
    return ", ".join(f"{r.stage} {r.seconds:.0f} s" for r in rows if r.stage != "gate" and r.status != SKIP) \
        + f"; total {sum(r.seconds for r in rows):.0f} s"


class Log:
    """<book dir>/<book>_check.log, written as the steps end; the rows that are not OK also go to the screen."""

    def __init__(self, out):
        out.parent.mkdir(parents=True, exist_ok=True)
        self.path = out.with_name(out.stem + "_check.log")
        self.file = self.path.open("w", encoding="utf-8")

    def row(self, r):
        self.line(f"{r.stage} {r.status} {r.seconds:.1f} s {r.reason}")
        if r.status != OK:
            print(f"{r.stage} {r.status}: {r.reason}", flush=True)

    def line(self, text):
        self.file.write(text + "\n")
        self.file.flush()

    def finish(self, rows, spec_path, out, last):
        """The end of the screen and of the log: the verdict line, the times, the picture, the log's path."""
        for line in [last, "steps: " + times(rows)] + [f"picture: {p}" for p in pictures(rows, spec_path, out)]:
            print(line)
            self.line(line)
        self.file.close()
        print(f"full log: {self.path}")


def main(argv=None):
    from .reconcile import report_text, summary_line
    ap = argparse.ArgumentParser(prog="tbuilder to-tableau-check", description=__doc__.split("\n")[0])
    ap.add_argument("spec", type=Path)
    ap.add_argument("html", type=Path)
    ap.add_argument("--case", type=Path, help="reconcile case: filter state of the page and accepted numbers")
    ap.add_argument("-o", "--out", type=Path, help="the book (default out/<spec>.twbx)")
    ap.add_argument("--no-desktop", action="store_true", help="skip Tableau Desktop: verdict INCOMPLETE at best")
    ap.add_argument("--profile", help="the user profile (decisions/193)")
    a = ap.parse_args(argv)
    user_profile.forced = a.profile
    out = book_path(a.spec, a.out)
    log = Log(out)
    rows, book, rec = run(a.spec, a.html, a.case, out, desktop=not a.no_desktop, show=log.row)
    log.line("\n" + table(rows))
    if rec:
        log.line("\nreconcile:\n" + report_text(rec))
        print("reconcile: " + summary_line(rec))
    v = verdict(rows)
    log.finish(rows, a.spec, out, f"{v}: " + (str(book) if v == "OK" else "the book is deleted, fix the spec"
                                              if v == "FAIL" else f"{book} is not ready to hand out (a step did not run)"))
    return VERDICT_EXIT[v]


def preview_main(argv=None):
    ap = argparse.ArgumentParser(prog="tbuilder to-tableau-preview", description="A look at the book, not an acceptance.")
    ap.add_argument("spec", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="the book of the check; the preview goes next to it, <name>_preview")
    ap.add_argument("--profile", help="the user profile (decisions/193)")
    a = ap.parse_args(argv)
    user_profile.forced = a.profile
    log = Log(preview_path(a.spec, a.out))
    rows, book = preview(a.spec, a.out, show=log.row)
    log.line("\n" + table(rows))
    v = verdict(rows)
    log.finish(rows, a.spec, preview_path(a.spec, a.out),
               f"PREVIEW {v}, NOT AN ACCEPTANCE: no lint, no reconcile. {book if book else 'The book is deleted.'} "
               "Hand out only a book that passed to-tableau-check.")
    return VERDICT_EXIT[v]
