"""'&' in the free texts of a spec (decisions/136, after 132 did the titles): each of them builds, passes the gate, and
the .twb carries it escaped (parsed back: '&'). One case = one spec file + the path of the text to mutate."""
import copy
import json
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from tbuilder.build import build
from test_roundtrip import OUT, ROOT

MARK = "R&D"  # the mutated text: must come back out of the parsed .twb as is
# texts that only name something for the generator / the expected numbers and are not drawn in the .twb
NOT_DRAWN = {"bar measure.label", "benchmark.label"}

# (case id, spec file, path to the text: keys / list indexes, text or None = "<old> & R&D")
CASES = [
    ("bar measure.label", "acceptance/plotly/spec.json", ["sheets", 1, "measure", "label"], MARK),
    ("benchmark.label", "specs/benchmark.json", ["sheets", 0, "benchmark", "label"], MARK),
    ("reference.label", "specs/benchmark.json", ["sheets", 0, "reference", "label"], MARK),
    ("repeat label", "specs/benchmark.json", ["sheets", 0, "repeat", 3, "label"], MARK),
    ("action hint", "specs/actions.json", ["dashboard", "actions", 1, "hint"], MARK),
    ("insight", "specs/insight.json", ["sheets", 1, "insight"], "**[Top Region]** leads, Q&A with R&D"),
    ("axis_lines.label", "specs/scatter.json", ["sheets", 0, "axis_lines", "label"], MARK),
    ("history_reference.label", "specs/kpi_v2.json", ["sheets", 0, "history_reference", "label"], MARK),
    ("status_labels", "specs/kpi_status.json", ["sheets", 1, "status_labels", 0], MARK),
    ("pill level label", "specs/registry_spark_pill.json", ["sheets", 0, "columns", 2, "levels", 0, "label"], MARK),
    ("topbar title", "specs/shell.json", ["dashboard", "topbar", "title"], MARK),
    ("sidebar footer", "specs/shell.json", ["dashboard", "sidebar", "footer", 0], MARK),
]


def _set(obj, path, value):
    for k in path[:-1]:
        obj = obj[k] if k in obj or isinstance(obj, list) else obj.setdefault(k, {})
    obj[path[-1]] = value


class AmpersandTexts(unittest.TestCase):
    def _case(self, name, file, path, text):
        spec_file = ROOT / file
        spec = copy.deepcopy(json.loads(spec_file.read_text(encoding="utf-8")))
        if path[0] == "sheets" and path[-1] == "label" and path[-2] == "history_reference":
            spec["sheets"][path[1]].setdefault("history_reference", {}).setdefault("type", "avg")
        _set(spec, path, text)
        stem = "amp_" + re.sub(r"\W+", "_", name)
        out = build(spec, OUT / f"{stem}.twbx", spec_file.parent)  # schema + data checks + validation gate
        with zipfile.ZipFile(out) as z:
            raw = z.read(out.stem + ".twb").decode("utf-8")
        root = ET.fromstring(raw)  # well-formed: every '&' escaped
        self.assertNotRegex(raw, r"&(?!amp;|lt;|gt;|quot;|apos;|#)", name)
        if name in NOT_DRAWN:
            return
        seen = [v for e in root.iter() for v in [e.text or "", *e.attrib.values()] if "R&D" in v]
        self.assertTrue(seen, f"{name}: the text with '&' is nowhere in the .twb")
        self.assertNotIn("&amp;amp;", raw, name)  # not escaped twice

    def test_each_text(self):
        for case in CASES:
            with self.subTest(case[0]):
                self._case(*case)


if __name__ == "__main__":
    unittest.main()
