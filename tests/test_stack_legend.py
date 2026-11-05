"""Stack order from fields.<dim>.order and the legend under the block with groups (decisions/173)."""
import copy
import unittest
import zipfile

from lxml import etree

from tbuilder import design, gate, insight
from tbuilder.build import build
from test_insight import spec, sheet
from test_roundtrip import OUT

GROUPS = [{"label": "online", "values": ["Online", "Partner"]}, {"label": "shops", "values": ["Retail"]}]


def twb(s, name):
    out = build(s, OUT / "stack_legend_test" / f"{name}.twbx")
    with zipfile.ZipFile(out) as z:
        return etree.fromstring(z.read(next(n for n in z.namelist() if n.endswith(".twb"))))


def view_sorts(root, sheet_name):
    ws = next(w for w in root.iter("worksheet") if w.get("name") == sheet_name)
    return ws.findall(".//view/manual-sort")


class StackOrder(unittest.TestCase):
    def test_horizontal_stack_sorts_backwards_in_the_view(self):
        s = spec()
        order = s["fields"]["Channel"]["order"]
        sorts = view_sorts(twb(s, "order"), "By Region")
        self.assertEqual(len(sorts), 1)
        got = [b.text.strip('"') for b in sorts[0].iter("bucket")]
        self.assertEqual(got, list(reversed(order)))  # first member of the order lands at the left

    def test_no_view_sort_without_a_legend_or_order(self):
        s = spec()
        del sheet(s, "By Region")["legend"]
        self.assertEqual(view_sorts(twb(s, "nolegend"), "By Region"), [])
        s = spec()
        del s["fields"]["Channel"]["order"]
        self.assertEqual(view_sorts(twb(s, "noorder"), "By Region"), [])


class LegendBelow(unittest.TestCase):
    def below(self, groups=GROUPS):
        s = spec()
        sheet(s, "By Region")["legend"] = {"position": "below", **({"groups": groups} if groups else {})}
        return s

    def test_two_lines_with_group_labels(self):
        root = twb(self.below(), "below")
        zone = next(z for z in root.iter("zone") if z.get("type-v2") == "text"
                    and "online: " in "".join(z.itertext()))
        text = "".join(zone.itertext())
        self.assertIn("online: ", text)
        self.assertIn("shops: ", text)
        self.assertLess(text.index("Online"), text.index("Partner"))  # the field's order inside a group
        self.assertEqual(sum(r.text == "Æ\n" for r in zone.iter("run")), 1)
        header = "".join("".join(z.itertext()) for z in root.iter("zone") if z.get("type-v2") == "text" and z is not zone)
        self.assertNotIn("■ Online", header)  # no legend line in the header

    def test_without_groups_one_line(self):
        root = twb(self.below(None), "below1")
        self.assertTrue(any(z.get("type-v2") == "text" and "Online" in "".join(z.itertext()) for z in root.iter("zone")))

    def test_groups_must_cover_every_member_once(self):
        with self.assertRaisesRegex(ValueError, "in no group"):
            twb(self.below([GROUPS[0]]), "gap")
        dup = copy.deepcopy(GROUPS)
        dup[1]["values"].append("Online")
        with self.assertRaisesRegex(ValueError, "once"):
            twb(self.below(dup), "dup")

    def test_predicates(self):
        self.assertTrue(insight.inline({"legend": "inline"}))
        self.assertFalse(insight.below({"legend": "inline"}))
        self.assertTrue(insight.below({"legend": {"position": "below"}}))
        self.assertFalse(insight.below({"legend": {"position": "header"}}))


LONG = {"Online": "Online orders via marketplace", "Partner": "Partner resellers in the north", "Retail": "Retail"}


class LegendBelowWhole(unittest.TestCase):
    """Every label of the legend under the block is shown whole: the zone is as tall as Desktop's wrap (decisions/185)."""

    def book(self, name, aliases=LONG, groups=GROUPS, width=None):
        s = spec()
        s["fields"]["Channel"]["aliases"] = aliases
        sheet(s, "By Region")["legend"] = {"position": "below", "groups": groups}
        if width:
            s["dashboard"]["width"] = width
        return twb(s, name)

    @staticmethod
    def zone(root):
        return next(z for z in root.iter("zone") if z.get("type-v2") == "text" and "online" in "".join(z.itertext()))

    def test_the_longest_member_wraps_and_the_zone_holds_its_lines(self):
        root = self.book("long")
        z = self.zone(root)
        db = next(root.iter("dashboard"))
        size = db.find("size")
        tall = int(z.get("h")) * int(size.get("maxheight")) // gate.FULL
        self.assertGreaterEqual(tall, design.line_px(9) * 3)  # online takes two lines, shops one
        self.assertEqual(gate.check_legend_below(root), [])

    def test_the_wrap_is_an_explicit_break_between_members(self):
        # Desktop breaks a free wrap inside a label, a no-break space too (decisions/185)
        runs = [r.text for r in self.zone(self.book("rows")).iter("run")]
        self.assertEqual(runs.count("\u00c6\n"), 2)  # online: its two members on two lines; shops
        self.assertEqual("".join(runs).split("\u00c6\n")[1].rstrip(), "\u25a0 Partner resellers in the north")

    def test_the_wrap_goes_by_the_font_metric_not_the_character_count(self):
        # The case of decisions/173: the character estimate saw one line in 500px, Desktop draws two (512px of text)
        tokens = ["road and client: ", "\u25a0 Traffic jams    ", "\u25a0 Unloading queue    ", "\u25a0 Vehicle breakdown"]
        px = design.text_px("".join(tokens), 9)
        self.assertEqual(len(insight.legend_wrap(tokens, 9, px + 100)), 1)
        self.assertEqual(len(insight.legend_wrap(tokens, 9, px - 1)), 2)

    def test_a_label_wider_than_the_block_is_refused(self):
        aliases = {**LONG, "Online": "Online orders through the partner marketplace and the regional reseller network"}
        with self.assertRaisesRegex(ValueError, "widen the block or shorten the label"):
            self.book("refused", aliases)


class GateCatchesLegendBelow(unittest.TestCase):
    """Mutations of the built legend zone: lines taller than the zone, a label wider than it (decisions/185)."""

    def setUp(self):
        self.root = LegendBelowWhole().book("gate_legend")
        self.z = LegendBelowWhole.zone(self.root)

    def issues(self):
        return [i for i in gate.check_legend_below(self.root) if i.check == "legend-below"]

    def test_clean(self):
        self.assertEqual(self.issues(), [])

    def test_catches_a_zone_cut_to_one_line(self):
        self.z.set("h", str(int(self.z.get("h")) // 3))
        self.assertIn("height", self.issues()[0].message)

    def test_catches_a_member_wider_than_the_zone(self):
        self.z.set("w", str(int(self.z.get("w")) // 6))
        self.assertIn("does not fit", self.issues()[0].message)

    def test_catches_a_label_grown_after_the_build(self):
        run = next(r for r in self.z.iter("run") if (r.text or "").startswith("Online"))
        run.text = run.text.rstrip() + " long long long long long long long long"
        self.assertTrue(self.issues())


if __name__ == "__main__":
    unittest.main()
