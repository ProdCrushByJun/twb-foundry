# twb-foundry

Builds a Tableau workbook (.twbx) in the style of workbooks you like and checks it in real Tableau Desktop 2025.1.

## Rules
- Zero errors: a file is not handed over unless it passed the gate.
- Acceptance: it opens clean in Tableau Desktop 2025.1 and its numbers match the source.
- Pipeline: HTML → `spec.json` (LLM) → generator on templates saved by Desktop (deterministic code) → gate.
- Workbooks are in English.
- `tests/` run without Desktop: `python tools/ptest.py`. `python -m tbuilder regress --no-unit` checks specs and goldens; `--desktop` also opens books in Desktop.

## Layout
- `tbuilder/`: generator, checks, commands.
- `.claude/skills/`, `.claude/agents/`: `/copy-style`, `/pick-charts`, `/draft-style`, `/to-tableau`, `dashboard-designer`.
- `procedures/html-to-spec.md`, `context/design-rules.md`: mapping and design rules.
- `profiles/`: the house style, an example; your own profiles stay out of git.
- `golden/`, `specs/`, `acceptance/`, `tests/`: baselines saved by Desktop, specs, synthetic cases, tests.

Comments like `decisions/052` point to the project's design log, which is not published.
