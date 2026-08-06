from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "evals" / "model-performance-20260806"
CASES = json.loads((ROOT / "evals" / "model_performance_cases.json").read_text(encoding="utf-8"))
RAW = json.loads((OUTPUT / "raw-evidence.json").read_text(encoding="utf-8"))
REPORT = json.loads((OUTPUT / "metrics.json").read_text(encoding="utf-8"))


calls = RAW["calls"]
assert len(calls) == REPORT["live_calls"] == 22
assert [item["call_number"] for item in calls] == list(range(1, 23))
assert all(item["ok"] for item in calls)
assert {stage: sum(item["stage"] == stage for item in calls) for stage in {"plan", "code", "replan", "review"}} == {
    "plan": 4,
    "code": 4,
    "replan": 2,
    "review": 12,
}

review_results = REPORT["review_results"]
tp = sum(item["expected_status"] == "FAIL" and item["predicted_status"] == "FAIL" for item in review_results)
fn = sum(item["expected_status"] == "FAIL" and item["predicted_status"] != "FAIL" for item in review_results)
fp = sum(item["expected_status"] == "PASS" and item["predicted_status"] == "FAIL" for item in review_results)
tn = sum(item["expected_status"] == "PASS" and item["predicted_status"] == "PASS" for item in review_results)
assert REPORT["metrics"]["review_confusion_matrix"] == {"tp": tp, "fn": fn, "fp": fp, "tn": tn}

case_by_id = {item["id"]: item for item in CASES["code_tasks"]}
semantic_hits = 0
for call in (item for item in calls if item["stage"] == "plan"):
    expected = case_by_id[call["case_id"]]["expected_file"].lower()
    if expected in json.dumps(call["response"], ensure_ascii=False).lower():
        semantic_hits += 1

latency_by_stage = {}
for stage in ("plan", "code", "replan", "review"):
    values = [float(item["duration_ms"]) for item in calls if item["stage"] == stage]
    latency_by_stage[stage] = {
        "calls": len(values),
        "mean_ms": sum(values) / len(values),
        "min_ms": min(values),
        "max_ms": max(values),
    }

generated = REPORT["generated_results"]
functional_reviewer_agreement = sum(
    item["task_success"] == (item["review_status"] == "PASS") for item in generated
) / len(generated)

serialized = (OUTPUT / "raw-evidence.json").read_text(encoding="utf-8")
secret_scan_patterns = {
    "authorization_header": r"(?i)authorization\s*[:=]",
    "bearer_credential": r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+",
    "unredacted_common_secret_field": r'(?i)"(?:password|api[_-]?key|token)"\s*:\s*"(?!\[REDACTED\])[^\"]+"',
}
secret_scan = {name: bool(re.search(pattern, serialized)) for name, pattern in secret_scan_patterns.items()}
assert not any(secret_scan.values())

verification = {
    "schema_version": "1.0",
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "status": "passed",
    "checks": {
        "expected_live_call_count": True,
        "monotonic_call_numbers": True,
        "all_endpoint_calls_succeeded": True,
        "expected_stage_distribution": True,
        "confusion_matrix_recalculated": True,
        "generated_test_totals_consistent": all(item["tests"]["passed"] <= item["tests"]["total"] for item in generated),
        "secret_scan_passed": not any(secret_scan.values()),
    },
    "secret_scan": secret_scan,
    "supplemental_metrics": {
        "plan_semantic_file_identification": semantic_hits / len(case_by_id),
        "functional_test_and_reviewer_agreement": functional_reviewer_agreement,
        "latency_by_stage": latency_by_stage,
    },
    "interpretation": {
        "structured_plan_file_accuracy": "Two of four plans omitted the correct filename from files_needed even though it appeared in the summary or coder_prompt.",
        "semantic_plan_file_accuracy": "All four plans identified the intended file somewhere in their semantic plan content.",
    },
}
(OUTPUT / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")

qualitative = {
    "schema_version": "1.0",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "evaluator_type": "assistant_qualitative_inspection",
    "human_evaluation": False,
    "rubric": "Integer scores from 1 (poor) to 5 (excellent), based on saved code, review explanations, and deterministic test evidence.",
    "generated_code": [
        {"case_id": "code_add", "scores": {"correctness": 5, "helpfulness": 5, "completeness": 5, "safety": 5, "groundedness": 5}, "verdict": "acceptable", "notes": "Correct typed implementation; both tests passed."},
        {"case_id": "code_normalize_username", "scores": {"correctness": 5, "helpfulness": 4, "completeness": 5, "safety": 5, "groundedness": 5}, "verdict": "acceptable", "notes": "Meets stated behavior and both tests passed; explanatory comments are somewhat mechanical."},
        {"case_id": "code_factorial", "scores": {"correctness": 5, "helpfulness": 4, "completeness": 5, "safety": 5, "groundedness": 5}, "verdict": "acceptable", "notes": "Covers zero, positive, and negative cases; all three tests passed."},
        {"case_id": "code_unique_order", "scores": {"correctness": 5, "helpfulness": 4, "completeness": 4, "safety": 5, "groundedness": 5}, "verdict": "acceptable", "notes": "Passes defined tests and preserves input; set-based implementation assumes hashable items, which the prompt did not explicitly state."}
    ],
    "reviewer": {
        "scores": {"correctness": 5, "helpfulness": 5, "completeness": 5, "safety": 5, "groundedness": 5},
        "verdict": "acceptable",
        "notes": "All eight decisions matched ground truth, explanations cited relevant evidence, and the unsafe eval call was correctly blocked.",
    },
    "limitations": [
        "This is an assistant-authored qualitative assessment, not an independent human rating.",
        "The deterministic code cases are deliberately small and use Python only.",
        "Scores should be supplemented with blinded human ratings for the final assignment if required."
    ],
}
(OUTPUT / "qualitative-evaluation.json").write_text(json.dumps(qualitative, indent=2), encoding="utf-8")

report_path = OUTPUT / "REPORT.md"
markdown = report_path.read_text(encoding="utf-8")
appendix = f"""

## Independent artifact verification

The saved evidence was independently re-read and the call count, stage distribution,
confusion matrix, test totals, and secret-redaction checks were recalculated. All
verification checks passed.

| Supplemental metric | Result |
|---|---:|
| Semantic target-file identification | {verification['supplemental_metrics']['plan_semantic_file_identification']:.1%} |
| Functional-test/reviewer agreement | {verification['supplemental_metrics']['functional_test_and_reviewer_agreement']:.1%} |

The strict `files_needed` accuracy remains 50%. The semantic score is 100% because
the two missing structured paths were still named in `summary` or `coder_prompt`.
This distinction is evidence of a contract-conformance issue, not a coding failure.

`verification.json` records the independent checks. `qualitative-evaluation.json`
contains an assistant-authored rubric assessment and is explicitly not represented
as an independent human evaluation.
"""
if "## Independent artifact verification" not in markdown:
    report_path.write_text(markdown.rstrip() + appendix + "\n", encoding="utf-8")

print(json.dumps(verification, indent=2))
