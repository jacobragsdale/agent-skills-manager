#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Safely install and update the team skill runtime.

The skills repository is cloned under local state and treated as a runtime
appliance: member machines only fetch and fast-forward it, never push, reset,
or rewrite it. Each machine subscribes to one skill set from sets.toml; sync
resolves the set's inheritance chain and rebuilds a generated view directory
(~/.agents) holding exactly the subscribed skills, which Cursor reads.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, Sequence


CONFIG_VERSION = 3
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
    skill_set: str
    schema_version: int = CONFIG_VERSION

    @classmethod
    def new(
        cls,
        runtime_path: Path,
        runtime_repo_url: str,
        view_path: Path,
        branch: str = "main",
        skill_set: str = "global",
    ) -> ManagerConfig:
        return cls(
            runtime_path=str(Path(runtime_path).expanduser().resolve()),
            runtime_repo_url=runtime_repo_url.rstrip("/"),
            branch=branch,
            view_path=str(Path(view_path).expanduser().resolve()),
            skill_set=skill_set,
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
        if not NAME_RE.fullmatch(self.skill_set):
            raise ManagerError(f"unsafe skill set name: {self.skill_set!r}")
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


# Skill sets and inheritance


def load_sets(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Parse and structurally validate sets.toml from a skills checkout."""

    path = repo_root / "sets.toml"
    if not path.is_file():
        raise ManagerError(f"missing sets manifest: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManagerError(f"invalid sets.toml: {exc}") from exc
    if not data:
        raise ManagerError("sets.toml defines no sets")
    roots = []
    for name, table in data.items():
        if not NAME_RE.fullmatch(name):
            raise ManagerError(f"unsafe set name: {name!r}")
        if not isinstance(table, dict):
            raise ManagerError(f"set {name!r} must be a TOML table")
        unknown = set(table) - {"inherits", "skills"}
        if unknown:
            raise ManagerError(
                f"set {name!r} has unknown keys: {', '.join(sorted(unknown))}"
            )
        skills = table.get("skills")
        if not isinstance(skills, list) or not all(
            isinstance(skill, str) and NAME_RE.fullmatch(skill) for skill in skills
        ):
            raise ManagerError(
                f"set {name!r} needs a skills list of kebab-case names"
            )
        if len(set(skills)) != len(skills):
            raise ManagerError(f"set {name!r} lists a skill twice")
        parent = table.get("inherits")
        if parent is None:
            roots.append(name)
        elif not isinstance(parent, str) or parent not in data:
            raise ManagerError(f"set {name!r} inherits unknown set {parent!r}")
    if len(roots) != 1:
        raise ManagerError(
            f"sets.toml must define exactly one root set without 'inherits' "
            f"(found {len(roots)})"
        )
    return data


def resolve_set(
    sets: dict[str, dict[str, Any]], name: str
) -> tuple[list[str], list[str]]:
    """Return (inheritance chain root-first, ordered union of skills)."""

    if name not in sets:
        raise ManagerError(
            f"unknown skill set {name!r}; available: {', '.join(sorted(sets))}"
        )
    chain: list[str] = []
    current: str | None = name
    while current is not None:
        if current in chain:
            raise ManagerError(f"set inheritance cycle at {current!r}")
        chain.append(current)
        current = sets[current].get("inherits")
    chain.reverse()
    skills: list[str] = []
    for set_name in chain:
        for skill in sets[set_name]["skills"]:
            if skill in skills:
                raise ManagerError(
                    f"skill {skill!r} appears twice on the {name!r} chain"
                )
            skills.append(skill)
    return chain, skills


def validate_sets(repo_root: Path) -> list[str]:
    """Return every structural problem with sets.toml and the skills tree."""

    try:
        sets = load_sets(repo_root)
    except ManagerError as exc:
        return [str(exc)]
    errors: list[str] = []
    owners: dict[str, list[str]] = {}
    for name, table in sets.items():
        for skill in table["skills"]:
            owners.setdefault(skill, []).append(name)
    for skill, names in sorted(owners.items()):
        if len(names) > 1:
            errors.append(
                f"skill {skill!r} is listed in multiple sets: {', '.join(names)}"
            )
        if not (repo_root / "skills" / skill / "SKILL.md").is_file():
            errors.append(f"set {names[0]!r} lists missing skill: {skill}")
    skills_dir = repo_root / "skills"
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir()):
            if entry.is_dir() and entry.name not in owners:
                errors.append(
                    f"skill directory {entry.name!r} is not listed in any set"
                )
    for name in sets:
        try:
            resolve_set(sets, name)
        except ManagerError as exc:
            errors.append(str(exc))
    return errors


# Materialized skills view

VIEW_MARKER = ".agent-skills-managed"
VIEW_HELPERS = ("fix-signin.cmd", "fix-signin.ps1")


def materialize_view(config: ManagerConfig) -> None:
    """Rebuild the Cursor-facing skills view from the subscribed set.

    The view is generated and disposable: it is rebuilt in a temp directory
    and swapped in whole, and an existing directory is only ever replaced if
    it carries the marker file proving a previous run created it.
    """

    runtime = Path(config.runtime_path)
    view = Path(config.view_path)
    chain, skills = resolve_set(load_sets(runtime), config.skill_set)
    for skill in skills:
        if not (runtime / "skills" / skill / "SKILL.md").is_file():
            raise ManagerError(f"resolved skill is missing from the runtime: {skill}")
    if view.exists() and not (view / VIEW_MARKER).is_file():
        raise RuntimeSafetyError(
            f"{view} exists but is not a managed skills view; refusing to replace it"
        )
    temp = view.parent / f".{view.name}.{uuid.uuid4().hex}.tmp"
    try:
        (temp / "skills").mkdir(parents=True)
        for skill in skills:
            shutil.copytree(runtime / "skills" / skill, temp / "skills" / skill)
        for helper in VIEW_HELPERS:
            if (runtime / helper).is_file():
                shutil.copy2(runtime / helper, temp / helper)
        (temp / VIEW_MARKER).write_text(
            "Generated by manage.py; do not edit. Replaced on every sync.\n",
            encoding="utf-8",
        )
        _atomic_write_json(
            temp / "installed.json",
            {
                "set": config.skill_set,
                "chain": chain,
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
    log(f"view: set '{config.skill_set}' -> {len(skills)} skill(s) at {view}")


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
        args.skill_set,
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
        try:
            _, skills = resolve_set(load_sets(runtime), config.skill_set)
        except ManagerError as exc:
            report(False, f"skill set '{config.skill_set}' resolves", str(exc))
        else:
            report(
                True, f"skill set '{config.skill_set}' resolves", ", ".join(skills)
            )
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
                current = (
                    installed.get("set") == config.skill_set
                    and installed.get("skills") == skills
                    and installed.get("source_sha") == runtime_head(runtime)
                )
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


def validate_sets_command(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root).expanduser().resolve()
    errors = validate_sets(repo_root)
    if errors:
        for error in errors:
            log(f"sets: {error}")
        raise ManagerError(f"sets validation failed with {len(errors)} error(s)")
    sets = load_sets(repo_root)
    for name in sorted(sets):
        _, skills = resolve_set(sets, name)
        log(f"sets: {name} -> {', '.join(skills) or '(no skills)'}")
    log(f"sets: {len(sets)} set(s) valid")


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
    configure.add_argument("--skill-set", default="global")
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
        "validate-sets", help="check sets.toml and the skills tree for conflicts"
    )
    validate.add_argument("--repo-root", default=str(REPO_ROOT))
    validate.set_defaults(handler=validate_sets_command)

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
