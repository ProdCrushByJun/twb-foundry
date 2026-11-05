# Golden workbooks: Tableau Desktop 2025.1

Each `golden_<x>_2025_1.twbx` is the output of `specs/<x>.json`, opened in Desktop 2025.1 and saved by it, so the XML is what Tableau itself writes. `.twb` next to it is the same XML, for reading and diffs.

They are test baselines: `python -m tbuilder regress` rebuilds each spec and compares it with its golden.

`golden/expected/<golden>.json` holds the control numbers of a golden, computed with pandas from its data by `golden/expected/make_expected.py`.

`pandas` is not in `requirements.txt`: the tests and `regress` only read these JSON files. To recompute them, `pip install pandas`, then `python golden/expected/make_expected.py --check`. The same goes for `acceptance/*/make_expected.py`.
