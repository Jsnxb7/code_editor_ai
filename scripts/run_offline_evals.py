from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bob_core.contracts import PlanContract

consolidated = json.loads((ROOT / "evals" / "consolidated_cases.json").read_text(encoding="utf-8"))
dataset = consolidated["offline_suite"]
results = []
for case in dataset["cases"]:
    plan = PlanContract.model_validate(case["fixture"])
    results.append({"id": case["id"], "passed": bool(plan.summary and case.get("expected_stage")), "category": case["category"]})
passed = sum(item["passed"] for item in results)
report = {"dataset_version": dataset["dataset_version"], "total": len(results), "passed": passed, "success_rate": passed / len(results), "results": results}
print(json.dumps(report, indent=2))
raise SystemExit(0 if passed == len(results) == 12 else 1)
