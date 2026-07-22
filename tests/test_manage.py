from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
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


def write_skill(root: Path, name: str) -> None:
    skill = root / "skills" / name
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "Test skill."\n---\n\n# Test\n',
        encoding="utf-8",
    )
    (skill / "LEARNINGS.md").write_text("# Learnings\n", encoding="utf-8")


def write_sets(root: Path, sets_toml: str, skills: tuple[str, ...] = ()) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sets.toml").write_text(sets_toml, encoding="utf-8")
    for name in skills:
        write_skill(root, name)
    return root


class SetResolutionTests(unittest.TestCase):
    def test_child_set_resolves_to_union_root_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_sets(
                Path(tmp),
                '[global]\nskills = ["base-a", "base-b"]\n'
                '[team]\ninherits = "global"\nskills = ["team-a"]\n',
                ("base-a", "base-b", "team-a"),
            )

            sets = manage.load_sets(root)
            chain, skills = manage.resolve_set(sets, "team")

            self.assertEqual(chain, ["global", "team"])
            self.assertEqual(skills, ["base-a", "base-b", "team-a"])
            self.assertEqual(manage.validate_sets(root), [])

    def test_root_set_resolves_to_its_own_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_sets(
                Path(tmp),
                '[global]\nskills = ["base-a"]\n',
                ("base-a",),
            )

            chain, skills = manage.resolve_set(manage.load_sets(root), "global")

            self.assertEqual(chain, ["global"])
            self.assertEqual(skills, ["base-a"])

    def test_unknown_set_and_unknown_parent_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_sets(Path(tmp), '[global]\nskills = []\n')
            sets = manage.load_sets(root)

            with self.assertRaises(manage.ManagerError):
                manage.resolve_set(sets, "nonexistent")

            write_sets(
                Path(tmp),
                '[global]\nskills = []\n[team]\ninherits = "missing"\nskills = []\n',
            )
            with self.assertRaises(manage.ManagerError):
                manage.load_sets(root)

    def test_inheritance_cycle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_sets(
                Path(tmp),
                '[global]\nskills = []\n'
                '[a]\ninherits = "b"\nskills = []\n'
                '[b]\ninherits = "a"\nskills = []\n',
            )

            errors = manage.validate_sets(root)

            self.assertTrue(any("cycle" in error for error in errors))

    def test_exactly_one_root_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_sets(
                Path(tmp),
                '[global]\nskills = []\n[second-root]\nskills = []\n',
            )

            with self.assertRaises(manage.ManagerError):
                manage.load_sets(root)

    def test_orphan_missing_and_double_listed_skills_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = write_sets(
                Path(tmp),
                '[global]\nskills = ["listed-twice", "missing-dir"]\n'
                '[team]\ninherits = "global"\nskills = ["listed-twice"]\n',
                ("listed-twice", "orphan-skill"),
            )

            errors = "\n".join(manage.validate_sets(root))

            self.assertIn("multiple sets", errors)
            self.assertIn("missing skill: missing-dir", errors)
            self.assertIn("'orphan-skill' is not listed in any set", errors)

    def test_repo_sets_manifest_is_valid(self) -> None:
        self.assertEqual(manage.validate_sets(manage.REPO_ROOT), [])


class ConfigTests(unittest.TestCase):
    def test_config_round_trips_through_state_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(runtime, str(remote), root / "view")

            config.save(paths)
            loaded = manage.ManagerConfig.load(paths)

            self.assertEqual(loaded, config)

    def test_outdated_v1_config_is_rejected_with_reconfigure_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = manage.StatePaths(Path(tmp))
            paths.ensure()
            paths.config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runtime_path": "/somewhere/.agents",
                        "runtime_repo_url": "https://example.invalid/skills",
                        "inbox_repo_url": "https://example.invalid/inbox",
                        "branch": "main",
                        "machine_id": "00000000-0000-4000-8000-000000000000",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(manage.ManagerError) as caught:
                manage.ManagerConfig.load(paths)

            self.assertIn("configure", str(caught.exception))

    def test_unsafe_branch_is_rejected(self) -> None:
        config = manage.ManagerConfig(
            runtime_path="/somewhere/repo",
            runtime_repo_url="https://example.invalid/skills",
            branch="../evil",
            view_path="/somewhere/view",
            skill_set="global",
        )

        with self.assertRaises(manage.ManagerError):
            config.validate()

    def test_overlapping_view_and_runtime_paths_are_rejected(self) -> None:
        for view in ("/somewhere/repo", "/somewhere/repo/view", "/somewhere"):
            with self.subTest(view=view):
                config = manage.ManagerConfig(
                    runtime_path="/somewhere/repo",
                    runtime_repo_url="https://example.invalid/skills",
                    branch="main",
                    view_path=view,
                    skill_set="global",
                )

                with self.assertRaises(manage.ManagerError):
                    config.validate()


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
            config = manage.ManagerConfig.new(runtime, str(remote), root / "view")

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
            config = manage.ManagerConfig.new(runtime, str(remote), root / "view")

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
            config = manage.ManagerConfig.new(runtime, str(remote), root / "view")

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.sync_runtime(config)

            self.assertEqual(marker.read_text(), "local edit\n")

    def test_local_commits_are_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            git(runtime, "config", "user.name", "Tests")
            git(runtime, "config", "user.email", "tests@example.invalid")
            (runtime / "local.txt").write_text("local\n", encoding="utf-8")
            git(runtime, "add", "local.txt")
            git(runtime, "commit", "-m", "local work")
            head_before = git(runtime, "rev-parse", "HEAD").stdout.strip()
            config = manage.ManagerConfig.new(runtime, str(remote), root / "view")

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.sync_runtime(config)

            self.assertEqual(
                git(runtime, "rev-parse", "HEAD").stdout.strip(), head_before
            )


TEAM_SETS = (
    '[global]\nskills = ["base-a"]\n'
    '[team]\ninherits = "global"\nskills = ["team-a"]\n'
)


def publish(root: Path, remote: Path, label: str, sets_toml: str,
            skills: tuple[str, ...]) -> None:
    work = root / label
    git(root, "clone", str(remote), str(work))
    git(work, "config", "user.name", "Tests")
    git(work, "config", "user.email", "tests@example.invalid")
    write_sets(work, sets_toml, skills)
    git(work, "add", "-A")
    git(work, "commit", "-m", f"publish {label}")
    git(work, "push", "origin", "main")


class MaterializeTests(unittest.TestCase):
    def test_child_subscription_materializes_inherited_union(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            publish(root, remote, "seed", TEAM_SETS, ("base-a", "team-a"))
            runtime = clone_runtime(root, remote)
            view = root / "view"
            config = manage.ManagerConfig.new(
                runtime, str(remote), view, skill_set="team"
            )

            manage.materialize_view(config)

            self.assertTrue((view / "skills" / "base-a" / "SKILL.md").is_file())
            self.assertTrue((view / "skills" / "team-a" / "SKILL.md").is_file())
            self.assertTrue((view / manage.VIEW_MARKER).is_file())
            installed = json.loads(
                (view / "installed.json").read_text(encoding="utf-8")
            )
            self.assertEqual(installed["set"], "team")
            self.assertEqual(installed["chain"], ["global", "team"])
            self.assertEqual(installed["skills"], ["base-a", "team-a"])
            self.assertEqual(
                installed["source_sha"],
                git(runtime, "rev-parse", "HEAD").stdout.strip(),
            )

    def test_sync_rebuilds_view_after_remote_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            publish(root, remote, "seed", TEAM_SETS, ("base-a", "team-a"))
            runtime = clone_runtime(root, remote)
            view = root / "view"
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(
                runtime, str(remote), view, skill_set="team"
            )
            config.save(paths)
            args = type("Args", (), {"state_dir": str(paths.root)})()

            manage.sync_command(args)
            self.assertFalse((view / "skills" / "base-b").exists())

            updated = TEAM_SETS.replace('["base-a"]', '["base-a", "base-b"]')
            publish(root, remote, "update", updated, ("base-b",))
            manage.sync_command(args)

            self.assertTrue((view / "skills" / "base-b" / "SKILL.md").is_file())
            installed = json.loads(
                (view / "installed.json").read_text(encoding="utf-8")
            )
            self.assertEqual(installed["skills"], ["base-a", "base-b", "team-a"])

    def test_unmanaged_view_directory_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            publish(root, remote, "seed", TEAM_SETS, ("base-a", "team-a"))
            runtime = clone_runtime(root, remote)
            view = root / "view"
            view.mkdir()
            precious = view / "notes.txt"
            precious.write_text("mine\n", encoding="utf-8")
            config = manage.ManagerConfig.new(
                runtime, str(remote), view, skill_set="team"
            )

            with self.assertRaises(manage.RuntimeSafetyError):
                manage.materialize_view(config)

            self.assertEqual(precious.read_text(), "mine\n")

    def test_broken_manifest_preserves_previous_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            publish(root, remote, "seed", TEAM_SETS, ("base-a", "team-a"))
            runtime = clone_runtime(root, remote)
            view = root / "view"
            config = manage.ManagerConfig.new(
                runtime, str(remote), view, skill_set="team"
            )
            manage.materialize_view(config)
            snapshot = json.loads(
                (view / "installed.json").read_text(encoding="utf-8")
            )

            publish(root, remote, "break", "not valid toml [", ())
            manage.sync_runtime(config)
            with self.assertRaises(manage.ManagerError):
                manage.materialize_view(config)

            self.assertTrue((view / "skills" / "base-a" / "SKILL.md").is_file())
            self.assertEqual(
                json.loads((view / "installed.json").read_text(encoding="utf-8")),
                snapshot,
            )


class OperationalTests(unittest.TestCase):
    def test_sync_fails_on_dirty_runtime_without_discarding_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = init_bare_remote(root, "skills")
            runtime = clone_runtime(root, remote)
            paths = manage.StatePaths(root / "state")
            config = manage.ManagerConfig.new(runtime, str(remote), root / "view")
            config.save(paths)
            (runtime / "dirty.txt").write_text("keep\n", encoding="utf-8")
            args = type("Args", (), {"state_dir": str(paths.root)})()

            with self.assertRaises(manage.ManagerError):
                manage.sync_command(args)

            self.assertEqual((runtime / "dirty.txt").read_text(), "keep\n")

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
