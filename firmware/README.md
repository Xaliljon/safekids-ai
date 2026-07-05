# firmware/

Guardian Edge Box **system layer**: OS image build, device provisioning, and
the OTA update mechanism. Everything between bare hardware and the `edge/`
runtime container.

## What belongs here

- OS image build (JetPack-based for Jetson; minimal Linux for N100)
- First-boot provisioning & device registration flow
- Disk encryption setup (storage must be encrypted — CLAUDE.md)
- OTA update client: **signed** bundles, health-check, automatic rollback

## Rules

- Updates are pull-based, signed, and rollback-safe (docs/03 deployment rules). Devices are never pushed to.
- Never trust the network the box is deployed on (docs/03, security by default).
- Application logic stays out — this layer only delivers and supervises the `edge/` runtime.
