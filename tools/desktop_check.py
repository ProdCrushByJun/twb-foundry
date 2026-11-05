"""Open .twbx files in Tableau Desktop, one process each: OK / ERROR / CRASH / TIMEOUT (decisions/022).

  python tools/desktop_check.py <file.twbx> [...] [--timeout 120]

Same as `python -m tbuilder check-desktop`; the logic is tbuilder/desktop_check.py (import `check` from there).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tbuilder.desktop_check import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
