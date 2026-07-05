# Weekly learnings fold — headless agent prompt

You are running unattended at the root of a clone of the team agent-skills
repo. Nobody will answer questions; work autonomously and prefer the smaller,
safer action when uncertain. Your job: fold the week's harvested learnings
from `learnings/inbox/` into each skill's `LEARNINGS.md`, fold *recurring*
lessons into `SKILL.md` where the evidence supports it, and open or update
the Azure DevOps pull request.

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
   If `learnings/inbox/` contains no entry files (`.gitkeep` aside), stop —
   there is nothing to do this week.
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
7. Commit in reviewable units: one commit
   `learnings: fold inbox (YYYY-MM-DD)` for the LEARNINGS/inbox changes,
   then one commit per SKILL.md fold —
   `skills/<name>: fold recurring lesson into SKILL.md` — so the reviewer
   can drop any single fold without losing the rest.
8. Push: `git -c "http.extraheader=AUTHORIZATION: Basic <b64>" push origin
   +learnings/fold` where `<b64>` is `printf ':%s' "$AGENT_SKILLS_PAT" | base64`.
9. Pull request: derive org/project/repo from `git remote get-url origin`.
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
   orphaned entries, and anything you skipped or found ambiguous.
10. Leave the clone clean: check out the default branch and reset to origin.

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
