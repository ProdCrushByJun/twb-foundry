"""Parallel test run: one process per tests/test_*.py module.

    PYTHONUTF8=1 ./.venv/Scripts/python tools/ptest.py            # all modules
    PYTHONUTF8=1 ./.venv/Scripts/python tools/ptest.py cards dates # only test_cards, test_dates
    -j N  workers (default 6)

Prints only failing modules (their output tail) and one summary line; exit 1 on failure.
"""
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# slowest modules: one process per TestCase class, started first; a group shares one process (and the module's
# cache): Books and Catches both use the same rebuild (~150 s), built once per process
SPLIT = {"test_rebuild": [("Books", "Catches")], "test_drawn": []}


def units(mod):
    """Process units of a module: 'mod' whole, or 'mod.A mod.B' (classes run in one process)."""
    if mod not in SPLIT:
        return [mod]
    src = (ROOT / "tests" / (mod + ".py")).read_text(encoding="utf-8")
    classes = re.findall(r"^class (\w+)\(unittest\.TestCase\)", src, re.M)
    grouped = [c for g in SPLIT[mod] for c in g]
    return [" ".join(f"{mod}.{c}" for c in g) for g in SPLIT[mod]] + [f"{mod}.{c}" for c in classes if c not in grouped]


def run(unit):
    t = time.time()
    cmd = ["-m", "unittest", *unit.split()] if "." in unit else ["-m", "unittest", "discover", "-s", "tests", "-p", unit + ".py"]
    p = subprocess.run(
        [sys.executable, *cmd],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**{k: v for k, v in os.environ.items() if k != "TB_PROFILE"}, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT / "tests")},
    )
    m = re.search(r"^Ran (\d+) test", p.stderr, re.M)
    return unit, p.returncode, int(m.group(1)) if m else 0, time.time() - t, p.stderr


def main(argv):
    jobs = 6
    if "-j" in argv:
        i = argv.index("-j")
        jobs = int(argv[i + 1])
        del argv[i:i + 2]
    mods = sorted(p.stem for p in (ROOT / "tests").glob("test_*.py"))
    if argv:
        want = {"test_" + a.removeprefix("test_") for a in argv}
        if want - set(mods):
            sys.exit(f"no such test module: {', '.join(sorted(want - set(mods)))}")
        mods = [m for m in mods if m in want]
    todo = [u for m in mods if m in SPLIT for u in units(m)] + [m for m in mods if m not in SPLIT]
    t = time.time()
    with ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(run, todo))
    failed = [r for r in res if r[1] != 0]
    for mod, _, _, dt, err in failed:
        print(f"--- FAIL {mod} ({dt:.0f}s)\n" + "\n".join(err.splitlines()[-30:]))
    slow = ", ".join(f"{m} {dt:.0f}s" for m, _, _, dt, _ in sorted(res, key=lambda r: -r[3])[:3])
    print(f"Ran {sum(r[2] for r in res)} tests in {len(mods)} modules, {time.time() - t:.0f}s "
          f"(-j {jobs}; slowest: {slow}) — {'FAILED ' + str(len(failed)) if failed else 'OK'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
