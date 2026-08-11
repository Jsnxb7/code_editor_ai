import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConsolidatedEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = json.loads((ROOT / "evals" / "consolidated_cases.json").read_text(encoding="utf-8"))
        cls.evaluation = json.loads(
            (ROOT / "output" / "evals" / "consolidated" / "consolidated_evaluation.json").read_text(encoding="utf-8")
        )

    def test_consolidated_dataset_inventory(self):
        inventory = self.dataset["inventory"]
        self.assertEqual(inventory["offline_cases"], 12)
        self.assertEqual(inventory["live_prompt_variants"], 178)
        self.assertEqual(inventory["paired_requirements"], 74)
        self.assertEqual(
            inventory["prompt_categories"],
            {"as_is": 74, "naturalized_existing": 74, "new_user_natural": 30},
        )

    def test_consolidated_history_preserves_all_accepted_runs(self):
        inventory = self.evaluation["inventory"]
        self.assertEqual(inventory["accepted_live_runs"], 5)
        self.assertEqual(inventory["recorded_live_call_attempts"], 688)
        self.assertEqual(inventory["latest_scored_approach_results"], 534)
        self.assertEqual(inventory["latest_duplicate_successful_attempts"], 6)

    def test_consolidated_matrix_recalculates_from_results(self):
        master = self.evaluation["runs"]["three_approach_20260810"]["master"]
        cells = Counter(
            item["confusion_cell"].lower()
            for result in master["case_results"].values()
            for item in result["approaches"].values()
        )
        self.assertEqual(
            {cell: cells[cell] for cell in ("tp", "fn", "fp", "tn")},
            {"tp": 62, "fn": 164, "fp": 10, "tn": 298},
        )


if __name__ == "__main__":
    unittest.main()
