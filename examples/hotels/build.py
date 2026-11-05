"""The hotels example from nothing, one command, run from anywhere:

  python examples/hotels/build.py [--desktop]

Downloads the data, prepares it, builds spec.json, applies the edits the generator has no option for, gates the result
and checks its numbers against the raw file. The book: out/hotels/hotel_cancellations.twbx. --desktop also opens it in
Tableau Desktop and diffs what Desktop saves.
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from tbuilder import design, gate, user_profile  # noqa: E402

DATA_URL = "https://raw.githubusercontent.com/rfordatascience/tidytuesday/main/data/2020/2020-02-11/hotels.csv"
RAW = HERE / "data" / "raw_hotels.csv"
OUT = ROOT / "out" / "hotels"
BOOK = OUT / "hotel_cancellations.twbx"


def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True, env={**os.environ, "PYTHONUTF8": "1"})


def patch(ops):
    tmp = OUT / "patched.twbx"
    run("-m", "tbuilder", "patch", BOOK, HERE / ops, "-o", tmp)
    tmp.replace(BOOK)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desktop", action="store_true", help="also check the book in Tableau Desktop")
    a = ap.parse_args()
    RAW.parent.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if not RAW.exists():
        print(f"Downloading {DATA_URL}")
        urllib.request.urlretrieve(DATA_URL, RAW)
    run(HERE / "prep.py")
    run("-m", "tbuilder", "build", HERE / "spec.json", "-o", BOOK)
    patch("hotels.ops.json")
    run(HERE / "month_axis.py", BOOK)  # before ops2: its axis edit reaches the months' new continuous axis too
    patch("hotels.ops2.json")
    run(HERE / "totals_label.py", BOOK)
    run(HERE / "hide_nulls.py", BOOK)
    spec = json.loads((HERE / "spec.json").read_text(encoding="utf-8"))
    with design.apply(user_profile.active(spec)):
        gate.enforce(BOOK, spec)
    run(HERE / "verify_numbers.py")
    if a.desktop:
        run("-m", "tbuilder", "check-desktop", BOOK, "--resave")
    print(f"{BOOK}: gate OK, numbers OK")


if __name__ == "__main__":
    main()
