# NextUp Branching and Branch Naming Guide

## 1. Purpose and default workflow

Use a short-lived branch for one reviewable outcome, open a pull request into `main`, verify the change, and squash merge it. Keep `main` as the integration branch—not a claim of production readiness.

This guide takes its naming inspiration from Jack Pritom Soren's [GitHub Branching Name Best Practices][article]: meaningful prefixes, descriptive names, hyphen-separated words, and issue references where useful. The workflow, safeguards, limits, and examples below are NextUp-specific recommendations. GitHub's own [GitHub flow documentation][github-flow] provides the underlying branch-and-pull-request model.

NextUp is a pre-release, single-user application, and its README currently says outside contributions are not yet accepted. This guide establishes a maintainer workflow; it does not change the contribution or release policy. The README describes an architecture using React/TypeScript/Vite, Python/FastAPI, SQLAlchemy/Alembic, PostgreSQL, Celery/Redis, and Docker Compose. [Repository evidence: README][repo-readme]

**Default topology:**

```text
main
  ├── feature/google-oauth-onboarding       → pull request → main
  ├── bugfix/calendar-dst-display           → pull request → main
  └── docs/branching-conventions            → pull request → main
```

Do not add permanent `develop`, `staging`, `production`, `ai`, or personal-environment branches. For NextUp, deployment environments should remain configuration and deployment concerns, not separate product histories. Revisit maintenance branches only after a documented release-support policy requires them. The current security policy maintains only the newest state of `main`. [Repository evidence: SECURITY.md][repo-security]

## 2. Branch name format

```text
type/short-description
type/issue-number-short-description
```

Examples:

```text
feature/google-oauth-onboarding
bugfix/123-calendar-dst-display
docs/branching-conventions
```

`123` is an illustrative issue number, not a verified NextUp issue. Use a real issue number when one exists; do not invent one or make issue creation a prerequisite for a small maintenance change.

### Naming rules

- Use lowercase ASCII letters, digits, and single hyphens within the description. Use exactly one slash, immediately after the type.
- Start the description with a letter. An optional positive issue number goes immediately after the slash, followed by a hyphen. Do not pad issue numbers with zeroes.
- Limit the entire branch name to **80 characters**. This is a NextUp policy choice, not Git's maximum. Prefer a few descriptive words over abbreviations.
- Name the outcome, not the developer, tool, date, or implementation session. Keep employer names, applicant details, email addresses, credentials, and private infrastructure identifiers out of branch names.
- Use one type and one primary outcome. Do not stack prefixes or add directory levels. Put dependencies, secondary issues, and detailed scope in the pull request.

The policy is deliberately narrower than Git's valid-reference syntax. Git's own syntax check is useful, but does not enforce this convention. [Git reference validation][git-ref]

```bash
git check-ref-format --branch feature/google-oauth-onboarding
```

### Approved types

| Prefix | Use when the primary outcome is… | Illustrative NextUp branch |
| --- | --- | --- |
| `feature/` | New user-visible behavior or integration capability. | `feature/google-oauth-onboarding` |
| `bugfix/` | Correction of existing behavior. | `bugfix/calendar-dst-display` |
| `hotfix/` | A narrowly scoped, urgent correction with documented impact. | `hotfix/credential-log-redaction` |
| `design/` | A presentation or interaction improvement without new application rules. | `design/integration-status-layout` |
| `refactor/` | Internal restructuring with intended behavior preserved. | `refactor/correspondence-source-boundary` |
| `test/` | Tests, fixtures, or evaluation coverage without a product behavior change. | `test/email-classifier-disagreement` |
| `docs/` | Documentation, examples, or public-status clarification. | `docs/google-oauth-setup` |
| `chore/` | Dependencies, packaging, or routine maintenance not covered above. | `chore/frontend-dependency-update` |
| `ci/` | CI workflows, checks, or verification infrastructure. | `ci/branch-name-validation` |

Use `docs/`, not the article's `doc/`, to match NextUp's documentation directory. Do not mix aliases such as `feat/` and `feature/` or `fix/` and `bugfix/`.

**Choose by intent.** A feature with accompanying tests remains `feature/`; a regression fix with tests remains `bugfix/`. A known keyboard-accessibility defect is a `bugfix/`, not a cosmetic `design/` task. A change to GitHub Actions is `ci/`; a general container dependency update is normally `chore/`.

A `hotfix/` name conveys urgency only. It does not imply a supported production release, authorize a bypass, or trigger deployment. For the current project, hotfix work starts from current `main` and returns through a pull request into `main`.

### Examples to reject or revise

| Avoid | Reason | Prefer |
| --- | --- | --- |
| `Feature/GoogleOAuth` | Mixed case and compressed wording. | `feature/google-oauth-onboarding` |
| `feature/google/oauth` | Additional slash-delimited level. | `feature/google-oauth-onboarding` |
| `bugfix/fix-stuff` | Does not identify the defect. | `bugfix/calendar-dst-display` |
| `feature/google-api-key` | Misstates the planned user-data authorization mechanism. | `feature/google-oauth-onboarding` |
| `feature/n8n-openwebui-grafana-everything` | Bundles unrelated outcomes. | Separate narrowly scoped branches. |
| `docs/0123-setup-guide` | Issue numbers must not have leading zeroes. | `docs/123-setup-guide` |
| `weston-local-setup` | Personal environment, no approved type. | `docs/optional-integrations-setup` |
| `feature/oauth--setup` | Repeated separator. | `feature/oauth-setup` |

Syntactic validation will not detect vague descriptions, misleading capability claims, or sensitive data that happens to fit the pattern. Human review remains necessary.

## 3. Scope work around NextUp boundaries

The following names are **planning examples, not claims that these capabilities are implemented or publicly supported**.

| Workstream | Small branch examples | Boundary to preserve |
| --- | --- | --- |
| Google account access | `feature/google-oauth-onboarding`; `test/google-token-revocation` | Keep account authorization separate from application authentication. |
| Correspondence | `bugfix/gmail-import-deduplication`; `test/calendar-dst-boundaries` | Preserve user edits; test duplicate delivery and timezone boundaries. |
| Optional workflows | `feature/n8n-summary-workflow`; `docs/n8n-workflow-import` | Keep NextUp authoritative and workflows optional. |
| AI assistance | `feature/ai-provider-adapter`; `test/ai-summary-grounding` | Treat model output as untrusted; retain human review. |
| Operations | `docs/portainer-deployment-notes`; `feature/sync-health-metrics` | Do not make operations tools hidden core dependencies. |
| Database safeguards | `test/migration-identity-refusals`; `refactor/config-validation` | Preserve identity checks, role separation, and historical migration hashes. |

Use draft pull requests for incomplete work. Split a broad initiative into independently reviewable slices rather than maintaining one long-lived integration branch. Prefer branches from `main`; if a temporary stacked change is necessary, document its base and dependency explicitly, then retarget and revalidate after the prerequisite merges.

## 4. Branch lifecycle

### Create from current `main`

These commands assume a maintainer checkout where `origin` points to NextUp. Start with a clean working tree; inspect and resolve existing work before switching branches.

```bash
git status --short
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c docs/branching-conventions
```

After placing this file at `docs/BRANCHING.md`:

```bash
git add docs/BRANCHING.md
git diff --cached --check
git diff --cached
git commit -m "docs: document branching conventions"
git push -u origin docs/branching-conventions
```

Stage explicit paths and inspect the staged diff. These are instructions, not commands executed as part of generating this document. Commit-message prefixes are an example here, not a newly imposed commit-message policy.

### Review, verify, and merge

Open a pull request targeting `main`. Explain the outcome, affected modules, acceptance criteria, test evidence, and remaining risks. Link a real issue with `Closes #123` only when the change actually resolves it; otherwise use a non-closing reference.

Refresh the branch when its base becomes materially stale, resolve conflicts, and rerun affected checks. Do not rewrite another contributor's branch history without agreement. Never force-push `main` as a routine workflow.

Prefer **squash merge** for one coherent change per pull request. The inspected ruleset requires linear history; GitHub documents squash or rebase merging as compatible with that rule. Do not choose a merge-commit method merely because it appears in an allowed-method list. [Ruleset evidence][repo-ruleset]; [GitHub rule behavior][github-rules]

After confirming the pull request is merged and contains all intended work, delete its remote topic branch. Check for unique local commits before deleting a local branch. Do not blindly use forced deletion when Git refuses cleanup after a squash merge. Create a fresh branch from updated `main` for subsequent work.

### Pull request evidence template

```markdown
## Outcome
What changes for the user or maintainer? What is explicitly out of scope?

## Traceability
Related issue or decision; dependencies; base branch and reviewed commit.

## Acceptance criteria
Observable behavior, failure behavior, and manual fallback where relevant.

## Verification
Commands actually run, environment, results, and evidence links.
List skipped or unexecuted checks separately with reasons.

## Safety and compatibility
Secrets and data egress; permissions; migration impact; user-data preservation.
Document rollback or forward-fix steps and their limitations.

## Documentation and public claims
Files updated; distinguish implementation from enabled/validated public capability.
```

## 5. NextUp-specific merge gates

The prefix never reduces the quality bar. Before merging, check the following according to the change's risk:

- **Configuration and data protection:** Preserve deployment identity validation, secret-file handling, database role separation, and loopback-only exposure. Do not restore rejected legacy environment variables as a shortcut. Relevant reviewed files include `backend/app/config.py` and `backend/tests/test_config.py`. [Configuration][repo-config]; [configuration tests][repo-tests]
- **Migrations:** Never edit or reformat pinned historical revisions under `backend/migrations/versions/`. Add new revisions through the established migration process; preserve `backend/migrations/LINEAGE.sha256` and guard behavior. A failing guard is not permission to weaken it. [Development notes][repo-development]
- **Optional integrations:** Keep external services off by default and retain a manual path. Preserve the external-classifier contract: hints must not override authoritative detection or existing links. [Classifier contract][repo-classifier]
- **Verification:** Use synthetic data and isolated environments. Include regression, accessibility, timezone, and failure-path coverage where applicable. For calendar work, include UTC and America/Chicago daylight-saving boundaries. Do not introduce live Google credentials or personal email into CI fixtures.
- **AI and communication:** Require review before outbound or consequential actions. Test unsupported claims, ambiguous matches, prompt injection, and degraded provider behavior when those capabilities are touched. Do not report local-only integrations or proposed AI features as public functionality.

The documented full-verification entry point is:

```bash
NEXTUP_INTEGRATION_APPROVED=1 scripts/verify.sh
```

Run it only with deliberate approval in the intended disposable test environment, following `docs/DEVELOPMENT.md`. The harness is not a way to test against a personal or staging database. The development notes require non-root execution and describe Docker prerequisites. This guide does not modify or bypass that process. [Verification wrapper][repo-verify]; [development notes][repo-development]

The checked-in CI workflow is named `Nextup CI`, with job ID `verify`. It runs `scripts/verify_ci.py` and retains test evidence. Its presence is not proof of a successful hosted run. [CI workflow][repo-ci]

## 6. Existing protection versus proposed enforcement

The repository API was inspected on November 13, 2026. Repository settings can change independently of commits; recheck them when adopting this guide.

| Control | Observed state | Recommended next action |
| --- | --- | --- |
| Default-branch ruleset | `Protect main` is active and targets the default branch. | Retain it; review its effective rules rather than relying only on legacy branch-protection fields. |
| Pull requests | Required by the ruleset; required approval count is `0`. | Keep PRs for traceability. While operating solo, record self-review; add independent approval when a qualified reviewer is available. |
| Linear history | Required. | Use squash merging as the default. |
| Deletion and force pushes | Deletion and non-fast-forward protections are present. | Retain both. |
| Bypass | A role-based bypass is configured in `always` mode. | Review and narrow it where practical; document exceptional use rather than treating it as routine. |
| Required checks | No `required_status_checks` rule appears in the inspected ruleset. | Validate hosted checks, then require their exact emitted names and expected source app. |
| Review conversations | Resolution is not required by the inspected ruleset. | Consider enabling required conversation resolution. |
| Branch naming | Not enforced by the inspected ruleset or `ci.yml`. | Adopt the policy first, then introduce and validate the check below. |

Evidence: [active ruleset][repo-ruleset] and [checked-in CI workflow][repo-ci]. Rulesets and legacy branch protection can coexist; inspect their combined effect. [GitHub rulesets documentation][github-rulesets]

**A policy document or green check alone does not configure a merge gate.** After a successful hosted validation, add the intended check to the ruleset. Do not guess a check name or make an unavailable check required. Documented safeguards remain the expected maintainer practice while enforcement is being established.

## 7. Optional automated naming check

The following is a proposed addition at `.github/workflows/branch-name.yml`. It is included here for review; it has not been installed or executed on GitHub.

The check validates the source branch of pull requests into `main`. It needs no checkout, secrets, package installation, or write permissions. It uses an environment variable rather than interpolating the branch name into shell source. [GitHub secure-use guidance][github-security]; [pull-request events][github-events]

```yaml
name: Branch naming

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened, edited, ready_for_review]

permissions: {}

jobs:
  branch-name:
    name: Branch name policy
    runs-on: ubuntu-24.04
    timeout-minutes: 2
    steps:
      - name: Validate source branch
        env:
          BRANCH_NAME: ${{ github.head_ref }}
        shell: bash
        run: |
          python3 - <<'PY'
          import os
          import re
          import sys

          branch = os.environ.get("BRANCH_NAME", "")
          pattern = (
              r"(?:feature|bugfix|hotfix|design|refactor|test|docs|chore|ci)/"
              r"(?:[1-9][0-9]*-)?[a-z][a-z0-9]*(?:-[a-z0-9]+)*"
          )
          valid = len(branch) <= 80 and re.fullmatch(pattern, branch) is not None
          if not valid:
              print(
                  "::error::Use type/short-description or "
                  "type/issue-number-short-description, maximum 80 characters. "
                  "See docs/BRANCHING.md."
              )
              sys.exit(1)
          print("Branch name satisfies the NextUp naming policy.")
          PY
```

The pattern is strict enough to exclude Git's prohibited reference characters as well as the project's disallowed formats. It intentionally rejects `main` as a **PR source branch**; normal pushes to `main` do not trigger this workflow.

This check is a convention check, not a security boundary. Do not use branch names to authorize secret access, select a personal database, expose services, or deploy—even for `hotfix/`. Review changes to workflow code like any other executable change. Do not introduce a privileged `pull_request_target` workflow that checks out and runs untrusted PR code. [GitHub secure-use guidance][github-security]

For future dependency bots, either configure compliant names or approve a narrow exception backed by verified bot identity. A bot-looking prefix alone must not create an exception. Do not silently grandfather arbitrary names or rename active branches without coordinating their pull requests.

### Validation cases for adoption

| Expected | Input | What it tests |
| --- | --- | --- |
| Pass | `feature/google-oauth-onboarding` | Standard feature. |
| Pass | `bugfix/123-calendar-dst-display` | Positive issue number. |
| Pass | `test/ai-summary-grounding` | AI quality coverage. |
| Pass | `ci/branch-name-validation` | CI-specific type. |
| Fail | `main` | Integration branch is not a topic branch. |
| Fail | `feature/123` | Missing description. |
| Fail | `feature/0-oauth` | Invalid issue number. |
| Fail | `feature/0123-oauth` | Leading-zero issue number. |
| Fail | `feature/oauth--setup` | Repeated hyphen. |
| Fail | `feature/google/oauth` | Additional slash. |
| Fail | `Feature/google-oauth` | Uppercase type. |
| Fail | `feature/oauth$(id)` | Shell-like characters. |
| Fail | An otherwise valid name of 81 characters. | Length boundary. |

Also test an otherwise valid 80-character name, trailing whitespace/newlines, every approved prefix, and missing input. Then verify the workflow on GitHub with both passing and failing PRs before adding it as a required check. Recheck fork-PR behavior when the project opens contributions.

## 8. Adoption sequence and completion criteria

| Slice | Scope | Acceptance criteria |
| --- | --- | --- |
| 1. Document | Add `docs/BRANCHING.md`; link it from `docs/DEVELOPMENT.md`. | Maintainer approves the taxonomy and examples; no implication that outside contributions are open. |
| 2. Automate | Add the optional workflow through `ci/branch-name-validation`. | Positive, negative, length-boundary, and injection-like inputs behave as specified; passing and failing hosted PR evidence is recorded. |
| 3. Enforce | Update the existing default-branch ruleset. | Exact validated check names are required; bypass policy and solo-review expectations are documented; a failing check prevents a normal non-bypass merge. |
| 4. Reuse | Reference this guide in a future contribution guide and PR template. | One authoritative naming policy; no duplicated or conflicting prefix lists. |

Do not combine this documentation change with unrelated application changes or public integration enablement.

### Review and validation record

Repository evidence reviewed includes `README.md`, `SECURITY.md`, `docs/DEVELOPMENT.md`, `docs/CORRESPONDENCE_SYNC.md`, `backend/app/config.py`, `backend/tests/test_config.py`, `scripts/verify.sh`, and `.github/workflows/ci.yml`, together with the current `main` ref and active ruleset. The branch and commit were rechecked for this document; unchanged evidence from the earlier review was reused where applicable.

Document checks: The embedded validator was executed locally against 60 named positive/negative cases (28 accepted; 32 rejected), plus a missing-variable case. All matched the expected outcomes. Every accepted name also passed `git check-ref-format --branch`. Four representative cases passed through the exact workflow shell snippet, including the 80/81-character boundary. YAML parsing, Python syntax, shell syntax, Markdown structure, and source-reference resolution were checked. These are document/example checks, not NextUp application test results.

Not performed: application runtime tests, the full disposable-stack verification, hosted execution of the proposed naming workflow, or end-to-end ruleset enforcement testing. No branches, pull requests, repository files, or GitHub settings were changed by generating this document. Owner-reported local enhancements are not treated as verified public integrations.

## References

### Naming and GitHub behavior

- [GitHub Branching Name Best Practices][article] — Jack Pritom Soren, DEV Community, January 17, 2025; inspiration, not an adopted standard in full.
- [GitHub flow][github-flow] — official workflow guidance.
- [git-check-ref-format][git-ref] — official Git reference-name validation.
- [About rulesets][github-rulesets] and [available rules][github-rules] — official protection behavior.
- [Secure use of GitHub Actions][github-security] and [workflow events][github-events] — official automation guidance.

### NextUp evidence

Source-file links below are pinned to the reviewed commit. The ruleset link reflects live repository configuration rather than versioned source.

- [README.md][repo-readme] and [SECURITY.md][repo-security]
- [docs/DEVELOPMENT.md][repo-development] and [docs/CORRESPONDENCE_SYNC.md][repo-classifier]
- [backend/app/config.py][repo-config] and [backend/tests/test_config.py][repo-tests]
- [scripts/verify.sh][repo-verify] and [.github/workflows/ci.yml][repo-ci]
- [Protect main ruleset][repo-ruleset]

[article]: https://dev.to/jps27cse/github-branching-name-best-practices-49ei
[github-flow]: https://docs.github.com/en/get-started/using-github/github-flow
[git-ref]: https://git-scm.com/docs/git-check-ref-format
[github-rulesets]: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
[github-rules]: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
[github-security]: https://docs.github.com/en/actions/reference/security/secure-use
[github-events]: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request
[repo-readme]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/README.md
[repo-security]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/SECURITY.md
[repo-development]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/docs/DEVELOPMENT.md
[repo-classifier]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/docs/CORRESPONDENCE_SYNC.md
[repo-config]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/backend/app/config.py
[repo-tests]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/backend/tests/test_config.py
[repo-verify]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/scripts/verify.sh
[repo-ci]: https://github.com/westondunn/nextup-get-hired/blob/4aacc0e99ea4f4482454f604cdbdc24d54d883e9/.github/workflows/ci.yml
[repo-ruleset]: https://github.com/westondunn/nextup-get-hired/rules/27214912
