# Windows 11 and Cursor pilot protocol

Automated tests cover the Python manager and real local Git repositories. These
checks cover Windows installation, Task Scheduler, Git Credential Manager, and
Cursor discovery.

Record a dated result before distributing an installer or filesystem-path
change. Use a clean Windows 11 snapshot, a standard user, production-like Azure
DevOps permissions, and a reviewed `bootstrap.ps1` served over internal HTTPS.

## Install

1. Run the hosted `irm .../bootstrap.ps1 | iex` command as a standard user with
   neither Git nor uv installed.
2. Confirm no UAC or credential prompt for an administrator appears. Git and uv
   must install under `%LOCALAPPDATA%\AgentSkills\tools`, and both paths must be
   persisted in the user's `PATH`. Managed Python must stay under the Agent
   Skills state directory and `AGENT_SKILLS_PYTHON` must point at it.
3. Confirm `~\.agents` is a clean clone on `main` and mutable state exists only
   under `%LOCALAPPDATA%\AgentSkills`.
4. Confirm `AgentSkillsNightly` has `StartWhenAvailable`, a one-hour execution
   limit, `IgnoreNew` multiple-instance behavior, and interactive-token logon.
5. Re-run the installer. Confirm the machine UUID is unchanged, exactly one task
   exists, and queued feedback is untouched.
6. Run `manage.py doctor` and an on-demand nightly task.

## Safety and recovery

1. Advance remote `main` and confirm the runtime fast-forwards.
2. Test a dirty tracked file, an untracked file, a wrong branch, and a local
   commit. Each must remain unchanged while sync exits nonzero.
3. Disconnect the inbox remote during publication. The learning must remain in
   `feedback\pending` and publish once after recovery.
4. Start scheduled and manual nightly runs together. One must own the lock and
   the other must exit without duplicate feedback.
5. Remove cached credentials for both repositories, run `fix-signin.cmd`, and
   confirm the next nightly succeeds.

## Feedback

1. Run each installed skill and correct one factual instruction.
2. Confirm ordinary successful use writes nothing.
3. Confirm each correction creates one schema-valid pending JSON file with no
   prompt, code, repository, username, or hostname data.
4. Publish and verify only `feedback/v1/<machine-id>` changes in the inbox;
   inbox `main` and the skills repository remain unchanged.
5. Aggregate from a clean review branch. Confirm the two lessons land only in
   their intended `LEARNINGS.md` files.
6. Run aggregation again and confirm it produces no diff.
7. Inject malformed JSON, an unsafe skill name, and a mismatched machine UUID.
   Confirm content-free rejections and no path escape.

## Cursor

1. Confirm both `SKILL.md` files appear in Cursor Settings and the slash menu.
2. Trigger each skill explicitly and automatically in fresh conversations.
3. Confirm bundled script paths resolve from the installed runtime.
4. Confirm a feedback command failure does not block completion of the user's
   task.

## Manual uninstall documentation

Follow the README instructions on a test installation. Confirm the task and two
owned directories are removed. Repeat with a dirty runtime and confirm the
operator is instructed not to delete it. This is documentation validation, not
an automated uninstaller contract.

## Results

Add one dated section per session with Windows image, Cursor version, account
type, repository permission model, cases completed, friction, and failures.
Historical results for the removed usage telemetry and automated uninstaller do
not establish this design.

### 2026-07-09 — home-server Windows 11 VM

Environment:

- Windows 11 test guest over OpenSSH, administrator account, Git 2.55.0 and
  uv 0.11.26 already installed.
- Candidate working tree committed into temporary guest-local skills and
  feedback repositories; no Azure DevOps or GCM interaction in this run.

Passed:

- All 19 manager tests passed on Windows. The first run exposed a Windows
  lock-contention `PermissionError`; after normalizing that path to
  `LockBusyError`, the complete suite passed.
- Fresh bootstrap completed in one second, produced a clean runtime, passed
  `doctor`, and registered one task with `StartWhenAvailable=true`,
  `ExecutionTimeLimit=PT1H`, and `MultipleInstances=2` (`IgnoreNew`).
- Ordinary installation wrote no feedback. One explicit learning moved from
  pending to the sole `feedback/v1/<machine-id>` branch while inbox `main`
  remained present and the skills repository remained read-only.
- Aggregation changed only the intended `LEARNINGS.md` and processed-event
  state. After committing that review result, a second aggregation produced no
  diff.
- The README manual removal steps started from the expected origin and a clean
  runtime, then removed the scheduled task, runtime, and LocalAppData state.
  Git and uv remained installed. Temporary canary repositories were removed.

Not verified:

- Missing-dependency installation, hosted HTTP, standard-user permissions,
  real Azure DevOps branch policy, and GCM prompts/expiry.
- Cursor GUI discovery and explicit/automatic triggering require an interactive
  signed-in Cursor session.

### 2026-07-09 — home-server Windows 11 standard-user install

Environment:

- Windows 11 Pro x64 guest with a fresh local `skills-canary` account in
  `Users` and not in `Administrators`.
- Git and uv absent before installation. The candidate was served over a
  guest-local HTTP endpoint and used guest-local skills and feedback Git
  repositories, so no Azure DevOps or GCM interaction was required.
- An administrator-side 100 ms `consent.exe` monitor covered the complete
  install. The account also remained logged into the VM console for the
  interactive-token scheduled-task check.

Passed:

- The hosted `irm .../bootstrap.ps1 | iex` flow completed in 92 seconds with
  no UAC process or administrator credential prompt. Portable Git 2.55.0.2,
  uv 0.11.28, and managed Python 3.14.6 installed only under
  `%LOCALAPPDATA%\AgentSkills`; `C:\Program Files\Git` remained absent. The
  portable install exposed Git Credential Manager 2.8.0 and its configured
  `helper-selector`.
- The first attempt exposed Git's missing non-winget fallback. A pinned,
  SHA-256-verified Portable Git install fixed it. A hardened PowerShell/OpenSSH
  session also rejected uv's convenience junction with Windows error 448; the
  bootstrap now removes that junction, verifies the real versioned interpreter,
  and records it as `AGENT_SKILLS_PYTHON`.
- Bootstrap produced a clean `main` runtime, passed `sync` and `doctor`, and
  registered exactly one LUA task with interactive-token logon,
  `StartWhenAvailable=true`, `ExecutionTimeLimit=PT1H`, and
  `MultipleInstances=2`. With the standard user logged into the console, the
  on-demand task returned `0` and wrote a successful nightly log.
- The final installed interpreter passed all 19 manager tests and
  `py_compile`; both skills passed `tools/validate_skill.py` through uv with
  the installed interpreter.
- Reinstallation preserved the machine UUID, the single task, and one pending
  learning. The next scheduled run published that learning and cleared the
  queue. The inbox retained `main` plus only the machine's
  `feedback/v1/<machine-id>` branch.
- Aggregation accepted two canary learnings and changed only
  `feedback/ingestion-state.json` and the two intended `LEARNINGS.md` files.
  After committing that review result, a second aggregation was idempotent.
- The README manual removal commands deleted the task, runtime, LocalAppData
  state, project-owned PATH entries, and `AGENT_SKILLS_PYTHON`. A new session
  again had neither Git nor uv on PATH.

Not verified:

- Production HTTPS hosting, Azure DevOps branch policy, and real GCM
  authentication or expiry.
- Cursor GUI discovery and skill triggering; the VM has no signed-in Cursor
  canary environment.
