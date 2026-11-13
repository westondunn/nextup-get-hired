# Wiki drafts

The files in this directory are the reviewed sources for the [GitHub wiki](https://github.com/westondunn/nextup-get-hired/wiki). As of 2026-11-13 the Home and Roadmap pages are published (wiki revision `bfd088d`, from repository commit `6548863`). Their drafts here have changed since then and have not been republished. An Integrations page is drafted and unpublished. The other pages are not drafted.

The wiki is a separate Git repository with no pull-request review. To keep one reviewed source, wiki pages are short summaries that link back to the canonical documents here and to the live issues.

## Source-to-page mapping

| Draft | Wiki page | Canonical source | Status |
| --- | --- | --- | --- |
| [Home.md](Home.md) | [Home](https://github.com/westondunn/nextup-get-hired/wiki) | [README.md](../../README.md) | Published 2026-11-13 from `6548863`; draft changed since, not republished |
| [Roadmap.md](Roadmap.md) | [Roadmap](https://github.com/westondunn/nextup-get-hired/wiki/Roadmap) | [docs/ROADMAP.md](../ROADMAP.md), [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) | Published 2026-11-13 from `6548863`; draft changed since, not republished |
| not drafted | Contributor Guide | `CONTRIBUTING.md` (not yet written) | Waiting on the source |
| not drafted | Architecture | README architecture section, [decision records](../decisions/) | Not drafted |
| [Integrations.md](Integrations.md) | Integrations | [docs/INTEGRATIONS.md](../INTEGRATIONS.md), [decision 0002](../decisions/0002-standards-first-interoperability.md) | Drafted, unpublished |
| not drafted | Integration Setup | setup guide (not yet written) | Waiting on the source |
| combined into Roadmap | Release Status and Known Limitations | [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md), [SECURITY.md](../../SECURITY.md) | Published 2026-11-13 as part of Roadmap; draft changed since |

## Publishing steps

Publish only after the canonical document is merged to `main` and the maintainer approves publication.

1. Clone the wiki: `git clone https://github.com/westondunn/nextup-get-hired.wiki.git`.
2. Check the current revision of each page you will change, and keep unrelated pages as they are.
3. Copy the draft without its first quoted line, replace the relative links with full links (file paths on GitHub are case-sensitive), and record the source commit and synchronization date at the foot of the page.
4. Commit and push to the wiki repository, then open each page and confirm that its links resolve.
5. Update the status column and the revision recorded above in a documentation pull request.
