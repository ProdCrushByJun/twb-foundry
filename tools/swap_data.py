"""Refresh the data under a built workbook: replace the packaged CSV, .xlsx or .hyper inside a .twbx, nothing else
(decisions/021, 025, 026).

  python tools/swap_data.py <book.twbx> <new.csv|new.xlsx> -o <out.twbx>

The workbook XML is copied as is, so Desktop opens the old book on the new data (a text or Excel connection is live:
Desktop unpacks the .twbx and reads the file again). The package must hold exactly one data file: a new .xlsx replaces
the packaged .xlsx, a new CSV the packaged CSV or .hyper. A .hyper (decisions/026) is rebuilt from the new CSV with the
profiler's types; its columns and types must still match the workbook's (the gate's Hyper check), otherwise nothing
is written.
"""
import argparse
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tbuilder import gate, hyper  # noqa: E402
from tbuilder.profile import profile_csv  # noqa: E402


def swap(book, csv, out):
    with zipfile.ZipFile(book) as z:
        members = {n: z.read(n) for n in z.namelist()}
    kinds = (".xlsx",) if Path(csv).suffix.lower() == ".xlsx" else (".csv", ".hyper")
    data = [n for n in members if n.lower().endswith(kinds)]
    if len(data) != 1:
        raise SystemExit(f"{book}: expected one packaged {' or '.join(kinds)} file, got {data}")
    with tempfile.TemporaryDirectory() as tmp:
        if data[0].lower().endswith(".hyper"):
            members[data[0]] = hyper.write(profile_csv(csv), Path(tmp) / "new.hyper").read_bytes()
        else:
            members[data[0]] = Path(csv).read_bytes()
        candidate = Path(tmp) / "out.twbx"
        with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        twb = next(n for n in members if n.endswith(".twb"))
        issues = gate.check_hyper(candidate, set(members), gate.etree.fromstring(members[twb]))
        if issues:
            raise SystemExit(f"{csv} does not fit {book}:\n" + "\n".join(f"  - {i}" for i in issues))
        Path(out).write_bytes(candidate.read_bytes())
    return data[0]


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("book", type=Path)
    a.add_argument("csv", type=Path)
    a.add_argument("-o", "--out", type=Path, required=True)
    args = a.parse_args()
    print(f"{args.out}: {swap(args.book, args.csv, args.out)} <- {args.csv}")
