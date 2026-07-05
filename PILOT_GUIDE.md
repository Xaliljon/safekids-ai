# Guardian Edge Box — Pilot Guide

For the kindergarten pilot team. No programming knowledge required.
Every command below is typed in a terminal on the Guardian Edge Box.

## What this box does

The box watches the RTSP cameras you connect to it and uses on-device AI
to detect **potential** safety events (currently: possible falls). When it
sees one, it sends a notification to the paired staff phones on the local
network. **A human always verifies** — the box never accuses anyone, and
staff confirm or dismiss every alert in the SafeKids app.

**Privacy:** video never leaves the box and is never stored. Notifications
contain metadata only (time, camera, event type) — no images, no video, no
names. The box works fully offline; it does not need internet.

## 1. Installation (once)

```bash
git clone <release-tag> guardian-ai && cd guardian-ai
GUARDIAN_HOME=~/guardian ./deploy/install.sh
```

The installer checks the machine (Python, memory, disk, network), installs
everything, and writes a report to `~/guardian/reports/install-report.json`.
If a check fails, it tells you what to fix and stops.

## 2. Connect the cameras (once)

```bash
guardianctl wizard
```

The wizard scans the network for cameras, then asks for each camera's
RTSP address (it is on a sticker or in the camera's manual, like
`rtsp://user:password@192.168.1.50:554/stream1`). It tests every camera —
connection, picture size, frames per second — before saving.

To test a camera again later: `guardianctl test-camera room-1`

## 3. Start the box

```bash
sudo systemctl start guardian-edge     # starts now, and on every boot
```

Pair the staff phones with the SafeKids app (the app asks for the box's
IP address and a 6-digit code the box displays).

## 4. Daily use

Nothing. The box runs itself: it restarts anything that crashes,
reconnects cameras that drop, and keeps working through network
interruptions. Check on it whenever you like:

```bash
guardianctl health
```

```
status: ok   version: 0.2.0
cpu 23%  ram 41%  disk 18%  temp 52°C
  ✓ cameras: ok
  ✓ inference: ok
  ✓ tracking: ok
  ✓ risk: ok
  ✓ notifications: ok
```

`status: warning` means the box is still working but wants attention —
the lines below tell you what.

## 5. If something seems wrong

```bash
guardianctl diagnose
```

This tests every part of the system (cameras, AI, tracking, notifications,
phone connection) and prints problems **with recommendations**, for example
"1 camera(s) unreachable — check camera power, cabling and RTSP
credentials". A report is saved to `~/guardian/reports/` — send that file
to Guardian AI support if you need help.

Common fixes:

| Symptom | Do this |
| --- | --- |
| A camera shows ✗ | Check the camera's power and cable, then `guardianctl test-camera <id>` |
| Phones get no notifications | `guardianctl health` — check `notifications` and that phones are on the same Wi-Fi |
| Box seems frozen | Restart it: `sudo systemctl restart guardian-edge` |
| Anything else | `guardianctl diagnose`, send the report to support |

## 6. Backup (recommended monthly)

```bash
guardianctl backup
```

Saves the camera setup and paired phones to a small zip in
`~/guardian/backups/`. Copy it to a USB stick. After replacing or
re-imaging a box: install (step 1), then
`guardianctl restore <backup.zip>`, then restart.

The backup never contains video, images, or logs.

## 7. Updating / rolling back

Follow [deploy/README.md](deploy/README.md) — in short: backup, stop the
service, check out the new (or previous) release tag, re-run the
installer, restore, start. Release contents are in
[deploy/RELEASE_NOTES.md](deploy/RELEASE_NOTES.md).

## What the pilot version can and cannot do

- Detects **possible falls** of people in view. It does not recognize
  faces, does not identify children, does not detect fights or crying —
  those are future work.
- Every alert is "potential" by design. Expect some false alarms,
  especially in the first weeks; dismissing them in the app is part of
  the pilot and helps tune the system.
- The box trusts your local network (phones and cameras on the same LAN).
  Keep the Wi-Fi password private.

Emergency contact: Guardian AI support — attach the newest files from
`~/guardian/reports/` to any message.
