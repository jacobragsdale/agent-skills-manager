from __future__ import annotations

import datetime as dt
import json
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


def learning(
    config: manage.ManagerConfig,
    runtime: Path,
    message: str = "Use the safe mode for this operation.",
) -> dict:
    return manage.make_learning_event(
        machine_id=config.machine_id,
        skill_name="demo-skill",
        skill_version=git(runtime, "rev-parse", "HEAD").stdout.strip(),
        correction_category="instruction",
        message=message,
        now=dt.datetime(2026, 7, 9, 12, 30, tzinfo=dt.timezone.utc),
    )


class LearningSchemaTests(unittest.TestCase):
    def test_learning_has_only_feedback_fields(self) -> None:
        event = manage.make_learning_event(
            machine_id=str(uuid.uuid4()),
            skill_name="demo-skill",
            skill_version="a" * 40,
            correction_category="instruction",
            message="Prefer the documented flag.",
            now=dt.datetime(2026, 7, 9, 12, 30, tzinfo=dt.timezone.utc),
        )

        manage.validate_learning(event)

        self.assertEqual(
            set(event),
            {
                "schema_version",
                "event_id",
                "recorded_at",
                "machine_id",
                "skill",
                "category",
                "message",
            },
        )

    def test_path_traversal_skill_is_rejected(self) -> None:
        event = manage.make_learning_event(
            machine_id=str(uuid.uuid4()),
            skill_name="../../outside",
            skill_version="a" * 40,
            correction_category="instruction",
            message="Prefer the documented flag.",
            now=dt.datetime.now(dt.timezone.utc),
        )

        with self.assertRaises(manage.FeedbackValidationError):
            manage.validate_learning(event)

    def test_learning_message_must_be_one_line(self) -> None:
        event = manage.make_learning_event(
            machine_id=str(uuid.uuid4()),
            skill_name="demo-skill",
            skill_version="a" * 40,
            correction_category="instruction",
            message="First line\n# injected heading",
            now=dt.datetime.now(dt.timezone.utc),
        )

        with self.assertRaises(manage.FeedbackValidationError):
            manage.validate_learning(event)

    def test_wrong_json_type_for_any_field_is_a_validation_error(self) -> None:
        base_event = manage.make_learning_event(
            machine_id=str(uuid.uuid4()),
            skill_name="demo-skill",
            skill_version="a" * 40,
            correction_category="instruction",
            message="Prefer the documented flag.",
            now=dt.datetime.now(dt.timezone.utc),
        )
        wrong_values = {
            "schema_version": [],
            "event_id": [],
            "recorded_at": [],
            "machine_id": [],
            "skill": [],
            "category": [],
            "message": [],
        }

        for field, wrong_value in wrong_values.items():
            with self.subTest(field=field):
                event = dict(base_event)
                event[field] = wrong_value

                with self.assertRaises(manage.FeedbackValidationError):
                    manage.validate_learning(event)

    def test_category_rejects_every_non_string_json_type(self) -> None:
        base_event = manage.make_learning_event(
            machine_id=str(uuid.uuid4()),
            skill_name="demo-skill",
            skill_version="a" * 40,
            correction_category="instruction",
            message="Prefer the documented flag.",
            now=dt.datetime.now(dt.timezone.utc),
        )

        for value in (None, False, 1, 1.5, [], {}):
            with self.subTest(value=value):
                event = dict(base_event)
                event["category"] = value

                with self.assertRaises(manage.FeedbackValidationError):
                    manage.validate_learning(event)


class FeedbackStoreTests(unittest.TestCase):
    def test_invalid_file_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = manage.StatePaths(Path(tmp))
            paths.ensure()
            bad = paths.pending / "bad.json"
            bad.write_text('{"schema_version": 1}', encoding="utf-8")

            events = manage.FeedbackStore(paths).load_pending()

            self.assertEqual(events, [])
            self.assertFalse(bad.exists())
            self.assertTrue((paths.quarantine / "bad.json").is_file())
            self.assertTrue((paths.quarantine / "bad.reason.txt").is_file())

    def test_learning_is_written_atomically_and_deleted_after_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = manage.StatePaths(Path(tmp))
            event = manage.make_learning_event(
                machine_id=str(uuid.uuid4()),
                skill_name="demo-skill",
                skill_version="b" * 40,
                correction_category="instruction",
                message="Prefer the documented flag.",
                now=dt.datetime.now(dt.timezone.utc),
            )
            store = manage.FeedbackStore(paths)

            path = store.write(event)
            store.mark_published(path)

            self.assertFalse(path.exists())
            self.assertEqual(list(paths.pending.glob("*.tmp")), [])

    def test_malformed_event_is_quarantined_without_blocking_valid_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = manage.StatePaths(Path(tmp))
            machine_id = str(uuid.uuid4())
            valid = manage.make_learning_event(
                machine_id=machine_id,
                skill_name="demo-skill",
                skill_version="b" * 40,
                correction_category="instruction",
                message="Prefer the documented flag.",
                now=dt.datetime.now(dt.timezone.utc),
            )
            malformed = dict(valid)
            malformed["event_id"] = str(uuid.uuid4())
            malformed["category"] = []
            paths.ensure()
            malformed_path = paths.pending / f"{malformed['event_id']}.json"
            malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
            manage.FeedbackStore(paths).write(valid)

            events = manage.FeedbackStore(paths).load_pending()

            self.assertEqual([event for _, event in events], [valid])
            self.assertFalse(malformed_path.exists())
            self.assertTrue((paths.quarantine / malformed_path.name).is_file())
            reason_path = paths.quarantine / f"{malformed['event_id']}.reason.txt"
            reason = reason_path.read_text(encoding="utf-8")
            self.assertNotIn("[]", reason)


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
                runtime,
                str(remote),
                str(init_bare_remote(root, "inbox")),
            )

            manage.sync_runtime(config)

            self.assertEqual((runtime / "new.txt").read_text(), "new\n")
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
                runtime,
                str(remote),
                str(init_bare_remote(root, "inbox")),
            )

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.sync_runtime(config)

            self.assertEqual(
                git(runtime, "branch", "--show-current").stdout.strip(),
                "work-in-progress",
            )
            self.assertEqual(marker.read_text(), "keep me")

    def test_dirty_runtime_is_not_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            marker = runtime / "README.md"
            marker.write_text("local edit\n", encoding="utf-8")
            config = manage.ManagerConfig.new(
                runtime,
                str(remote),
                str(init_bare_remote(root, "inbox")),
            )

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.sync_runtime(config)

            self.assertEqual(marker.read_text(), "local edit\n")


class FeedbackTransportTests(unittest.TestCase):
    def test_two_clients_publish_to_different_refs(self) -> None:
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
                config = manage.ManagerConfig.new(
                    runtime, str(skills_remote), str(inbox_remote)
                )
                manage.FeedbackStore(paths).write(learning(config, runtime))
                jobs.append((config, paths))

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda job: manage.publish_pending(job[0], job[1]),
                        jobs,
                    )
                )

            self.assertEqual(results, [1, 1])
            refs = git(
                inbox_remote,
                "for-each-ref",
                "--format=%(refname)",
                "refs/heads/feedback/v1/",
            ).stdout.splitlines()
            self.assertEqual(len(refs), 2)

    def test_publish_preserves_inbox_main_and_clears_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote)
            )
            manage.FeedbackStore(paths).write(learning(config, runtime))
            main_before = git(
                inbox_remote, "rev-parse", "refs/heads/main"
            ).stdout.strip()

            published = manage.publish_pending(config, paths)

            branch = f"refs/heads/feedback/v1/{config.machine_id}"
            self.assertEqual(published, 1)
            self.assertEqual(
                git(inbox_remote, "rev-parse", "refs/heads/main").stdout.strip(),
                main_before,
            )
            self.assertTrue(git(inbox_remote, "rev-parse", branch).stdout.strip())
            self.assertEqual(list(paths.pending.glob("*.json")), [])

    def test_failed_push_keeps_pending_learning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote)
            )
            manage.FeedbackStore(paths).write(learning(config, runtime))
            inbox_remote.rename(root / "inbox-missing.git")

            with self.assertRaises(manage.ManagerError):
                manage.publish_pending(config, paths)

            self.assertEqual(len(list(paths.pending.glob("*.json"))), 1)


class FeedbackAggregationTests(unittest.TestCase):
    def test_aggregation_appends_once_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote)
            )
            manage.FeedbackStore(paths).write(learning(config, runtime))
            manage.publish_pending(config, paths)

            first = manage.aggregate_feedback(runtime, str(inbox_remote), paths)
            learnings = runtime / "skills" / "demo-skill" / "LEARNINGS.md"
            snapshot = learnings.read_text()
            state = (runtime / "feedback" / "ingestion-state.json").read_text()
            second = manage.aggregate_feedback(runtime, str(inbox_remote), paths)

            self.assertEqual(first.accepted, 1)
            self.assertEqual(second.accepted, 0)
            self.assertEqual(learnings.read_text(), snapshot)
            self.assertEqual(
                (runtime / "feedback" / "ingestion-state.json").read_text(),
                state,
            )

    def test_processed_event_is_not_reapplied_after_branch_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote)
            )
            event = learning(config, runtime)
            manage.FeedbackStore(paths).write(event)
            manage.publish_pending(config, paths)
            manage.aggregate_feedback(runtime, str(inbox_remote), paths)
            branch = manage.feedback_branch(config.machine_id)
            learnings = runtime / "skills" / "demo-skill" / "LEARNINGS.md"
            snapshot = learnings.read_text()

            attacker = clone_runtime(root, inbox_remote, "rewriter")
            git(attacker, "checkout", "--orphan", "replacement")
            git(attacker, "rm", "-rf", "--ignore-unmatch", ".")
            git(attacker, "config", "user.name", "Tests")
            git(attacker, "config", "user.email", "tests@example.invalid")
            event["message"] = "Changed text under an already processed event ID."
            target = attacker / "learnings" / f"{event['event_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(event), encoding="utf-8")
            git(attacker, "add", "learnings")
            git(attacker, "commit", "-m", "rewrite history")
            git(attacker, "push", "--force", "origin", f"HEAD:refs/heads/{branch}")

            result = manage.aggregate_feedback(runtime, str(inbox_remote), paths)

            self.assertEqual(result.accepted, 0)
            self.assertEqual(result.scanned_refs, 1)
            self.assertEqual(learnings.read_text(), snapshot)

    def test_malicious_skill_name_is_rejected_without_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            machine_id = str(uuid.uuid4())
            config = manage.ManagerConfig.new(
                runtime,
                str(skills_remote),
                str(inbox_remote),
                machine_id=machine_id,
            )
            paths = manage.StatePaths(root / "state")
            event = learning(config, runtime)
            event["skill"]["name"] = "../../outside"
            attacker = clone_runtime(root, inbox_remote, "attacker")
            branch = manage.feedback_branch(machine_id)
            git(attacker, "checkout", "--orphan", branch)
            git(attacker, "rm", "-rf", "--ignore-unmatch", ".")
            target = attacker / "learnings" / f"{event['event_id']}.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(event), encoding="utf-8")
            git(attacker, "config", "user.name", "Tests")
            git(attacker, "config", "user.email", "tests@example.invalid")
            git(attacker, "add", "learnings")
            git(attacker, "commit", "-m", "malicious feedback")
            git(attacker, "push", "origin", f"HEAD:refs/heads/{branch}")

            result = manage.aggregate_feedback(runtime, str(inbox_remote), paths)

            self.assertEqual(result.accepted, 0)
            self.assertFalse((root / "outside" / "LEARNINGS.md").exists())
            rejection = (runtime / "feedback" / "REJECTED.md").read_text()
            self.assertIn("unsafe skill name", rejection)
            self.assertNotIn("outside", rejection)

    def test_learning_append_deduplicates_date_and_category_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skills" / "demo-skill"
            skill.mkdir(parents=True)
            target = skill / "LEARNINGS.md"
            target.write_text("# Learnings\n", encoding="utf-8")
            event = manage.make_learning_event(
                machine_id=str(uuid.uuid4()),
                skill_name="demo-skill",
                skill_version="a" * 40,
                correction_category="instruction",
                message="Use the safe mode for this operation.",
                now=dt.datetime(2026, 7, 9, tzinfo=dt.timezone.utc),
            )

            self.assertTrue(manage._append_learning(root, event))
            event["recorded_at"] = "2026-07-10T00:00:00Z"
            self.assertFalse(manage._append_learning(root, event))
            self.assertEqual(
                target.read_text().count("Use the safe mode for this operation."),
                1,
            )

    def test_malformed_event_does_not_block_valid_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            machine_id = str(uuid.uuid4())
            config = manage.ManagerConfig.new(
                runtime,
                str(skills_remote),
                str(inbox_remote),
                machine_id=machine_id,
            )
            paths = manage.StatePaths(root / "state")
            valid = learning(config, runtime)
            malformed = dict(valid)
            malformed["event_id"] = "00000000-0000-4000-8000-000000000000"
            malformed["category"] = []
            attacker = clone_runtime(root, inbox_remote, "malformed-feedback")
            branch = manage.feedback_branch(machine_id)
            git(attacker, "checkout", "--orphan", branch)
            git(attacker, "rm", "-rf", "--ignore-unmatch", ".")
            learning_dir = attacker / "learnings"
            learning_dir.mkdir(parents=True)
            (learning_dir / f"{malformed['event_id']}.json").write_text(
                json.dumps(malformed), encoding="utf-8"
            )
            (learning_dir / f"{valid['event_id']}.json").write_text(
                json.dumps(valid), encoding="utf-8"
            )
            git(attacker, "config", "user.name", "Tests")
            git(attacker, "config", "user.email", "tests@example.invalid")
            git(attacker, "add", "learnings")
            git(attacker, "commit", "-m", "add mixed feedback")
            git(attacker, "push", "origin", f"HEAD:refs/heads/{branch}")

            result = manage.aggregate_feedback(runtime, str(inbox_remote), paths)

            self.assertEqual(result.accepted, 1)
            self.assertEqual(result.rejected, 1)
            learnings = runtime / "skills" / "demo-skill" / "LEARNINGS.md"
            self.assertIn(valid["message"], learnings.read_text(encoding="utf-8"))
            rejection = (runtime / "feedback" / "REJECTED.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("invalid correction category", rejection)
            self.assertNotIn("[]", rejection)


class OperationalTests(unittest.TestCase):
    def test_nightly_publishes_feedback_even_when_sync_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills_remote = init_bare_remote(root, "skills")
            inbox_remote = init_bare_remote(root, "inbox")
            runtime = clone_runtime(root, skills_remote)
            seed_skill(runtime)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(skills_remote), str(inbox_remote)
            )
            config.save(paths)
            manage.FeedbackStore(paths).write(learning(config, runtime))
            (runtime / "dirty.txt").write_text("keep\n", encoding="utf-8")
            args = type("Args", (), {"state_dir": str(paths.root)})()

            with self.assertRaises(manage.ManagerError):
                manage.nightly_command(args)

            self.assertEqual(list(paths.pending.glob("*.json")), [])
            self.assertEqual((runtime / "dirty.txt").read_text(), "keep\n")

    def test_aggregation_requires_clean_review_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            checkout = clone_runtime(root, remote)

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.validate_maintainer_checkout(checkout)

            git(checkout, "switch", "-c", "feedback/review")
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
