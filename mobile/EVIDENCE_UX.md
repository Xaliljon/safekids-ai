# SafeKids Mobile — Evidence UX

- **Date:** 2026-07-06 (Sprint 16)
- **Grounding:** ADR-0017 (evidence management), UX_GUIDE.md, docs/04 (AI ethics)

## What the director experiences

Opening an incident now answers *"what actually happened?"* — not just
*"what did the AI conclude?"*. The review page reads top to bottom as an
explanation:

```
Incident      what and how severe
  ↓
Video         the 30 seconds around the moment (15 s before + 15 s after)
  ↓
AI signals    the strongest signals, as bars — why the AI suspected
  ↓
Timeline      candidate events with per-signal scores over time
  ↓
Review        current status, reviewer, note
  ↓
Decision      Confirm / Dismiss — always the human's call
```

## The two views

A segmented switch above the clip:

- **Original** — the raw camera view. What a person standing there saw.
- **AI analysis** — the same clip with bounding boxes, track numbers
  (never names), confidence, a timeline bar and a red marker at the
  incident moment. What the *AI* saw, made inspectable.

Directors start on **AI analysis**: the goal of evidence is
explainability first, surveillance never. Each view downloads and caches
independently; switching serves from cache when possible.

## Playback states (honest at every step)

| State | UI |
|---|---|
| box exporting | spinner + "preparing the clip (15 s before + after)" |
| export failed | plain-language failure (buffer was empty) — no dead buttons |
| ready, not downloaded | thumbnail poster + Download button + clip facts (duration · date · size) |
| downloading | progress bar with percent |
| downloaded | player: play / pause / replay / scrub / fullscreen |
| no evidence | honest empty state (older box or expired clip) |

No editing, no sharing, no export — the player is the only sink. The
offline note under the player says exactly that.

## Offline behavior

Downloaded clips and thumbnails live in a local cache and play with no
box connection — a director can review evidence away from the building's
Wi-Fi. The cache is size-bounded (Settings → Video evidence: 100/250/500
MB, default 250) and evicts least-recently-watched clips first. "Clear
downloaded evidence" wipes the phone's copies only; the box keeps its
originals under the retention policy (dismissed 24 h, confirmed 30 d,
critical 90 d).

## Privacy posture in the UI

- Evidence reaches the app only over the paired LAN connection; every
  fetch is audited on the box with this device's name.
- Nothing uploads anywhere; there is no share sheet, no save-to-photos,
  no AirDrop path.
- People appear as track numbers in the AI view — identity is never
  attached to a clip.
- When the clip expires on the box, the phone's cached copy ages out of
  the LRU cache; there is no long-term archive on the device.
