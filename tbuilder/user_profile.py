"""The user's profile (decisions/193): profiles/<name>/, the user's taste as data.

profile.yaml sets defaults: the design tokens (design.apply), the theme, and for /to-tableau and dashboard-designer the
preferences and the user's MD files. A profile writes no XML and turns no gate off; what a spec says is stronger. An
unset value comes from based_on (default house). house sets nothing: it is design.py as it stands.

Which profile: --profile, then spec.profile, then TB_PROFILE, then house.
"""
import difflib
import json
import os
import re
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from . import design, shell

ROOT = Path(__file__).resolve().parent.parent / "profiles"
HOUSE = "house"
ENV = "TB_PROFILE"
SCHEMA = json.loads((Path(__file__).parent / "profile.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_VALIDATOR = Draft202012Validator(SCHEMA)
NAME = re.compile(SCHEMA["$defs"]["name"]["pattern"])
# The gate, not taste (architecture §2.1): contrast, data-ink, spacing; a profile's rules cannot touch them
LOCKED_RULE = re.compile(r"C8|C9|D5|I\d+")
TOKEN_GROUPS = {"color": design.COLOR, "font": {**design.FONT, "family": None}, "space": design.SPACE}
CONTEXT_TOKENS = 40000  # the user's MD a skill reads at most (as the outline in /to-tableau); ~4 characters a token
forced = None  # --profile


class ProfileError(ValueError):
    pass


def resolve(spec=None):
    """The name of the profile in force for this spec."""
    return forced or (spec or {}).get("profile") or os.environ.get(ENV) or HOUSE


def active(spec=None):
    return load(resolve(spec))


def load(name):
    """The profile with its based_on chain merged over it; raises ProfileError with every problem found."""
    layers, seen = [], []
    while True:
        if name in seen:
            raise ProfileError(f"Profile '{seen[0]}': based_on goes round: {' -> '.join(seen + [name])}")
        seen.append(name)
        raw = _read(name)
        layers.append(raw)
        if name == HOUSE:
            break
        name = raw.get("based_on", HOUSE)
    merged = {}
    for raw in reversed(layers):
        merged = _merge(merged, raw)
    merged.pop("based_on", None)
    merged.pop("profile_version", None)
    _derive(merged.setdefault("tokens", {}))
    return {**merged, "name": seen[0], "dir": ROOT / seen[0]}


def _read(name):
    if not NAME.fullmatch(str(name)):
        raise ProfileError(f"Profile name '{name}': a folder name of profiles/ (letters, digits, - and _), not a path")
    path = ROOT / name / "profile.yaml"
    if not path.is_file():
        have = ", ".join(sorted(p.name for p in ROOT.iterdir() if (p / "profile.yaml").is_file()))
        raise ProfileError(f"Profile '{name}': no {path} (there are: {have})")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ProfileError(f"Profile '{name}': {path.name} is not YAML: {e}") from e
    found = problems(raw)
    if found:
        raise ProfileError(f"Profile '{name}' is invalid:\n" + "\n".join(f"  - {p}" for p in found))
    return raw


def problems(raw):
    """Everything wrong with one profile.yaml: the schema, the token keys of design.py, the locked rules."""
    found = [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in
             sorted(_VALIDATOR.iter_errors(raw), key=lambda e: list(map(str, e.absolute_path)))]
    if not isinstance(raw, dict):
        return found
    tokens = raw.get("tokens")
    for group, keys in TOKEN_GROUPS.items():
        given = tokens.get(group) if isinstance(tokens, dict) else None
        for k in given if isinstance(given, dict) else ():
            if k not in keys:
                near = difflib.get_close_matches(str(k), keys, 1)
                found.append(f"tokens/{group}/{k}: no such token in design.py" + (f" (did you mean '{near[0]}'?)" if near else ""))
    rules = raw.get("rules")
    for rule in rules if isinstance(rules, dict) else ():
        if LOCKED_RULE.fullmatch(str(rule)):
            found.append(f"rules/{rule}: contrast, data-ink and spacing are the gate, a profile cannot change them")
    return found


def _merge(base, over):
    out = {**base, **over}
    if "tokens" in base and "tokens" in over:
        out["tokens"] = {g: {**base["tokens"].get(g, {}), **over["tokens"].get(g, {})} for g in TOKEN_GROUPS}
    if "rules" in base and "rules" in over:
        out["rules"] = {**base["rules"], **over["rules"]}
    return out


def _derive(tokens):
    """Tokens that follow another one (design.py says how each was made): a profile that gives only its good color
    gets its pill and its text in that color too, not the house teal."""
    color = {k: v.lower() for k, v in tokens.get("color", {}).items()}
    for sign in ("good", "bad"):
        if sign in color:
            color.setdefault(f"{sign}_text", _text_color(color[sign]))
            color.setdefault(f"{sign}_fill", _tint(color[sign], 0.2))
    if "card_bg" in color:  # a registry's text cell is a mark in the card's face (decisions/194)
        color.setdefault("cell_text", color["card_bg"])
    tokens["color"] = color
    if "card_margin" in tokens.get("space", {}):  # edge = gap (187)
        tokens["space"].setdefault("theme_edge", tokens["space"]["card_margin"])


def _rgb(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


def _tint(c, share):
    """c at this share on white, as a solid color (decisions/037)."""
    return "#" + "".join(f"{round(255 + (v - 255) * share):02x}" for v in _rgb(c))


def _text_color(c):
    """c darkened to the contrast floor of text on white (C9)."""
    floor = shell.contrast(design.TEXT_FLOOR, "#ffffff")
    k = 1.0
    while shell.contrast("#" + "".join(f"{round(v * k):02x}" for v in _rgb(c)), "#ffffff") < floor:
        k -= 0.01
    return "#" + "".join(f"{round(v * k):02x}" for v in _rgb(c))


def missing_paths(profile):
    """Paths of the profile that do not exist: not a broken build, a thing the user should know (lint P1)."""
    out = []
    book = profile.get("style_book", {})
    for where, file in [("style_book", book.get("file"))] + [("sources", s.get("file")) for s in profile.get("sources", [])]:
        if file and not (profile["dir"] / file).is_file():
            out.append(f"{where}: no file {file} in {profile['dir']}")
    out += [f"context_dirs: no folder {d}" for d in profile.get("context_dirs", []) if not Path(d).expanduser().is_dir()]
    return out


def context_files(profile):
    """-> (read, skipped): the user's MD in the order a skill reads them, profile's context/ then context_dirs (the
    folders themselves, not below them), within CONTEXT_TOKENS. A context/README.md explains the folder, it is not
    context."""
    files = [p for p in sorted((profile["dir"] / "context").glob("*.md")) if p.name.lower() != "readme.md"]
    for d in profile.get("context_dirs", []):
        files += sorted(Path(d).expanduser().glob("*.md"))
    read, skipped, tokens = [], [], 0
    for p in files:
        tokens += len(p.read_text(encoding="utf-8", errors="replace")) // 4
        (read if tokens <= CONTEXT_TOKENS and not skipped else skipped).append(p)
    return read, skipped


def card(name):
    """What a skill needs to know of the profile, based_on already merged (`tb user-profile`)."""
    p = load(name)
    read, skipped = context_files(p)
    return {**{k: v for k, v in p.items() if k != "dir"}, "dir": str(p["dir"]),
            "context": {"read": [str(f) for f in read], "skipped": [str(f) for f in skipped]},
            "missing": missing_paths(p)}
