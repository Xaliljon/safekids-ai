# hardware/

Physical design of the **Guardian Edge Box**: bill of materials, schematics,
enclosure design, thermal notes, and platform specifications for the supported
targets — NVIDIA Jetson (primary) and Intel N100 (secondary).

## What belongs here

- BOM per hardware revision (versioned: `rev-a/`, `rev-b/`, …)
- Enclosure CAD / drawings
- Camera & microphone compatibility lists (RTSP/ONVIF)
- Power, thermal, and mounting documentation

## Rules

- Hardware is modular and replaceable (ENGINEERING.md hardware principles); the `edge/` runtime declares which targets it supports, not the other way around.
- No application logic here. Software that runs on the box lives in `edge/`; OS image and provisioning live in `firmware/`.
- Hardware failures must never corrupt user data (docs/03) — storage design decisions get documented here and reviewed against that rule.
