# Design direction for the plasmon dashboard

Written by the agent at the owner's request and revised with the owner's feedback after
the first version: more energy, live diagrams, motion that shows work. The owner can
replace any line. Every choice carries its reason.

## Reading

Operations dashboard for two audiences: an admin who watches a fleet, and an employee who
lends a PC and wants one answer ("is my machine training, and what?"). Technical buyers,
but also non-technical staff. References the owner named for the feel: Weights & Biases
(dense metric cards and charts), the OpenRouter dashboard (cards with percentages), the
PlanetScale cluster view (boxes connected by paths that move when data flows) and the
Apache Flink job graph. They are references for structure and liveliness, not a skin:
plasmon keeps its own palette and motif.

Dial: ENERGY 2 / RHYTHM 2 / MOTION 2.

- ENERGY 2: the owner asked for a dashboard that feels alive. Cards with one large number
  each, a diagram as the first thing on the overview, colour used for state. Not 3: the
  pages are still about reading numbers.
- RHYTHM 2: each page opens with a different shape (a diagram, a chart, a status line, a
  table) and continues with cards and tables on one grid.
- MOTION 2: motion carries information and nothing else. The inventory is closed:
  1. Marching ants on a path: data is moving on that link right now (a machine training,
     an update in flight). Static when nothing moves.
  2. Pulse ring on a status dot: a live heartbeat was received in the last interval.
  3. Rise-in on first paint: cards and rows appear in order so the eye lands on the
     focal point first. Never replayed on refresh.
  4. Progress bars and numbers change in place with a 200 ms ease; a changed cell gets a
     short background flash.
  5. Skeleton shimmer while a diagram waits for its first data.
  Everything stops under `prefers-reduced-motion: reduce`, and dashes stay static.

## Identity

- Name and motif: plasmon, a collective wave. One thin sine wave drawn as inline SVG is the
  logo mark and the loading indicator. Sparklines and diagram paths use the same stroke
  width, so every line reads as part of one system.
- Typeface: the system UI stack. Reason: no font download, so the dashboard loads on an
  air-gapped network at full speed, and it matches the machine's own UI, which fits a tool
  that reports on that machine. Tabular figures on every number.
- Palette: two neutrals (paper and ink, light and dark values) plus one accent, teal
  `#0f766e` light / `#5eead4` dark. The accent marks the focal element, focus rings,
  progress and the coordinator in diagrams. Contrast: teal on paper 5.3:1, light teal on
  dark 12.8:1.
- Status scale (semantic, always paired with the word):
  training green, idle blue, paused yellow, unavailable grey, offline red, error magenta.
  Light and dark values chosen for 4.5:1 or more against their background. In diagrams
  the same six colours drive the node border, the port dot and the path.
- Shape: radius 4 px on inputs and buttons, 8 px on cards and diagram nodes. Nothing
  pill-shaped except status chips, which are pills because they are read as labels.
- Elevation: cards have a hairline border and one soft shadow (0 1px 2px). Reason: a page
  now holds many small cards and the shadow separates them from the page without heavier
  borders. One level only.
- Layout: a fixed left rail with the pages the role can open, and a content column with a
  maximum width of 1320 px. Metric cards sit on an auto-fill grid of 180 px columns. Below
  720 px the rail becomes a horizontal row of links and cards stack.
- Themes: light and dark, following the system and switchable with a button that
  remembers the choice. Both are checked for contrast.

## Diagrams

- Network diagram (overview, fleet): coordinator on top, running jobs in the middle,
  machines below in rows of six. A machine's path goes to the job it trains, otherwise to
  the coordinator. Node border, port dot and path take the status colour. Marching ants
  only on paths that carry data. Click a node to open its page.
- Job diagram (job page): shards, the trainers of the current round, the aggregation step
  and the resulting weights, left to right. Each trainer's edge shows its state in the
  round: assigned (dashed grey), committed (yellow), revealed (green, moving), accepted or
  rejected after the close.
- Diagrams are SVG drawn by `diagram.js` from the JSON API and updated in place every
  three seconds, so animations do not restart on refresh. They render a skeleton first and
  an error line when the API is unreachable.

## Focal points

- Overview: the network diagram, then the machines-online card.
- Jobs: the loss curve of the opened job; the job diagram shows the round in progress.
- My machine: the status line ("training mnist-home for you, round 12").
- Fleet: the diagram, then the status totals.
- Server: the scheduler state and the ledger head.

## Copy

Short, factual labels in sentence case. No marketing words. Buttons name the action
("Download latest weights", "Cancel job", "Confirm code", "Switch theme").
