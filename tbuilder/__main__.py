"""CLI.

  python -m tbuilder build   <spec.json> [-o out.twbx] [--desktop-check] [--hyper-mb N] [--profile P]  spec -> gated .twbx
  python -m tbuilder check-desktop <file.twbx> [...]              opens cleanly in Tableau Desktop? (decisions/022)
  python -m tbuilder check-desktop --resave <file.twbx> [...] [-d out/resave] [--no-sheets]
                                                                  re-save in Desktop + diff: what it dropped (decisions/054)
  python -m tbuilder outline <page.html> [-o x.json] [--png x.png] HTML dashboard -> outline
  python -m tbuilder lint    <spec.json> [--profile P]           design rules (context/design-rules.md) + all that stops the build
  python -m tbuilder profile <data.csv|.xlsx> [--sheet S]         columns, types, samples (.xlsx: sheets listed)
  python -m tbuilder user-profile [P]                             a user profile, merged, with its MD files (decisions/193)
  python -m tbuilder copy-style <book...> --out profiles/<P>/ [--dashboard D] [--set color.good=#rrggbb]
                                                                  a profile from workbooks, tokens.md with counts (decisions/194)
  python -m tbuilder profile-css [P] [--list]                     a profile's tokens as CSS variables for an HTML mock; the profiles to choose from (decisions/194, 195)
  python -m tbuilder analyze <page.html> <data> [--sheet S] [-d dir]  outline + screenshot + evidence for HTML->spec
  python -m tbuilder reconcile <spec.json> <page.html> [--case c.json] [-o r.json]
                                                                  every HTML number found in the workbook? (decisions/024)
  python -m tbuilder regress [--desktop [--changed]] [--no-unit]           the whole regression suite (decisions/027)
  python -m tbuilder to-tableau-check <spec.json> <page.html> [--case c.json] [-o x.twbx] [--no-desktop] [--profile P]
                                                                  lint + build/gate + Desktop + reconcile (decisions/038)
  python -m tbuilder to-tableau-preview <spec.json> [-o x.twbx] [--profile P]   a look: build/gate + Desktop + drawn, not an acceptance (179)
  python -m tbuilder compare-shots <page.html> <book.twbx> [-d dir] [--tableau-png x.png] [--mutate dark|swapped]
                                                                  HTML vs dashboard by pictures (decisions/048)
  python -m tbuilder check-drawn <book.twbx> <spec.json> [-d dir]  every number on screen in Desktop? (decisions/076)
  python -m tbuilder restyle <in.twbx> -o <out.twbx> [--theme cards|flat]
                                                                  design system on a foreign book's style XML (decisions/049)
  python -m tbuilder rebuild <in.twbx> -o <spec.json> [--data <file.csv>]
                                                                  a book's simple sheets -> our spec + its data (decisions/053)
  python -m tbuilder patch <in.twbx> <ops.json> -o <out.twbx> [--resave [-d dir]]
                                                                  point edits of a foreign book, gated (decisions/161)
  python -m tbuilder inspect <book.twbx|.twb>                     sources, parameters, sheets, calculated fields; read only (decisions/188)
"""
import argparse
import json
import sys
from pathlib import Path


def _build(a):
    from . import desktop_check as dc
    from .build import build_file
    if a.desktop_check and dc.find_tableau() is None:
        raise RuntimeError(f"--desktop-check: tableau.exe not found ({dc.TABLEAU_EXE}; set TABLEAU_EXE)")
    out = build_file(a.spec, a.out or Path("out") / (a.spec.stem + ".twbx"), a.hyper_mb)
    if a.desktop_check:  # part of the gate: a file Desktop does not open cleanly is not handed out
        r = dc.check(out)
        if r.status != dc.OK:
            Path(out).unlink(missing_ok=True)
            raise RuntimeError(f"Desktop check {r.status}: {r.message}")
    print(out)


def _check_desktop(a):
    if a.resave:
        from .resave import main as resave_main
        sys.exit(resave_main([str(p) for p in a.twbx] + ["-d", str(a.out_dir)] + (["--no-sheets"] if a.no_sheets else [])
                             + (["--timeout", str(a.timeout)] if a.timeout else [])))
    from .desktop_check import main as check_main
    sys.exit(check_main([str(p) for p in a.twbx] + (["--timeout", str(a.timeout)] if a.timeout else [])))


def _regress(a):
    from .regress import main as regress_main
    sys.exit(regress_main(["--desktop"] * a.desktop + ["--changed"] * a.changed + ["--no-unit"] * a.no_unit))


def _to_tableau_check(a):
    from .pipeline import main as check_main
    sys.exit(check_main(a.argv))


def _to_tableau_preview(a):
    from .pipeline import preview_main
    sys.exit(preview_main(a.argv))


def _compare_shots(a):
    from .screenshot import main as shots_main
    sys.exit(shots_main(a.argv))


def _check_drawn(a):
    from .drawn import main as drawn_main
    sys.exit(drawn_main(a.argv))


def _restyle(a):
    from .restyle import restyle_file
    print(f"{a.out}: {restyle_file(a.src, a.out, a.theme)}")


def _rebuild(a):
    from .rebuild import rebuild
    print(rebuild(a.src, a.out, a.data).text())


def _patch(a):
    from .patch import main as patch_main
    sys.exit(patch_main(a.argv))


def _inspect(a):
    from .inspect_book import main as inspect_main
    sys.exit(inspect_main(a.argv))


def _lint(a):
    from .design_lint import lint
    from .spec import load
    findings = lint(load(a.spec), a.spec.parent, build=True)
    for f in findings:
        print(f)
    errors = sum(f.level == "error" for f in findings)
    print(f"{a.spec.name}: {errors} error(s), {len(findings) - errors} other finding(s)")
    if errors:
        sys.exit(1)


def _outline(a):
    from .html_outline import outline
    o = outline(a.html, screenshot=a.png)
    text = json.dumps(o, ensure_ascii=False, indent=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text, encoding="utf-8")
        print(a.out)
    else:
        print(text)


def _profile(a):
    from .excel import is_excel, load
    p = load(a.csv, a.sheet)
    print(f"{p.path.name}: {len(p.rows)} rows, " + (f"sheet '{p.sheet}', table {p.grid}" if is_excel(a.csv)
                                                    else f"text-file locale {p.locale or 'of the workbook'}"))
    for c in p.columns:
        values = [r[c.name] for r in p.rows if r[c.name] != ""]
        nulls = len(p.rows) - len(values)
        extra = f"{len(c.distinct)} distinct: {c.distinct[:8]}" if c.datatype == "string" else f"e.g. {values[:3]}"
        if c.date_format:  # values are shown as parsed (ISO)
            extra = f"{c.date_format.label} in the CSV, {extra}"
        print(f"  {c.name:<24} {c.datatype:<8} {c.role:<9} nulls={nulls:<6} {extra}")


def _user_profile(a):
    from . import user_profile
    print(json.dumps(user_profile.card(a.name or user_profile.resolve()), ensure_ascii=False, indent=1))


def _profile_from(a):
    from . import profile_from
    try:
        if a.list:
            print(profile_from.to_json({str(b): profile_from.outline(b) for b in a.books}))
            return
        if not a.out:
            raise profile_from.SourceError("--out profiles/<name>/ is required")
        if not (a.books or a.set or a.brandbook):
            raise profile_from.SourceError("nothing to do: give a workbook, --set or --brandbook")
        meta = {"url": a.url, "site": a.site, "workbook_id": a.workbook_id}
        print(profile_from.to_json(profile_from.write(a.out, a.books, a.dashboard, a.set, meta, a.brandbook)))
    except profile_from.SourceError as e:
        sys.exit(str(e))


def _refs(a):
    from . import profile_from, refs_catalog, spec as spec_mod
    try:
        if a.cmd == "book-catalog":
            meta = {"url": a.url, "site": a.site, "workbook_id": a.workbook_id}
            cat = refs_catalog.make(a.books, a.out, meta)
            out = {**refs_catalog.summary(cat), "catalog": str(a.out / "refs" / "catalog.json"), "gallery": str(a.out / "refs" / "gallery.md")}
        elif a.cmd == "pick-charts":
            out = refs_catalog.pick(a.profile, a.pick.split())
        else:
            out = refs_catalog.layout_cli(a.profile, a.layout, a.map, a.spec, a.out)
        print(profile_from.to_json(out))
    except (profile_from.SourceError, spec_mod.SpecError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _profile_css(a):
    from . import profile_from, user_profile
    if a.list:
        print("\n".join(profile_from.listing()))
        return
    print(profile_from.css(a.name or user_profile.resolve()), end="")


def _analyze(a):
    from .html_outline import outline
    from .match import match
    d = a.dir or Path("out") / a.html.stem
    d.mkdir(parents=True, exist_ok=True)
    o = outline(a.html, screenshot=d / "page.png")
    m = match(o, a.csv, a.sheet)
    (d / "outline.json").write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")
    (d / "evidence.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{d}: page.png, outline.json ({len(o['blocks'])} blocks), evidence.json")
    if o["profile"]:
        print(f"the mock is drawn in profile '{o['profile']}': the book takes it through spec.profile (decisions/195)")


def _reconcile(a):
    from .html_outline import outline
    from .reconcile import check, load_case, report_text
    from .spec import load
    r = check(load(a.spec), a.spec.parent, outline(a.html), load_case(a.case), a.spec.name)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report_text(r))
    if not r["ok"]:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(prog="tbuilder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    profile_help = "the user profile (profiles/<name>); stronger than the spec's and TB_PROFILE (decisions/193)"
    b = sub.add_parser("build")
    b.add_argument("spec", type=Path)
    b.add_argument("-o", "--out", type=Path)
    b.add_argument("--desktop-check", action="store_true", help="also open the file in Tableau Desktop (off by "
                   "default: Desktop is not everywhere)")
    b.add_argument("--hyper-mb", type=float, help="package the data as Hyper when the CSV is larger than this many "
                   "MB (default 20, 0 = always; the spec's datasource.hyper overrides it; decisions/026)")
    b.add_argument("--profile", help=profile_help)
    b.set_defaults(fn=_build)
    c = sub.add_parser("check-desktop")
    c.add_argument("twbx", nargs="+", type=Path)
    c.add_argument("--timeout", type=float)
    c.add_argument("--resave", action="store_true", help="also File > Save As in Desktop and diff the XML: what Desktop "
                   "silently dropped (decisions/054)")
    c.add_argument("-d", "--out-dir", type=Path, default=Path("out") / "resave", help="--resave: where the re-saved "
                   "books and reports go")
    c.add_argument("--no-sheets", action="store_true", help="--resave: do not show every sheet tab before saving")
    c.set_defaults(fn=_check_desktop)
    n = sub.add_parser("lint")
    n.add_argument("spec", type=Path)
    n.add_argument("--profile", help=profile_help)
    n.set_defaults(fn=_lint)
    o = sub.add_parser("outline")
    o.add_argument("html", type=Path)
    o.add_argument("-o", "--out", type=Path)
    o.add_argument("--png", type=Path)
    o.set_defaults(fn=_outline)
    p = sub.add_parser("profile")
    p.add_argument("csv", type=Path)
    p.add_argument("--sheet", help=".xlsx: the sheet with the table (decisions/025)")
    p.set_defaults(fn=_profile)
    up = sub.add_parser("user-profile", help="a user profile, merged, with its MD files (decisions/193)")
    up.add_argument("name", nargs="?")
    up.set_defaults(fn=_user_profile)
    pf = sub.add_parser("copy-style", help="a profile from workbooks (decisions/194)")
    pf.add_argument("books", nargs="*", help=".twbx, .twb or Preferences.tps")
    pf.add_argument("--out", type=Path, help="the profile's folder: profiles/<name>/")
    pf.add_argument("--dashboard", help="the one dashboard of the book to take the style from")
    pf.add_argument("--list", action="store_true", help="only list the dashboards of the books")
    pf.add_argument("--set", action="append", default=[], metavar="GROUP.KEY=VALUE", help="a token by hand: color.good=#2ca02c")
    pf.add_argument("--url", help="the book's Tableau Public page, for style_book")
    pf.add_argument("--site", help="the book's Server / Cloud site, for style_book")
    pf.add_argument("--workbook-id", help="the book's id on Server / Cloud, for style_book")
    pf.add_argument("--brandbook", help="the brand book the --set values came from, relative to the profile's folder")
    pf.set_defaults(fn=_profile_from)
    pc = sub.add_parser("profile-css", help="a profile's tokens as CSS variables for an HTML mock (decisions/194)")
    pc.add_argument("name", nargs="?")
    pc.add_argument("--list", action="store_true", help="the profiles to choose a mock's style from (decisions/195)")
    pc.set_defaults(fn=_profile_css)
    rc = sub.add_parser("book-catalog", help="the blocks of workbooks: sheets, statuses, layouts (decisions/196)")
    rc.add_argument("books", nargs="*", help=".twbx or .twb; the books of the catalog are read again")
    rc.add_argument("--out", type=Path, required=True, help="the profile's folder: profiles/<name>/")
    rc.add_argument("--url", help="the book's Tableau Public page")
    rc.add_argument("--site", help="the book's Server / Cloud site")
    rc.add_argument("--workbook-id", help="the book's id on Server / Cloud")
    rc.set_defaults(fn=_refs)
    rp = sub.add_parser("pick-charts", help="numbers of the gallery -> refs.md, prefer, requests, readings (decisions/196)")
    rp.add_argument("profile", type=Path, help="the profile's folder")
    rp.add_argument("--pick", required=True, help="'3 7 B1 L2': sheets, a whole book, a dashboard's layout")
    rp.set_defaults(fn=_refs)
    rl = sub.add_parser("pick-layout", help="a dashboard's rows and columns; with --spec, in a spec (decisions/196)")
    rl.add_argument("profile", type=Path, help="the profile's folder")
    rl.add_argument("layout", nargs="?", help="L2 or the dashboard's name; default the one picked")
    rl.add_argument("--spec", type=Path, help="the spec to put the grid in")
    rl.add_argument("--map", action="append", default=[], metavar="S1=SHEET", help="a slot and the spec's sheet for it")
    rl.add_argument("-o", "--out", type=Path, help="write here, not over the spec")
    rl.set_defaults(fn=_refs)
    z = sub.add_parser("analyze")
    z.add_argument("html", type=Path)
    z.add_argument("csv", type=Path)
    z.add_argument("--sheet", help=".xlsx: the sheet with the table")
    z.add_argument("-d", "--dir", type=Path)
    z.set_defaults(fn=_analyze)
    r = sub.add_parser("reconcile")
    r.add_argument("spec", type=Path)
    r.add_argument("html", type=Path)
    r.add_argument("--case", type=Path, help="filter state of the HTML page and accepted differences (JSON)")
    r.add_argument("-o", "--out", type=Path, help="full report (JSON)")
    r.set_defaults(fn=_reconcile)
    g = sub.add_parser("regress")
    g.add_argument("--desktop", action="store_true", help="also check-desktop every built book")
    g.add_argument("--changed", action="store_true", help="with --desktop: open only the books changed since the "
                   "last OK Desktop run (hash cache out/regress/desktop-cache.json, decisions/113)")
    g.add_argument("--no-unit", action="store_true", help="skip the unit tests (tools/ptest.py runs them)")
    g.set_defaults(fn=_regress)
    t = sub.add_parser("to-tableau-check", add_help=False, help="lint + build/gate + Desktop + reconcile")
    t.add_argument("argv", nargs=argparse.REMAINDER)
    t.set_defaults(fn=_to_tableau_check)
    tp = sub.add_parser("to-tableau-preview", add_help=False, help="a look: build/gate + Desktop + drawn, no reconcile")
    tp.add_argument("argv", nargs=argparse.REMAINDER)
    tp.set_defaults(fn=_to_tableau_preview)
    s = sub.add_parser("compare-shots", add_help=False, help="HTML vs Tableau dashboard by pictures")
    s.add_argument("argv", nargs=argparse.REMAINDER)
    s.set_defaults(fn=_compare_shots)
    cd = sub.add_parser("check-drawn", add_help=False, help="every number of a number sheet on screen in Desktop")
    cd.add_argument("argv", nargs=argparse.REMAINDER)
    cd.set_defaults(fn=_check_drawn)
    rs =sub.add_parser("restyle", help="the design system on a workbook's style XML only (decisions/049)")
    rs.add_argument("src", type=Path)
    rs.add_argument("-o", "--out", type=Path, required=True)
    rs.add_argument("--theme", choices=["cards", "flat"], default="cards")
    rs.set_defaults(fn=_restyle)
    rb = sub.add_parser("rebuild", help="a book's sheets the schema covers -> spec.json + data (decisions/053)")
    rb.add_argument("src", type=Path)
    rb.add_argument("-o", "--out", type=Path, required=True)
    rb.add_argument("--data", type=Path, help="the data file to write (default: the spec's path without .json)")
    rb.set_defaults(fn=_rebuild)
    pt = sub.add_parser("patch", add_help=False, help="point edits of a foreign book, gated (decisions/161)")
    pt.add_argument("argv", nargs=argparse.REMAINDER)
    pt.set_defaults(fn=_patch)
    ins = sub.add_parser("inspect", add_help=False, help="sources, parameters, sheets, calculated fields of a book (decisions/188)")
    ins.add_argument("argv", nargs=argparse.REMAINDER)
    ins.set_defaults(fn=_inspect)
    a = ap.parse_args()
    try:
        if getattr(a, "profile", None):
            from . import user_profile
            user_profile.forced = a.profile
        a.fn(a)
    except (ValueError, RuntimeError) as e:  # SpecError, GateError, data errors, Chrome failures
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
