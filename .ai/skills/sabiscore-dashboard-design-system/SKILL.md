---
name: sabiscore-dashboard-design-system
description: >
  Designs and audits SabiScore dashboard visuals for prediction confidence
  and verdict states — UNVERIFIED/OFFLINE_VALIDATED/SHADOW/FORECAST_ONLY/
  ACTIONABLE_CERTIFIED and SPECULATIVE/HIGH_CONVICTION betting verdicts.
  Enforces that styling never implies more certainty than the data
  warrants: SHADOW cannot read like ACTIONABLE_CERTIFIED, and verdict
  distinctions must be color-blind safe, not color-only. Verifies real
  design tokens from the live codebase (globals.css, tailwind config)
  rather than persona-brief hex codes. Covers dark-mode analytics UI: odds
  tables, probability bars, confidence gauges, fixture cards, WCAG AA
  legibility for dense numerics. Complements, doesn't duplicate, generic
  accessibility-system-architect/design-token-system-architect skills — SabiScore
  verdict/confidence-state specific. Triggers: "dashboard design", "verdict
  badge", "confidence gauge", "prediction UI", "SabiScore design system",
  "odds table design", "watchlist styling", "SHADOW vs CERTIFIED", "verdict
  color", "fixture card design".
argument-hint: "[surface: fixture_card | verdict_badge | odds_table | confidence_gauge | full_dashboard]"
allowed-tools: Read, Grep, Bash(grep -n:*)
user-invocable: true
---

# SabiScore Dashboard Design System

## Purpose

SabiScore's UI has to do something most dashboards don't: represent
*epistemic status* honestly. A prediction sitting at `SHADOW` and one sitting
at `ACTIONABLE_CERTIFIED` are different in kind, not just in a badge label —
one has never been checked against a real result and the other has settlement
history behind it. If the visual design doesn't carry that distinction
loudly, the UI is making a claim the data doesn't support, which is the same
failure class as a fabricated accuracy number, just rendered instead of
printed. This skill exists to keep the interface as honest as the backend
invariants require.

## Non-negotiable: verify tokens against HEAD, not a brief

Before proposing or auditing any color, type scale, or spacing value, locate
the actual source of truth in the repo — `globals.css`, `tailwind.config.*`,
or a dedicated tokens file — and read it. Do not carry over hex codes,
font pairings, or palette descriptions from a persona brief or prior prompt
without checking them against what's actually defined in code. This mirrors
the CA-7/CA-9 discipline already established for the backend stack: briefs
go stale, HEAD doesn't lie (as long as you actually read it).

If no tokens file exists yet, say so and propose one — don't invent values
and present them as if they were already established.

## The verdict/status visual hierarchy

Two independent status systems exist and must stay visually distinguishable
from each other, not just internally consistent:

**Promotion ladder** (pipeline maturity of the prediction itself):
`UNVERIFIED → OFFLINE_VALIDATED → SHADOW → FORECAST_ONLY → ACTIONABLE_CERTIFIED`

**Betting verdict** (the engine's confidence conclusion, gated by
`critical_gaps`): `SPECULATIVE` watchlist vs `HIGH_CONVICTION`, subject to the
`PARTIAL` gate and UCL cap.

Rules for both:
1. **Never let a lower-maturity or lower-conviction item borrow the visual
   weight of a higher one.** No matching color family, no matching badge
   shape, no matching size/emphasis. If `ACTIONABLE_CERTIFIED` gets a solid
   fill, `SHADOW` should not also get a solid fill in a different hue —
   solid-fill itself should read as "this has been checked."
2. **Distinction must survive grayscale and common color-vision deficiencies.**
   Run any proposed verdict palette through a protanopia/deuteranopia check
   conceptually — if two states are only distinguishable by hue at similar
   lightness, that's a defect, not a style choice. Prefer shape, icon, or
   position redundancy alongside color, never color alone.
3. **`SPECULATIVE` items are never given confident framing** — no bold
   headline treatment, no prominent stake/EV display styled the same as a
   certified pick. If a component would make a SPECULATIVE watchlist entry
   look like a strong recommendation, that's the same defect as reporting an
   unsourced accuracy number: visual overconfidence standing in for evidence
   that doesn't exist yet.
4. Status labels appear as text somewhere in every verdict component, never
   conveyed by color/icon alone — this is both an accessibility requirement
   and a corollary of rule 1.

## Data-density patterns

Betting/analytics dashboards are numeric-dense by nature. Default patterns:

- **Odds tables**: tabular-nums font-feature, right-aligned numerics,
  consistent decimal precision within a column, muted zebra striping only if
  it doesn't reduce contrast below WCAG AA on the numeric text itself.
- **Probability bars/gauges**: label the number, don't rely on bar length
  alone to communicate a probability — bar length differences below ~10
  percentage points are hard to compare visually.
- **Confidence gauges**: reserve for values that have cleared the calibration
  bar (see the settlement-calibration-architect skill); do not render a
  confidence gauge for a `SPECULATIVE`/pre-settlement prediction — that's
  rule 3 applied to a specific component.
- **Fixture cards**: league/kickoff time/team identity must be
  `canonicalLeagueId()`-consistent with the backend — if the card displays a
  league name or team that doesn't match canonical identity, that's a defect
  to flag, not just a display bug.

## WCAG AA baseline

Body and data text: 4.5:1 contrast minimum against its background. Large
text (badges, headlines) may use the 3:1 large-text threshold, but verdict
badges specifically should meet 4.5:1 regardless, since a misread verdict
badge has real-money consequences beyond typical readability concerns.
Keyboard focus states and touch targets follow the same standard as the rest
of the platform's components — don't relax them for this surface.

## Zero-fabrication constraint

Don't invent a design token, don't invent a hex value "in the spirit of" a
described palette, and don't claim a component is accessible without
actually checking contrast ratios against the real background/foreground
pair defined in code. If contrast can't be verified in-session (no live
render, no computed styles available), say that plainly rather than
asserting AA compliance.

## Output contract

A response from this skill states, per surface touched: (a) which token
source was checked and what it actually contained, (b) how the proposed or
audited treatment keeps the two status systems visually distinct per the
rules above, (c) any contrast/accessibility check performed and its result
or the reason it couldn't be performed, and (d) whether any canonical
identity mismatch was found in fixture/team/league display.
