# NextUp maintainer work program

This is a maintainer execution index for the repository's issues, proposed issue drafts, and agent
prompts. It is not a second roadmap or an authority for product behavior. Live GitHub issues and
accepted decisions/contracts define scope; [the roadmap](ROADMAP.md) defines ordered outcomes;
[the release checklist](RELEASE_CHECKLIST.md) defines evidence gates; and
[Integrations and compatibility](INTEGRATIONS.md) defines implementation and support status.

**Review baseline:** `main` at `f9024aacbfead69bf9afafa93877b9a001f7a59a`, reviewed
2026-11-23. At that point nine issues were open, no pull request was open, and the
[hosted verification at the baseline commit](https://github.com/westondunn/nextup-get-hired/actions/runs/44973000992)
passed. This snapshot is evidence, not an instruction to work from an old commit. Every prompt
requires a fresh clean `origin/main` and a re-read of the live issue before work starts.

## Direction and boundaries

The first public milestone is a **core-only public preview**: guided local setup and the core job
search workflows are validated with job providers, mail, calendar, AI, workflow tools, and other
optional connections off. Google remains the first connection track, but it does not block that
core milestone. P2/P3 ideas and deferred capabilities remain discovery work until their decisions
are accepted.

The work program does not open contributions. It never authorizes automatic job applications,
external messages, or replacement of a user's decisions or edits. Prompts can create a compliant
branch, implement an approved issue, push it, and open a review-ready pull request. They stop before
the `maintainer-approval` workflow and merge. Issue publication, issue closure, wiki publication,
live accounts/providers, repository-rule changes, and full disposable verification each require
their own explicit approval.

## Model routing

| Work shape | Primary model | Why |
| --- | --- | --- |
| Architecture, security, migrations, cross-system behavior, evidence reconciliation, and current-provider research | `gpt-6.2-astra`, `ultra` | These tasks depend on nuanced invariants, failure behavior, and claim/evidence separation |
| Narrow, accepted code/test/documentation changes | `gpt-6.2-sol`, `ultra` | A focused coding model is the better fit once no product decision remains |
| Interactive browser, keyboard, screen-reader, visual, or clean-machine operation | `gpt-6.1-terra`, `ultra` | This is specialist validation; Astra still reviews the resulting evidence and claims |

The exact assignment and any validation model are metadata in each [agent prompt](prompts/README.md).

## Work order

1. **Governance and truth.** The maintainer accepted the interoperability policy tracked in #23 and
   the correspondence contract tracked in #24. Review #28 for acceptance, audit #10 evidence,
   reconcile the live repository rules with the documents, and make workflow lint cover every
   checked-in workflow.
2. **Core public preview:** choose the first platform/packaging path, implement guided setup and
   in-application first run, fix the Today defect, establish the application accessibility
   baseline, prove the six core workflows with integrations off, then run separately approved
   clean-machine and representative-user validation.
3. **Google connection:** after #10 evidence, implement #11, add a guarded off-by-default enablement
   path, extend #12, and perform #14 only with an approved dedicated test Google account containing
   synthetic mailbox and calendar data.
4. **Contract and quality work:** evaluate the second mail adapter after #24, decompose
   correspondence implementation, and schedule the seed, typed-event, and Content/Evidence work
   according to evidence from the core milestone.
5. **Discovery backlog:** evaluate AI implementation, workflow/API/MCP access, calendar
   interoperability, outbound-mail approval, job-source enablement, and frontend architecture.
   Discovery may recommend deferral; it does not authorize its implementation.

Core work is the release-critical path. Independent Google or discovery work may proceed in
parallel only when it does not delay core evidence or weaken the off-by-default boundary.

## Existing open issues

| Issue | Next action | Prompt |
| --- | --- | --- |
| [#3](https://github.com/westondunn/nextup-get-hired/issues/3) | Refresh the stale integration tracker after child decisions; keep it open | [Tracker reconciliation](prompts/open/03-integration-readiness-tracker.md) |
| [#10](https://github.com/westondunn/nextup-get-hired/issues/10) | Audit merged implementation evidence only; do not reimplement | [Google connect evidence](prompts/open/10-google-connect-evidence.md) |
| [#11](https://github.com/westondunn/nextup-get-hired/issues/11) | Implement lifecycle, test, reauthorization, disconnect/revocation, and preservation | [Connection lifecycle](prompts/open/11-google-connection-lifecycle.md) |
| [#12](https://github.com/westondunn/nextup-get-hired/issues/12) | Extend the existing card after #11; do not rebuild PR #56 | [Settings lifecycle](prompts/open/12-google-settings-lifecycle.md) |
| [#14](https://github.com/westondunn/nextup-get-hired/issues/14) | Keep blocked through #11, #12, guarded enablement, and live-account approval | [Clean-machine Google validation](prompts/open/14-google-clean-machine-validation.md) |
| [#25](https://github.com/westondunn/nextup-get-hired/issues/25) | Evaluate Microsoft Graph, OAuth-capable IMAP, and JMAP against the [accepted contract](CORRESPONDENCE_CAPABILITY.md). Deferral is an option. | [Second-adapter evaluation](prompts/open/25-second-email-adapter-evaluation.md) |
| [#28](https://github.com/westondunn/nextup-get-hired/issues/28) | Accept or amend the design, close it as design work, then publish children selectively | [Onboarding acceptance](prompts/open/28-core-onboarding-acceptance.md) |

## Proposed issue drafts

These are reviewable local drafts, not live issues. `proposed` prompts are implementation-oriented;
`discovery` prompts produce decisions or decompositions. The maintainer approves each publication
individually.

### Governance and core preview

| Proposed outcome | Draft | Prompt |
| --- | --- | --- |
| Track execution/governance reconciliation | [Draft](planning/issue-drafts/governance-execution-tracker.md) | [Prompt](prompts/proposed/governance-execution-tracker.md) |
| Reconcile live rulesets and maintainer approval with repository docs | [Draft](planning/issue-drafts/reconcile-live-repository-rules.md) | [Prompt](prompts/proposed/reconcile-live-repository-rules.md) |
| Lint every checked-in GitHub Actions workflow | [Draft](planning/issue-drafts/lint-all-workflows.md) | [Prompt](prompts/proposed/lint-all-workflows.md) |
| Track the core-only public preview | [Draft](planning/issue-drafts/core-public-preview-tracker.md) | [Prompt](prompts/proposed/core-public-preview-tracker.md) |
| Choose the first platform and packaging path | [Draft](planning/issue-drafts/initial-platform-and-packaging-decision.md) | [Prompt](prompts/discovery/initial-platform-and-packaging-decision.md) |
| Implement guided local setup | [Draft](planning/issue-drafts/guided-core-setup.md) | [Prompt](prompts/proposed/guided-core-setup.md) |
| Implement in-application first run and actionable empty states | [Draft](planning/issue-drafts/in-app-first-run.md) | [Prompt](prompts/proposed/in-app-first-run.md) |
| Prove core workflows, persistence, and no unexpected egress | [Draft](planning/issue-drafts/core-workflow-e2e-evidence.md) | [Prompt](prompts/proposed/core-workflow-e2e-evidence.md) |
| Establish the application accessibility baseline | [Draft](planning/issue-drafts/app-accessibility-baseline.md) | [Prompt](prompts/proposed/app-accessibility-baseline.md) |
| Validate each claimed platform from a clean machine | [Draft](planning/issue-drafts/clean-machine-core-validation.md) | [Prompt](prompts/proposed/clean-machine-core-validation.md) |
| Record representative-user and release evidence | [Draft](planning/issue-drafts/representative-user-validation.md) | [Prompt](prompts/proposed/representative-user-validation.md) |
| Fix Today commitments/follow-ups rendering | [Draft](planning/issue-drafts/today-commitments-followups.md) | [Prompt](prompts/proposed/today-commitments-followups.md) |

### Connections, governance publication, and product quality

| Proposed outcome | Draft | Prompt |
| --- | --- | --- |
| Add explicit guarded Google enablement while defaults remain off | [Draft](planning/issue-drafts/guarded-google-enablement.md) | [Prompt](prompts/proposed/guarded-google-enablement.md) |
| Synchronize and separately publish reviewed wiki summaries | [Draft](planning/issue-drafts/sync-publish-wiki.md) | [Prompt](prompts/proposed/sync-publish-wiki.md) |
| Make seed preview/apply one bounded atomic plan | [Draft](planning/issue-drafts/seed-import-hardening.md) | [Prompt](prompts/proposed/seed-import-hardening.md) |
| Replace metric text parsing with typed pursuit events | [Draft](planning/issue-drafts/typed-pursuit-events.md) | [Prompt](prompts/proposed/typed-pursuit-events.md) |
| Cover Content and Evidence API contracts | [Draft](planning/issue-drafts/content-evidence-contract-tests.md) | [Prompt](prompts/proposed/content-evidence-contract-tests.md) |

### Discovery backlog

| Proposed outcome | Draft | Prompt |
| --- | --- | --- |
| Decompose correspondence-contract implementation | [Draft](planning/issue-drafts/correspondence-implementation-decomposition.md) | [Prompt](prompts/discovery/correspondence-implementation-decomposition.md) |
| Decompose optional AI consent, adapter, integration, and evaluation | [Draft](planning/issue-drafts/ai-implementation-decomposition.md) | [Prompt](prompts/discovery/ai-implementation-decomposition.md) |
| Decide the workflow/API/MCP boundary | [Draft](planning/issue-drafts/workflow-api-mcp-boundary.md) | [Prompt](prompts/discovery/workflow-api-mcp-boundary.md) |
| Evaluate calendar interoperability beyond Google | [Draft](planning/issue-drafts/calendar-interoperability-evaluation.md) | [Prompt](prompts/discovery/calendar-interoperability-evaluation.md) |
| Define an outbound-mail approval contract | [Draft](planning/issue-drafts/outbound-mail-approval-contract.md) | [Prompt](prompts/discovery/outbound-mail-approval-contract.md) |
| Evaluate safe enablement of existing job sources | [Draft](planning/issue-drafts/job-source-enablement-evaluation.md) | [Prompt](prompts/discovery/job-source-enablement-evaluation.md) |
| Evaluate frontend navigation, loading, and view boundaries | [Draft](planning/issue-drafts/frontend-architecture-evaluation.md) | [Prompt](prompts/discovery/frontend-architecture-evaluation.md) |

## Draft publication lifecycle

1. Rebase the draft against current `origin/main`, its dependencies, and current primary sources.
2. Review one draft with the maintainer. Approval of one does not approve the directory.
3. Create the issue only when explicitly authorized; record blocked-by/parent relationships.
4. Replace `issue: pending` in the matching prompt, add the live link here and in the roadmap where
   appropriate, and remove the draft in a review-ready documentation pull request.
5. Run implementation prompts only after the issue contains every required interface, failure,
   migration, preservation, and evidence decision. A discovery result may end in deferral.

## Verification

Run the planning-pack check after any prompt or issue-draft change:

```sh
python3 scripts/check_planning_pack.py
python3 -m unittest discover -s scripts/tests -p 'test_planning_pack.py' -v
```

The check validates prompt metadata and sections, unique work IDs, repository-path references,
relative Markdown links, issue-draft structure, and one matching proposed/discovery prompt per
draft. Documentation validation does not authorize `NEXTUP_INTEGRATION_APPROVED=1`; product prompts
must request that opt-in for each full-verification run.
