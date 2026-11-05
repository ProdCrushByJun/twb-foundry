"""PrintWindow of a book's dashboard in Desktop 2025.1 (decisions/048 mechanism; no mouse, no keyboard).

usage: python shot.py <book.twbx> <out.png>   (run from the repo root)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tbuilder import desktop_check as dc  # noqa: E402
from tbuilder import screenshot as sh  # noqa: E402


def main(book, png):
    _, w, h, _ = sh.dashboard_info(book)
    shots = {}
    r = dc.check(Path(book), on_loaded=lambda pid: shots.setdefault("window", sh.capture_tableau(pid, w + 700, h + 400)))
    print(r.status, r.message)
    win = shots["window"]
    sh.save_png(win, Path(png).with_suffix(".window.png"))
    try:
        sh.save_png(sh.crop(win, sh.locate_dashboard(win, w, h)), png)
    except RuntimeError as e:
        print(e)


if __name__ == "__main__":
    main(*sys.argv[1:3])
