import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from capabilities import invoke
from config import MAX_FILE_SIZE, WORKSPACE_DIR


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

        snapshot = invoke("worktree.create_snapshot", {"project": self.project, "label": "v2", "message": "Update app.py"})
        self.assertEqual("v2", snapshot["label"])
        self.assertEqual("Update app.py", snapshot["message"])
        self.assertEqual("manual_checkpoint", snapshot["type"])
        self.assertEqual([change_id], snapshot["staged_changes"])
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual("clean", status["state"])
        self.assertEqual("main", status["active_worktree"])

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

    def test_apply_passing_and_batch_errors(self):
        from bob_core.json_worktree import create_run, record_model_proposal

        run = create_run(self.project, "two proposals", "agent")
        good = record_model_proposal(
            self.project,
            run["run_id"],
            {"good.py": "print('good')\n"},
            "PASS",
        )[0]
        bad = record_model_proposal(
            self.project,
            run["run_id"],
            {"bad.py": "print('bad')\n"},
            "FAIL",
        )[0]

        hunks = invoke("worktree.get_hunks", {"project": self.project, "change_id": good["change_id"]})
        self.assertGreaterEqual(len(hunks["hunks"]), 1)

        result = invoke("worktree.apply_passing", {"project": self.project})
        self.assertEqual([good["change_id"]], [item["change_id"] for item in result["applied"]])
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual(1, len([item for item in status["proposed"] if item["change_id"] == bad["change_id"]]))

        batch = invoke(
            "worktree.stage_many",
            {"project": self.project, "change_ids": [good["change_id"], "missing"]},
        )
        self.assertEqual([good["change_id"]], [item["change_id"] for item in batch["staged"]])
        self.assertEqual("missing", batch["errors"][0]["change_id"])

    def test_hunk_stage_discard_and_apply(self):
        original = "\n".join([f"line {index}" for index in range(1, 120)]) + "\n"
        changed = original.replace("line 2\n", "line 2 changed\n").replace("line 110\n", "line 110 changed\n")
        invoke("file.write", {"project": self.project, "path": "app.py", "content": original})
        invoke("worktree.stage_all", {"project": self.project})
        invoke("worktree.create_snapshot", {"project": self.project, "label": "base"})
        invoke("file.write", {"project": self.project, "path": "app.py", "content": changed})
        status = invoke("worktree.status", {"project": self.project})
        change = status["changes"][0]
        self.assertGreaterEqual(len(change["hunks"]), 2)

        first_hunk = change["hunks"][0]["hunk_id"]
        invoke("worktree.stage_hunk", {"project": self.project, "change_id": change["change_id"], "hunk_id": first_hunk})
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual("staged", status["changes"][0]["hunks"][0]["status"])

        second_hunk = status["changes"][0]["hunks"][1]["hunk_id"]
        invoke("worktree.discard_hunk", {"project": self.project, "change_id": change["change_id"], "hunk_id": second_hunk})
        content = (self.root / "app.py").read_text(encoding="utf-8")
        self.assertIn("line 2 changed", content)
        self.assertIn("line 110\n", content)

        from bob_core.json_worktree import create_run, record_model_proposal

        run = create_run(self.project, "proposal hunks", "agent")
        proposal_content = original.replace("line 3\n", "line 3 bob\n").replace("line 111\n", "line 111 bob\n")
        proposal = record_model_proposal(self.project, run["run_id"], {"app.py": proposal_content}, "PASS")[0]
        invoke("worktree.apply_hunk", {
            "project": self.project,
            "change_id": proposal["change_id"],
            "hunk_id": proposal["hunks"][0]["hunk_id"],
        })
        content = (self.root / "app.py").read_text(encoding="utf-8")
        self.assertIn("line 3 bob", content)
        self.assertIn("line 111\n", content)

    def test_ignore_restore_compare_timeline_and_large_file(self):
        ignored = self.root / "ignored.py"
        ignored.write_text("print('ignore')\n", encoding="utf-8")
        invoke("worktree.ignore_path", {"project": self.project, "path": "ignored.py"})
        status = invoke("worktree.status", {"project": self.project})
        self.assertFalse(any(item["path"] == "ignored.py" for item in status["changes"]))

        invoke("file.write", {"project": self.project, "path": "app.py", "content": "print('changed')\n"})
        diff = invoke("worktree.compare_with_snapshot", {"project": self.project, "path": "app.py"})
        self.assertIn("changed", diff["diff"])
        invoke("worktree.restore_file", {"project": self.project, "path": "app.py"})
        self.assertEqual("print('v1')\n", (self.root / "app.py").read_text(encoding="utf-8"))

        invoke("file.write", {"project": self.project, "path": "app.py", "content": "print('snapshot restore')\n"})
        invoke("worktree.restore_snapshot", {"project": self.project, "snapshot_id": "snapshot_000001"})
        self.assertEqual("print('v1')\n", (self.root / "app.py").read_text(encoding="utf-8"))

        large = self.root / "large.txt"
        large.write_text("x" * (MAX_FILE_SIZE + 1), encoding="utf-8")
        status = invoke("worktree.status", {"project": self.project})
        large_change = next(item for item in status["changes"] if item["path"] == "large.txt")
        self.assertTrue(large_change["large_file"])
        self.assertNotIn("after_blob", large_change)
        large_diff = invoke("worktree.get_diff", {"project": self.project, "change_id": large_change["change_id"]})
        self.assertEqual("Large file changed", large_diff["diff"])

        timeline = invoke("worktree.timeline", {"project": self.project})
        self.assertTrue(timeline["events"])


if __name__ == "__main__":
    unittest.main()
