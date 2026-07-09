import os
import shutil
import stat
import unittest
from uuid import uuid4

from capabilities import invoke
from config import WORKSPACE_DIR
from bob_core.proposal_store import create_proposal


def remove_readonly(func, path, _error):
    os.chmod(path, stat.S_IWRITE)
    func(path)


class WorktreeCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.project = f"test_worktree_{uuid4().hex[:8]}"
        self.root = WORKSPACE_DIR / self.project
        self.root.mkdir(parents=True)
        invoke("worktree.init", {"project": self.project})
        invoke("git.set_identity", {
            "project": self.project,
            "name": "Bob Test",
            "email": "bob-test@localhost",
        })
        (self.root / "app.py").write_text("print('v1')\n", encoding="utf-8")
        invoke("git.stage_all", {"project": self.project})
        invoke("git.commit", {"project": self.project, "message": "Baseline"})

    def tearDown(self):
        shutil.rmtree(self.root, onerror=remove_readonly)

    def test_worktree_aliases_use_git(self):
        invoke("file.write", {
            "project": self.project,
            "path": "app.py",
            "content": "print('v2')\n",
        })
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual(1, status["summary"]["changes"])
        change = status["changes"][0]
        self.assertTrue(change["change_id"].startswith("git:"))

        diff = invoke("worktree.get_diff", {
            "project": self.project,
            "change_id": change["change_id"],
        })
        self.assertIn("v1", diff["before_content"])
        self.assertIn("v2", diff["after_content"])

        invoke("worktree.stage_change", {
            "project": self.project,
            "change_id": change["change_id"],
        })
        status = invoke("worktree.status", {"project": self.project})
        self.assertEqual(1, status["summary"]["staged"])
        invoke("worktree.create_snapshot", {
            "project": self.project,
            "message": "Update app",
        })
        self.assertEqual("clean", invoke("worktree.status", {"project": self.project})["state"])

    def test_worktree_aliases_apply_and_discard_proposals(self):
        proposal = create_proposal(
            self.project,
            "run_000001",
            {"app.py": "print('bob')\n"},
            "PASS",
        )
        status = invoke("worktree.status", {"project": self.project})
        row = status["proposed"][0]
        self.assertEqual(proposal["proposal_id"], row["proposal_id"])
        invoke("worktree.apply_change", {
            "project": self.project,
            "change_id": row["change_id"],
        })
        self.assertEqual("print('bob')\n", (self.root / "app.py").read_text(encoding="utf-8"))

        second = create_proposal(
            self.project,
            "run_000002",
            {"other.py": "print('other')\n"},
            "PASS",
        )
        row = next(item for item in invoke("worktree.status", {"project": self.project})["proposed"] if item["proposal_id"] == second["proposal_id"])
        invoke("worktree.discard_change", {
            "project": self.project,
            "change_id": row["change_id"],
        })
        self.assertFalse(any(item["proposal_id"] == second["proposal_id"] for item in invoke("worktree.status", {"project": self.project})["proposed"]))

    def test_worktree_timeline_combines_commits_and_proposals(self):
        create_proposal(
            self.project,
            "run_000003",
            {"new.py": "print('new')\n"},
            "PASS",
            summary="Add new file",
        )
        timeline = invoke("worktree.timeline", {"project": self.project})
        types = {item["type"] for item in timeline["events"]}
        self.assertIn("commit", types)
        self.assertIn("proposal", types)


if __name__ == "__main__":
    unittest.main()
