# Core first-run setup

**Status:** Proposed for maintainer review in [#28](https://github.com/westondunn/nextup-get-hired/issues/28). Baseline reviewed at `6e778c6` on 2026-11-20. The design follows the [standards-first policy](decisions/0002-standards-first-interoperability.md).

## Current setup

| Step | What a new user must do or decide |
|---|---|
| Prepare the machine | Obtain a checkout, open a terminal at its root, install Python 3.12 or later and Docker Engine with the Compose plugin, and make sure Docker is running and accessible. The first build needs network access for images and dependencies. The web interface needs a browser. See [development requirements](DEVELOPMENT.md#requirements). |
| Choose configuration | Select the `dev` environment. Leave the default loopback ports (15173 for the frontend and 18000 for the API) unless they conflict with another local service. Resolve conflicts in the development configuration. |
| Check prerequisites | Optionally run `python3 scripts/local.py --env dev doctor`. It checks Docker and configuration without starting services. A fresh checkout may lack the environment file and secrets that `start` provisions. |
| Start | Run `python3 scripts/local.py --env dev start`. The launcher creates missing local configuration and secret files, verifies isolation, builds images and starts services. The first startup can take minutes. The application needs its schema before the health check can report readiness. |
| Initialize the database | Run `python3 scripts/local.py --env dev migrate` in an interactive terminal. Read the guarded plan, then type the displayed confirmation code to apply it. Any other input cancels. The same step is needed again when an update adds a migration. |
| Open and operate | Run `python3 scripts/local.py --env dev status` and open the printed loopback frontend URL once ready. Choose a starting view yourself. Use `python3 scripts/local.py --env dev stop` to stop while retaining data. |

Job-listing fetching, Gmail, Calendar and the optional external classifier are off in the shipped configuration. Core use needs neither a provider account nor the separate local-session setup code used by the integration controls. The Job Board has **Add Job** for manual entry. The Settings card titled **CSV Job Import** points to manual entry and an API endpoint.

## Proposed guided setup

1. **Check this machine.** Identify missing runtime prerequisites, permissions, disk space and conflicting local ports before building or creating installation state. Give one actionable fix per failure and let the user recheck. Explain any downloads before they start. Use a dedicated core installation identity and remember it across attempts.
2. **Prepare NextUp locally.** Generate missing instance configuration and protected secret files and start the local dependencies. Show progress and preserve existing configuration, secrets and volumes on retry. Use available loopback ports for a fresh installation if defaults conflict and remember the chosen address. Keep job providers, mail, calendar, external classification and AI off without asking for any provider credential.
3. **Review database initialization.** Show which local instance will change and a plain-language summary of the guarded plan. Retain the guard's typed, one-time confirmation in the same interactive flow. Keep its authorization internal to the guard. On cancellation, pause and offer to review the plan again. On failure, show a redacted error and recheck the instance and migration state before offering retry. If the guard refuses or migration state is uncertain, show a recovery route that preserves the database and files. Never reset storage automatically.
4. **Open the workspace.** Wait for local health and confirm the frontend address is on loopback. Offer **Open NextUp** and display the URL for reopening. A health or browser failure should offer a retry using the same installation. Offer **Stop NextUp** with data retained.

Keep manual port overrides, diagnostics, staging, database administration and backup or restore in advanced configuration. Keep the API and frontend bound to loopback. Store credentials in restricted files, and exclude their contents and confirmation input from logs and support artifacts. Dependency downloads can reach registries during setup. Once installed, the core workflow must operate with external egress denied and job-search data stays on the machine. Packaging, the initial platform list and the presentation of the guarded prompt remain maintainer decisions.

## First run in the application

Open Today with a clear **Add an application** action and a direct path to the Job Board for users who want to save a listing first. Offer Profile as an optional step for entering preferences and experience. Allow skipping it and returning later. Show a local-only status and keep integration controls in Settings. Each empty view should say what belongs there and expose its first action. Preserve records across reloads and keep the first-run prompts from interrupting returning users.

Use synthetic records for the following end-to-end checks. Exercise the visible interface with no provider credentials, integrations or AI configured. Reload after saving and restart after completing the workflow to verify persistence.

| Workflow | Observable evidence |
|---|---|
| Applications | Add a synthetic application, move it to another stage and confirm the new stage and history persist. |
| Tasks | Create a due task in Search Plan, find it in the plan, complete it and confirm its saved status. |
| Contacts | Add and update a synthetic contact and verify the saved details. |
| Résumé versions | Create a local résumé version, edit it and reopen it with the saved content. |
| Manual Job Board | Use **Add Job**, save a synthetic listing and find it on the board. |
| Optional profile | Complete one workflow with an empty profile, then save preferences and confirm they persist. |

Check the effective configuration and credential absence without dumping secrets. After dependency downloads, deny external egress while retaining loopback and internal service traffic. Record both successful actions and any attempted external connection. An unexpected outbound attempt fails validation even if the workflow completes.

## Validation

### Targets before claiming support

- Run from a pristine machine or VM for every proposed OS version and architecture to be claimed. Begin without a NextUp checkout, configuration, secrets or volumes. Include all prerequisite steps, run the core workflow above, then stop and restart to confirm records are retained. On a disposable instance, exercise a missing prerequisite, port conflict, cancelled migration and interrupted startup. Verify that each recovery preserves existing installation state and synthetic data.
- Propose at least five sessions with representative job seekers who do not routinely use developer tooling. Cover each platform proposed for support. Give participants the setup entry point and a synthetic job-search scenario. Observe whether they can reach the workspace, complete the core workflows and recover from a handled setup interruption without coaching. Record completion, time, points of confusion and any assistance. Resolve blockers and repeat the affected steps before making a claim.
- Require accessibility coverage for every new setup or onboarding screen before release. Check the full flow with keyboard alone and with a screen reader, including names and instructions, logical focus order, visible focus, progress announcements, error and retry focus, and migration cancellation. Check contrast, zoom and reflow. Pair automated checks with manual coverage and include assistive technology in representative sessions.

### Evidence records

No clean-machine run or representative-user session is recorded for this design. Existing [developer verification](DEVELOPMENT.md#what-has-been-validated) covers a different path. Keep the [release gates](RELEASE_CHECKLIST.md#core-application) open until dated results are linked there.

For each clean-machine run, record date, NextUp commit, OS version and architecture, starting state, runtime versions, off-state and egress checks, workflow and recovery results, accessibility coverage where applicable, and a redacted artifact link. For each session, use a participant code and record platform, date, commit, completed steps, assistance and observed blockers. Use synthetic data and omit personal information and secrets.

The maintainer reviews and accepts the design in #28 before any implementation issues are filed. Clean-machine runs and user sessions follow implementation.
