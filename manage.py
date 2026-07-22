#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Safely install and update the team skill runtime.

The skills repository is cloned to ~/.agents and treated as a runtime
appliance. Mutable configuration, locks, and logs live outside that checkout.
Member machines only fetch and fast-forward the skills repository; they never
push, reset, or rewrite it.
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


CONFIG_VERSION = 2
STATE_DIR_ENV = "AGENT_SKILLS_STATE_DIR"
NET_TIMEOUT = 300
VERSION_RE = re.compile(r"^[0-9a-f]{7,64}$")
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
    schema_version: int = CONFIG_VERSION

    @classmethod
    def new(
        cls,
        runtime_path: Path,
        runtime_repo_url: str,
        branch: str = "main",
    ) -> ManagerConfig:
        return cls(
            runtime_path=str(Path(runtime_path).expanduser().resolve()),
            runtime_repo_url=runtime_repo_url.rstrip("/"),
            branch=branch,
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
                "Git sign-in expired - run fix-signin.cmd in your .agents folder."
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


# Command handlers


def _state_paths(value: str | None = None) -> StatePaths:
    return StatePaths(Path(value).expanduser() if value else default_state_root())


def configure_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.new(
        Path(args.runtime_path),
        args.repo_url,
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
    with ProcessLock(paths.locks / "nightly.lock"):
        sync_runtime(config)


def nightly_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.load(paths)
    try:
        with ProcessLock(paths.locks / "nightly.lock"):
            sync_runtime(config)
    except ManagerError as exc:
        notify_user("Agent Skills nightly job needs attention; see the task log.")
        raise ManagerError(f"sync: {exc}") from exc


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
    configure.add_argument("--branch", default="main")
    _add_state_arg(configure)
    configure.set_defaults(handler=configure_command)

    doctor = subparsers.add_parser(
        "doctor", help="verify runtime, state, and tools"
    )
    _add_state_arg(doctor)
    doctor.set_defaults(handler=doctor_command)

    sync = subparsers.add_parser(
        "sync", help="fast-forward the verified clean runtime"
    )
    _add_state_arg(sync)
    sync.set_defaults(handler=sync_command)

    nightly = subparsers.add_parser(
        "nightly", help="safely update the runtime and notify on failure"
    )
    _add_state_arg(nightly)
    nightly.set_defaults(handler=nightly_command)

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
