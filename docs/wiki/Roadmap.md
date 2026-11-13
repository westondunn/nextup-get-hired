# Roadmap and release status

> Draft for the wiki [Roadmap](https://github.com/westondunn/nextup-get-hired/wiki/Roadmap) page. **This draft has changed since the page was published.** The published page still reflects repository commit `6548863` (wiki revision `bfd088d`). Republish only after these changes are merged; see [README.md](README.md) in this directory.

This page is a summary. The ordered outcomes are in [docs/ROADMAP.md](../ROADMAP.md), the readiness gates are in [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md), and live status is in the [tracking issue](https://github.com/westondunn/nextup-get-hired/issues/3).

| Phase | Aim | State on 2026-11-13 |
| --- | --- | --- |
| P0 | Tracking baseline and a local request boundary for the unauthenticated API | In progress; host and cross-origin checks are merged, the session requirement is not |
| P1 | Connect a Google account for read-only Gmail and Calendar, as the first connection path | Planned; issues filed |
| Not yet placed | Interoperability policy, a shared correspondence contract, evaluation of a second email adapter, an optional AI task contract, a compatibility matrix, and guided setup of the core | Planned; issues filed; priority provisional |
| P2 | Optional workflow access | Planned; not yet tracked |
| P3 | Optional AI assistance and operations tooling | Planned; first AI contract tracked |

## Known limitations

- The API has no authentication; ports are published on the loopback interface only.
- No external integration can be enabled in a supported way, and none has a support status.
- There is no guided setup.
- No platform is supported yet.

See the [security policy](../../SECURITY.md) for the full list and for how to report a vulnerability privately.

Source commit: to be filled in at republication. Published page last synchronized: 2026-11-13, from `6548863`.
