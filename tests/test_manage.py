from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import manage


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def init_bare_remote(root: Path, name: str) -> Path:
    remote = root / f"{name}.git"
    git(root, "init", "--bare", str(remote))
    seed = root / f"{name}-seed"
    git(root, "init", "-b", "main", str(seed))
    git(seed, "config", "user.name", "Tests")
    git(seed, "config", "user.email", "tests@example.invalid")
    (seed / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    git(seed, "add", "README.md")
    git(seed, "commit", "-m", "seed")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    return remote


def clone_runtime(root: Path, remote: Path, name: str = "runtime") -> Path:
    runtime = root / name
    git(root, "clone", str(remote), str(runtime))
    return runtime


def seed_skill(runtime: Path, name: str = "demo-skill") -> None:
    skill = runtime / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "Test skill."\n---\n\n# Test\n',
        encoding="utf-8",
    )
    (skill / "LEARNINGS.md").write_text("# Learnings\n", encoding="utf-8")
    git(runtime, "config", "user.name", "Tests")
    git(runtime, "config", "user.email", "tests@example.invalid")
    git(runtime, "add", "skills")
    git(runtime, "commit", "-m", "add test skill")
    git(runtime, "push", "origin", "main")


class EventSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.machine_id = str(uuid.uuid4())
        self.now = dt.datetime(2026, 7, 9, 12, 30, tzinfo=dt.timezone.utc)

    def test_invocation_event_round_trips(self) -> None:
        event = manage.make_invocation_event(
            machine_id=self.machine_id,
            skill_name="demo-skill",
            skill_version="a" * 40,
            surface_name="cursor",
            surface_version="3.5.0",
            now=self.now,
        )

        manage.validate_event(event)

        self.assertEqual(event["schema_version"], 1)
        self.assertEqual(event["outcome"], "unknown")
        self.assertTrue(event["recorded_at"].endswith("Z"))
        self.assertEqual(event["event_id"], event["invocation_id"])

    def test_path_traversal_skill_is_rejected(self) -> None:
        event = manage.make_invocation_event(
            machine_id=self.machine_id,
            skill_name="../../outside",
            skill_version="a" * 40,
            surface_name="cursor",
            surface_version=None,
            now=self.now,
        )

        with self.assertRaises(manage.EventValidationError):
            manage.validate_event(event)

    def test_correction_requires_a_category(self) -> None:
        event = manage.make_outcome_event(
            machine_id=self.machine_id,
            invocation_id=str(uuid.uuid4()),
            skill_name="demo-skill",
            skill_version="a" * 40,
            surface_name="cursor",
            surface_version=None,
            outcome="corrected",
            correction_category=None,
            now=self.now,
        )

        with self.assertRaises(manage.EventValidationError):
            manage.validate_event(event)

    def test_learning_message_must_be_one_line(self) -> None:
        event = manage.make_learning_event(
            machine_id=self.machine_id,
            invocation_id=str(uuid.uuid4()),
            skill_name="demo-skill",
            skill_version="a" * 40,
            surface_name="cursor",
            surface_version=None,
            correction_category="instruction",
            message="First line\n# injected heading",
            now=self.now,
        )

        with self.assertRaises(manage.EventValidationError):
            manage.validate_event(event)


class EventStoreTests(unittest.TestCase):
    def test_invalid_file_is_quarantined_and_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = manage.StatePaths(Path(tmp))
            paths.ensure()
            bad = paths.pending / "bad.json"
            bad.write_text('{"schema_version": 1}', encoding="utf-8")
            store = manage.EventStore(paths)

            events = store.load_pending()

            self.assertEqual(events, [])
            self.assertFalse(bad.exists())
            self.assertTrue((paths.quarantine / "bad.json").is_file())
            self.assertTrue((paths.quarantine / "bad.reason.txt").is_file())

    def test_event_is_written_atomically_and_marked_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = manage.StatePaths(Path(tmp))
            paths.ensure()
            event = manage.make_heartbeat_event(
                machine_id=str(uuid.uuid4()),
                runtime_version="b" * 40,
                now=dt.datetime.now(dt.timezone.utc),
            )
            store = manage.EventStore(paths)

            path = store.write(event)
            store.mark_sent(path)

            self.assertFalse(path.exists())
            self.assertTrue((paths.sent / path.name).is_file())
            self.assertEqual(list(paths.pending.glob("*.tmp")), [])


class RuntimeSafetyTests(unittest.TestCase):
    def test_clean_runtime_fast_forwards_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            updater = clone_runtime(root, remote, "updater")
            git(updater, "config", "user.name", "Tests")
            git(updater, "config", "user.email", "tests@example.invalid")
            (updater / "new.txt").write_text("new\n", encoding="utf-8")
            git(updater, "add", "new.txt")
            git(updater, "commit", "-m", "update")
            git(updater, "push", "origin", "main")
            config = manage.ManagerConfig.new(
                runtime_path=runtime,
                runtime_repo_url=str(remote),
                inbox_repo_url=str(init_bare_remote(root, "inbox")),
                branch="main",
            )

            manage.sync_runtime(config)

            self.assertEqual((runtime / "new.txt").read_text(encoding="utf-8"), "new\n")
            self.assertEqual(git(runtime, "status", "--porcelain").stdout, "")

    def test_wrong_branch_is_never_reset_or_switched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            git(runtime, "switch", "-c", "work-in-progress")
            marker = runtime / "draft.txt"
            marker.write_text("keep me", encoding="utf-8")
            config = manage.ManagerConfig.new(
                runtime_path=runtime,
                runtime_repo_url=str(remote),
                inbox_repo_url=str(init_bare_remote(root, "inbox")),
                branch="main",
            )

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.sync_runtime(config)

            self.assertEqual(
                git(runtime, "branch", "--show-current").stdout.strip(),
                "work-in-progress",
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")

    def test_dirty_main_is_not_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            marker = runtime / "README.md"
            marker.write_text("local edit\n", encoding="utf-8")
            config = manage.ManagerConfig.new(
                runtime_path=runtime,
                runtime_repo_url=str(remote),
                inbox_repo_url=str(init_bare_remote(root, "inbox")),
                branch="main",
            )

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.sync_runtime(config)

            self.assertEqual(marker.read_text(encoding="utf-8"), "local edit\n")


class InboxTransportTests(unittest.TestCase):
    def test_two_clients_publish_concurrently_to_different_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            seed = clone_runtime(root, skills_remote, "seed-runtime")
            seed_skill(seed)
            jobs: list[tuple[manage.ManagerConfig, manage.StatePaths]] = []
            for number in range(2):
                runtime = clone_runtime(root, skills_remote, f"runtime-{number}")
                paths = manage.StatePaths(root / f"state-{number}")
                paths.ensure()
                config = manage.ManagerConfig.new(
                    runtime, str(skills_remote), str(inbox_remote), "main"
                )
                config.save(paths)
                manage.EventStore(paths).write(
                    manage.make_heartbeat_event(
                        machine_id=config.machine_id,
                        runtime_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                        now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
                    )
                )
                jobs.append((config, paths))

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda job: manage.publish_pending(
                            job[0],
                            job[1],
                            now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
                        ),
                        jobs,
                    )
                )

            self.assertEqual(results, [1, 1])
            refs = git(
                inbox_remote,
                "for-each-ref",
                "--format=%(refname)",
                "refs/heads/inbox/v1/",
            ).stdout.splitlines()
            self.assertEqual(len(refs), 2)

    def test_publish_uses_machine_branch_and_preserves_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            paths.ensure()
            config = manage.ManagerConfig.new(runtime, str(skills_remote), str(inbox_remote), "main")
            config.save(paths)
            store = manage.EventStore(paths)
            store.write(
                manage.make_invocation_event(
                    machine_id=config.machine_id,
                    skill_name="demo-skill",
                    skill_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                    surface_name="cursor",
                    surface_version=None,
                    now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
                )
            )
            main_before = git(inbox_remote, "rev-parse", "refs/heads/main").stdout.strip()

            published = manage.publish_pending(config, paths, now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc))

            branch = f"refs/heads/inbox/v1/{config.machine_id}/2026-07"
            self.assertEqual(published, 1)
            self.assertEqual(git(inbox_remote, "rev-parse", "refs/heads/main").stdout.strip(), main_before)
            self.assertTrue(git(inbox_remote, "rev-parse", branch).stdout.strip())
            self.assertEqual(list(paths.pending.glob("*.json")), [])
            self.assertEqual(len(list(paths.sent.glob("*.json"))), 1)

    def test_failed_push_keeps_pending_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            paths.ensure()
            config = manage.ManagerConfig.new(runtime, str(skills_remote), str(inbox_remote), "main")
            config.save(paths)
            store = manage.EventStore(paths)
            store.write(
                manage.make_heartbeat_event(
                    machine_id=config.machine_id,
                    runtime_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                    now=dt.datetime.now(dt.timezone.utc),
                )
            )
            config.inbox_repo_url = str(root / "missing.git")
            config.save(paths)

            with self.assertRaises(manage.ManagerError):
                manage.publish_pending(config, paths)

            self.assertEqual(len(list(paths.pending.glob("*.json"))), 1)


class AggregationTests(unittest.TestCase):
    def test_processed_event_id_is_deduplicated_across_monthly_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote), "main"
            )
            event = manage.make_invocation_event(
                machine_id=config.machine_id,
                skill_name="demo-skill",
                skill_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                surface_name="cursor",
                surface_version=None,
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )
            manage.EventStore(paths).write(event)
            manage.publish_pending(
                config,
                paths,
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )
            manage.aggregate_inbox(runtime, str(inbox_remote), paths)
            history_path = runtime / "metrics" / "history.jsonl"
            first_history = history_path.read_text(encoding="utf-8")

            copier = clone_runtime(root, inbox_remote, "copier")
            branch = f"inbox/v1/{config.machine_id}/2026-08"
            git(copier, "checkout", "--orphan", branch)
            git(copier, "rm", "-rf", "--ignore-unmatch", ".")
            git(copier, "config", "user.name", "Tests")
            git(copier, "config", "user.email", "tests@example.invalid")
            target = copier / "events" / "2026-08" / f"{event['event_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(event), encoding="utf-8")
            git(copier, "add", "events")
            git(copier, "commit", "-m", "copy old event")
            git(copier, "push", "origin", f"HEAD:refs/heads/{branch}")

            result = manage.aggregate_inbox(runtime, str(inbox_remote), paths)

            self.assertEqual(result.accepted, 0)
            self.assertEqual(result.advanced_refs, 1)
            self.assertEqual(history_path.read_text(encoding="utf-8"), first_history)

    def test_rewritten_inbox_branch_is_rejected_without_advancing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote), "main"
            )
            manage.EventStore(paths).write(
                manage.make_heartbeat_event(
                    machine_id=config.machine_id,
                    runtime_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                    now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
                )
            )
            manage.publish_pending(
                config,
                paths,
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )
            manage.aggregate_inbox(runtime, str(inbox_remote), paths)
            branch = f"inbox/v1/{config.machine_id}/2026-07"
            state_path = runtime / "metrics" / "ingestion-state.json"
            checkpoint = json.loads(state_path.read_text(encoding="utf-8"))[
                "checkpoints"
            ][branch]

            attacker = clone_runtime(root, inbox_remote, "rewriter")
            git(attacker, "checkout", "--orphan", "replacement")
            git(attacker, "rm", "-rf", "--ignore-unmatch", ".")
            git(attacker, "config", "user.name", "Tests")
            git(attacker, "config", "user.email", "tests@example.invalid")
            event = manage.make_heartbeat_event(
                machine_id=config.machine_id,
                runtime_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                now=dt.datetime(2026, 7, 10, tzinfo=dt.timezone.utc),
            )
            target = attacker / "events" / "2026-07" / f"{event['event_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(event), encoding="utf-8")
            git(attacker, "add", "events")
            git(attacker, "commit", "-m", "rewrite history")
            git(attacker, "push", "--force", "origin", f"HEAD:refs/heads/{branch}")

            result = manage.aggregate_inbox(runtime, str(inbox_remote), paths)

            self.assertEqual(result.accepted, 0)
            self.assertEqual(result.advanced_refs, 0)
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["checkpoints"][branch],
                checkpoint,
            )
            self.assertIn(
                "branch was rewritten",
                (runtime / "metrics" / "REJECTED.md").read_text(encoding="utf-8"),
            )

    def test_malicious_remote_skill_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            machine_id = str(uuid.uuid4())
            event = manage.make_invocation_event(
                machine_id=machine_id,
                skill_name="demo-skill",
                skill_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                surface_name="cursor",
                surface_version=None,
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )
            event["skill"]["name"] = "../../outside"
            attacker = clone_runtime(root, inbox_remote, "attacker")
            branch = f"inbox/v1/{machine_id}/2026-07"
            git(attacker, "checkout", "--orphan", branch)
            git(attacker, "rm", "-rf", "--ignore-unmatch", ".")
            target = attacker / "events" / "2026-07" / f"{event['event_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(event), encoding="utf-8")
            git(attacker, "config", "user.name", "Tests")
            git(attacker, "config", "user.email", "tests@example.invalid")
            git(attacker, "add", "events")
            git(attacker, "commit", "-m", "malicious event")
            git(attacker, "push", "origin", f"HEAD:refs/heads/{branch}")
            paths = manage.StatePaths(root / "state")

            result = manage.aggregate_inbox(runtime, str(inbox_remote), paths)

            self.assertEqual(result.accepted, 0)
            self.assertEqual(result.rejected, 1)
            self.assertFalse((root / "outside" / "LEARNINGS.md").exists())
            self.assertIn(
                "unsafe skill name",
                (runtime / "metrics" / "REJECTED.md").read_text(encoding="utf-8"),
            )
            self.assertNotIn(
                "outside",
                (runtime / "metrics" / "REJECTED.md").read_text(encoding="utf-8"),
            )

    def test_learning_append_deduplicates_date_and_category_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skills" / "demo-skill"
            skill.mkdir(parents=True)
            learnings = skill / "LEARNINGS.md"
            learnings.write_text("# Learnings\n", encoding="utf-8")
            event = manage.make_learning_event(
                machine_id=str(uuid.uuid4()),
                invocation_id=str(uuid.uuid4()),
                skill_name="demo-skill",
                skill_version="a" * 40,
                surface_name="cursor",
                surface_version=None,
                correction_category="instruction",
                message="Use the safe mode for this operation.",
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )

            self.assertTrue(manage._append_learning(root, event))
            event["recorded_at"] = "2026-07-10T00:00:00Z"
            self.assertFalse(manage._append_learning(root, event))
            self.assertEqual(
                learnings.read_text(encoding="utf-8").count(
                    "Use the safe mode for this operation."
                ),
                1,
            )

    def test_aggregation_is_idempotent_and_rejects_unsafe_skill_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            paths.ensure()
            config = manage.ManagerConfig.new(runtime, str(skills_remote), str(inbox_remote), "main")
            config.save(paths)
            store = manage.EventStore(paths)
            invocation = manage.make_invocation_event(
                machine_id=config.machine_id,
                skill_name="demo-skill",
                skill_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                surface_name="cursor",
                surface_version="3.5.0",
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )
            store.write(invocation)
            store.write(
                manage.make_learning_event(
                    machine_id=config.machine_id,
                    invocation_id=invocation["invocation_id"],
                    skill_name="demo-skill",
                    skill_version=invocation["skill"]["version"],
                    surface_name="cursor",
                    surface_version="3.5.0",
                    correction_category="instruction",
                    message="The command needs --safe in this environment.",
                    now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
                )
            )
            manage.publish_pending(config, paths, now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc))

            first = manage.aggregate_inbox(runtime, str(inbox_remote), paths)
            snapshot = {
                p.relative_to(runtime).as_posix(): p.read_text(encoding="utf-8")
                for p in [
                    runtime / "metrics" / "history.jsonl",
                    runtime / "metrics" / "DASHBOARD.md",
                    runtime / "metrics" / "ingestion-state.json",
                    runtime / "skills" / "demo-skill" / "LEARNINGS.md",
                ]
            }
            second = manage.aggregate_inbox(runtime, str(inbox_remote), paths)

            self.assertEqual(first.accepted, 2)
            self.assertEqual(second.accepted, 0)
            for relative, content in snapshot.items():
                self.assertEqual((runtime / relative).read_text(encoding="utf-8"), content)
            self.assertFalse((root / "outside" / "LEARNINGS.md").exists())


class RemovedAuthoringTests(unittest.TestCase):
    def test_cli_has_no_proposal_or_request_commands(self) -> None:
        parser = manage.build_parser()
        help_text = parser.format_help()
        self.assertNotIn("sweep-proposals", help_text)
        self.assertNotIn("propose", help_text)
        self.assertNotIn("request", help_text)


class OperationalPrimitiveTests(unittest.TestCase):
    def test_nightly_publishes_pending_event_but_no_heartbeat_when_sync_is_unsafe(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote), "main"
            )
            config.save(paths)
            invocation = manage.make_invocation_event(
                machine_id=config.machine_id,
                skill_name="demo-skill",
                skill_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
                surface_name="cursor",
                surface_version=None,
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )
            manage.EventStore(paths).write(invocation)
            (runtime / "dirty.txt").write_text("keep\n", encoding="utf-8")
            args = type("Args", (), {"state_dir": str(paths.root)})()

            with self.assertRaises(manage.ManagerError):
                manage.nightly_command(args)

            sent = [json.loads(path.read_text(encoding="utf-8")) for path in paths.sent.glob("*.json")]
            self.assertEqual([event["event_type"] for event in sent], ["skill_invocation"])
            self.assertEqual((runtime / "dirty.txt").read_text(encoding="utf-8"), "keep\n")

    def test_maintainer_aggregation_requires_clean_review_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            checkout = clone_runtime(root, remote)

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.validate_maintainer_checkout(checkout)

            git(checkout, "switch", "-c", "telemetry/review")
            (checkout / "draft.txt").write_text("draft\n", encoding="utf-8")
            with self.assertRaises(manage.RuntimeSafetyError):
                manage.validate_maintainer_checkout(checkout)

            git(checkout, "config", "user.name", "Tests")
            git(checkout, "config", "user.email", "tests@example.invalid")
            git(checkout, "add", "draft.txt")
            git(checkout, "commit", "-m", "prepare review branch")
            self.assertEqual(
                manage.validate_maintainer_checkout(checkout), checkout.resolve()
            )

    def test_second_process_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "nightly.lock"
            with manage.ProcessLock(lock_path):
                with self.assertRaises(manage.LockBusyError):
                    with manage.ProcessLock(lock_path):
                        self.fail("second lock unexpectedly succeeded")

    def test_authentication_failure_is_detected(self) -> None:
        proc = subprocess.CompletedProcess(
            ["git", "push"],
            1,
            stdout="",
            stderr="fatal: Authentication failed for remote",
        )
        self.assertTrue(manage.is_auth_failure(proc))


if __name__ == "__main__":
    unittest.main()
