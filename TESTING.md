# Windows 11 and Cursor pilot protocol

Automated tests exercise the Python manager and real local Git repositories.
This protocol covers what they cannot: standard-user installation, UAC,
SmartScreen, Git Credential Manager, Task Scheduler, LocalAppData paths, Cursor
discovery, and Cursor's own Skill Adoption telemetry.

Do not distribute an installer change until the relevant runs below have a
dated result. The acceptance question is: **would a skeptical teammate finish
without asking the maintainer for help, and could the system fail without
losing work or telemetry?**

## Test environment

Prepare:

- a clean Windows 11 VM snapshot;
- one standard local user and one administrator;
- no Git, uv, `%USERPROFILE%\.agents`, or
  `%LOCALAPPDATA%\AgentSkills`;
- Cursor on the team plan under test;
- a skills test repository and a separate inbox test repository;
- production-like Azure DevOps permissions:
  - member can read skills but cannot push protected `main`;
  - member can create and update inbox branches;
  - maintainer can read all inbox refs and open skills PRs;
- a configured `bootstrap.ps1` served as `text/plain` over internal HTTPS.

Restore the clean snapshot before each independent install run.

## Install matrix

| ID | Run | Account | Required observation |
|---|---|---|---|
| I1 | Hosted `irm .../bootstrap.ps1 \| iex` | Standard | Flagship path; note UAC, agreements, sign-in foreground/background, total time |
| I2 | Hosted one-liner | Admin | Compare prompts and install scope with I1 |
| I3 | Browser Zip, extract, `install.cmd` | Standard | Record Mark-of-the-Web and SmartScreen text |
| I4 | Explicit `-RepoUrl` and `-InboxRepoUrl` | Standard | Works with both defaults blank |
| I5 | Immediate re-run after I1 | Standard | Same machine ID, no duplicate task, no lost events |
| I6 | `bootstrap.ps1 -Uninstall` | Standard | Separate runtime/state prompts show pending count |
| I7 | Reinstall after I6 | Standard | Clean new install; identity behavior documented |
| I8 | Bad skills URL, then bad inbox URL | Standard | Actionable error and nonzero exit; no green success banner |
| I9 | Cancel GCM sign-in | Standard | No hang; rerun recovers |

## Runtime and scheduler matrix

| ID | Scenario | Expected result |
|---|---|---|
| S1 | Run `AgentSkillsNightly` on demand | Result 0; heartbeat branch appears; task and manager logs are in LocalAppData |
| S2 | Start scheduled and manual nightly together | One owns the lock; the other exits nonzero with an actionable lock message; no duplicate heartbeat commit |
| S3 | Modify a tracked runtime file | Nightly refuses; file remains byte-for-byte unchanged |
| S4 | Add an untracked runtime file | Nightly refuses; file remains present |
| S5 | Switch runtime to another branch | Nightly refuses; branch and files remain unchanged |
| S6 | Add a local commit on `main` | Nightly refuses; commit remains; nothing is pushed |
| S7 | Advance protected remote `main` | Clean runtime fast-forwards without a reset commit |
| S8 | Disconnect network during inbox push | Event remains in `events\pending`; later retry sends it once |
| S9 | Disconnect network during runtime fetch | Installed skills remain usable; task exits nonzero and logs the failure |
| S10 | Delete cached credentials for both repos | `fix-signin.cmd` repairs both; next task succeeds |
| S11 | Miss the scheduled time while powered off | `StartWhenAvailable` catches up after login |
| S12 | Keep machine offline across a month boundary | Old event timestamps publish to the current upload-month branch |

## Repository permission rehearsal

From the standard user VM, prove all four statements:

1. `git -C %USERPROFILE%\.agents fetch origin` succeeds.
2. A direct push to skills `main` is rejected by permissions/policy.
3. A normal nightly push creates only
   `inbox/v1/<machine-id>/<YYYY-MM>` in the inbox repository.
4. The inbox push does not require policy-bypass permission.

Capture the Azure DevOps permission and branch-policy screenshots in the pilot
record. Do not weaken skills `main` to make the client work.

## Cursor canary

Add a uniquely named, harmless `telemetry-canary-<date>` skill through a test
PR. Its body records start and finish but makes no source changes.

Test in fresh conversations:

1. Confirm the skill appears in Cursor Settings and the slash menu.
2. Invoke it explicitly once.
3. Trigger it automatically with three known-positive prompts.
4. Send two near-miss prompts that should not trigger it.
5. Invoke it twice in one conversation.
6. Correct one invocation so it records a categorized learning.
7. Run nightly publication.
8. Aggregate the inbox and compare:
   - locally recorded invocation starts;
   - recorded outcomes;
   - the learning event;
   - Cursor Enterprise `/analytics/team/skills` on the following day.

Document:

- whether user-scoped `~/.agents/skills` appear in Cursor Analytics;
- explicit versus automatic counting behavior;
- whether repeated use in one conversation counts once or twice;
- Analytics latency;
- local capture completeness versus the known test count;
- any Cursor version-specific behavior.

Until this passes, call local values `recorded invocations` and treat Cursor
Analytics as unverified for this installation model.

## Maintainer aggregation rehearsal

Use at least three test machines and inject:

- a valid invocation and outcome;
- a valid learning;
- malformed JSON;
- an unknown schema version;
- a skill name containing path traversal;
- an event whose machine ID differs from its branch;
- a modified previously published event;
- a force-rewritten inbox branch;
- the same aggregation command twice.

Expected results:

- valid data is counted once;
- learning lands only in the intended `LEARNINGS.md`;
- invalid data produces a content-free entry in `metrics/REJECTED.md`;
- rewritten or non-append-only branches do not advance checkpoints;
- the second aggregation run produces no diff;
- the resulting changes enter protected `main` only through a reviewed PR.

## Acceptance checklist

- [ ] Runtime clone exists at `%USERPROFILE%\.agents` and is clean on `main`
- [ ] Local state exists only under `%LOCALAPPDATA%\AgentSkills`
- [ ] `config.json` contains random machine ID and the two expected remotes
- [ ] `AgentSkillsNightly` has `StartWhenAvailable`, one-hour limit, and `IgnoreNew`
- [ ] First heartbeat is present on the expected inbox branch
- [ ] No member-authored commit or branch appears in the skills repository
- [ ] `uv run manage.py doctor --state-dir ...` exits 0
- [ ] Cursor discovers and invokes a runtime skill
- [ ] Failure cases preserve runtime files and pending events
- [ ] Aggregation tests and canary comparison are recorded
- [ ] Uninstall explains pending-event loss before deleting state

## Results

Add one dated section per test session with VM image, Cursor version, account
type, repository permission model, runs completed, wall times, exact prompts,
blockers, friction, and fixes. Historical results from the former single-repo
hard-reset architecture do not count as evidence for this design.

### 2026-07-10 — home-server Windows 11 VM (partial pass)

Environment:

- Windows 11 Pro 10.0.26200, administrator account, native Windows OpenSSH.
- Cursor 3.10.11 installed after the SSH test; it reached the login screen.
- Git and uv were already installed, so dependency installation was not tested.
- The current uncommitted working tree was seeded into two temporary local bare
  repositories in the guest. This tested the two-repository design without
  Azure DevOps or Git Credential Manager.
- The installer was piped through `Invoke-Expression` with repository URLs in
  `AGENT_SKILLS_REPO_URL` and `AGENT_SKILLS_INBOX_URL`. It completed in two
  seconds and every initial `doctor` check passed.

Passed observations:

- Fresh runtime clone at `%USERPROFILE%\.agents`; LocalAppData state was
  separate; the runtime was clean on `main`; no runtime `.manager` existed.
- First heartbeat reached exactly one monthly machine ref while inbox `main`
  remained unchanged.
- `AgentSkillsNightly` had `StartWhenAvailable`, `IgnoreNew`, a one-hour limit,
  and the expected LocalAppData log redirection. An on-demand run returned 0,
  published one heartbeat, and left zero pending events.
- Immediate installer rerun preserved the installation UUID, retained exactly
  one scheduled task, and left the runtime clean.
- `record-start`, corrected `record-finish`, and `record-learning` created three
  valid pending event files; publication moved all three to `sent` only after a
  successful push.
- A missing inbox remote made publication exit 1 with the pending event intact;
  restoring the remote allowed a single successful retry.
- Malformed local JSON moved to quarantine with a reason file and did not block
  later publication.
- A remote `main` advance fast-forwarded into the clean runtime. Wrong-branch
  and dirty-main sync attempts both exited 1, preserved their marker files and
  branches, and did not reset or delete anything.
- Maintainer aggregation on a review branch accepted six events and produced
  one recorded invocation, one correction, one learning, and one fleet machine.
  After committing that result, the second aggregation produced no diff.
- Aggregation on protected `main` exited 1 and left the branch clean.

Not yet verified:

- Standard-user install, missing-dependency installation, hosted `irm | iex`,
  Azure DevOps permissions, GCM prompts/expiry, concurrent task locking, missed
  schedule catch-up, and month-boundary publication.
- Cursor contained both actual runtime `SKILL.md` files, but the GUI stopped at
  account login. Discovery, explicit/automatic invocation, and platform
  Analytics comparison remain blocked until an interactive Cursor sign-in.
