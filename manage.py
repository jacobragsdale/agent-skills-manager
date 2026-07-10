#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Safely update the team skill runtime and publish factual skill learnings.

The skills repository is cloned to ~/.agents and treated as a runtime appliance.
Mutable configuration, queued feedback, locks, and logs live outside that
checkout. Member machines fetch the skills repository and publish only explicit
learning feedback to a per-machine branch in a separate inbox repository.
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


SCHEMA_VERSION = 1
CONFIG_VERSION = 1
STATE_DIR_ENV = "AGENT_SKILLS_STATE_DIR"
INBOX_URL_ENV = "AGENT_SKILLS_INBOX_URL"
NET_TIMEOUT = 300
MAX_LEARNING_LENGTH = 2000
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[0-9a-f]{7,64}$")
REMOTE_LEARNING_PATH_RE = re.compile(
    r"^learnings/(?P<event>[0-9a-f-]{36})\.json$"
)
CORRECTION_CATEGORIES = {
    "trigger-false-positive",
    "trigger-false-negative",
    "instruction",
    "tool-drift",
    "environment",
    "missing-context",
    "other",
}
REPO_ROOT = Path(__file__).resolve().parent


# Errors and process helpers


class ManagerError(RuntimeError):
    """Expected operational failure with a user-actionable message."""


class RuntimeSafetyError(ManagerError):
    """The managed checkout is not safe to update automatically."""


class FeedbackValidationError(ManagerError):
    """A learning event does not satisfy the committed schema."""


class LockBusyError(ManagerError):
    """Another manager process currently owns the state lock."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def format_utc(value: dt.datetime) -> str:
    if value.tzinfo is None:
        raise FeedbackValidationError("timestamps must be timezone-aware")
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
    def pending(self) -> Path:
        return self.root / "feedback" / "pending"

    @property
    def quarantine(self) -> Path:
        return self.root / "feedback" / "quarantine"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def publisher_repo(self) -> Path:
        return self.root / "feedback-inbox-repo"

    @property
    def aggregate_repo(self) -> Path:
        return self.root / "aggregate-feedback-inbox-repo"

    def ensure(self) -> None:
        for path in (self.pending, self.quarantine, self.locks, self.logs):
            path.mkdir(parents=True, exist_ok=True)


@dataclass
class ManagerConfig:
    runtime_path: str
    runtime_repo_url: str
    inbox_repo_url: str
    branch: str
    machine_id: str
    schema_version: int = CONFIG_VERSION

    @classmethod
    def new(
        cls,
        runtime_path: Path,
        runtime_repo_url: str,
        inbox_repo_url: str,
        branch: str = "main",
        *,
        machine_id: str | None = None,
    ) -> ManagerConfig:
        return cls(
            runtime_path=str(Path(runtime_path).expanduser().resolve()),
            runtime_repo_url=runtime_repo_url.rstrip("/"),
            inbox_repo_url=inbox_repo_url.rstrip("/"),
            branch=branch,
            machine_id=machine_id or str(uuid.uuid4()),
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
            raise ManagerError(f"invalid manager config {paths.config}: {exc}") from exc
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != CONFIG_VERSION:
            raise ManagerError(
                f"unsupported config schema {self.schema_version}; expected {CONFIG_VERSION}"
            )
        _parse_uuid(self.machine_id, "machine_id")
        if not self.runtime_repo_url or not self.inbox_repo_url:
            raise ManagerError("both runtime_repo_url and inbox_repo_url are required")
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


# Learning schema and local retry queue


def _parse_utc(value: Any, field_name: str = "recorded_at") -> dt.datetime:
    if not isinstance(value, str):
        raise FeedbackValidationError(f"{field_name} must be an ISO-8601 UTC string")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeedbackValidationError(f"invalid {field_name}: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise FeedbackValidationError(f"{field_name} must be UTC")
    return parsed


def _parse_uuid(value: Any, field_name: str) -> uuid.UUID:
    if not isinstance(value, str):
        raise FeedbackValidationError(f"{field_name} must be a UUID string")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise FeedbackValidationError(f"invalid {field_name}: {value!r}") from exc


def make_learning_event(
    *,
    machine_id: str,
    skill_name: str,
    skill_version: str,
    correction_category: str,
    message: str,
    now: dt.datetime,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "recorded_at": format_utc(now),
        "machine_id": machine_id,
        "skill": {"name": skill_name, "version": skill_version},
        "category": correction_category,
        "message": message.strip(),
    }


def validate_learning(event: Any) -> None:
    """Validate any JSON-shaped value without leaking built-in type errors."""

    try:
        _validate_learning_fields(event)
    except FeedbackValidationError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise FeedbackValidationError(
            "learning contains invalid field types"
        ) from exc


def _validate_learning_fields(event: Any) -> None:
    if not isinstance(event, dict):
        raise FeedbackValidationError("learning must be a JSON object")
    expected = {
        "schema_version",
        "event_id",
        "recorded_at",
        "machine_id",
        "skill",
        "category",
        "message",
    }
    missing = expected - set(event)
    extra = set(event) - expected
    if missing:
        raise FeedbackValidationError(
            f"learning is missing fields: {', '.join(sorted(missing))}"
        )
    if extra:
        raise FeedbackValidationError(
            f"learning has unknown fields: {', '.join(sorted(extra))}"
        )
    if event["schema_version"] != SCHEMA_VERSION:
        raise FeedbackValidationError(
            f"unsupported learning schema {event['schema_version']!r}; expected {SCHEMA_VERSION}"
        )
    _parse_uuid(event["event_id"], "event_id")
    _parse_uuid(event["machine_id"], "machine_id")
    _parse_utc(event["recorded_at"])
    skill = event["skill"]
    if not isinstance(skill, dict) or set(skill) != {"name", "version"}:
        raise FeedbackValidationError("skill must contain exactly name and version")
    if not isinstance(skill["name"], str) or not SKILL_NAME_RE.fullmatch(skill["name"]):
        raise FeedbackValidationError(f"unsafe skill name: {skill['name']!r}")
    if not isinstance(skill["version"], str) or not VERSION_RE.fullmatch(
        skill["version"]
    ):
        raise FeedbackValidationError(f"invalid skill version: {skill['version']!r}")
    category = event["category"]
    if not isinstance(category, str) or category not in CORRECTION_CATEGORIES:
        raise FeedbackValidationError("invalid correction category")
    message = event["message"]
    if not isinstance(message, str) or not message.strip():
        raise FeedbackValidationError("learning message must be non-empty")
    if "\n" in message or "\r" in message or any(
        ord(character) < 32 and character != "\t" for character in message
    ):
        raise FeedbackValidationError(
            "learning message must be one line without controls"
        )
    if len(message) > MAX_LEARNING_LENGTH:
        raise FeedbackValidationError(
            f"learning message exceeds {MAX_LEARNING_LENGTH} characters"
        )


class FeedbackStore:
    def __init__(self, paths: StatePaths):
        self.paths = paths
        paths.ensure()

    def write(self, event: dict[str, Any]) -> Path:
        validate_learning(event)
        event_id = event["event_id"]
        target = self.paths.pending / f"{event_id}.json"
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if existing != event:
                raise ManagerError(f"learning event id collision: {event_id}")
            return target
        temp = self.paths.pending / f".{event_id}.{uuid.uuid4().hex}.tmp"
        payload = json.dumps(event, indent=2, sort_keys=True) + "\n"
        try:
            with temp.open("x", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return target

    def load_pending(self) -> list[tuple[Path, dict[str, Any]]]:
        valid: list[tuple[Path, dict[str, Any]]] = []
        for path in sorted(self.paths.pending.glob("*.json")):
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
                validate_learning(event)
                if path.stem != event["event_id"]:
                    raise FeedbackValidationError(
                        f"filename {path.name} does not match event_id {event['event_id']}"
                    )
            except (OSError, json.JSONDecodeError, FeedbackValidationError) as exc:
                self.quarantine(path, str(exc))
                continue
            valid.append((path, event))
        return valid

    def quarantine(self, path: Path, reason: str) -> None:
        target = self.paths.quarantine / path.name
        if target.exists():
            target = self.paths.quarantine / (
                f"{path.stem}-{uuid.uuid4().hex[:8]}{path.suffix}"
            )
        shutil.move(str(path), target)
        target.with_suffix(".reason.txt").write_text(
            reason.strip() + "\n", encoding="utf-8"
        )
        log(f"quarantined invalid learning {path.name}: {reason}")

    def mark_published(self, path: Path) -> None:
        path.unlink(missing_ok=True)


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


def skill_version(config: ManagerConfig, skill_name: str) -> str:
    if not SKILL_NAME_RE.fullmatch(skill_name):
        raise FeedbackValidationError(f"unsafe skill name: {skill_name!r}")
    runtime = Path(config.runtime_path)
    if not (runtime / "skills" / skill_name / "SKILL.md").is_file():
        raise FeedbackValidationError(f"skill is not installed: {skill_name}")
    return runtime_head(runtime)


def record_learning(
    config: ManagerConfig,
    paths: StatePaths,
    *,
    skill_name: str,
    correction_category: str,
    message: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    event = make_learning_event(
        machine_id=config.machine_id,
        skill_name=skill_name,
        skill_version=skill_version(config, skill_name),
        correction_category=correction_category,
        message=message,
        now=now or utc_now(),
    )
    FeedbackStore(paths).write(event)
    return event


# Per-machine feedback publication


def feedback_branch(machine_id: str) -> str:
    _parse_uuid(machine_id, "machine_id")
    return f"feedback/v1/{machine_id}"


def _clear_worktree(repo: Path) -> None:
    git(repo, "rm", "-rf", "--ignore-unmatch", ".", check=False)
    git(repo, "clean", "-fdx", check=False)


def _ensure_publisher_branch(
    config: ManagerConfig, paths: StatePaths, branch: str
) -> Path:
    repo = paths.publisher_repo
    if not (repo / ".git").exists():
        if repo.exists():
            shutil.rmtree(repo)
        clone = run(
            ["git", "clone", config.inbox_repo_url, str(repo)],
            check=False,
            timeout=NET_TIMEOUT,
        )
        if clone.returncode != 0:
            detail = (clone.stderr or clone.stdout).strip()[:400]
            raise ManagerError(f"could not clone feedback inbox: {detail}")
    origin = git(repo, "remote", "get-url", "origin").stdout.strip()
    if _normalize_repo_url(origin) != _normalize_repo_url(config.inbox_repo_url):
        raise ManagerError(
            f"local feedback clone points at {origin!r}, expected {config.inbox_repo_url!r}"
        )
    remote_ref = f"refs/heads/{branch}"
    exists = git(
        repo,
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        remote_ref,
        check=False,
        network=True,
    )
    if exists.returncode == 0:
        git(
            repo,
            "fetch",
            "origin",
            f"+{remote_ref}:refs/remotes/origin/{branch}",
            network=True,
        )
        git(repo, "checkout", "-B", branch, f"origin/{branch}")
        git(repo, "reset", "--hard", f"origin/{branch}")
        git(repo, "clean", "-fdx")
    elif exists.returncode == 2:
        git(repo, "checkout", "--orphan", branch)
        _clear_worktree(repo)
    else:
        detail = (exists.stderr or exists.stdout).strip()[:400]
        raise ManagerError(f"could not query feedback branch: {detail}")
    return repo


def publish_pending(config: ManagerConfig, paths: StatePaths) -> int:
    store = FeedbackStore(paths)
    pending = store.load_pending()
    if not pending:
        log("feedback: nothing pending")
        return 0
    branch = feedback_branch(config.machine_id)
    repo = _ensure_publisher_branch(config, paths, branch)
    copied: list[Path] = []
    for source, event in pending:
        if event["machine_id"] != config.machine_id:
            store.quarantine(
                source, "learning machine_id does not match this installation"
            )
            continue
        target = repo / "learnings" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if json.loads(target.read_text(encoding="utf-8")) != event:
                raise ManagerError(f"remote learning path collision: {source.name}")
        else:
            shutil.copy2(source, target)
        copied.append(source)
    if not copied:
        return 0
    git(repo, "add", "--", "learnings")
    changed = git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
    if changed:
        short = config.machine_id.split("-", 1)[0]
        git(
            repo,
            "-c",
            f"user.name=Agent Skills {short}",
            "-c",
            f"user.email={config.machine_id}@agent-skills.invalid",
            "commit",
            "-m",
            f"feedback: publish {len(copied)} learning(s) from {short}",
        )
        push = git(
            repo,
            "push",
            "origin",
            f"HEAD:refs/heads/{branch}",
            check=False,
            network=True,
        )
        if push.returncode != 0:
            if is_auth_failure(push):
                notify_user(
                    "Inbox sign-in expired - run fix-signin.cmd in your .agents folder."
                )
            detail = (push.stderr or push.stdout).strip()[:400]
            raise ManagerError(
                f"feedback push failed; pending learnings were kept: {detail}"
            )
    for source in copied:
        store.mark_published(source)
    log(f"feedback: published {len(copied)} learning(s) to {branch}")
    return len(copied)


# Maintainer aggregation


@dataclass(frozen=True)
class AggregationResult:
    accepted: int
    rejected: int
    scanned_refs: int


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


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManagerError(f"invalid JSON in {path}: {exc}") from exc


def _ensure_aggregate_clone(inbox_repo_url: str, paths: StatePaths) -> Path:
    repo = paths.aggregate_repo
    if not (repo / ".git").exists():
        if repo.exists():
            shutil.rmtree(repo)
        clone = run(
            ["git", "clone", inbox_repo_url, str(repo)],
            check=False,
            timeout=NET_TIMEOUT,
        )
        if clone.returncode != 0:
            detail = (clone.stderr or clone.stdout).strip()[:400]
            raise ManagerError(
                f"could not clone feedback inbox for aggregation: {detail}"
            )
    origin = git(repo, "remote", "get-url", "origin").stdout.strip()
    if _normalize_repo_url(origin) != _normalize_repo_url(inbox_repo_url):
        raise ManagerError(f"aggregate feedback clone has unexpected origin: {origin}")
    fetch = git(
        repo,
        "fetch",
        "--prune",
        "origin",
        "+refs/heads/feedback/v1/*:refs/remotes/origin/feedback/v1/*",
        check=False,
        network=True,
    )
    if fetch.returncode != 0:
        detail = (fetch.stderr or fetch.stdout).strip()[:400]
        raise ManagerError(f"could not fetch feedback refs: {detail}")
    return repo


def _normalize_learning(message: str) -> str:
    return re.sub(r"\s+", " ", message).strip().casefold()


def _append_learning(repo_root: Path, event: dict[str, Any]) -> bool:
    skill_name = event["skill"]["name"]
    if not SKILL_NAME_RE.fullmatch(skill_name):
        raise FeedbackValidationError(f"unsafe skill name: {skill_name!r}")
    skills_root = (repo_root / "skills").resolve()
    target = (skills_root / skill_name / "LEARNINGS.md").resolve()
    try:
        target.relative_to(skills_root)
    except ValueError as exc:
        raise FeedbackValidationError(
            f"learning target escapes skills root: {target}"
        ) from exc
    if not target.is_file():
        raise FeedbackValidationError(
            f"learning references missing skill: {skill_name}"
        )
    existing = target.read_text(encoding="utf-8")
    normalized = _normalize_learning(event["message"])
    existing_messages = (
        re.sub(r"^- \d{4}-\d{2}-\d{2}: \[[^]]+\]\s*", "", line)
        for line in existing.splitlines()
        if line.startswith("- ")
    )
    if any(normalized == _normalize_learning(message) for message in existing_messages):
        return False
    line = (
        f"- {event['recorded_at'][:10]}: [{event['category']}] "
        f"{event['message'].strip()}"
    )
    _atomic_write_text(target, existing.rstrip("\n") + "\n" + line + "\n")
    return True


def _safe_rejection_reason(error: Exception) -> str:
    """Return a useful label without copying attacker-controlled event values."""

    if isinstance(error, json.JSONDecodeError):
        return "malformed JSON"
    text = str(error).casefold()
    labels = (
        ("unsupported learning schema", "unsupported learning schema"),
        ("unsafe skill name", "unsafe skill name"),
        ("event_id does not match", "event ID does not match filename"),
        ("machine_id does not match", "event machine ID does not match branch"),
        ("escapes skills root", "learning target escapes skills root"),
        ("missing skill", "learning references a missing skill"),
        ("timestamp", "invalid UTC timestamp"),
        ("uuid", "invalid UUID"),
        ("unknown fields", "learning contains unknown fields"),
        ("missing fields", "learning is missing required fields"),
        ("skill", "invalid skill fields"),
        ("category", "invalid correction category"),
        ("message", "invalid learning message"),
    )
    for marker, label in labels:
        if marker in text:
            return label
    return "learning failed schema or application validation"


def aggregate_feedback(
    repo_root: Path, inbox_repo_url: str, paths: StatePaths
) -> AggregationResult:
    repo_root = repo_root.resolve()
    feedback = repo_root / "feedback"
    state_path = feedback / "ingestion-state.json"
    rejected_path = feedback / "REJECTED.md"
    state = _load_json(
        state_path,
        {"schema_version": 1, "processed_events": {}},
    )
    if (
        state.get("schema_version") != 1
        or not isinstance(state.get("processed_events"), dict)
    ):
        raise ManagerError(f"invalid feedback ingestion state: {state_path}")
    existing_rejections = (
        rejected_path.read_text(encoding="utf-8")
        if rejected_path.is_file()
        else "# Rejected feedback\n\n"
    )
    rejection_lines = {
        line for line in existing_rejections.splitlines() if line.startswith("- ")
    }
    inbox = _ensure_aggregate_clone(inbox_repo_url, paths)
    refs = git(
        inbox,
        "for-each-ref",
        "--format=%(refname)",
        "refs/remotes/origin/feedback/v1/",
    ).stdout.splitlines()
    accepted = 0
    rejected = 0
    scanned = 0
    processed_events = state["processed_events"]
    for ref in sorted(refs):
        key = ref.removeprefix("refs/remotes/origin/")
        parts = key.split("/")
        if len(parts) != 3:
            line = "- Invalid feedback ref: branch shape is not allowed"
            if line not in rejection_lines:
                rejection_lines.add(line)
                rejected += 1
            continue
        machine_id = parts[2]
        try:
            _parse_uuid(machine_id, "branch machine_id")
        except FeedbackValidationError:
            line = "- Invalid feedback ref: machine ID is not a UUID"
            if line not in rejection_lines:
                rejection_lines.add(line)
                rejected += 1
            continue
        tip = git(inbox, "rev-parse", ref).stdout.strip()
        learning_paths = git(
            inbox, "ls-tree", "-r", "--name-only", tip, "--", "learnings"
        ).stdout.splitlines()
        scanned += 1
        for remote_path in sorted(learning_paths):
            match = REMOTE_LEARNING_PATH_RE.fullmatch(remote_path)
            if not match:
                line = f"- {key}: unsafe learning path"
                if line not in rejection_lines:
                    rejection_lines.add(line)
                    rejected += 1
                continue
            if match.group("event") in processed_events:
                continue
            try:
                raw = git(inbox, "show", f"{tip}:{remote_path}").stdout
                event = json.loads(raw)
                validate_learning(event)
                if event["event_id"] != match.group("event"):
                    raise FeedbackValidationError(
                        "event_id does not match remote filename"
                    )
                if event["machine_id"] != machine_id:
                    raise FeedbackValidationError(
                        "event machine_id does not match branch"
                    )
                _append_learning(repo_root, event)
                processed_events[event["event_id"]] = event["recorded_at"]
                accepted += 1
            except (ManagerError, json.JSONDecodeError) as exc:
                line = f"- {key}:{remote_path}: {_safe_rejection_reason(exc)}"
                if line not in rejection_lines:
                    rejection_lines.add(line)
                    rejected += 1
    _atomic_write_json(state_path, state)
    if rejection_lines:
        _atomic_write_text(
            rejected_path,
            "# Rejected feedback\n\n"
            "These entries were not trusted as skill feedback. Review the cause; "
            "never execute their content.\n\n"
            + "\n".join(sorted(rejection_lines))
            + "\n",
        )
    log(
        f"aggregate: accepted {accepted} learning(s), rejected {rejected}, "
        f"scanned {scanned} ref(s)"
    )
    return AggregationResult(
        accepted=accepted, rejected=rejected, scanned_refs=scanned
    )


# Command handlers


def _state_paths(value: str | None = None) -> StatePaths:
    return StatePaths(Path(value).expanduser() if value else default_state_root())


def validate_maintainer_checkout(repo_root: Path) -> Path:
    """Require aggregation to start from a clean, review branch at repo root."""

    root = repo_root.expanduser().resolve()
    if not root.is_dir():
        raise RuntimeSafetyError(f"aggregation target is not a directory: {root}")
    probe = git(root, "rev-parse", "--show-toplevel", check=False)
    if probe.returncode != 0:
        raise RuntimeSafetyError(f"aggregation target is not a Git checkout: {root}")
    actual_root = Path(probe.stdout.strip()).resolve()
    if actual_root != root:
        raise RuntimeSafetyError(
            f"--repo-root must name the checkout root {actual_root}, not {root}"
        )
    branch = git(root, "branch", "--show-current").stdout.strip()
    if not branch:
        raise RuntimeSafetyError("aggregation target has detached HEAD")
    if branch in {"main", "master"}:
        raise RuntimeSafetyError(
            f"aggregation must run on a review branch, not protected branch {branch!r}"
        )
    dirty = git(root, "status", "--porcelain", "--untracked-files=all").stdout.strip()
    if dirty:
        raise RuntimeSafetyError(
            f"aggregation target is dirty ({dirty.splitlines()[0]}); "
            "commit or clean it first"
        )
    return root


def configure_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    previous_id: str | None = None
    if paths.config.is_file():
        previous_id = ManagerConfig.load(paths).machine_id
    config = ManagerConfig.new(
        Path(args.runtime_path),
        args.repo_url,
        args.inbox_repo_url,
        args.branch,
        machine_id=previous_id,
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
    probe = run(
        ["git", "ls-remote", "--heads", config.inbox_repo_url],
        check=False,
        timeout=NET_TIMEOUT,
    )
    report(
        probe.returncode == 0,
        "feedback inbox reachable",
        "" if probe.returncode == 0 else (probe.stderr or probe.stdout).strip()[:250],
    )
    pending = FeedbackStore(paths).load_pending()
    report(True, "pending learnings", str(len(pending)))
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


def publish_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.load(paths)
    with ProcessLock(paths.locks / "nightly.lock"):
        publish_pending(config, paths)


def nightly_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.load(paths)
    errors: list[str] = []
    with ProcessLock(paths.locks / "nightly.lock"):
        try:
            sync_runtime(config)
        except ManagerError as exc:
            errors.append(f"sync: {exc}")
        try:
            publish_pending(config, paths)
        except ManagerError as exc:
            errors.append(f"feedback: {exc}")
    if errors:
        notify_user("Agent Skills nightly job needs attention; see the task log.")
        raise ManagerError("; ".join(errors))


def record_learning_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    config = ManagerConfig.load(paths)
    event = record_learning(
        config,
        paths,
        skill_name=args.skill,
        correction_category=args.category,
        message=args.message,
    )
    print(event["event_id"])


def aggregate_command(args: argparse.Namespace) -> None:
    paths = _state_paths(args.state_dir)
    paths.ensure()
    inbox_url = args.inbox_repo_url or os.environ.get(INBOX_URL_ENV)
    if not inbox_url and paths.config.is_file():
        inbox_url = ManagerConfig.load(paths).inbox_repo_url
    if not inbox_url:
        raise ManagerError(
            f"inbox URL required via --inbox-repo-url, {INBOX_URL_ENV}, or config"
        )
    repo_root = validate_maintainer_checkout(Path(args.repo_root))
    with ProcessLock(paths.locks / "aggregate.lock"):
        aggregate_feedback(repo_root, inbox_url, paths)


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
        "configure", help="write local runtime and feedback configuration"
    )
    configure.add_argument("--runtime-path", required=True)
    configure.add_argument("--repo-url", required=True)
    configure.add_argument("--inbox-repo-url", required=True)
    configure.add_argument("--branch", default="main")
    _add_state_arg(configure)
    configure.set_defaults(handler=configure_command)

    doctor = subparsers.add_parser(
        "doctor", help="verify runtime, state, tools, and feedback inbox access"
    )
    _add_state_arg(doctor)
    doctor.set_defaults(handler=doctor_command)

    sync = subparsers.add_parser(
        "sync", help="fast-forward the verified clean runtime"
    )
    _add_state_arg(sync)
    sync.set_defaults(handler=sync_command)

    publish = subparsers.add_parser(
        "publish", help="publish queued learning feedback"
    )
    _add_state_arg(publish)
    publish.set_defaults(handler=publish_command)

    nightly = subparsers.add_parser(
        "nightly", help="safely update the runtime and publish queued feedback"
    )
    _add_state_arg(nightly)
    nightly.set_defaults(handler=nightly_command)

    learning = subparsers.add_parser(
        "record-learning", help="queue one factual skill correction for review"
    )
    learning.add_argument("--skill", required=True)
    learning.add_argument(
        "--category", required=True, choices=sorted(CORRECTION_CATEGORIES)
    )
    learning.add_argument("--message", required=True)
    _add_state_arg(learning)
    learning.set_defaults(handler=record_learning_command)

    aggregate = subparsers.add_parser(
        "aggregate", help="fold new feedback into skill LEARNINGS.md files"
    )
    aggregate.add_argument("--repo-root", default=str(REPO_ROOT))
    aggregate.add_argument("--inbox-repo-url")
    _add_state_arg(aggregate)
    aggregate.set_defaults(handler=aggregate_command)

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
