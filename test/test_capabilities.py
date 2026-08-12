import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capabilities import CAPABILITIES, invoke, workspace_list
from bob_core.file_manager import safe_path


class CapabilityRegistryTests(unittest.TestCase):
    def test_expected_tools_are_registered(self):
        expected = {
            "system.status",
            "workspace.list",
            "workspace.create",
            "workspace.import",
            "workspace.tree",
            "workspace.list_files",
            "file.read",
            "file.write",
            "file.create",
            "file.delete",
            "file.rename",
            "folder.create",
            "folder.delete",
            "folder.rename",
            "code.validate",
            "code.search",
            "code.run_python",
            "code.stop_python",
            "terminal.execute",
            "test.pytest",
            "assistant.chat",
            "worktree.init",
            "worktree.status",
            "worktree.indexed_changes",
            "worktree.scan",
            "worktree.get_diff",
            "worktree.stage_change",
            "worktree.unstage_change",
            "worktree.stage_all",
            "worktree.unstage_all",
            "worktree.stage_many",
            "worktree.unstage_many",
            "worktree.apply_change",
            "worktree.apply_many",
            "worktree.apply_passing",
            "worktree.override_and_apply",
            "worktree.apply_all",
            "worktree.discard_change",
            "worktree.discard_many",
            "worktree.discard_all",
            "worktree.create_snapshot",
            "worktree.history",
            "worktree.file_history",
            "worktree.file_status",
            "worktree.get_hunks",
            "worktree.stage_hunk",
            "worktree.discard_hunk",
            "worktree.apply_hunk",
            "worktree.apply_all_hunks",
            "worktree.generate_checkpoint_message",
            "worktree.restore_file",
            "worktree.compare_with_snapshot",
            "worktree.restore_snapshot",
            "worktree.ignore_path",
            "worktree.timeline",
            "model.get_config",
            "model.set_config",
            "model.health",
            "model.plan",
            "model.code_direct",
            "model.queue_status",
            "model.run_agent",
            "model.run_status",
        }
        self.assertTrue(expected.issubset(CAPABILITIES))
        self.assertTrue({
            "git.init",
            "git.status",
            "git.diff",
            "git.stage",
            "git.unstage",
            "git.commit",
            "proposal.list",
            "proposal.diff",
            "proposal.apply",
            "proposal.discard",
        }.issubset(CAPABILITIES))

    def test_unknown_capability_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown capability"):
            invoke("missing.tool")

    def test_validation_returns_structured_problems(self):
        result = invoke(
            "code.validate",
            {"path": "broken.py", "content": "def broken(:\n"},
        )
        self.assertEqual("error", result["problems"][0]["severity"])

    def test_project_cannot_escape_workspace_root(self):
        with self.assertRaisesRegex(ValueError, "Invalid workspace"):
            safe_path("..")

    def test_scoped_workspace_list_ignores_internal_directories(self):
        scope = "worker--00000000-0000-0000-0000-000000000001"
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace_root = Path(temporary_directory)
            user_root = workspace_root / scope
            (user_root / ".bob" / "runtime").mkdir(parents=True)
            (user_root / "valid_project").mkdir()
            (user_root / "invalid.project").mkdir()

            with patch("capabilities.WORKSPACE_DIR", workspace_root):
                self.assertEqual(
                    {"projects": ["valid_project"]},
                    workspace_list(scope),
                )


if __name__ == "__main__":
    unittest.main()
