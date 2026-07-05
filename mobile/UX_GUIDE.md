# SafeKids Mobile — UX Guide

- **Date:** 2026-07-06 (Sprint 15, Mobile UX 1.0)
- **Audience:** anyone designing or reviewing SafeKids screens
- **Grounding:** docs/02 (values), docs/04 (AI ethics), docs/13–14 (personas & journey)

## Who this is for

A kindergarten director — busy, not technical, often holding a phone in
one hand. Every design decision optimizes for **calm confidence**: the
app must answer "is everything okay?" in one glance and "what do I do?"
in one tap.

## Voice and tone

- The AI **suspects**, humans **decide**. Copy always says *potential*
  fall; nothing in the app ever accuses a person. People are track
  numbers, never names or faces.
- No jargon in operator-facing text. "Box unreachable — showing the last
  known snapshot", not error codes.
- Honesty over reassurance: offline states, stale data and unsupported
  actions are labeled as such, always with what happens next.

## Information architecture

Five tabs, ordered by the director's questions:

1. **Dashboard** — is everything okay? (status, cameras, recent
   incidents, CPU/RAM, last sync)
2. **Alerts** — what needs my attention? (unread/read/archived shelves,
   search, severity & camera filters, date groups)
3. **Cameras** — are my rooms covered? (per-camera status, FPS, counters,
   restart)
4. **Health** — is the box itself well? (subsystems, host gauges, network)
5. **Settings** — how do I want to be alerted? (theme, language,
   sensitivity, quiet hours)

Incident review is a **pushed** page (back always returns to context).
Pairing is a wizard outside the shell; the app cannot wander unpaired.

## Color language

| Meaning | Color | Usage |
|---|---|---|
| calm / healthy | green | status dots, connected chip — never on alerts |
| low severity | blue-grey | severity dot/chip |
| medium | orange | severity, degraded states |
| high | deep orange | severity |
| critical / error | red 700 | severity, unhealthy camera, error status |

Severity color is the *only* red in the app; screens at rest are neutral.
Both light and dark themes derive from the Guardian green seed
(`#1F6E43`) via Material 3.

## Alerting rules (the most important UX decision)

- A live alert raises a colored banner with one action (open the
  incident). It never blocks the screen.
- **Sensitivity** = minimum severity that alerts. **Quiet hours** soften
  the rest. **CRITICAL always comes through** — no setting can silence an
  emergency; the settings screen says so explicitly.
- The alert list itself is never filtered by these settings — they shape
  interruption, not information.

## Localization

Uzbek, Russian and English ship together; the default follows the system.
Rules: no concatenated sentences (full strings in ARB), dates/times
rendered locally, translations must fit 390 px wide — long labels
truncate with ellipsis, never overflow (enforced by golden tests).

## Evidence and privacy in the UI

The incident page shows a timeline of candidate events with per-signal
score bars — the AI's reasoning, made legible. The evidence section
states plainly: metadata only, no images or video ever leave the box.
Absence of pictures is a feature; the UI explains it rather than
apologizing for it.

## Offline behavior

Every screen renders from the cache first. Offline adds an amber banner
and (on status screens) the snapshot's age. Local actions (read, archive,
settings) work offline and persist; box actions (confirm/dismiss,
restart) fail honestly with retry guidance.

## Accessibility & ergonomics

- Touch targets ≥ 44 px; primary actions are full-width buttons.
- Status is never conveyed by color alone — always dot + label.
- Text scales with system font size; layouts use flexible rows
  (`KeyValueRow`) that truncate rather than overflow.
