# Design direction for the plasmon dashboard

Written by the agent at the owner's request; the owner can replace any line. Agent-written
direction tends toward default taste, so every choice below carries its reason.

## Reading

Operations dashboard for two audiences: an admin who watches a fleet, and an employee who
lends a PC and wants one answer ("is my machine training, and what?"). Technical buyers,
but also non-technical staff.

Dial: ENERGY 1 / RHYTHM 2 / MOTION 1.

- ENERGY 1: the content is live numbers and tables. A calm surface keeps attention on them.
- RHYTHM 2: pages share one grid, but the first block of every page is different in shape
  (a large status line, a chart, a two-column panel) because each page answers a different
  question.
- MOTION 1: hover and focus states, and one loading indicator. Live data changes in place
  without animation so a table that refreshes every few seconds does not flicker.

## Identity

- Name and motif: plasmon, a collective wave. One thin sine wave drawn as inline SVG is the
  logo mark and the loading indicator. Sparklines in tables use the same stroke width, so
  every chart reads as part of the same wave.
- Typeface: the system UI stack (`system-ui, -apple-system, Segoe UI, Roboto, …`). Reason:
  no font download, so the dashboard loads on an air-gapped network at full speed, and it
  matches the machine's own UI, which fits a tool that reports on that machine. Tabular
  figures are enabled for every number so columns stay aligned while values change.
- Palette: two neutrals (paper and ink, both with a light and a dark value) plus one
  accent, teal `#0f766e` light / `#5eead4` dark. Reason: the accent is used once per
  screen, on the focal element and on focus rings; teal reads as "signal" without being
  the blue-purple default. Contrast: teal on paper 5.3:1, light teal on dark ink 11:1.
- Status scale (semantic, not decorative; always paired with the word):
  training green, idle blue, paused yellow, unavailable grey, offline red, error magenta.
  Each has a light and a dark value chosen for 4.5:1 against the page background.
- Shape: radius 4 px on inputs and buttons, 8 px on panels. Nothing pill-shaped. Shadows
  are not used; borders separate panels (one hairline), because the pages are dense.
- Layout: a fixed left rail with the pages the role can open, and a content column with a
  maximum width of 1280 px. Below 720 px the rail becomes a horizontal row of links.
- Themes: light and dark, following the system and switchable with a button that
  remembers the choice. Both are checked for contrast.

## Focal points

- Overview: the machines-online count.
- Jobs: the loss curve of the opened job.
- My machine: the status line ("training mnist-home for you, round 12").
- Fleet: the status totals row above the table.
- Server: the scheduler state and the ledger head.

## Copy

Short, factual labels in sentence case. No marketing words. Buttons name the action
("Confirm code", "Cancel job", "Switch theme").
