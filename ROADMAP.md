# Roadmap

The load-bearing idea: the repo is a distribution channel with a nightly,
conflict-free, bidirectional pipe to every machine. Harvest/inbox is not a
learnings feature — it is a generic "ship any file upstream without
coordination" mechanism, and everything below rides on it.

## 1. Pilot (built)

- Windows fleet bootstrap (`bootstrap.ps1`): prereqs, PAT, `~/.agents`
  clone, WSL mirror, nightly Scheduled Task.
- Nightly harvest: LEARNINGS.md diffs → `learnings/inbox/` → hard reset.
  Doubles as the update pull; machines are appliances.
- Weekly agent-driven fold (`prompts/weekly-learnings-fold.md`): semantic
  dedupe, SKILL.md folds gated on corroboration, one reviewable PR.

## 2. Metrics + fleet health (built)

- Usage telemetry rides the harvest pipe: agents append to
  `.manager/usage.jsonl` (per `rules/team-loop.md`); harvest ships valid
  lines to `metrics/inbox/`. No telemetry infrastructure, no server.
- Heartbeats: every harvest updates `machines/<host>.json`. A machine
  silent 3+ days is a broken install nobody noticed — the weekly job flags
  it in the fold PR.
- Weekly job aggregates `metrics/inbox/` into `metrics/history.jsonl` and
  regenerates `metrics/DASHBOARD.md` inside the fold PR. Headline numbers:
  invocations per skill (adoption), learnings per skill per week
  (friction), corrected-rate per skill (quality), distinct contributors
  (health), skills used per teammate per week (the adoption story for
  management).

## 3. Contribution (built)

- `/propose-skill`: teammate describes a pain point; the agent runs the
  jacob-create-skill interview, scaffolds on a branch, validates, opens the
  PR. Contribution without knowing git, ADO, or the house format.
- Demand signal: agents log uncovered struggles to `.manager/requests.md`
  (per `rules/team-loop.md`); harvest ships them to `requests/inbox/`; the
  weekly job triages into `requests/BACKLOG.md` — a ranked backlog of
  skills people actually need, written by the agents that watched them
  struggle.
- Recognition: fold attribution (`[user@host]`) is already stamped; weekly
  job posts a Teams digest (set `TEAMS_WEBHOOK_URL`) — the week's lessons
  and whose learning got promoted into a SKILL.md.
- Ownership: treat `metadata.author` as maintainer; tag them as reviewer on
  fold PRs touching their skill.

## 4. Self-improving skills and rules (next)

- Rules get the learnings loop: each `rules/*.md` gains a LEARNINGS
  sibling, same harvest/fold path. A rule repeatedly ignored is a learning
  about the rule's wording.
- Trigger regression tests in CI: freeze each skill's six-message trigger
  table as `tests/triggers.md`; an ADO pipeline judges name + first 250
  chars of description on every PR.
- Golden-task evals: 1–3 canonical tasks per skill, run headless
  before/after any proposed SKILL.md fold; results go in the PR
  description. Folds become evidence-backed.
- Drift detection: skills declare tool-specific identifiers; a weekly job
  runs the real tools and files an inbox entry when reality moves.
- Lifecycle: many learnings = struggling skill; zero invocations in 90
  days = deprecation candidate. Both fall out of the metrics.

## 5. Multi-team and company scale (later)

- Core + overlay repos: company `agent-skills-core` (conventions, security
  rules, universal skills) plus per-team repos; bootstrap layers both.
  Team rules override core; core policy rules are non-overridable.
  Learnings route by origin — core-skill lessons aggregate centrally.
- Generated `CATALOG.md`: every skill's name, description, owner, team,
  usage count. Cross-team discoverability stops five teams writing five
  deployment skills. A team skill copied by a second team is a core
  candidate.
- Release channels: teams pin `stable` while the pilot team rides `main`;
  promotion is a fast-forward, rollback is `git revert`.
- Platformizing: service principal instead of personal PATs; Credential
  Manager storage; branch policies + owner-reviewers; validation CI as the
  quality bar that scales beyond one maintainer.

## Sequencing

Ship 1–3 to the pilot team and let the weekly fold PRs accumulate — they
are the proof artifact. Metrics sell the second team. Contribution features
matter when the second team arrives. Split core/overlay only when a second
team actually exists. Platformize at company scale, at which point the
"skill review board" is just the existing PR process with more names on it.
