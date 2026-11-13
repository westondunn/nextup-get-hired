# Roadmap and release status

> Repository copy of the published wiki [Roadmap](https://github.com/westondunn/nextup-get-hired/wiki/Roadmap) page. See [README.md](README.md) in this directory.

This page is a summary. The ordered outcomes are in [docs/ROADMAP.md](../ROADMAP.md), the readiness gates are in [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md), and live status is in the [tracking issue](https://github.com/westondunn/nextup-get-hired/issues/3).

| Phase | Aim | State on 2026-11-13 |
| --- | --- | --- |
| P0 | Tracking baseline and a local session boundary for the unauthenticated API | Planned; issues filed |
| P1 | Connect a Google account for read-only Gmail and Calendar | Planned; issues filed |
| P2 | Portable, optional n8n workflows | Planned; not yet tracked |
| P3 | Optional AI and operations tooling | Planned; not yet tracked |

## Known limitations

- The API has no authentication; ports are published on the loopback interface only.
- No external integration can be enabled in a supported way.
- No platform is supported yet.

See the [security policy](../../SECURITY.md) for the full list and for how to report a vulnerability privately.

Published from commit `6548863`. Last synchronized: 2026-11-13 (wiki revision `bfd088d`).
