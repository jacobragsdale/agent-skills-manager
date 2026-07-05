# Research notes — evidence behind the house rules

Compiled 2026-07-01 from vendor docs, empirical studies, and analyses of
production AGENTS.md files. Cite these when a house rule is challenged.

## The headline numbers

- **Auto-generated context files hurt; human-written help.** ETH Zurich eval
  (138 real tasks, 4 agents): LLM-generated files −3% task success, +20%
  inference cost; human-written +4% success. Auto-generated codebase
  overviews did not even speed up file discovery.
  https://arxiv.org/html/2602.11988v1
- **Length: gains reverse past ~150 lines.** Augment Code benchmark: 100–150
  lines gave 10–15% improvement; beyond ~150 the gains reversed — "a good
  AGENTS.md is a model upgrade, a bad one is worse than no docs at all."
  https://www.augmentcode.com/guides/how-to-build-agents-md
- **Anthropic's pruning test:** "For each line, ask: 'Would removing this
  cause Claude to make mistakes?' If not, cut it." Target under 200 lines.
  https://code.claude.com/docs/en/best-practices
- **Structure cosmetics don't matter; content and session length do.**
  Factorial study of 1,650 Claude Code sessions: file size/position/
  architecture had no detectable adherence effect after correction;
  within-session decay dominated (~5.6% lower compliance odds per generated
  function). https://arxiv.org/abs/2605.10039
- **Real snippets and numbered workflows beat prose.** Augment: 3–10-line
  production snippets improved code reuse ~20%; numbered workflows cut
  missing-wiring errors 40%→10%. GitHub's 2,500-repo analysis: "One real
  code snippet showing your style beats three paragraphs describing it."
  https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/

## What reliably works (community consensus)

- Exact commands with flags, early in the file; file-scoped (single-file
  test/lint) over project-wide. (GitHub study; HumanLayer
  https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- "Facts always work" — structure, commands, doc pointers get followed;
  from-scratch behavioral rules mostly don't. Rules stick when tied to an
  observed failure, one sentence each.
  https://news.ycombinator.com/item?id=48160604
- Add rules only after failures; validate by revert-and-rerun (pamelafox,
  https://news.ycombinator.com/item?id=47044313). Claude Code's creator:
  "Anytime we see Claude do something incorrectly we add it to the
  CLAUDE.md." https://howborisusesclaudecode.com/
- Positive/conditional phrasing: "do not X" measurably primes X; first-person
  reframe ("I will follow...") went 0/3 → 3/3 in one adherence test
  (https://news.ycombinator.com/item?id=46809708). 15+ "never" stacks made
  agents timid (Augment).
- Three-tier boundaries (Always / Ask first / Never); "Never commit secrets"
  is the single most common useful constraint (GitHub study).
- Progressive disclosure: a rich index pointing at on-demand docs beat both
  inlined docs and skills in Vercel's eval (100% vs 53% baseline); bare "go
  read X" pointers are unreliable — make the pointer self-explanatory.
  https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals
- Hard rules belong in hooks/linters/CI; the file is advisory context —
  Claude Code injects it with "may or may not be relevant" framing.
  https://code.claude.com/docs/en/memory

## Tool interop (as of mid-2026)

- Read AGENTS.md natively: Codex, Cursor (root + nested), Copilot coding
  agent/CLI, Jules, Amp, Devin, Aider (config), VS Code, Zed, 20+ more.
  https://agents.md
- **Claude Code does NOT** — official bridge: CLAUDE.md containing
  `@AGENTS.md` (preferred; Windows-safe) or a symlink.
  https://code.claude.com/docs/en/memory
- Nesting semantics differ: agents.md spec says nearest wins; Codex
  concatenates root→cwd (32 KiB combined cap, later files soft-override);
  Claude Code concatenates ancestors and lazy-loads subdirectory files;
  Copilot treats ROOT as primary and nested as secondary. Keep root global,
  nested files self-contained.
- Codex also reads `~/.codex/AGENTS.md` (global) and supports
  `AGENTS.override.md`. Cursor keeps `.cursor/rules/*.mdc` for glob-scoped
  rules; Claude Code's equivalent is `.claude/rules/*.md` with `paths:`.

## Exemplars worth imitating

- **ghostty-org/ghostty** (39 lines) — minimalist; commands with speed hints.
- **openai/codex** (322 lines) — long but every line a non-inferable rule;
  quantified structural rules ("file exceeds ~800 LoC → new module").
- **cloudflare/agents** (196) — cleanest Always/Ask-first/Never boundaries;
  agent-appended "Learned Workspace Facts" section.
- **getsentry/sentry** (234) — "# Do not run pytest by itself; it'll take
  forever!" inline in the command block.
- **vercel/next.js** (475) — every fence annotated with timing; explicit
  anti-patterns section. Length earned by repo weirdness.
- **coder/coder** (243) — hub-and-spoke: short root + topic docs in
  `.claude/docs/`.

Median real-world file is ~335–535 words (arXiv 2511.12884, 2,303 files);
Testing is the most common section (75%); files grow ~+57 words per edit and
almost never shrink — pruning must be deliberate.
