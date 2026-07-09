# Install test protocol (Windows 11 VM)

The install is a teammate's first taste of this system — every change to
`bootstrap.ps1` or `install.cmd` gets validated on a clean VM before it is
distributed. The grade for each run is a single question: **would a
skeptical teammate finish without pinging you for help?**

## VM preparation (once)

1. On the Windows 11 test VM, create two local accounts: one **admin**, one
   **standard user** (most corporate teammates are effectively standard
   users behind UAC).
2. Update Windows + Microsoft Store "App Installer" (winget), then confirm
   the machine is otherwise clean: no git, no uv, no `%USERPROFILE%\.agents`.
3. Take a snapshot named `clean`. Restore it before every numbered run
   below unless the run says otherwise.

## Serving the script for the one-liner

The one-liner needs `bootstrap.ps1` reachable over HTTP. For testing, serve
the repo from any host the VM can reach:

```bash
# Python's default MIME map serves .ps1 as application/octet-stream, which
# irm may not decode to text — force text/plain:
python3 - <<'EOF'
import http.server
H = http.server.SimpleHTTPRequestHandler
H.extensions_map['.ps1'] = 'text/plain'
http.server.ThreadingHTTPServer(('0.0.0.0', 8000), H).serve_forever()
EOF
```

Then on the VM:

```powershell
$env:AGENT_SKILLS_REPO_URL = '<repo-url>'   # or set $DefaultRepoUrl in the served copy
irm http://<host-ip>:8000/bootstrap.ps1 | iex
```

If `irm | iex` chokes on the response type, record it and use the fallback
(and fix the served content type):
`iex (New-Object Net.WebClient).DownloadString('http://<host-ip>:8000/bootstrap.ps1')`

In production the maintainer sets `$DefaultRepoUrl` inside the hosted copy,
so members run the one-liner with no env var — mirror that in at least one run.

## Test matrix

| # | Run | Account | Notes |
|---|-----|---------|-------|
| R1 | One-liner (`irm \| iex`) | standard | The flagship path. |
| R2 | One-liner | admin | Compare prompts vs R1. |
| R3 | Zip → extract → double-click `install.cmd` | standard | Download the zip **through the VM's browser** so Mark-of-the-Web is real; note every SmartScreen / security-warning dialog. |
| R4 | Clone + `powershell -File bootstrap.ps1` | standard | Legacy path; still documented. |
| R5 | Re-run installer immediately after R1 (no snapshot restore) | standard | Idempotency: every step should report "already". |
| R6 | Break the sign-in after R1 (delete the `git:https://...` entry in Windows Credential Manager), then double-click `fix-signin.cmd` | standard | The repair story. |
| R7 | After R1, run `AgentSkillsNightly` on demand from Task Scheduler | standard | Check `.manager\task.log`, and that the heartbeat lands in `machines/` upstream. |
| R8 | `bootstrap.ps1 -Uninstall`, then reinstall | standard | Task gone, clone gone (after the y/N prompt), reinstall clean. |
| R9 | Failure modes: bogus `-RepoUrl`; cancel the sign-in window | standard | Error text must say what to do next, not stack-trace. |

## What to record, per run

- **Total wall time** and per-step time (the script prints `[n/4]` steps).
- **Every prompt** the user sees: UAC, SmartScreen, "Open File — Security
  Warning", winget source agreements, the Microsoft sign-in window — and
  whether the sign-in window opened in the **foreground**.
- **Every hesitation**: any moment where the next action isn't obvious, with
  the verbatim on-screen text.
- Classify each issue: **blocker** (a teammate would stall or ping you — fix
  before distribution) vs **friction** (finishes but feels rough — backlog).

## Acceptance checklist (per successful install)

- [ ] `%USERPROFILE%\.agents` exists; `git -C %USERPROFILE%\.agents status` is clean
- [ ] Scheduled task `AgentSkillsNightly` exists with the expected next run time
- [ ] First sync succeeded (console + `.manager\task.log` free of errors)
- [ ] Heartbeat file for the VM appears in `machines/` on origin
- [ ] `uv run manage.py doctor` exits 0
- [ ] An agent actually sees the skills (open Cursor/Copilot on the VM and
      trigger one, e.g. "set up this Python repo to our standards")
- [ ] Uninstall (`-Uninstall`) leaves no task and, if confirmed, no clone

## Open questions the first session must answer

1. Does `winget install Git.Git` as a **standard user** succeed, trigger
   UAC, or fail? Decide the response: add `--scope user`, or document "one
   admin approval during install".
2. Does `irm | iex` decode the served script correctly (content-type), and
   does the `param()` block behave under `iex`?
3. What exactly does SmartScreen show for `install.cmd` out of a
   browser-downloaded zip, and is the wording survivable without support?
4. Does the GCM sign-in window appear in front of the console?
5. Does the very first `winget` use on a fresh profile still stop for a
   source-agreement prompt despite `--accept-source-agreements`?

Findings go in this file under a dated `## Results` section per session, so
the next round of polish works from evidence, not memory.

## Results — 2026-07-09 (headless session, dockurr/windows test VM)

Rig: dockurr/windows (Win 11 Pro 26200) driven over SSH; repo served from the
host via HTTP (`bootstrap.ps1`, text/plain) + git smart HTTP (`git
http-backend` bridge) because local changes weren't pushed anywhere. Admin
account only (dockurr creates one), no GUI — so the standard-user/UAC,
GCM-sign-in, and SmartScreen/zip questions (matrix R3, open questions 1/3/4)
remain OPEN for a GUI session.

Passed: R1 one-liner (fresh: 59s incl. git+VCRedist+uv downloads; warm: 2-4s),
R5 idempotent re-run (1s, all "already", same-day heartbeat no-op), R7
on-demand task run (Last Result 0, task.log written), R8 uninstall/reinstall
(task+clone removed, deps kept), R9 bad-URL failure modes (actionable errors,
no stack traces). Heartbeat verified upstream (`machines/<host>.json`,
attributed commit). `irm | iex` handled the `param()` block fine (open
question 2: answered yes). winget worked headless over SSH.

Bugs found and fixed this session (all in repo, re-verified on the VM):
1. BLOCKER: fresh machines have no git identity -> heartbeat commit died
   (`git_commit()` in manage.py now supplies `-c user.name/user.email`).
2. bootstrap printed green "All set" even when the first sync failed
   (now checks exit codes and prints an honest yellow banner).
3. manage.py had no subprocess timeouts -> a stalled push froze the install
   forever; plus Windows `git` is a shim, so a naive timeout-kill orphans the
   real git.exe and deadlocks pipe cleanup (`run()` now has NET_TIMEOUT=300
   on network ops and tree-kills via `taskkill /T /F`).
4. winget progress spam + msstore agreement noise in non-interactive output
   (`--disable-interactivity --source winget`).
5. Em dashes in console output mojibake on Windows (`-` now; keep manage.py
   *output* ASCII).
6. doctor failed member machines on non-ADO remotes (now informational
   unless PAT/FOLD set).

Rig quirks (not product bugs): the host's kernel/modules mismatch forces
dockurr into user-mode networking (passt), which needed `USER_PORTS: "22"`
in the compose file for guest SSH, and stalls `git://`-protocol pushes
entirely (plain HTTP upload is fine -> use the smart-HTTP bridge, which is
also closer to production ADO-over-HTTPS). A host reboot restores real NAT.
