# Roadmap

The system is intentionally narrow: distribute reviewed user-scoped Cursor
skills, preserve a clean runtime, return privacy-bounded field evidence through
an untrusted inbox, and improve skills through ordinary reviewed pull requests.

## Implemented in the current development version

- Runtime/state separation: `~/.agents` is read-only; mutable files live in
  `%LOCALAPPDATA%\AgentSkills`.
- Safe runtime sync: verified path, origin, expected branch, completely clean
  worktree, fetch, and fast-forward only.
- Cross-platform process lock around nightly publication and sync.
- Versioned immutable JSON events with atomic local writes, strict field
  validation, quarantine, and local retention.
- Random installation identity with no username or hostname collection.
- Separate inbox repository and monthly per-machine append-only refs.
- Failure-safe publication: pending events move only after successful push.
- Deterministic aggregation with checkpoints, rewritten-ref detection, path
  validation, daily metrics, fleet state, rejected-event reporting, and
  idempotent learning append.
- A Cursor Skill Adoption canary protocol that keeps platform counts separate
  from locally recorded invocations.
- A per-user Windows Installed apps entry and safety-checked standalone
  uninstaller that preserves modified or unrecognized runtime files.
- Teammate skill authoring, proposal sweeping, and uncovered-skill request
  collection removed.
- Standard-library unit and local bare-Git integration tests, including
  concurrent clients and malicious input.

## Pilot gates

- Complete every standard-user and GUI run in `TESTING.md` against the new
  two-repository architecture.
- Verify `New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew` on the
  supported Windows 11 image.
- Run the Cursor canary: explicit invocation, automatic invocation, repeated
  use in one conversation, local start/finish events, Enterprise Analytics
  comparison, and capture of the endpoint's actual response contract.
- Configure Azure DevOps permissions in a rehearsal project: members read
  skills, create inbox branches, and cannot push or bypass protected skills
  `main`.
- Exercise expired GCM credentials for both repositories.
- Add and rehearse processed inbox-branch retention automation.
- Run a five-to-ten-person pilot for at least two weekly aggregation cycles.

Pilot success criteria:

- at least 90% first-attempt installation completion;
- no runtime checkout rewritten or user work lost;
- no event loss in injected failure tests;
- nightly success visible through heartbeats;
- aggregation reruns produce no duplicate counts or learnings;
- dashboard wording survives privacy and engineering review;
- canary establishes the measured completeness of local recording.

## After the pilot

- Trigger regression fixtures and CI judging for every skill description.
- A tested Cursor Skill Adoption importer, if the pilot proves stable
  user-scoped coverage and a documented response contract.
- Stable and canary release branches with a documented rollback rehearsal.
- Automated monthly inbox-ref deletion after successful checkpoints and the
  retention grace period.
- A service account for maintainer aggregation instead of a personal token.
- Drift probes for tool-specific flags and identifiers used by runtime skills.
- Generated catalog and owner-review policies if the library grows enough to
  need them.

## Explicitly deferred

- Multi-team overlays and company-wide catalogs.
- Per-user dashboards or productivity scoring.
- Conversation transcript collection.
- Automatic creation of new skills from demand signals.
- Unattended LLM edits to `SKILL.md`.
- Supporting additional agent runtimes before the Windows/Cursor pilot is
  stable.
