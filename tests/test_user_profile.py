"""User profile (decisions/193): profiles/<name>/profile.yaml, design.apply, --profile / spec.profile / TB_PROFILE, lint P."""
import ast
import copy
import json
import os
import random
import shutil
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest import mock

import yaml

from tbuilder import design, design_lint, gate, spec as spec_mod, theme, user_profile
from tbuilder.build import build_file

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "specs" / "benchmark.json"  # cards, an accent, a reference band over card_bg
TOKENS = {"color": {"accent": "#8a3ffc", "canvas": "#eef2f7", "card_bg": "#fffdf8"},
          "font": {"family": "Arial", "block_title": 13},
          "space": {"card_margin": 10}}


class Base(unittest.TestCase):
    """A profiles/ folder of its own: house and whatever a test writes."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(ROOT / "profiles" / "house", self.root / "house")
        for p in (mock.patch.object(user_profile, "ROOT", self.root), mock.patch.object(user_profile, "forced", None),
                  mock.patch.dict(os.environ)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop(user_profile.ENV, None)

    def write(self, name, **body):
        (self.root / name).mkdir(exist_ok=True)
        (self.root / name / "profile.yaml").write_text(yaml.safe_dump({"profile_version": 1, **body}), encoding="utf-8")


class Load(Base):
    def test_house_sets_nothing(self):
        """house is design.py itself (decisions/193): a token set there would be a second copy."""
        raw = yaml.safe_load((ROOT / "profiles" / "house" / "profile.yaml").read_text(encoding="utf-8"))
        self.assertEqual(raw, {"profile_version": 1})

    def test_example_is_valid(self):
        with mock.patch.object(user_profile, "ROOT", ROOT / "profiles"):
            p = user_profile.load("example")
        self.assertEqual(p["tokens"]["color"]["accent"], "#1f77b4")
        self.assertEqual(p["rules"]["C2"]["max_categories"], 6)

    def test_based_on_merges_token_by_token(self):
        self.write("a", tokens={"color": {"accent": "#111111", "canvas": "#222222"}}, theme="flat", avoid=["pie"])
        self.write("b", based_on="a", tokens={"color": {"accent": "#333333"}}, avoid=["gauge"])
        p = user_profile.load("b")
        self.assertEqual((p["tokens"]["color"]["accent"], p["tokens"]["color"]["canvas"]), ("#333333", "#222222"))
        self.assertEqual((p["theme"], p["avoid"]), ("flat", ["gauge"]))

    def test_based_on_loop(self):
        self.write("a", based_on="b")
        self.write("b", based_on="a")
        with self.assertRaisesRegex(user_profile.ProfileError, "goes round"):
            user_profile.load("a")

    def test_name_is_not_a_path(self):
        with self.assertRaisesRegex(user_profile.ProfileError, "not a path"):
            user_profile.load("../house")

    def test_missing_names_what_there_is(self):
        with self.assertRaisesRegex(user_profile.ProfileError, "there are: house"):
            user_profile.load("nope")

    def test_every_problem_at_once(self):
        self.write("bad", tokens={"color": {"acent": "#111111", "good": "green"}, "space": {"card_margin": -1}},
                   rules={"C9": {"level": "info"}})
        with self.assertRaises(user_profile.ProfileError) as e:
            user_profile.load("bad")
        for text in ("did you mean 'accent'", "tokens/color/good", "tokens/space/card_margin", "rules/C9"):
            self.assertIn(text, str(e.exception))

    def test_one_book_for_the_style(self):
        self.write("a", style_book={"kind": "public", "url": "https://public.tableau.com/x", "dashboard": "Overview"})
        self.assertEqual(user_profile.load("a")["style_book"]["dashboard"], "Overview")
        self.write("b", style_book=[{"kind": "file"}])
        with self.assertRaisesRegex(user_profile.ProfileError, "style_book"):
            user_profile.load("b")

    def test_followers(self):
        """A profile that gives only good and card_margin does not keep the house teal text or a 6px edge."""
        self.write("a", tokens={"color": {"good": "#22AA22", "bad": "#d62728", "card_bg": "#fafafa"},
                                "space": {"card_margin": 9}})
        t = user_profile.load("a")["tokens"]
        self.assertEqual(t["color"]["good"], "#22aa22")
        floor = user_profile.shell.contrast(design.TEXT_FLOOR, "#ffffff")
        self.assertGreaterEqual(user_profile.shell.contrast(t["color"]["good_text"], "#ffffff"), floor)
        self.assertEqual(t["color"]["bad_fill"], "#f7d4d4")
        self.assertEqual(t["space"]["theme_edge"], 9)
        self.write("b", tokens={"color": {"good": "#22aa22", "good_text": "#000000"}, "space": {"card_margin": 9, "theme_edge": 4}})
        t = user_profile.load("b")["tokens"]
        self.assertEqual((t["color"]["good_text"], t["space"]["theme_edge"]), ("#000000", 4))


class WhichProfile(Base):
    def test_order(self):
        for name in ("flag", "spec", "env"):
            self.write(name)
        spec = {"profile": "spec"}
        self.assertEqual(user_profile.resolve(), "house")
        os.environ[user_profile.ENV] = "env"
        self.assertEqual(user_profile.resolve(), "env")
        self.assertEqual(user_profile.resolve(spec), "spec")
        user_profile.forced = "flag"
        self.assertEqual(user_profile.resolve(spec), "flag")

    def test_schema_takes_a_name_only(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        spec_mod.validate({**spec, "profile": "acme"})
        with self.assertRaises(spec_mod.SpecError):
            spec_mod.validate({**spec, "profile": "../acme"})


class Apply(Base):
    def test_sets_and_restores(self):
        before = copy.deepcopy((design.COLOR, design.FONT, design.FONT_CARDS, design.SPACE, design.BOOK))
        with design.apply({"tokens": TOKENS, "theme": "flat"}):
            self.assertEqual(design.COLOR["canvas"], "#eef2f7")
            self.assertEqual(design.SPACE["card_margin"], 10)
            self.assertEqual(design.BOOK, {"theme": "flat", "theme_font": "Arial"})
        self.assertEqual((design.COLOR, design.FONT, design.FONT_CARDS, design.SPACE, design.BOOK), before)

    def test_restores_after_an_error(self):
        accent = design.COLOR["accent"]
        with self.assertRaises(KeyError), design.apply({"tokens": TOKENS}):
            raise KeyError
        self.assertEqual(design.COLOR["accent"], accent)

    def test_font_size_in_both_scales(self):
        """The card theme has its own scale: a profile's block_title must hold there too."""
        spec = {"dashboard": {}}
        with design.apply({"tokens": TOKENS}):
            self.assertEqual(theme.font(spec)["block_title"], 13)
            self.assertEqual(theme.font({"dashboard": {"theme": "flat"}})["block_title"], 13)

    def test_spec_accent_beats_profile(self):
        self.write("a", tokens={"color": {"accent": "#8a3ffc"}})
        with design.book_accent({"profile": "a", "dashboard": {"accent": "#C4572A"}}):
            self.assertEqual(design.COLOR["accent"], "#c4572a")
        with design.book_accent({"profile": "a", "dashboard": {}}):
            self.assertEqual(design.COLOR["accent"], "#8a3ffc")

    def test_spec_theme_beats_profile(self):
        with design.apply({"theme": "flat"}):
            self.assertFalse(theme.on({"dashboard": {}}))
            self.assertTrue(theme.on({"dashboard": {"theme": "cards"}}))

    def test_no_token_read_at_import(self):
        """design.apply changes the dicts: a value copied out of them at import, at module level or in a default
        argument, would keep the house token in a profile's book."""
        found = []
        for path in (ROOT / "tbuilder").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            at_import = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
            for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
                at_import += [d for d in fn.args.defaults + fn.args.kw_defaults if d is not None]
            for top in at_import:
                for n in ast.walk(top):
                    if isinstance(n, ast.Subscript) and getattr(n.value, "id", getattr(n.value, "attr", "")) in ("COLOR", "FONT", "SPACE"):
                        found.append(f"{path.name}:{n.lineno}")
        self.assertEqual(found, [])


def seeded_twb(out):
    """The .twb of a build with its random ids seeded, to compare byte for byte."""
    random.seed(193)
    with mock.patch.object(uuid, "uuid4", lambda: uuid.UUID(int=random.getrandbits(128), version=4)):
        book = build_file(SPEC, out)
    with zipfile.ZipFile(book) as z:
        return next(z.read(n) for n in z.namelist() if n.endswith(".twb"))


class Book(Base):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_house_is_byte_for_byte(self):
        plain = seeded_twb(self.out / "plain.twbx")
        user_profile.forced = "house"
        self.assertEqual(seeded_twb(self.out / "house.twbx"), plain)

    def test_profile_in_the_book_and_gate_clean(self):
        self.write("a", tokens=TOKENS)
        user_profile.forced = "a"
        twb = seeded_twb(self.out / "a.twbx").decode("utf-8")
        for value in ('value="#eef2f7"', 'value="#fffdf8"', 'value="#8a3ffc"', 'value="Arial"'):
            self.assertIn(value, twb)
        self.assertNotIn('"#f5f5f5"', twb)  # the house canvas

    def test_gate_of_another_profile_catches(self):
        """A book built with one profile fails the gate of another: the gate reads the tokens, it is not switched off."""
        self.write("a", tokens=TOKENS)
        user_profile.forced = "a"
        book = self.out / "a.twbx"
        seeded_twb(book)
        self.assertEqual(gate.run(book), [])
        user_profile.forced = "house"
        self.assertTrue([i for i in gate.run(book) if "canvas" in str(i)])

    def test_broken_profile_stops_the_build(self):
        self.write("a", tokens={"color": {"accent": "blue"}})
        user_profile.forced = "a"
        with self.assertRaises(user_profile.ProfileError):
            seeded_twb(self.out / "a.twbx")
        self.assertFalse((self.out / "a.twbx").exists())


class LintP(Base):
    def lint(self, name, **body):
        self.write(name, **body)
        user_profile.forced = name
        return design_lint.lint(spec_mod.load(SPEC), SPEC.parent)

    def rule(self, findings, rule):
        return [f for f in findings if f.rule == rule]

    def test_house_has_no_p(self):
        self.assertEqual([f for f in design_lint.lint(spec_mod.load(SPEC), SPEC.parent) if f.rule.startswith("P")], [])

    def test_p1_foreign_key(self):
        found = self.lint("a", tokens={"color": {"acent": "#111111"}})
        self.assertEqual([(f.rule, f.level) for f in found], [("P1", "error")])
        self.assertIn("acent", found[0].text)

    def test_p1_not_hex(self):
        self.assertEqual(self.rule(self.lint("a", tokens={"color": {"accent": "blue"}}), "P1")[0].level, "error")

    def test_p1_paths_warn(self):
        found = self.rule(self.lint("a", style_book={"kind": "file", "file": "refs/x.twbx"}, context_dirs=["C:/no/such"]), "P1")
        self.assertEqual([f.level for f in found], ["warn", "warn"])

    def test_p2_text_on_card(self):
        found = self.rule(self.lint("a", tokens={"color": {"text": "#cccccc"}}), "P2")
        self.assertEqual({f.level for f in found}, {"error"})
        self.assertIn("'text' #cccccc on 'card_bg'", found[0].text)

    def test_p2_muted_warns(self):
        found = self.rule(self.lint("a", tokens={"color": {"muted": "#cccccc"}}), "P2")
        self.assertEqual([f.level for f in found], ["warn"])

    def test_p4_mock_in_another_profile(self):
        """A mock drawn in a style and a book left in house no longer look alike (decisions/195)."""
        base = self.root / "case"
        base.mkdir()
        (base / "outline.json").write_text('{"profile": "a"}', encoding="utf-8")
        check = lambda name: design_lint._mock_style({"name": name}, base)
        self.assertEqual(check("a"), [])
        self.assertEqual([(f.rule, f.level) for f in check("house")], [("P4", "warn")])
        (base / "outline.json").write_text('{"profile": null}', encoding="utf-8")
        self.assertEqual(check("house"), [])
        self.assertEqual(design_lint._mock_style({"name": "house"}, self.root / "none"), [])

    def test_p3_palette_of_seven(self):
        seven = [f"#00000{i}" for i in range(7)]
        self.assertEqual(self.rule(self.lint("a", palettes={"categorical": seven}), "P3")[0].level, "warn")
        self.assertEqual(self.rule(self.lint("b", palettes={"categorical": seven},
                                             rules={"C2": {"max_categories": 7}}), "P3"), [])

    def test_rules_move_warn_never_error(self):
        spec = spec_mod.load(SPEC)
        spec["dashboard"].pop("subtitle", None)  # T1: warn
        self.assertEqual({f.level for f in design_lint.lint(spec, SPEC.parent) if f.rule == "T1"}, {"warn"})
        self.write("a", rules={"T1": {"level": "info"}, "P2": {"level": "info"}}, tokens={"color": {"text": "#cccccc"}})
        user_profile.forced = "a"
        found = design_lint.lint(spec, SPEC.parent)
        self.assertEqual({f.level for f in found if f.rule == "T1"}, {"info"})
        self.assertEqual({f.level for f in found if f.rule == "P2"}, {"error"})

    def test_locked_rules(self):
        for rule in ("C8", "C9", "D5", "I3"):
            self.assertEqual(self.rule(self.lint("a", rules={rule: {"level": "info"}}), "P1")[0].level, "error")


class Context(Base):
    def test_order_limit_readme(self):
        ext = self.root / "ext"
        ext.mkdir()
        self.write("a", context_dirs=[str(ext)])
        ctx = self.root / "a" / "context"
        ctx.mkdir()
        (ctx / "README.md").write_text("about the folder", encoding="utf-8")
        (ctx / "brand.md").write_text("b" * 100, encoding="utf-8")
        (ext / "glossary.md").write_text("g" * 100, encoding="utf-8")
        (ext / "notes.txt").write_text("not md", encoding="utf-8")
        (ext / "z_big.md").write_text("z" * (user_profile.CONTEXT_TOKENS * 4), encoding="utf-8")
        (ext / "zz_small.md").write_text("after the limit", encoding="utf-8")
        read, skipped = user_profile.context_files(user_profile.load("a"))
        self.assertEqual([p.name for p in read], ["brand.md", "glossary.md"])
        self.assertEqual([p.name for p in skipped], ["z_big.md", "zz_small.md"])

    def test_card(self):
        self.write("a", based_on="house", prefer={"kpi": "cards"}, context_dirs=["C:/no/such"])
        card = user_profile.card("a")
        self.assertEqual(card["prefer"], {"kpi": "cards"})
        self.assertEqual(card["context"], {"read": [], "skipped": []})
        self.assertEqual(len(card["missing"]), 1)
        json.dumps(card)


if __name__ == "__main__":
    unittest.main()
