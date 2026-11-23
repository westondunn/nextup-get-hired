# Agent prompt pack

These prompts are maintainer execution aids. They are **not authoritative**: the live
GitHub issue, accepted decision records, capability contracts, `docs/ROADMAP.md`,
`docs/RELEASE_CHECKLIST.md`, and `docs/INTEGRATIONS.md` control whenever they disagree.

Before using any prompt:

1. Fetch `origin`, start from a clean current `origin/main`, and record its full commit.
2. Re-read the live issue and its linked pull requests, comments, decisions, and evidence.
3. Reconcile changed facts before editing. Never assume the reviewed commit in a prompt is
   still current.
4. Use the prompt's primary model and reasoning effort. A validation model is a specialist
   second pass, not permission to broaden scope.

The directories distinguish live issue work from proposed and discovery work:

- `open/`: executable prompts for existing issues.
- `proposed/`: prompts paired with an unfiled issue draft. Publish the issue first.
- `discovery/`: bounded research or decision work, not authorization to implement its result.

## Universal execution boundary

Prompts may create a compliant branch, implement their stated outcome, run authorized checks,
push the branch, and open a review-ready pull request. They must stop before running the
`maintainer-approval` workflow or merging. They do not authorize creating or closing issues,
publishing the wiki, changing repository rules, using a live account, or any other external
mutation that the prompt does not name.

Never set `NEXTUP_INTEGRATION_APPROVED=1` without explicit permission for that specific run.
Full verification, migration round trips, and browser tests use a disposable stack but remain
approval-gated. Use synthetic data and mocked providers unless a separately approved validation
prompt explicitly says otherwise.

Preserve loopback-only publication, disabled-by-default integrations, user records and edits,
and the manual approval boundary for applications and correspondence. Never expose credentials
or personal data. Never edit a pinned migration or `backend/migrations/LINEAGE.sha256`; a schema
change uses the next `oss_NNNN` revision through the guard.

## Metadata

Every executable prompt has one-line metadata between `---` delimiters. `issue` is a number for
a live issue and `pending` for an approved draft that has not been filed. `depends_on` and
`approval_gates` use comma-separated values or `none`. `canonical_sources` lists the minimum
sources that must be refreshed before work begins. `last_reviewed_commit` is evidence of the
prompt's baseline, not a commit to check out blindly.

Copy [TEMPLATE.md](TEMPLATE.md) for new work and keep every required section. The work-program
validator checks the metadata, headings, unique work IDs, local paths, and matching issue drafts.
