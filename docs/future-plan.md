# PC Lifelog Stats: Next Concept

## Core Vision

PC Lifelog Stats should become a local-first personal observatory for screen life.

The point is not to shame the user with raw screen time. The point is to turn PC and Android logs into a readable picture:

- when the day got focused
- when it got scattered
- when Android pulled attention away
- when late-night drift appeared
- what one small change would improve tomorrow

## Product Position

ActivityWatch already provides the strongest foundation: open-source, automatic, cross-platform, and local-first. Its docs state that ActivityWatch stores data locally and does not transmit it to external servers.

Commercial tools such as RescueTime and Rize are strong at interpretation: focus sessions, goals, alerts, reports, focus quality scores, and personalized suggestions. The opportunity here is to keep the local-first trust model while adding that interpretive layer.

## Design Principles

1. Local-first remains sacred
   - Logs, tokens, imports, and sender events stay under `local_data/`.
   - The GitHub repo contains code and mock visuals, never personal history.

2. Make the useful thing visible in three seconds
   - Today total.
   - Android connection state.
   - Focus Score.
   - One sentence that says what kind of day this is.

3. Prefer interpretation over more charts
   - A new chart is only worth adding if it changes what the user understands.
   - The dashboard should say, "This day was scattered because..." rather than only showing more bars.

4. Keep the surface light
   - No noisy notifications by default.
   - No cloud account.
   - No always-on popup.
   - Open from Windows Search when needed.

## Phase 1: Focus Lab

Implemented first because it is high-value and low-risk.

Focus Lab reads the existing timeline and produces:

- Focus Score
- grade: `DEEP`, `STEADY`, `SCATTERED`, or `DRIFT`
- deep work minutes
- context switches
- Android share
- late-night share
- short recommendations

This turns "I used screens for 4.27h" into "today was steady, but Android pull was high."

### Review Notes

The first version had two risks:

- Focus Score could feel like a black box.
- Android could be connected technically, but still not feel alive in the UI.

The next polish pass should make both things more legible:

- show the score breakdown near the score
- show confidence based on analyzed event volume
- show Wi-Fi / 15-minute auto-sync status in the Android panel
- keep recommendations short and specific

### Expert Review: Measurement Integrity

The next sharp issue was not visual. It was measurement integrity.

Early aggregation assigned an event's whole duration to the day and hour where the event started. That is easy to implement, but it becomes wrong when a long activity crosses an hour boundary or midnight.

The corrected design treats every event as a time interval:

- daily totals receive only the seconds that overlap each day
- hourly heat receives only the seconds that overlap each hour
- selected-range rankings receive only the overlap with the selected range
- today's recent records show only the portion that overlaps today
- Android Sender "today" and "period" totals use the same interval logic

This matters because the dashboard is no longer just decorative. Once it gives advice and scores, the underlying accounting has to be trustworthy.

## Phase 2: Goals Without Nagging

Implemented as a light local panel.

The dashboard reads `local_data/goals.json` when present, otherwise it uses default rules:

- Android under N minutes
- screen time under N hours
- deep work over N minutes
- no screen drift after 21:00

The dashboard shows progress, not blame. The goal is to help the user choose the rest of the day, not punish the past.

## Phase 3: Weekly Story

Implemented as the first Story panel. It reads the selected period and summarizes:

- best focus day
- worst drift day
- top Android pull app
- most stable work window
- one next experiment for the coming week

The current version focuses on the simplest reliable story:

- heaviest day
- quietest active day
- front-half/back-half trend
- peak hour
- one next experiment

Markdown export is now available from the dashboard header. It includes:

- Story
- Summary
- Focus Lab
- Score Breakdown
- Goals
- Top Apps
- Daily table

## Phase 4: Categories

Add a local category map:

- Work
- Study
- Research
- Communication
- Entertainment
- Drift

Start with manual rules in a local JSON file. Avoid AI classification until the rule system is useful.

## Phase 5: Better Android Presence

Make Android feel truly connected:

- show "last packet received"
- show "queued/offline estimated"
- show "Wi-Fi-only auto sync"
- show battery-friendly explanation
- optionally show device name

## References Checked

- ActivityWatch FAQ and privacy docs: local-first, data stored on device, no external transmission.
- ActivityWatch downloads/docs: cross-platform watchers and Android support.
- RescueTime features/docs: automatic activity tracking, focus sessions, goals, alerts, reports.
- Rize features: focus metrics, Focus Quality Score, distraction blocking, break suggestions.

## One-Sentence Direction

Make it feel like a private, local "screen-life observatory" that turns raw PC and Android logs into a calm daily reading.
