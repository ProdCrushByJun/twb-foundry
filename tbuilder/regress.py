"""Regression suite (todo 4.4, decisions/027): everything that proves "zero errors", in one run.

  python -m tbuilder regress [--desktop [--changed]]

Stages, each a row "case | stage | OK/FAIL/WARN/SKIP | reason" in the report:
  unit      all unit tests (tests/), one FAIL row per failing test
  mutation  every mutation test (gate: classes GateCatches* / GateBlocks*, golden numbers: ExpectedCatches* in
            tests/) must pass = the break is caught
  lint      design_lint per spec: error -> FAIL (unless in LINT_KNOWN), warn -> WARN
  build     each spec of specs/ and acceptance/*/ builds (the build runs the gate itself)
  gate      the built book and each golden .twbx pass the gate
  roundtrip golden/golden_<X>_2025_1 vs its spec, normalized as in tests/test_roundtrip.py
  expected  acceptance/<case>/expected.json: control numbers vs expected.compute for each spec of the case;
            golden/expected/<golden>.json (pandas, decisions/052): every number vs expected.compute of the golden's
            spec, the data packaged in the golden = the data they were computed from
  reconcile acceptance/<case>/reconcile.json: every number of the case's HTML page in the book (decisions/024)
  desktop   --desktop: every built book opens in Desktop (OK), the Desktop mutants are refused (decisions/022);
            --changed: only the books that differ from the last OK Desktop run (decisions/113)

Cases come from the folders: a new golden, spec or acceptance folder is picked up without code changes.
The report also goes to out/regress/report.json. Exit code 0 = no FAIL.
"""
import argparse
import datetime as dt
import importlib
import io
import json
import hashlib
import os
import re
import sys
import time
import unittest
from dataclasses import asdict, dataclass
from pathlib import Path

from . import design_lint, expected, gate, spec as spec_mod, user_profile
from .build import build_file

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"  # the round-trip normalizer and the Desktop mutants live with the tests, one copy each

OK, FAIL, WARN, SKIP = "OK", "FAIL", "WARN", "SKIP"
GOLDEN_NAME = re.compile(r"^golden(?:_(?P<name>[^.]+?))?_2025_1$")  # not a mangled Save As name with a dot
MUTATION_CLASSES = ("GateCatches", "GateBlocks", "ExpectedCatches")  # gate; golden numbers (decisions/052)
# Lint errors that are there on purpose: specs that pin a golden or a test are generator fixtures, and a fixture is
# not edited for house style (decisions/023: the design pass goes to <name>_designed.json). (spec, rule) -> why.
LINT_KNOWN = {(f"specs/{n}.json", "T1"): "generator fixture from before dashboard headers (decisions/012)"
              for n in ("calcs", "calcs_v2", "charts", "declutter", "excel", "fixture_sales", "format", "golden", "hr",
                        "lods", "lods_view", "tablecalcs", "tablecalc_funcs", "tablecalc_v2", "params_v2")}
LINT_KNOWN[("specs/filters_cards_panel.json", "T1")] = "generator fixture: list cards stand in the right panel, " \
                                                       "which a dashboard without title has (decisions/162)"
# --desktop: broken books of tests/test_desktop_check.make_broken and the verdict Desktop must give. Not the crash
# mutant (each crash writes a ~300 MB dump) nor the dashboard one (a known limit: Desktop opens it).
DESKTOP_MUTANTS = {"dates_no_iso8601": "ERROR", "format_no_sorttagcleanup": "ERROR", "corrupt_zip": "ERROR"}
# Control numbers of each golden, computed with pandas from its data by golden/expected/make_expected.py
# (decisions/052). A golden without a file FAILs unless it is listed here with the reason (then SKIP).
GOLDEN_EXPECTED = Path("golden") / "expected"
GOLDEN_NO_EXPECTED = {}


@dataclass
class Row:
    case: str
    stage: str
    status: str
    reason: str = ""
    seconds: float = 0.0


@dataclass
class Case:
    name: str  # path of the spec without .json, relative to the root: specs/golden, acceptance/x/spec_designed
    spec: Path
    golden: Path = None  # .twb (or .twbx) the spec must rebuild 1:1
    expected: dict = None  # acceptance: control numbers of this spec ({} = the case has none for it)


def _tests_module(name):
    if str(TESTS) not in sys.path:
        sys.path.insert(0, str(TESTS))
    return importlib.import_module(name)


def _rel(root, p):
    return p.relative_to(root).as_posix()


# ---- discovery ---------------------------------------------------------------------------------------------------
def discover(root=ROOT):
    """(cases, rows): a case per spec of specs/ and acceptance/*/; rows for what does not pair up."""
    root = Path(root)
    cases, rows = {}, []
    for p in sorted((root / "specs").glob("*.json")):
        cases[p] = Case(_rel(root, p)[:-5], p)
    for d in sorted(x for x in (root / "acceptance").glob("*") if x.is_dir()):
        specs = sorted(d.glob("spec*.json"))
        if not specs:
            if (d / "NO_SPEC").is_file():  # built outside the generator (decisions/145): the file says why
                rows.append(Row(_rel(root, d), "build", SKIP, (d / "NO_SPEC").read_text(encoding="utf-8").strip()))
                continue
            rows.append(Row(_rel(root, d), "build", FAIL, "acceptance case without spec*.json"))
            continue
        exp_path, exp = d / "expected.json", {}
        if exp_path.is_file():
            try:
                exp = json.loads(exp_path.read_text(encoding="utf-8"))
            except ValueError as e:
                rows.append(Row(_rel(root, exp_path), "expected", FAIL, f"unreadable: {e}"))
        for p in specs:
            cases[p] = Case(_rel(root, p)[:-5], p, expected=exp.get(p.name, {}))
    goldens = {}
    for p in sorted((root / "golden").glob("golden*_2025_1.twb*")):
        goldens.setdefault(p.name.rsplit(".", 1)[0], []).append(p)
    for stem, files in goldens.items():
        m = GOLDEN_NAME.match(stem)
        if not m:
            rows.append(Row(f"golden/{stem}", "roundtrip", WARN, "not a golden name, skipped"))
            continue
        name = m.group("name")
        # golden_2025_1 <- specs/golden.json; golden_<x> <- specs/<x>.json or acceptance/<x with - for _>/spec.json
        candidates = [root / "specs" / f"{name or 'golden'}.json"]
        if name:
            candidates.append(root / "acceptance" / name.replace("_", "-") / "spec.json")
        spec = next((c for c in candidates if c in cases), None)
        if spec is None:
            rows.append(Row(f"golden/{stem}", "roundtrip", FAIL,
                            f"no spec for this golden (looked for {', '.join(_rel(root, c) for c in candidates)})"))
            continue
        cases[spec].golden = min(files, key=lambda f: f.suffix != ".twb")  # the readable .twb if there is one
    return list(cases.values()), rows


# ---- stages ------------------------------------------------------------------------------------------------------
class _Collect(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.outcomes = []  # (test id, test class, status, reason)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes.append((test.id(), type(test).__name__, OK, ""))

    def _bad(self, test, err, kind, cls=None):
        self.outcomes.append((test.id(), cls or type(test).__name__, FAIL,
                              f"{kind}: {self._exc_info_to_string(err, test).strip()}"))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._bad(test, err, "failure")

    def addError(self, test, err):
        super().addError(test, err)
        self._bad(test, err, "error")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = "failure" if issubclass(err[0], test.failureException) else "error"
            self._bad(subtest, err, kind, type(test).__name__)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes.append((test.id(), type(test).__name__, SKIP, reason))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.outcomes.append((test.id(), type(test).__name__, FAIL, "unexpected success"))


def run_tests(tests_dir=TESTS):
    """All unit tests of tests_dir, in this process -> [(test id, test class, status, reason)]."""
    suite = unittest.defaultTestLoader.discover(str(tests_dir), top_level_dir=str(tests_dir))
    runner = unittest.TextTestRunner(stream=io.StringIO(), resultclass=_Collect, verbosity=0)
    return runner.run(suite).outcomes


def _short(reason, limit=300):
    lines = [x for x in reason.splitlines() if x.strip()]
    last = lines[-1].strip() if lines else ""
    return last if len(last) <= limit else last[:limit] + "..."


def unit_rows(outcomes, seconds=0.0):
    bad = [o for o in outcomes if o[2] == FAIL]
    skipped = sum(o[2] == SKIP for o in outcomes)
    rows = [Row("unit", "unit", FAIL if bad or not outcomes else OK,
                f"{len(outcomes)} tests, {len(bad)} failed, {skipped} skipped" if outcomes else "no tests found",
                round(seconds, 1))]
    rows += [Row(f"unit/{tid}", "unit", FAIL, _short(r)) for tid, _, _, r in bad]
    return rows


def mutation_rows(outcomes):
    """A gate mutation test passes = the gate names the break; a failing one = a break that slips through.

    The classes also hold the controls (the clean book passes), so an OK row says "passes", not "caught"."""
    muts = [o for o in outcomes if o[1].startswith(MUTATION_CLASSES)]
    if not muts:
        return [Row("mutation", "mutation", FAIL, f"no gate mutation tests ({'/'.join(MUTATION_CLASSES)}*)")]
    return [Row(f"mutation/{tid}", "mutation", st, "passes" if st == OK else _short(r)) for tid, _, st, r in muts]


def lint_row(case, root):
    findings = design_lint.lint(spec_mod.load(case.spec), case.spec.parent)
    rel = _rel(root, case.spec)
    errors = [f for f in findings if f.level == "error" and (rel, f.rule) not in LINT_KNOWN]
    known = [f for f in findings if f.level == "error" and (rel, f.rule) in LINT_KNOWN]
    warns = [f for f in findings if f.level == "warn"]
    stale = [r for (s, r) in LINT_KNOWN if s == rel and r not in {f.rule for f in known}]
    if errors:
        return Row(case.name, "lint", FAIL, "; ".join(f"{f.rule} {f.where}: {f.text}" for f in errors))
    notes = [f"known {f.rule} ({LINT_KNOWN[(rel, f.rule)]})" for f in known]
    notes += [f"{f.rule} {f.where}: {f.text}" for f in warns]
    notes += [f"LINT_KNOWN entry {r} no longer fires: drop it" for r in stale]
    return Row(case.name, "lint", WARN if notes else OK, "; ".join(notes))


def build_rows(case, out_dir):
    """build + gate rows; the path of the book, or None when it was not written."""
    out = out_dir / f"{case.name.replace('/', '_')}.twbx"
    out.unlink(missing_ok=True)
    try:
        build_file(case.spec, out)
    except gate.GateError as e:
        return None, [Row(case.name, "build", FAIL, "blocked by the gate"),
                      Row(case.name, "gate", FAIL, "; ".join(map(str, e.issues)))]
    except spec_mod.SpecError as e:  # not a spec yet, or no data: no book to try
        return None, [Row(case.name, "build", FAIL, f"{type(e).__name__}: {e}"),
                      Row(case.name, "gate", SKIP, "no book")]
    except Exception as e:  # data errors, generator bugs: all are a FAIL of this case
        from . import trial
        found = trial.problems(spec_mod.load(case.spec), case.spec.parent)  # all of them at once (decisions/198)
        return None, [Row(case.name, "build", FAIL, f"{type(e).__name__}: " + ("; ".join(found) or str(e))),
                      Row(case.name, "gate", SKIP, "no book")]
    issues = gate.run(out, spec_mod.load(case.spec))  # the book's accent (decisions/137)
    return out, [Row(case.name, "build", OK, out.name),
                 Row(case.name, "gate", FAIL if issues else OK, "; ".join(map(str, issues)))]


def golden_gate_row(root, golden):
    twbx = golden.with_suffix(".twbx")
    if not twbx.is_file():
        return Row(f"golden/{golden.stem}", "gate", FAIL, "no .twbx next to the golden")
    issues = gate.run(twbx)
    return Row(f"golden/{golden.stem}", "gate", FAIL if issues else OK, "; ".join(map(str, issues)))


def roundtrip_row(case, book, root):
    import difflib
    import xml.etree.ElementTree as ET
    rt = _tests_module("test_roundtrip")
    if book is None:
        return Row(case.name, "roundtrip", SKIP, "no book")
    g = case.golden
    want = rt.read_twbx(g)[0] if g.suffix == ".twbx" else ET.parse(g).getroot()
    a, b = rt.canon(rt.normalize(want)), rt.canon(rt.normalize(rt.read_twbx(book)[0]))
    if a == b:
        return Row(case.name, "roundtrip", OK, f"= {_rel(root, g)}")
    diff = [x for x in difflib.unified_diff(a, b, "golden", "generated", lineterm="", n=0)
            if x[:1] in "+-" and x[:3] not in ("---", "+++")]
    return Row(case.name, "roundtrip", FAIL, f"!= {_rel(root, g)}, {len(diff)} lines differ, first: "
                                             f"{' | '.join(x.strip() for x in diff[:2])}")


def _tolerance(want):
    """Half a unit of the last digit written: 47 -> 0.5, 7.7 -> 0.05."""
    if isinstance(want, int):
        return 0.5
    digits = repr(want).split(".")[1] if "." in repr(want) else ""
    return 0.5 * 10 ** -len(digits) + 1e-9


def compare(want, got, where=""):
    """Mismatches of the control numbers `want` in `got` (expected.compute's shape); only the keys of want count.

    A key absent from got sums the values under "<key> | ..." (the total of a stacked bar)."""
    out = []
    for k, w in want.items():
        if k.startswith("_"):  # _source and other notes
            continue
        at = f"{where}{k}"
        if isinstance(got, dict) and k in got:
            g = got[k]
        else:
            parts = [v for gk, v in got.items() if gk.startswith(f"{k} | ")] if isinstance(got, dict) else []
            if not parts or not all(isinstance(v, (int, float)) for v in parts):
                out.append(f"{at}: not in the computed numbers")
                continue
            g = sum(parts)
        if isinstance(w, dict):
            if isinstance(g, dict):
                out += compare(w, g, f"{at} / ")
            else:
                out.append(f"{at}: {g!r}, expected a group")
        elif w is None or isinstance(w, str):  # an empty mark (the first of a difference), a text tile
            if g != w:
                out.append(f"{at}: {g!r} != {w!r}")
        elif not isinstance(g, (int, float)) or abs(g - w) > _tolerance(w):
            out.append(f"{at}: {g!r} != {w!r}")
    return out


def expected_row(case):
    if not case.expected:
        return Row(case.name, "expected", FAIL, f"no control numbers for {case.spec.name} in expected.json")
    spec = spec_mod.load(case.spec)
    got = expected.compute(spec, expected.data_path(spec, case.spec.parent))  # by source (decisions/083)
    bad = compare(case.expected, got)
    n = sum(len(v) for k, v in case.expected.items() if not k.startswith("_") and isinstance(v, dict))
    return Row(case.name, "expected", FAIL if bad else OK, "; ".join(bad) if bad else f"{n} numbers match")


def _leaves(d):
    return sum(_leaves(v) if isinstance(v, dict) else 1 for k, v in d.items() if not k.startswith("_"))


def _packaged_data(twbx, data):
    """The golden's copy of its data file vs the file the numbers were computed from: [mismatch] or []. Text
    compares line by line (Desktop rewrites the line ends); a package without the file is the gate's FAIL."""
    import zipfile
    with zipfile.ZipFile(twbx) as z:
        member = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == data.name), None)
        if member is None:
            return []
        packed, source = z.read(member), data.read_bytes()
    if data.suffix.lower() == ".csv":
        packed, source = packed.splitlines(), source.splitlines()
    return [] if packed == source else [f"{member} in the golden != {data.name}: the numbers are not the book's"]


def golden_expected_row(case, root):
    """golden/expected/<golden>.json (pandas over the data, decisions/052) vs expected.compute of the golden's spec;
    every mark of a listed sheet must be there and no other."""
    stem, name = case.golden.stem, f"golden/{case.golden.stem}"
    path = root / GOLDEN_EXPECTED / f"{stem}.json"
    if stem in GOLDEN_NO_EXPECTED:
        return Row(name, "expected", SKIP, GOLDEN_NO_EXPECTED[stem])
    if not path.is_file():
        return Row(name, "expected", FAIL, f"no {_rel(root, path)} (golden/expected/make_expected.py) and no reason "
                                           f"in GOLDEN_NO_EXPECTED")
    want = json.loads(path.read_text(encoding="utf-8"))
    spec = spec_mod.load(case.spec)
    got = expected.compute(spec, expected.data_path(spec, case.spec.parent))
    bad = [m for ds in spec_mod.sources(spec)  # each source's data file (decisions/083)
           for m in _packaged_data(case.golden.with_suffix(".twbx"), case.spec.parent / ds["path"])] + compare(want, got)
    for sheet, marks in want.items():
        if not sheet.startswith("_") and isinstance(marks, dict) and isinstance(got.get(sheet), dict):
            extra = [k for k in got[sheet] if k not in marks]
            bad += [f"{sheet}: {len(extra)} marks not in {path.name}, first {extra[0]!r}"] if extra else []
    if bad:
        return Row(name, "expected", FAIL, f"{len(bad)} of {_leaves(want)}: " + "; ".join(bad[:5]))
    return Row(name, "expected", OK, f"{_leaves(want)} numbers match {_rel(root, path)}")


def reconcile_row(case):
    """acceptance/<case>/reconcile.json + the case's HTML page: every number of the page found in the book or
    accepted with a reason (decisions/024)."""
    pages = sorted(case.spec.parent.glob("*.html"))
    if len(pages) != 1:
        return Row(case.name, "reconcile", FAIL, f"want one .html next to reconcile.json, found {len(pages)}")
    return reconcile_check(case.name, case.spec, pages[0], case.spec.parent / "reconcile.json")[0]


def reconcile_check(name, spec_path, html, case_path=None):
    """(Row, full report or None): every number of the page in the book (decisions/024). SKIP without Chrome."""
    from . import html_outline, reconcile
    try:
        html_outline._chrome()
    except RuntimeError as e:
        return Row(name, "reconcile", SKIP, str(e)), None
    r = reconcile.check(spec_mod.load(spec_path), Path(spec_path).parent, html_outline.outline(html),
                        reconcile.load_case(case_path), Path(spec_path).name)
    summary = reconcile.summary_line(r)
    if r["ok"]:
        return Row(name, "reconcile", OK, summary), r
    return Row(name, "reconcile", FAIL, "; ".join(reconcile.problems(r)[:8]) + f" ({summary})"), r


# ---- Desktop cache (decisions/113) -------------------------------------------------------------------------------
# Random per build: datasource / connection names (federated.x, textscan.x, excel-direct.x ...), object ids and the simple-id uuids of the .twb.
_RANDOM_ID = re.compile(r"[a-z][a-z-]*\.(?=[a-z0-9]{28}(?![a-z0-9]))[a-z0-9]{28}|_[0-9A-F]{32}|\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\}")


def book_hash(book):
    """sha256 of a built book that two builds of one spec share: the .twb with its random ids renamed by order of
    first appearance, every other member (data, images) as it is, members in name order."""
    import zipfile
    h = hashlib.sha256()
    with zipfile.ZipFile(book) as z:
        for n in sorted(z.namelist()):
            data = z.read(n)
            if n.endswith(".twb"):
                seen = {}
                data = _RANDOM_ID.sub(lambda m: seen.setdefault(m.group(), f"@{len(seen)}"),
                                      data.decode("utf-8")).encode("utf-8")
            h.update(b"*.twb" if n.endswith(".twb") else n.encode())  # the .twb is named after the output file
            h.update(hashlib.sha256(data).digest())
    return h.hexdigest()


def load_cache(path, exe):
    """{case: hash} of the last OK Desktop runs; empty when the file is absent, unreadable or of another Tableau."""
    try:
        c = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return c.get("books", {}) if isinstance(c, dict) and c.get("tableau") == str(exe) else {}


def save_cache(path, exe, books):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"tableau": str(exe), "books": books}, ensure_ascii=False, indent=1,
                                     sort_keys=True), encoding="utf-8")


def desktop_rows(books, out_dir, changed=False, cache_path=None):
    from . import desktop_check as dc
    exe = dc.find_tableau()
    if exe is None:
        return [Row("desktop", "desktop", FAIL, f"tableau.exe not found ({dc.TABLEAU_EXE}; set TABLEAU_EXE)")]
    cache_path = Path(cache_path or out_dir / "desktop-cache.json")
    old = load_cache(cache_path, exe)
    new = {}
    rows = []
    for name, book in books:
        digest = book_hash(book)
        if changed and old.get(name) == digest:
            rows.append(Row(name, "desktop", OK, "cached: unchanged since the last OK Desktop run"))
            new[name] = digest
            continue
        r = dc.check(book)
        ok = r.status == dc.OK
        if ok:
            new[name] = digest  # a FAIL drops the case from the cache: the next --changed opens it again
        rows.append(Row(name, "desktop", OK if ok else FAIL,
                        f"{r.status} in {r.seconds} s" + (f": {r.message}" if not ok else ""), r.seconds))
    save_cache(cache_path, exe, new)
    broken = _tests_module("test_desktop_check").make_broken(out_dir / "desktop_mutants")
    for name, want in DESKTOP_MUTANTS.items():
        if name not in broken:
            rows.append(Row(f"desktop-mutant/{name}", "desktop", FAIL, "make_broken no longer writes it"))
            continue
        r = dc.check(broken[name])
        rows.append(Row(f"desktop-mutant/{name}", "desktop", OK if r.status == want else FAIL,
                        f"{r.status} (want {want}): {r.message}", r.seconds))
    return rows


# ---- run ---------------------------------------------------------------------------------------------------------
def _stage(case, stage, fn, *a):
    """fn(*a) -> Row, timed; an exception (unreadable spec, BadZipFile of a broken golden...) is a FAIL row."""
    t = time.time()
    try:
        row = fn(*a)
    except Exception as e:
        row = Row(case, stage, FAIL, f"{type(e).__name__}: {e}")
    row.seconds = row.seconds or round(time.time() - t, 1)
    return row


def run(root=ROOT, out_dir=None, desktop=False, changed=False, unit=True, tests_dir=TESTS, log=None):
    """All rows of the suite. unit=False skips the unit and mutation stages (the runner's own tests)."""
    root = Path(root)
    out_dir = Path(out_dir or root / "out" / "regress")
    out_dir.mkdir(parents=True, exist_ok=True)
    say = log or (lambda *_: None)
    rows = []
    if unit:
        say("unit tests ...")
        t = time.time()
        outcomes = run_tests(tests_dir)
        rows += unit_rows(outcomes, time.time() - t) + mutation_rows(outcomes)
    cases, rows_discovery = discover(root)
    rows += rows_discovery
    books = []
    for c in cases:
        say(f"{c.name} ...")
        rows.append(_stage(c.name, "lint", lint_row, c, root))
        t = time.time()
        book, built = build_rows(c, out_dir)
        for r in built:
            r.seconds = round(time.time() - t, 1)
        rows += built
        if book:
            books.append((c.name, book))
        if c.golden:
            rows.append(_stage(c.name, "roundtrip", roundtrip_row, c, book, root))
        if c.expected is not None:
            rows.append(_stage(c.name, "expected", expected_row, c))
        if (c.spec.parent / "reconcile.json").is_file():
            rows.append(_stage(c.name, "reconcile", reconcile_row, c))
    for c in sorted((c for c in cases if c.golden), key=lambda c: c.golden.stem):
        g = c.golden.with_suffix(".twb")
        rows.append(_stage(f"golden/{g.stem}", "gate", golden_gate_row, root, g))
        rows.append(_stage(f"golden/{g.stem}", "expected", golden_expected_row, c, root))
    if desktop:
        say(f"desktop: {len(books)} books + {len(DESKTOP_MUTANTS)} mutants ...")
        rows += desktop_rows(books, out_dir, changed)
    return rows


def table(rows):
    w = [max(len(getattr(r, f)) for r in rows + [Row("case", "stage", "status")]) for f in ("case", "stage", "status")]
    w[0] = min(w[0], 60)
    lines = [f"{'case':<{w[0]}}  {'stage':<{w[1]}}  {'status':<{w[2]}}  reason"]
    for r in rows:
        lines.append(f"{r.case:<{w[0]}}  {r.stage:<{w[1]}}  {r.status:<{w[2]}}  {r.reason}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tbuilder regress", description=__doc__.split("\n")[0])
    ap.add_argument("--desktop", action="store_true", help="also open every built book in Tableau Desktop "
                    "(take the queue out/desktop-queue.md first)")
    ap.add_argument("--changed", action="store_true", help="with --desktop: skip the books whose content (random ids "
                    "aside) equals the last OK Desktop run in out/regress/desktop-cache.json (key: hash + tableau.exe "
                    "path); FAIL/WARN, new and changed books are opened. A run without --changed refills the cache")
    ap.add_argument("--no-unit", action="store_true", help="skip the unit tests (run them in parallel with "
                    "tools/ptest.py instead)")
    a = ap.parse_args(argv)
    os.environ.pop(user_profile.ENV, None)  # the suite is the house books whatever this machine prefers (decisions/193)
    start = time.time()
    if a.changed and not a.desktop:
        ap.error("--changed needs --desktop")
    rows = run(desktop=a.desktop, changed=a.changed, unit=not a.no_unit, log=lambda m: print(m, file=sys.stderr, flush=True))
    seconds = round(time.time() - start, 1)
    counts = {s: sum(r.status == s for r in rows) for s in (OK, FAIL, WARN, SKIP)}
    print(table(rows))
    print(f"\n{len(rows)} rows: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + f"; {seconds} s")
    cached = sum(r.stage == "desktop" and r.reason.startswith("cached") for r in rows)
    if a.changed:
        print(f"desktop: {cached} cached")
    report = {"started": dt.datetime.fromtimestamp(start).isoformat(timespec="seconds"), "seconds": seconds,
              "desktop": a.desktop, "changed": a.changed, "cached": cached, "ok": counts[FAIL] == 0, "counts": counts, "rows": [asdict(r) for r in rows]}
    path = ROOT / "out" / "regress" / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(path)
    return 1 if counts[FAIL] else 0
