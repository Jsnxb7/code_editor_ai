import os
import shutil
import stat
import time
import unittest
from uuid import uuid4

from bob_core import git_service, proposal_store
from config import WORKSPACE_DIR


def remove_readonly(func, path, _error):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_test_tree(path):
    for attempt in range(12):
        try:
            shutil.rmtree(path, onerror=remove_readonly)
            return
        except OSError:
            if attempt == 11:
                raise
            time.sleep(0.05 * (attempt + 1))


class GitProposalTests(unittest.TestCase):
    def setUp(self):
        self.project = f"test_git_{uuid4().hex[:8]}"
        self.root = WORKSPACE_DIR / self.project
        self.root.mkdir(parents=True)
        git_service.init_repo(self.project)
        git_service.set_identity(self.project, "Bob Test", "bob-test@localhost")

    def tearDown(self):
        remove_test_tree(self.root)

    def test_git_status_stage_commit_diff_and_discard(self):
        (self.root / "app.py").write_text("print('one')\n", encoding="utf-8")
        status = git_service.get_status(self.project)
        self.assertIn("app.py", [item["path"] for item in status["untracked"]])

        git_service.stage_file(self.project, "app.py")
        self.assertEqual(1, len(git_service.get_status(self.project)["staged"]))
        git_service.stage_all(self.project)
        commit = git_service.commit(self.project, "Initial commit")
        self.assertTrue(commit["commit"])
        self.assertEqual("clean", git_service.get_status(self.project)["state"])

        (self.root / "app.py").write_text("print('two')\n", encoding="utf-8")
        diff = git_service.get_diff(self.project, "app.py")
        self.assertIn("print('one')", diff["before_content"])
        self.assertIn("print('two')", diff["after_content"])
        self.assertTrue(diff["hunks"])

        git_service.stage_file(self.project, "app.py")
        staged = git_service.get_diff(self.project, "app.py", staged=True)
        self.assertIn("print('two')", staged["after_content"])
        git_service.unstage_file(self.project, "app.py")
        git_service.discard_file(self.project, "app.py")
        self.assertEqual("print('one')\n", (self.root / "app.py").read_text(encoding="utf-8"))

    def test_proposal_apply_turns_into_git_change(self):
        (self.root / "app.py").write_text("before\n", encoding="utf-8")
        git_service.stage_all(self.project)
        git_service.commit(self.project, "Baseline")

        proposal = proposal_store.create_proposal(
            self.project,
            "run_000001",
            {"app.py": "after\n", "new.py": "new\n"},
            "PASS",
            summary="Update app",
        )
        rows = proposal_store.proposal_rows(self.project)
        self.assertEqual(2, len(rows))
        diff = proposal_store.get_diff(self.project, proposal["proposal_id"], "app.py")
        self.assertEqual("before\n", diff["before_content"])
        self.assertEqual("after\n", diff["after_content"])

        result = proposal_store.apply_proposal(self.project, proposal["proposal_id"], "app.py")
        self.assertEqual(["app.py"], result["applied"])
        self.assertEqual("after\n", (self.root / "app.py").read_text(encoding="utf-8"))
        self.assertEqual(["app.py"], [item["path"] for item in git_service.get_status(self.project)["changes"]])

    def test_proposal_conflict_requires_override(self):
        (self.root / "app.py").write_text("base\n", encoding="utf-8")
        proposal = proposal_store.create_proposal(
            self.project,
            "run_000002",
            {"app.py": "proposal\n"},
            "PASS",
        )
        (self.root / "app.py").write_text("user edit\n", encoding="utf-8")
        result = proposal_store.apply_proposal(self.project, proposal["proposal_id"], "app.py")
        self.assertEqual(["app.py"], result["conflicts"])
        self.assertEqual("user edit\n", (self.root / "app.py").read_text(encoding="utf-8"))

        result = proposal_store.apply_proposal(
            self.project,
            proposal["proposal_id"],
            "app.py",
            override=True,
        )
        self.assertEqual(["app.py"], result["applied"])
        self.assertEqual("proposal\n", (self.root / "app.py").read_text(encoding="utf-8"))

    def test_failed_review_requires_override(self):
        (self.root / "app.py").write_text("base\n", encoding="utf-8")
        proposal = proposal_store.create_proposal(
            self.project,
            "run_failed",
            {"app.py": "risky\n"},
            "FAIL",
        )
        with self.assertRaises(PermissionError):
            proposal_store.apply_proposal(self.project, proposal["proposal_id"], "app.py")
        proposal_store.apply_proposal(self.project, proposal["proposal_id"], "app.py", override=True)
        self.assertEqual("risky\n", (self.root / "app.py").read_text(encoding="utf-8"))

    def test_stage_one_git_hunk(self):
        original = "".join(f"line {index}\n" for index in range(1, 80))
        (self.root / "multi.txt").write_text(original, encoding="utf-8")
        git_service.stage_all(self.project)
        git_service.commit(self.project, "Add multi")
        changed = original.replace("line 2\n", "line 2 changed\n").replace("line 70\n", "line 70 changed\n")
        (self.root / "multi.txt").write_text(changed, encoding="utf-8")
        diff = git_service.get_diff(self.project, "multi.txt")
        self.assertEqual(2, len(diff["hunks"]))
        git_service.stage_hunk(self.project, "multi.txt", diff["hunks"][0]["hunk_id"])
        status = git_service.get_status(self.project)
        self.assertEqual(1, len(status["staged"]))
        self.assertEqual(1, len(status["changes"]))


if __name__ == "__main__":
    unittest.main()
