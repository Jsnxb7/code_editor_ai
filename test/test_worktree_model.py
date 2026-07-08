import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from capabilities import invoke
from config import WORKSPACE_DIR


class WorktreeModelTests(unittest.TestCase):
    def setUp(self):
        self.project = f"test_worktree_{uuid4().hex[:8]}"
        self.root = WORKSPACE_DIR / self.project
        self.root.mkdir(parents=True)
        (self.root / "app.py").write_text("print('v1')\n", encoding="utf-8")
        invoke("worktree.init", {"project": self.project})

    def tearDown(self):
        if self.root.exists() and self.root.parent == WORKSPACE_DIR:
            shutil.rmtree(self.root)

    def test_manual_change_stage_and_checkpoint(self):
        result = invoke(
            "file.write",
            {"project": self.project, "path": "app.py", "content": "print('v2')\n"},
        )
        self.assertEqual("unstaged", result["change"]["status"])

        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual(1, status["summary"]["changes"])

        change_id = status["changes"][0]["change_id"]
        invoke("worktree.stage_change", {"project": self.project, "change_id": change_id})
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual(1, status["summary"]["staged"])

        snapshot = invoke("worktree.create_snapshot", {"project": self.project, "label": "v2"})
        self.assertEqual("v2", snapshot["label"])
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual("clean", status["state"])

    def test_failed_model_proposal_requires_override(self):
        from bob_core.json_worktree import create_run, record_model_proposal

        run = create_run(self.project, "stub proposal", "agent")
        proposal = record_model_proposal(
            self.project,
            run["run_id"],
            {"app.py": "print('from bob')\n"},
            "FAIL",
        )[0]
        with self.assertRaisesRegex(ValueError, "override"):
            invoke(
                "worktree.apply_change",
                {"project": self.project, "change_id": proposal["change_id"]},
            )

        invoke(
            "worktree.override_and_apply",
            {"project": self.project, "change_id": proposal["change_id"]},
        )
        self.assertEqual("print('from bob')\n", (self.root / "app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
