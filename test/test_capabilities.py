import unittest

from capabilities import CAPABILITIES, invoke
from bob_core.file_manager import safe_path


class CapabilityRegistryTests(unittest.TestCase):
    def test_expected_tools_are_registered(self):
        expected = {
            "system.status",
            "workspace.list",
            "workspace.create",
            "workspace.import",
            "workspace.tree",
            "file.read",
            "file.write",
            "file.create",
            "file.delete",
            "file.rename",
            "folder.create",
            "code.validate",
            "code.search",
            "code.run_python",
            "terminal.execute",
            "test.pytest",
            "assistant.chat",
            "worktree.init",
            "worktree.status",
            "worktree.get_diff",
            "worktree.stage_change",
            "worktree.unstage_change",
            "worktree.stage_all",
            "worktree.unstage_all",
            "worktree.apply_change",
            "worktree.override_and_apply",
            "worktree.apply_all",
            "worktree.discard_change",
            "worktree.discard_all",
            "worktree.create_snapshot",
            "worktree.history",
            "worktree.file_history",
            "model.plan",
            "model.run_agent",
            "model.run_status",
        }
        self.assertEqual(expected, set(CAPABILITIES))

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


if __name__ == "__main__":
    unittest.main()
