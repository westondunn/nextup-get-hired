# Wiki drafts

The files in this directory are the reviewed sources for the [GitHub wiki](https://github.com/westondunn/nextup-get-hired/wiki). As of 2026-11-14 the Home, Roadmap and Integrations pages are published. Home and Integrations were last synchronized from repository commit `ea8b896` on 2026-11-13, and Roadmap from `de6bc87` on 2026-11-14; the wiki is at revision `9d62f1b`. The other pages are not drafted. The Integrations draft has been updated and has not been republished, so the published page is older than the draft.

The wiki is a separate Git repository with no pull-request review. To keep one reviewed source, wiki pages are short summaries that link back to the canonical documents here and to the live issues.

## Source-to-page mapping

| Draft | Wiki page | Canonical source | Status |
| --- | --- | --- | --- |
| [Home.md](Home.md) | [Home](https://github.com/westondunn/nextup-get-hired/wiki) | [README.md](../../README.md) | Published 2026-11-13 from `ea8b896` |
| [Roadmap.md](Roadmap.md) | [Roadmap](https://github.com/westondunn/nextup-get-hired/wiki/Roadmap) | [docs/ROADMAP.md](../ROADMAP.md), [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) | Published 2026-11-14 from `de6bc87` |
| not drafted | Contributor Guide | [CONTRIBUTING.md](../../CONTRIBUTING.md) | Not drafted; the source was merged on 2026-11-14 as `e9628bd` |
| not drafted | Architecture | README architecture section, [decision records](../decisions/) | Not drafted |
| [Integrations.md](Integrations.md) | Integrations | [docs/INTEGRATIONS.md](../INTEGRATIONS.md), [decision 0002](../decisions/0002-standards-first-interoperability.md) | Published 2026-11-13 from `ea8b896`; draft updated, not republished |
| not drafted | Integration Setup | setup guide (not yet written) | Waiting on the source |
| combined into Roadmap | Release Status and Known Limitations | [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md), [SECURITY.md](../../SECURITY.md) | Published 2026-11-14 as part of Roadmap, from `de6bc87` |

## Publishing steps

Publish only after the canonical document is merged to `main` and the maintainer approves publication.

1. Clone the wiki: `git clone https://github.com/westondunn/nextup-get-hired.wiki.git`.
2. Check the current revision of each page you will change, and keep unrelated pages as they are.
3. Copy the draft without its title and first quoted line, replace the relative links with full links (file paths on GitHub are case-sensitive), and record the source commit and synchronization date at the foot of the page.
4. Commit and push to the wiki repository, then open each page and confirm that its links resolve.
5. Update the status column and the revision recorded above in a documentation pull request.
