# Weekly fold & fleet ops — headless agent prompt

You are running unattended at the root of a clone of the team agent-skills
repo. Nobody will answer questions; work autonomously and prefer the smaller,
safer action when uncertain. Your jobs, all landing in one branch and one
pull request: fold the week's harvested learnings from `learnings/inbox/`
into each skill's `LEARNINGS.md`, fold *recurring* lessons into `SKILL.md`
where the evidence supports it, aggregate the week's metrics into the
dashboard, triage skill requests, check fleet health, and open or update the
Azure DevOps pull request.

## Context — read these first

- `AGENTS.md` — house rules for this repo.
- `skills/jacob-create-skill/SKILL.md` — especially "Improving an existing
  skill"; its process governs every SKILL.md edit you make.
- Layout: `skills/<name>/` each with `SKILL.md` + `LEARNINGS.md`. Inbox files
  are `learnings/inbox/<timestamp>-<user>-<host>.md`: frontmatter with
  `user:`/`host:`, then `## skills/<name>` sections of entries shaped
  `- YYYY-MM-DD: <what happened> → <what to do instead>`.
- Auth: the `AGENT_SKILLS_PAT` env var holds an Azure DevOps PAT (Code
  read & write). Send it per git/API call as a Basic auth header for the
  user `""` (empty) — never write it into git config, remote URLs, or files.

## Steps

1. `git fetch origin`, then `git checkout -B learnings/fold origin/main`.
   If `learnings/inbox/`, `metrics/inbox/`, and `requests/inbox/` are all
   empty (`.gitkeep` aside), stop — there is nothing to do this week.
2. Read every inbox file. Group entries by skill, keeping attribution.
3. **Semantic dedupe.** Merge entries that teach the same lesson even when
   phrased differently, and drop entries already present in that skill's
   `LEARNINGS.md`. When merging duplicates: keep the clearest phrasing,
   the earliest date, and every distinct attribution.
4. Append survivors to each skill's `LEARNINGS.md` in the existing entry
   format, with attribution: `- YYYY-MM-DD: <lesson> [user@host, user@host]`.
   Entries for skills that no longer exist go to `learnings/ORPHANED.md`.
5. **Fold into SKILL.md** only when a lesson is corroborated: confirmed by
   two or more distinct users, or already present in `LEARNINGS.md` from a
   prior week and reported again now. Follow "Improving an existing skill":
   edit the SKILL.md in place in the section where the mistake happens,
   delete the folded `LEARNINGS.md` lines, and run
   `uv run skills/jacob-create-skill/scripts/validate_skill.py skills/<name>`
   — do not commit a SKILL.md that fails validation. A single report from a
   single user is never enough; leave it in LEARNINGS.md to season.
6. `git rm` the processed inbox files.
7. **Metrics.** Append every line from `metrics/inbox/*.jsonl` to
   `metrics/history.jsonl` (create if missing), `git rm` the inbox files,
   then regenerate `metrics/DASHBOARD.md` from the full history: per skill —
   invocations this week and per week over time, corrected-rate
   (`outcome == "corrected"` share), learnings received this week; per team —
   distinct contributors and skills-used-per-teammate-per-week. Flag skills
   with high corrected-rate or many learnings (struggling) and skills with
   zero invocations in 90 days (deprecation candidates). Plain markdown
   tables; no speculation, only what the data shows.
8. **Requests.** Merge entries from `requests/inbox/*.md` into
   `requests/BACKLOG.md`: group duplicates of the same underlying need,
   count distinct requesters per need (that is the ranking), keep
   attribution. `git rm` the processed inbox files. Never delete a backlog
   entry — mark it `(done: skills/<name>)` when a skill now covers it.
9. **Fleet health.** Read `machines/*.json`; list any machine whose
   `last_sync` is more than 3 days old in the PR description as a probable
   broken install.
10. Commit in reviewable units: one commit
    `learnings: fold inbox (YYYY-MM-DD)` for the LEARNINGS/inbox changes,
    one `metrics: weekly dashboard (YYYY-MM-DD)`, one
    `requests: triage (YYYY-MM-DD)`, then one commit per SKILL.md fold —
    `skills/<name>: fold recurring lesson into SKILL.md` — so the reviewer
    can drop any single fold without losing the rest.
11. Push: `git -c "http.extraheader=AUTHORIZATION: Basic <b64>" push origin
    +learnings/fold` where `<b64>` is `printf ':%s' "$AGENT_SKILLS_PAT" | base64`.
12. Pull request: derive org/project/repo from `git remote get-url origin`.
   If an active PR from `learnings/fold` already exists, the push updated it
   — done. Otherwise create one:

   ```
   curl -sf -X POST \
     -H "Authorization: Basic $(printf ':%s' "$AGENT_SKILLS_PAT" | base64)" \
     -H "Content-Type: application/json" \
     "https://dev.azure.com/<org>/<project>/_apis/git/repositories/<repo>/pullrequests?api-version=7.1" \
     -d '{"sourceRefName":"refs/heads/learnings/fold","targetRefName":"refs/heads/main","title":"learnings: weekly fold (YYYY-MM-DD)","description":"..."}'
   ```

   PR description must cover: new entries per skill, duplicates merged (and
   across whom), each SKILL.md fold with the evidence that justified it,
   the week's headline metrics, new/updated backlog needs with requester
   counts, stale machines, orphaned entries, and anything you skipped or
   found ambiguous.
13. **Digest (optional).** If the `TEAMS_WEBHOOK_URL` env var is set, POST a
    short summary card to it: the week's lesson count and top contributors,
    any learning promoted into a SKILL.md (name the contributor — that is
    the point), the top backlog need, and the PR link. Skip silently if the
    var is unset; a webhook failure must not fail the run.
14. Leave the clone clean: check out the default branch and reset to origin.

## Guardrails

- Never invent, embellish, or editorialize a lesson; merging duplicates is
  the only rewriting allowed.
- Never delete an existing `LEARNINGS.md` entry except one you folded into
  SKILL.md in this same run.
- Touch only files this job owns: `LEARNINGS.md`, `SKILL.md` (fold rule
  above), `learnings/inbox/`, `learnings/ORPHANED.md`.
- If the semantic work goes sideways (validation failures you cannot fix,
  conflicting evidence), fall back to the mechanical fold —
  `uv run manage.py fold` — and say so in the PR description.
- Exit with a clean working tree, always.
