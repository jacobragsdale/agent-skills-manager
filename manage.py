#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Team agent-skills manager.

This script lives at the ROOT of the team skills repo, which is cloned as
~/.agents on every machine. It is stdlib-only on purpose: the nightly job must
work behind corporate proxies with nothing but git + uv.

Commands (run from the repo root, i.e. `uv run manage.py <cmd>`):

  doctor    Check env vars, tools, and repo state. Exit nonzero on problems.
  harvest   Extract local LEARNINGS.md additions into a uniquely-named file
            under learnings/inbox/, push it to the default branch, then reset
            the working tree to origin. Leaves the machine clean and current.
  fold      Aggregate learnings/inbox/ entries into each skill's LEARNINGS.md
            (exact-ish dedupe, attribution), delete the inbox files, push the
            `learnings/fold` branch, and open/update an Azure DevOps PR.
            Only the designated fold machine (AGENT_SKILLS_FOLD=1) runs this.
  nightly   harvest, then (on Windows, if WSL has a clone) run harvest inside
            WSL, then fold if AGENT_SKILLS_FOLD=1. This is what the Windows
            Scheduled Task invokes.

Auth: requires the AGENT_SKILLS_PAT env var (Azure DevOps PAT, Code
read & write). The PAT is sent as a per-invocation Basic auth header and is
never written to git config or disk.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NoReturn

PAT_ENV = "AGENT_SKILLS_PAT"
FOLD_ENV = "AGENT_SKILLS_FOLD"
# Extend this list as the installer grows more required configuration.
REQUIRED_ENV = [PAT_ENV]

REPO_ROOT = Path(__file__).resolve().parent
INBOX = REPO_ROOT / "learnings" / "inbox"
ORPHANED = REPO_ROOT / "learnings" / "ORPHANED.md"
METRICS_INBOX = REPO_ROOT / "metrics" / "inbox"
REQUESTS_INBOX = REPO_ROOT / "requests" / "inbox"
MACHINES = REPO_ROOT / "machines"
MANAGER_DIR = REPO_ROOT / ".manager"  # gitignored: logs, backups, local spools
LOG_FILE = MANAGER_DIR / "manage.log"
# Local spools agents append to between harvests (see rules/team-loop.md):
USAGE_SPOOL = MANAGER_DIR / "usage.jsonl"      # one JSON object per line
REQUESTS_SPOOL = MANAGER_DIR / "requests.md"   # "- YYYY-MM-DD: <need>" lines
FOLD_BRANCH = "learnings/fold"
PUSH_RETRIES = 3


# ---------------------------------------------------------------- utilities

def log(msg: str) -> None:
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    try:
        MANAGER_DIR.mkdir(exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # logging must never break the job


def die(msg: str) -> NoReturn:
    log(f"ERROR: {msg}")
    raise SystemExit(1)


def run(args: list[str], check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        args, cwd=cwd or REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if check and proc.returncode != 0:
        die(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stdout}\n{proc.stderr}")
    return proc


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["git", *args], check=check)


def auth_header() -> str:
    pat = os.environ.get(PAT_ENV, "")
    return "AUTHORIZATION: Basic " + base64.b64encode(f":{pat}".encode()).decode()


def git_net(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """git command that talks to the remote — carries the PAT as a header."""
    return run(["git", "-c", f"http.extraheader={auth_header()}", *args], check=check)


def default_branch() -> str:
    proc = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if proc.returncode == 0:
        return proc.stdout.strip().removeprefix("origin/")
    for name in ("main", "master"):
        if git("rev-parse", "--verify", f"origin/{name}", check=False).returncode == 0:
            return name
    die("cannot determine default branch (no origin/HEAD, origin/main, or origin/master)")


def check_env() -> list[str]:
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def ensure_ready() -> str:
    if missing := check_env():
        die(f"missing required env vars: {', '.join(missing)}")
    if not (REPO_ROOT / ".git").exists():
        die(f"{REPO_ROOT} is not a git repository")
    git_net("fetch", "origin", "--prune")
    return default_branch()


def running_in_wsl() -> bool:
    if os.name == "nt":
        return False
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


# ---------------------------------------------------------------- harvest

LEARNINGS_GLOB = "*LEARNINGS.md"
ENTRY_RE = re.compile(r"^\s*-\s+")


def learnings_additions(base: str) -> dict[str, list[str]]:
    """Map skill dir (posix relpath) -> entry lines added in the working tree vs base."""
    diff = git("diff", base, "--", LEARNINGS_GLOB).stdout
    additions: dict[str, list[str]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = str(Path(line[6:].strip()).parent.as_posix())
        elif line.startswith("+++"):
            current = None
        elif current and line.startswith("+") and not line.startswith("+++"):
            text = line[1:].rstrip()
            if ENTRY_RE.match(text):
                additions.setdefault(current, []).append(text.strip())
    return additions


def backup_other_changes() -> None:
    """Copy non-LEARNINGS tracked modifications aside before the hard reset."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = MANAGER_DIR / "backup" / stamp
    for line in git("status", "--porcelain").stdout.splitlines():
        status, path = line[:2], line[3:].strip().strip('"')
        if status == "??" or path.endswith("LEARNINGS.md"):
            continue
        src = REPO_ROOT / path
        if src.is_file():
            dest = backup_dir / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            log(f"backed up local change before reset: {path} -> {dest}")


def push_with_retry(branch: str) -> None:
    for attempt in range(1, PUSH_RETRIES + 1):
        if git_net("push", "origin", f"HEAD:{branch}", check=False).returncode == 0:
            return
        log(f"push rejected (attempt {attempt}/{PUSH_RETRIES}); rebasing onto origin/{branch}")
        git_net("fetch", "origin")
        git("rebase", f"origin/{branch}")
    die(f"could not push to {branch} after {PUSH_RETRIES} attempts")


def identity() -> tuple[str, str]:
    user = re.sub(r"[^A-Za-z0-9._-]", "_", getpass.getuser())
    host = re.sub(r"[^A-Za-z0-9._-]", "_", socket.gethostname())
    if running_in_wsl():
        host += "-wsl"  # the Windows side of the same machine has its own clone
    return user, host


def frontmatter(user: str, host: str, now: dt.datetime) -> list[str]:
    return ["---", f"user: {user}", f"host: {host}", f"harvested: {now.isoformat(timespec='seconds')}", "---", ""]


def write_learnings_inbox(additions: dict[str, list[str]], user: str, host: str, now: dt.datetime) -> str:
    INBOX.mkdir(parents=True, exist_ok=True)
    inbox_file = INBOX / f"{now:%Y-%m-%d-%H%M%S}-{user}-{host}.md"
    lines = frontmatter(user, host, now)
    for skill, entries in sorted(additions.items()):
        lines.append(f"## {skill}")
        lines.extend(entries)
        lines.append("")
    inbox_file.write_text("\n".join(lines), encoding="utf-8")
    n = sum(len(v) for v in additions.values())
    return f"{n} learning(s) from {len(additions)} skill(s)"


def ship_usage_spool(user: str, host: str, now: dt.datetime) -> str | None:
    """Move valid JSON lines from the local usage spool to metrics/inbox/."""
    if not USAGE_SPOOL.is_file():
        return None
    valid: list[str] = []
    for line in USAGE_SPOOL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
            valid.append(line.strip())
        except json.JSONDecodeError:
            log(f"harvest: dropping malformed usage line: {line[:120]}")
    USAGE_SPOOL.unlink()
    if not valid:
        return None
    METRICS_INBOX.mkdir(parents=True, exist_ok=True)
    out = METRICS_INBOX / f"{now:%Y-%m-%d-%H%M%S}-{user}-{host}.jsonl"
    out.write_text("\n".join(valid) + "\n", encoding="utf-8")
    return f"{len(valid)} usage event(s)"


def ship_requests_spool(user: str, host: str, now: dt.datetime) -> str | None:
    """Move skill-request lines from the local requests spool to requests/inbox/."""
    if not REQUESTS_SPOOL.is_file():
        return None
    entries = [l.strip() for l in REQUESTS_SPOOL.read_text(encoding="utf-8").splitlines() if ENTRY_RE.match(l.strip())]
    REQUESTS_SPOOL.unlink()
    if not entries:
        return None
    REQUESTS_INBOX.mkdir(parents=True, exist_ok=True)
    out = REQUESTS_INBOX / f"{now:%Y-%m-%d-%H%M%S}-{user}-{host}.md"
    out.write_text("\n".join(frontmatter(user, host, now) + entries) + "\n", encoding="utf-8")
    return f"{len(entries)} skill request(s)"


def write_heartbeat(user: str, host: str, now: dt.datetime) -> None:
    """Per-machine fleet-health file. Date granularity so same-day re-runs are no-ops."""
    MACHINES.mkdir(parents=True, exist_ok=True)
    (MACHINES / f"{host}.json").write_text(json.dumps({
        "user": user,
        "host": host,
        "os": "wsl" if running_in_wsl() else os.name,
        "last_sync": now.date().isoformat(),
    }, indent=2) + "\n", encoding="utf-8")


def harvest() -> None:
    branch = ensure_ready()
    base = f"origin/{branch}"

    # Unpushed harvest commits from a previously failed night: push before any reset.
    ahead = int(git("rev-list", "--count", f"{base}..HEAD").stdout.strip() or "0")
    if ahead:
        log(f"{ahead} unpushed local commit(s) found; pushing before reset")
        push_with_retry(branch)
        git_net("fetch", "origin")

    additions = learnings_additions(base)
    backup_other_changes()
    git("reset", "--hard", base)

    user, host = identity()
    now = dt.datetime.now()
    shipped = [
        write_learnings_inbox(additions, user, host, now) if additions else None,
        ship_usage_spool(user, host, now),
        ship_requests_spool(user, host, now),
    ]
    write_heartbeat(user, host, now)

    git("add", "-A", "--", "learnings/inbox", "metrics/inbox", "requests/inbox", "machines")
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        log("harvest: nothing new; working tree synced to " + base)
        return
    parts = "; ".join(p for p in shipped if p) or "heartbeat only"
    git("commit", "-m", f"sync: {parts} from {user}@{host}")
    push_with_retry(branch)
    log(f"harvest: pushed {parts}")


# ---------------------------------------------------------------- fold

def parse_inbox(path: Path) -> tuple[str, dict[str, list[str]]]:
    """Return (attribution, {skill: [entries]}) for one inbox file."""
    user = host = "unknown"
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("user:"):
            user = line.split(":", 1)[1].strip()
        elif line.startswith("host:"):
            host = line.split(":", 1)[1].strip()
        elif line.startswith("## "):
            current = line[3:].strip()
        elif current and ENTRY_RE.match(line):
            sections.setdefault(current, []).append(line)
    return f"{user}@{host}", sections


NORM_DATE_RE = re.compile(r"^-\s*\d{4}-\d{2}-\d{2}:\s*")
NORM_ATTR_RE = re.compile(r"\s*\[[^\]]+@[^\]]+\]\s*$")


def normalize(entry: str) -> str:
    """Comparison key: drop the date prefix and [user@host] suffix, squash case/whitespace."""
    text = NORM_DATE_RE.sub("", entry.strip())
    text = NORM_ATTR_RE.sub("", text)
    return re.sub(r"\s+", " ", text).casefold()


def parse_remote() -> tuple[str, str, str] | None:
    """(org, project, repo) from the origin URL, or None if not Azure DevOps."""
    url = git("remote", "get-url", "origin").stdout.strip()
    m = re.match(r"https://(?:[^/@]+@)?dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/]+?)/?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)
    m = re.match(r"https://([^.@/]+)\.visualstudio\.com/(?:DefaultCollection/)?([^/]+)/_git/([^/]+?)/?$", url)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


def ado_api(method: str, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", auth_header().removeprefix("AUTHORIZATION: "))
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        die(f"Azure DevOps API {method} {url} failed: {e.code} {e.read().decode()[:500]}")


def ensure_pull_request(branch: str, target: str, title: str, description: str) -> None:
    remote = parse_remote()
    if remote is None:
        log("fold: origin is not an Azure DevOps URL; branch pushed, skipping PR creation")
        return
    org, project, repo = (urllib.parse.quote(p) for p in remote)
    api = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}/pullrequests"
    source = urllib.parse.quote(f"refs/heads/{branch}")
    existing = ado_api(
        "GET", f"{api}?searchCriteria.status=active&searchCriteria.sourceRefName={source}&api-version=7.1"
    )
    if existing.get("count", 0) > 0:
        pr = existing["value"][0]
        log(f"fold: updated existing PR !{pr['pullRequestId']}: {pr.get('title', '')}")
        return
    pr = ado_api("POST", f"{api}?api-version=7.1", {
        "sourceRefName": f"refs/heads/{branch}",
        "targetRefName": f"refs/heads/{target}",
        "title": title,
        "description": description,
    })
    log(f"fold: opened PR !{pr['pullRequestId']}: {title}")


def fold() -> None:
    branch = ensure_ready()
    base = f"origin/{branch}"
    dirty = [l for l in git("status", "--porcelain").stdout.splitlines() if not l.startswith("??")]
    if dirty:
        die("fold requires a clean working tree (untracked files are fine); run harvest first")
    git("checkout", "-B", FOLD_BRANCH, base)

    try:
        inbox_files = sorted(INBOX.glob("*.md")) if INBOX.is_dir() else []
        if not inbox_files:
            log("fold: inbox is empty; nothing to do")
            return

        folded: dict[str, int] = {}
        orphans: list[str] = []
        for path in inbox_files:
            attribution, sections = parse_inbox(path)
            for skill, entries in sections.items():
                target = REPO_ROOT / skill / "LEARNINGS.md"
                if not target.is_file():
                    orphans.extend(f"{e} [{attribution}, skill missing: {skill}]" for e in entries)
                    continue
                existing = target.read_text(encoding="utf-8")
                seen = {normalize(l) for l in existing.splitlines() if ENTRY_RE.match(l.strip())}
                new = []
                for entry in entries:
                    key = normalize(entry)
                    if key not in seen:
                        seen.add(key)
                        new.append(f"{entry} [{attribution}]")
                if new:
                    target.write_text(existing.rstrip("\n") + "\n" + "\n".join(new) + "\n", encoding="utf-8")
                    folded[skill] = folded.get(skill, 0) + len(new)
            git("rm", "-q", str(path.relative_to(REPO_ROOT).as_posix()))

        if orphans:
            prior = ORPHANED.read_text(encoding="utf-8") if ORPHANED.is_file() else "# Orphaned learnings\n"
            ORPHANED.write_text(prior.rstrip("\n") + "\n" + "\n".join(orphans) + "\n", encoding="utf-8")
            git("add", str(ORPHANED.relative_to(REPO_ROOT).as_posix()))

        git("add", "--", LEARNINGS_GLOB)
        today = dt.date.today().isoformat()
        summary = ", ".join(f"{skill}: {n}" for skill, n in sorted(folded.items())) or "dedupe only"
        git("commit", "-m", f"learnings: fold inbox ({today}) — {summary}")
        git_net("push", "origin", f"+{FOLD_BRANCH}")

        description = (
            f"Automated fold of `learnings/inbox/` ({len(inbox_files)} file(s)).\n\n"
            + "\n".join(f"- `{skill}`: {n} new entrie(s)" for skill, n in sorted(folded.items()))
            + ("\n- some entries referenced missing skills; see `learnings/ORPHANED.md`" if orphans else "")
            + "\n\nReview, merge, then fold recurring lessons into SKILL.md deliberately "
            "(see agent-create-skill, 'Improving an existing skill')."
        )
        ensure_pull_request(FOLD_BRANCH, branch, f"learnings: fold inbox ({today})", description)
    finally:
        git("checkout", branch, check=False)
        git("reset", "--hard", base, check=False)


# ---------------------------------------------------------------- nightly

def wsl_leg() -> None:
    if os.name != "nt" or not shutil.which("wsl.exe"):
        return
    # Make the PAT flow into WSL for this invocation.
    wslenv = os.environ.get("WSLENV", "")
    if PAT_ENV not in wslenv.split(":"):
        os.environ["WSLENV"] = f"{wslenv}:{PAT_ENV}/u".strip(":")
    probe = run(["wsl.exe", "-e", "bash", "-lc", "test -d ~/.agents/.git"], check=False)
    if probe.returncode != 0:
        log("nightly: WSL present but no ~/.agents clone inside it; skipping WSL leg")
        return
    log("nightly: running harvest inside WSL")
    proc = run(
        ["wsl.exe", "-e", "bash", "-lc",
         'cd ~/.agents && PATH="$HOME/.local/bin:$PATH" uv run manage.py harvest'],
        check=False,
    )
    for stream in (proc.stdout, proc.stderr):
        if stream.strip():
            log("  [wsl] " + stream.strip().replace("\n", "\n  [wsl] "))
    if proc.returncode != 0:
        log(f"nightly: WSL harvest failed with exit code {proc.returncode} (continuing)")


def nightly() -> None:
    harvest()
    wsl_leg()
    if os.environ.get(FOLD_ENV):
        if running_in_wsl():
            log("nightly: fold flag set but running inside WSL; fold runs on the Windows side only")
        else:
            fold()


# ---------------------------------------------------------------- doctor

def doctor() -> None:
    problems = 0

    def report(ok: bool, label: str, detail: str = "") -> None:
        nonlocal problems
        print(f"  [{'ok' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            problems += 1

    print("agent-skills doctor")
    for name in REQUIRED_ENV:
        report(bool(os.environ.get(name)), f"env {name}", "" if os.environ.get(name) else "not set")
    report(bool(os.environ.get(FOLD_ENV)) or True, f"env {FOLD_ENV}",
           "set — this is the fold machine" if os.environ.get(FOLD_ENV) else "not set (normal member machine)")
    report(shutil.which("git") is not None, "git on PATH")
    report(shutil.which("uv") is not None, "uv on PATH")
    report((REPO_ROOT / ".git").exists(), f"repo at {REPO_ROOT}")
    if (REPO_ROOT / ".git").exists():
        remote = parse_remote()
        url = git("remote", "get-url", "origin", check=False).stdout.strip()
        report(remote is not None, "origin is Azure DevOps", url)
        fetch = git_net("fetch", "origin", check=False) if os.environ.get(PAT_ENV) else None
        if fetch is not None:
            report(fetch.returncode == 0, "PAT can fetch from origin",
                   "" if fetch.returncode == 0 else fetch.stderr.strip()[:200])
    report(INBOX.is_dir() or not (REPO_ROOT / "learnings").exists(), "learnings/inbox exists",
           "" if INBOX.is_dir() else "create learnings/inbox/.gitkeep in the repo")
    if os.name == "nt":
        task = run(["schtasks", "/query", "/tn", "AgentSkillsNightly"], check=False)
        report(task.returncode == 0, "scheduled task AgentSkillsNightly", "" if task.returncode == 0 else "not registered")
    if problems:
        raise SystemExit(1)
    print("all checks passed")


# ---------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["doctor", "harvest", "fold", "nightly"])
    args = parser.parse_args()
    {"doctor": doctor, "harvest": harvest, "fold": fold, "nightly": nightly}[args.command]()


if __name__ == "__main__":
    main()
