---
name: draft-style
description: Choose a style before drafting an HTML dashboard mock or an Artifact mock, and draw the mock in it, so that the mock and the Tableau book look alike. Use when the user asks to draft, prepare or prototype an HTML mock of a dashboard for Tableau, or asks to pick a style for a mock.
---

# Style of a mock

The mock and the book take their look from one profile, chosen once (decisions/195).

## 1. Choose
`python -m tbuilder profile-css --list`, then one AskUserQuestion with the profiles from that list as options, `house` among them, each with its colors and source. The user named a profile already: skip the question. The style they want is a workbook with no profile yet: run `/copy-style` first.

## 2. Draw
`python -m tbuilder profile-css <name>` prints a CSS block. Put it whole into the mock's `<style>`, its first line `/* tb profile-css <name> */` included: `tb analyze` reads the name from that line, and `/to-tableau` builds the book in this profile. An Artifact takes the same block.

Colors, font sizes and gaps in the mock come from these variables (`var(--tb-color-accent)`, `var(--tb-font-block-title)`, `var(--tb-space-card-margin)`), not from values typed in. What a variable holds is what the book gets, so a color typed in by hand shows only in the mock.

A chart library that takes colors in JavaScript reads them with `getComputedStyle(document.documentElement).getPropertyValue("--tb-color-accent")`.

## 3. Keep it buildable
The numbers are written into the page, not loaded by a page capability: `tb analyze` opens the local file in headless Chrome, where those do not run. The data file stays separate: `/to-tableau` needs it.

## 4. Change of style
Replace the block and leave the rest of the mock. Another profile in the book than in the mock is a lint P4 warning.
