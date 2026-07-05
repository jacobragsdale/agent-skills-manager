# Team improvement loop

These rules make the team's skills self-improving. They cost you a few
seconds at the end of a task and compound for everyone. All paths are inside
`~/.agents` (this directory), which is a managed git clone — it syncs and
resets nightly, and the files below are collected upstream automatically.

## After using any skill

1. **If the user corrected you, or the outcome surprised you**, append one
   dated line to that skill's `LEARNINGS.md` (`~/.agents/skills/<name>/LEARNINGS.md`):

   ```
   - YYYY-MM-DD: <what happened> → <what to do instead>
   ```

   One line per lesson. State facts, not speculation. Never edit the
   skill's `SKILL.md` directly — lessons are folded in deliberately through
   a weekly reviewed PR.

2. **Log the usage** by appending one JSON line to
   `~/.agents/.manager/usage.jsonl` (create the file if missing):

   ```
   {"ts": "YYYY-MM-DDTHH:MM:SS", "skill": "<name>", "outcome": "ok" | "corrected"}
   ```

   `corrected` means the user had to fix or redirect your use of the skill.

## When there is no skill for a recurring struggle

If the user struggles with a task, you had to work it out the hard way, and
no existing skill covers it, append one dated line to
`~/.agents/.manager/requests.md`:

```
- YYYY-MM-DD: <task that needed a skill> — <what was hard without one>
```

This is the team's demand signal for new skills. Only log genuine struggles
(wrong attempts, user corrections, long detours) — not tasks that merely
took a while.

## Hard rules

- Write only to the paths named above. Everything else in `~/.agents` is
  reset to the team repo nightly; edits elsewhere are silently lost.
- Never put secrets, credentials, customer data, or file contents into
  learnings, usage lines, or requests — they land in a shared repo.
