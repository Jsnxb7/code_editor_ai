import unittest

from scripts.run_three_approach_live_evals import confusion_cell, evaluate_code, independent_evaluation


class ThreeApproachEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "file": "calculator.py",
            "function": "add",
            "requirement": "Implement add(left, right) so it returns the arithmetic sum.",
            "tests": [
                {"id": "public", "kind": "call", "visibility": "public", "function": "add", "args": [2, 3], "expected": 5, "check_no_mutation": True},
                {"id": "hidden", "kind": "call", "visibility": "hidden", "function": "add", "args": [-2, 1], "expected": -1, "check_no_mutation": True},
            ],
        }

    def test_execution_evidence_sets_ground_truth(self):
        good = evaluate_code("def add(left, right):\n    return left + right\n", {"calculator.py": "def add(left, right):\n    return left + right\n"}, self.case)
        bad = evaluate_code("def add(left, right):\n    return left - right\n", {"calculator.py": "def add(left, right):\n    return left - right\n"}, self.case)
        self.assertEqual(good["ground_truth"], "PASS")
        self.assertEqual(bad["ground_truth"], "FAIL")

    def test_blind_evaluator_does_not_include_hidden_test_evidence(self):
        code = "def add(left, right):\n    return left + right\n"
        result = independent_evaluation(code, {"calculator.py": code}, self.case)
        self.assertFalse(result["hidden_tests_seen"])
        self.assertEqual(result["public_evidence"]["tests_total"], 1)
        self.assertEqual(result["predicted_status"], "PASS")

    def test_confusion_mapping_uses_fail_as_positive(self):
        self.assertEqual(confusion_cell("FAIL", "FAIL"), "TP")
        self.assertEqual(confusion_cell("FAIL", "PASS"), "FN")
        self.assertEqual(confusion_cell("PASS", "FAIL"), "FP")
        self.assertEqual(confusion_cell("PASS", "PASS"), "TN")


if __name__ == "__main__":
    unittest.main()
