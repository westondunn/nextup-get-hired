# Wiki drafts (unpublished)

The files in this directory are staged drafts for the GitHub wiki. **None of them is published.** As of 2026-11-13 the wiki is enabled for the repository but has no pages.

The wiki is a separate Git repository with no pull-request review. To keep one reviewed source, wiki pages are short summaries that link back to the canonical documents here and to the live issues.

## Source-to-page mapping

| Draft | Wiki page | Canonical source | Status |
| --- | --- | --- | --- |
| [Home.md](Home.md) | Home | [README.md](../../README.md) | Drafted, unpublished |
| [Roadmap.md](Roadmap.md) | Roadmap | [docs/ROADMAP.md](../ROADMAP.md), [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) | Drafted, unpublished |
| not drafted | Contributor Guide | `CONTRIBUTING.md` (not yet written) | Waiting on the source |
| not drafted | Architecture | README architecture section, decision records (not yet written) | Waiting on the source |
| not drafted | Integration Setup | setup guide (not yet written) | Waiting on the source |
| combined into Roadmap | Release Status and Known Limitations | [docs/RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md), [SECURITY.md](../../SECURITY.md) | Drafted, unpublished |

## Publishing steps

Publish only after the canonical document is merged to `main` and the maintainer approves publication.

1. Create the first wiki page once in the GitHub web interface (the wiki repository does not exist until then).
2. Clone the wiki: `git clone https://github.com/westondunn/nextup-get-hired.wiki.git`.
3. Check the current revision of each page you will change, and keep unrelated pages as they are.
4. Copy the draft, replace the relative links with full links to the files on `main`, and fill in the source commit and synchronization date at the foot of the page.
5. Commit and push to the wiki repository, then open each page and confirm that its links resolve.
6. Update the status column above in a documentation pull request.
