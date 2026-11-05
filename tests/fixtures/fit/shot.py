"""PrintWindow of each book's first dashboard in Desktop 2025.1 (decisions/048 mechanism; no mouse, no keyboard).

usage: python tests/fixtures/fit/shot.py <out_dir> <book.twbx> [...]   -> <out_dir>/<book stem>.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tbuilder import desktop_check as dc  # noqa: E402
from tbuilder import screenshot as sh  # noqa: E402


def shoot(book, png):
    _, w, h, _ = sh.dashboard_info(book)
    shots = {}
    r = dc.check(Path(book), on_loaded=lambda pid: shots.setdefault("window", sh.capture_tableau(pid, w + 700, h + 400)))
    print(book, r.status, r.message, flush=True)
    win = shots.get("window")
    if win is None:
        return
    try:
        sh.save_png(sh.crop(win, sh.locate_dashboard(win, w, h)), png)
    except RuntimeError as e:
        print(e)
        sh.save_png(win, Path(png).with_suffix(".window.png"))


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for b in sys.argv[2:]:
        shoot(b, out / (Path(b).stem + ".png"))
