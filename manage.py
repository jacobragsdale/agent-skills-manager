#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Safely install and update the team skill pack.

The skills repository is cloned under local state and treated as a runtime
appliance: member machines only fetch and fast-forward it, never push, reset,
or rewrite it. Sync rebuilds ~/.agents from every skill under skills/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence


CONFIG_VERSION = 4
STATE_DIR_ENV = "AGENT_SKILLS_STATE_DIR"
NET_TIMEOUT = 300
VERSION_RE = re.compile(r"^[0-9a-f]{7,64}$")
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REPO_ROOT = Path(__file__).resolve().parent


# Errors and process helpers


class ManagerError(RuntimeError):
    """Expected operational failure with a user-actionable message."""


class RuntimeSafetyError(ManagerError):
    """The managed checkout is not safe to update automatically."""


class LockBusyError(ManagerError):
    """Another manager process currently owns the state lock."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def format_utc(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise ManagerError("timestamps must be timezone-aware")
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def log(message: str) -> None:
    print(f"{format_utc(utc_now())} {message}", flush=True)


def die(message: str) -> NoReturn:
    log(f"ERROR: {message}")
    raise SystemExit(1)


def run(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout: int | None = None,
    interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if not interactive:
        env["GIT_TERMINAL_PROMPT"] = "0"
    child = subprocess.Popen(
        list(args),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/pid", str(child.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            child.kill()
        try:
            stdout, stderr = child.communicate(timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            stdout, stderr = "", ""
        stderr = (stderr or "") + f"\ntimed out after {timeout}s"
        proc = subprocess.CompletedProcess(list(args), 124, stdout, stderr)
    else:
        proc = subprocess.CompletedProcess(list(args), child.returncode, stdout, stderr)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise ManagerError(
            f"command failed ({proc.returncode}): {' '.join(args)}"
            + (f"\n{detail}" if detail else "")
        )
    return proc


def git(
    cwd: Path,
    *args: str,
    check: bool = True,
    network: bool = False,
    interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", *args],
        cwd=cwd,
        check=check,
        timeout=NET_TIMEOUT if network else None,
        interactive=interactive,
    )


AUTH_ERROR_MARKERS = (
    "authentication failed",
    "could not read username",
    "logon failed",
    "access denied",
    "http 401",
    "http 403",
    "tf401019",
    "terminal prompts disabled",
)


def is_auth_failure(proc: subprocess.CompletedProcess[str]) -> bool:
    detail = f"{proc.stdout}\n{proc.stderr}".lower()
    return any(marker in detail for marker in AUTH_ERROR_MARKERS)


def notify_user(message: str) -> None:
    log(f"NOTIFY: {message}")
    if os.name != "nt":
        return
    safe = message.replace("'", "''")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$t.GetElementsByTagName('text').Item(0).InnerText='Agent Skills';"
        f"$t.GetElementsByTagName('text').Item(1).InnerText='{safe}';"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Agent Skills').Show("
        "[Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        timeout=30,
    )


# Paths, configuration, and locking


def default_state_root() -> Path:
    if configured := os.environ.get(STATE_DIR_ENV):
        return Path(configured).expanduser()
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "AgentSkills"
        return Path.home() / "AppData" / "Local" / "AgentSkills"
    return Path.home() / ".local" / "state" / "AgentSkills"


@dataclass(frozen=True)
class StatePaths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for path in (self.locks, self.logs):
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class ManagerConfig:
    runtime_path: str
    runtime_repo_url: str
    branch: str
    view_path: str
    schema_version: int = CONFIG_VERSION

    @classmethod
    def new(
        cls,
        runtime_path: Path,
        runtime_repo_url: str,
        view_path: Path,
        branch: str = "main",
    ) -> ManagerConfig:
        return cls(
            runtime_path=str(Path(runtime_path).expanduser().resolve()),
            runtime_repo_url=runtime_repo_url.rstrip("/"),
            branch=branch,
            view_path=str(Path(view_path).expanduser().resolve()),
        )

    @classmethod
    def load(cls, paths: StatePaths) -> ManagerConfig:
        if not paths.config.is_file():
            raise ManagerError(
                f"manager is not configured; run 'manage.py configure' first ({paths.config})"
            )
        try:
            data = json.loads(paths.config.read_text(encoding="utf-8"))
            config = cls(**data)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ManagerError(
                f"invalid or outdated manager config {paths.config}: {exc}; "
                "re-run 'manage.py configure'"
            ) from exc
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != CONFIG_VERSION:
            raise ManagerError(
                f"unsupported config schema {self.schema_version}; expected "
                f"{CONFIG_VERSION}; re-run 'manage.py configure'"
            )
        if not self.runtime_repo_url:
            raise ManagerError("runtime_repo_url is required")
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", self.branch) or ".." in self.branch:
            raise ManagerError(f"unsafe runtime branch: {self.branch!r}")
        runtime = Path(self.runtime_path)
        view = Path(self.view_path)
        if runtime == view or runtime in view.parents or view in runtime.parents:
            raise ManagerError(
                "view_path and runtime_path must not overlap; the view is "
                "regenerated on every sync"
            )

    def save(self, paths: StatePaths) -> None:
        self.validate()
        paths.ensure()
        _atomic_write_json(paths.config, self.__dict__)


class ProcessLock:
    """Cross-platform advisory lock held for the lifetime of one manager job."""

    def __init__(self, path: Path):
        self.path = path
        self._handle: Any = None

    def __enter__(self) -> ProcessLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._handle = self.path.open("a+b")
            self._handle.seek(0)
            if self._handle.read(1) == b"":
                self._handle.write(b"0")
                self._handle.flush()
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if self._handle is not None:
                self._handle.close()
            self._handle = None
            raise LockBusyError(
                f"another Agent Skills job is already running ({self.path})"
            ) from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is None:
            return
        self._handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


# Safe runtime updates


def _normalize_repo_url(value: str) -> str:
    return value.strip().rstrip("/")


def runtime_head(runtime: Path) -> str:
    head = git(runtime, "rev-parse", "HEAD").stdout.strip()
    if not VERSION_RE.fullmatch(head):
        raise RuntimeSafetyError(f"runtime HEAD is not a Git SHA: {head!r}")
    return head


def validate_runtime(config: ManagerConfig) -> Path:
    runtime = Path(config.runtime_path).resolve()
    if not runtime.is_dir() or not (runtime / ".git").exists():
        raise RuntimeSafetyError(f"configured runtime is not a Git clone: {runtime}")
    branch = git(runtime, "branch", "--show-current").stdout.strip()
    if branch != config.branch:
        raise RuntimeSafetyError(
            f"runtime is on branch {branch!r}, expected {config.branch!r}; refusing to switch or reset"
        )
    origin = git(runtime, "remote", "get-url", "origin").stdout.strip()
    if _normalize_repo_url(origin) != _normalize_repo_url(config.runtime_repo_url):
        raise RuntimeSafetyError(
            f"runtime origin is {origin!r}, expected {config.runtime_repo_url!r}"
        )
    dirty = git(runtime, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if dirty:
        first = dirty.splitlines()[0]
        raise RuntimeSafetyError(
            f"runtime checkout is dirty ({first}); refusing to discard local files"
        )
    return runtime


def sync_runtime(config: ManagerConfig) -> None:
    runtime = validate_runtime(config)
    fetch = git(runtime, "fetch", "origin", "--prune", check=False, network=True)
    if fetch.returncode != 0:
        if is_auth_failure(fetch):
            notify_user(
                "Git sign-in expired - run 'git fetch' in "
                "%LOCALAPPDATA%\\AgentSkills\\repo to sign in again."
            )
        detail = (fetch.stderr or fetch.stdout).strip()[:400]
        raise ManagerError(f"runtime fetch failed: {detail}")
    remote = f"origin/{config.branch}"
    verify = git(runtime, "rev-parse", "--verify", remote, check=False)
    if verify.returncode != 0:
        raise RuntimeSafetyError(f"remote branch does not exist: {remote}")
    counts = git(
        runtime, "rev-list", "--left-right", "--count", f"HEAD...{remote}"
    ).stdout.split()
    if len(counts) != 2:
        raise RuntimeSafetyError("could not determine runtime divergence")
    ahead, behind = (int(value) for value in counts)
    if ahead:
        raise RuntimeSafetyError(
            f"runtime has {ahead} local commit(s); refusing to rewrite them"
        )
    if behind:
        git(runtime, "merge", "--ff-only", remote)
        log(f"runtime: fast-forwarded {behind} commit(s) from {remote}")
    else:
        log(f"runtime: already current at {runtime_head(runtime)[:12]}")


# Flat skill pack


def list_skills(repo_root: Path) -> list[str]:
    """Return every skill directory in stable order."""

    skills_dir = repo_root / "skills"
    if not skills_dir.is_dir():
        raise ManagerError(f"missing skills directory: {skills_dir}")
    skills: list[str] = []
    for entry in sorted(skills_dir.iterdir(), key=lambda path: path.name):
        if not entry.is_dir():
            raise ManagerError(f"unexpected file in skills directory: {entry.name}")
        if not NAME_RE.fullmatch(entry.name):
            raise ManagerError(f"unsafe skill directory name: {entry.name!r}")
        skills.append(entry.name)
    if not skills:
        raise ManagerError("skills directory is empty")
    return skills


def _skill_problems(skill_dir: Path) -> list[str]:
    """Check the shape of one skill folder without any YAML dependency."""

    name = skill_dir.name
    problems: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return [f"skill {name!r}: missing SKILL.md"]
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return [f"skill {name!r}: SKILL.md lacks closed '---' frontmatter"]
    frontmatter = text[4 : text.index("\n---", 4)]
    declared = re.search(
        r"^name:\s*[\"']?([A-Za-z0-9-]+)[\"']?\s*$", frontmatter, re.MULTILINE
    )
    if not declared or declared.group(1) != name:
        problems.append(
            f"skill {name!r}: frontmatter name must match the folder name"
        )
    if not re.search(r"^description:\s*\S", frontmatter, re.MULTILINE):
        problems.append(f"skill {name!r}: frontmatter needs a description")
    return problems


def validate_skills(repo_root: Path) -> list[str]:
    """Return every structural problem with the flat skills pack."""

    try:
        skills = list_skills(repo_root)
    except ManagerError as exc:
        return [str(exc)]
    return [
        problem
        for skill in skills
        for problem in _skill_problems(repo_root / "skills" / skill)
    ]


# Materialized skills view

VIEW_MARKER = ".agent-skills-managed"


def materialize_view(config: ManagerConfig) -> None:
    """Rebuild the Cursor-facing view from the flat skill pack.

    The view is generated and disposable: it is rebuilt in a temp directory
    and swapped in whole, and an existing directory is only ever replaced if
    it carries the marker file proving a previous run created it.
    """

    runtime = Path(config.runtime_path)
    view = Path(config.view_path)
    errors = validate_skills(runtime)
    if errors:
        raise ManagerError("invalid skills pack: " + "; ".join(errors))
    skills = list_skills(runtime)
    if view.exists() and not (view / VIEW_MARKER).is_file():
        raise RuntimeSafetyError(
            f"{view} exists but is not a managed skills view; refusing to replace it"
        )
    temp = view.parent / f".{view.name}.{uuid.uuid4().hex}.tmp"
    try:
        (temp / "skills").mkdir(parents=True)
        for skill in skills:
            shutil.copytree(runtime / "skills" / skill, temp / "skills" / skill)
        (temp / VIEW_MARKER).write_text(
            "Generated by manage.py; do not edit. Replaced on every sync.\n",
            encoding="utf-8",
        )
        _atomic_write_json(
            temp / "installed.json",
            {
                "skills": skills,
                "source_sha": runtime_head(runtime),
                "generated_at": format_utc(utc_now()),
            },
        )
        if view.exists():
            shutil.rmtree(view)
        os.replace(temp, view)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    log(f"view: installed {len(skills)} skill(s) at {view}")


# Command handlers


def _state_paths(value: str | None = None) -> StatePaths:
    return StatePaths(Path(value).expanduser() if value else default_state_root())


def configure_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.new(
        Path(args.runtime_path),
        args.repo_url,
        Path(args.view_path),
        args.branch,
    )
    runtime = Path(config.runtime_path)
    if not (runtime / ".git").exists():
        raise ManagerError(f"runtime path is not a Git clone: {runtime}")
    config.save(paths)
    log(f"configured state at {paths.root}")


def doctor_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.load(paths)
    problems = 0

    def report(ok: bool, label: str, detail: str = "") -> None:
        nonlocal problems
        print(
            f"  [{'ok' if ok else 'FAIL'}] {label}"
            + (f" - {detail}" if detail else "")
        )
        if not ok:
            problems += 1

    print("agent-skills doctor")
    report(shutil.which("git") is not None, "git on PATH")
    report(shutil.which("uv") is not None, "uv on PATH")
    report(paths.config.is_file(), "configuration", str(paths.config))
    try:
        runtime = validate_runtime(config)
    except RuntimeSafetyError as exc:
        report(False, "runtime safety", str(exc))
    else:
        report(True, "runtime safety", str(runtime))
        report(
            REPO_ROOT.resolve() == runtime,
            "manager runs from configured runtime",
            str(REPO_ROOT),
        )
        errors = validate_skills(runtime)
        if errors:
            report(False, "skills pack", "; ".join(errors))
        else:
            skills = list_skills(runtime)
            report(True, "skills pack", ", ".join(skills))
            view = Path(config.view_path)
            installed_path = view / "installed.json"
            if not (view / VIEW_MARKER).is_file() or not installed_path.is_file():
                report(False, "skills view", f"not materialized yet: {view}")
            else:
                try:
                    installed = json.loads(
                        installed_path.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError:
                    installed = {}
                current = installed.get("skills") == skills and installed.get(
                    "source_sha"
                ) == runtime_head(runtime)
                report(
                    current,
                    "skills view is current",
                    str(view) if current else f"stale; run 'manage.py sync' ({view})",
                )
    if os.name == "nt":
        task = run(["schtasks", "/query", "/tn", "AgentSkillsNightly"], check=False)
        report(task.returncode == 0, "scheduled task AgentSkillsNightly")
    if problems:
        raise SystemExit(1)
    print("all checks passed")


def sync_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.load(paths)
    try:
        with ProcessLock(paths.locks / "sync.lock"):
            sync_runtime(config)
            materialize_view(config)
    except ManagerError:
        notify_user("Agent Skills sync needs attention; see the task log.")
        raise


def validate_skills_command(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).expanduser().resolve()
    errors = validate_skills(repo_root)
    if errors:
        for error in errors:
            log(f"skills: {error}")
        raise ManagerError(f"skill validation failed with {len(errors)} error(s)")
    skills = list_skills(repo_root)
    log(f"skills: {len(skills)} valid ({', '.join(skills)})")


def _add_state_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--state-dir",
        help=(
            "override local state directory "
            f"(default: {STATE_DIR_ENV} or platform default)"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser(
        "configure", help="write local runtime configuration"
    )
    configure.add_argument("--runtime-path", required=True)
    configure.add_argument("--repo-url", required=True)
    configure.add_argument("--view-path", required=True)
    configure.add_argument("--branch", default="main")
    _add_state_arg(configure)
    configure.set_defaults(handler=configure_command)

    doctor = subparsers.add_parser(
        "doctor", help="verify runtime, state, and tools"
    )
    _add_state_arg(doctor)
    doctor.set_defaults(handler=doctor_command)

    sync = subparsers.add_parser(
        "sync", help="fast-forward the clean runtime and rebuild the skills view"
    )
    _add_state_arg(sync)
    sync.set_defaults(handler=sync_command)

    validate = subparsers.add_parser(
        "validate-skills", help="check every folder in the flat skills pack"
    )
    validate.add_argument("--repo-root", default=str(REPO_ROOT))
    validate.set_defaults(handler=validate_skills_command)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except ManagerError as exc:
        die(str(exc))


if __name__ == "__main__":
    main()
