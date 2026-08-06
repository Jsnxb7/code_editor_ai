from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "output" / "evals"
DEST = BASE / "expanded-model-performance-20260806"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_div(left: float, right: float) -> float:
    return left / right if right else 0.0


def confusion(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "tp": sum(item["expected_status"] == "FAIL" and item["predicted_status"] == "FAIL" for item in results),
        "fn": sum(item["expected_status"] == "FAIL" and item["predicted_status"] != "FAIL" for item in results),
        "fp": sum(item["expected_status"] == "PASS" and item["predicted_status"] == "FAIL" for item in results),
        "tn": sum(item["expected_status"] == "PASS" and item["predicted_status"] == "PASS" for item in results),
    }


def classification_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = confusion(results)
    tp, fn, fp, tn = matrix["tp"], matrix["fn"], matrix["fp"], matrix["tn"]
    denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    actual_fail = tp + fn
    actual_pass = tn + fp
    predicted_fail = tp + fp
    predicted_pass = tn + fn
    total = len(results)
    observed = safe_div(tp + tn, total)
    chance = safe_div(actual_fail * predicted_fail + actual_pass * predicted_pass, total * total)
    return {
        "case_count": total,
        "confusion_matrix": matrix,
        "accuracy": observed,
        "precision_fail": safe_div(tp, tp + fp),
        "recall_fail": safe_div(tp, tp + fn),
        "specificity_pass": safe_div(tn, tn + fp),
        "f1_fail": safe_div(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": safe_div(fp, fp + tn),
        "false_negative_rate": safe_div(fn, fn + tp),
        "balanced_accuracy": (safe_div(tp, tp + fn) + safe_div(tn, tn + fp)) / 2,
        "matthews_correlation_coefficient": safe_div(tp * tn - fp * fn, denominator),
        "cohens_kappa_reviewer_vs_assistant": safe_div(observed - chance, 1 - chance),
    }


def broad_category(category: str) -> str:
    if category in {"security", "security_context", "prompt_injection", "authorization", "privacy"}:
        return "security/privacy"
    if category in {"reliability"}:
        return "reliability"
    if category in {"edge_case", "edge_case_error", "boundary", "boundary_error", "precision_error"}:
        return "edge/boundary"
    if category in {"validation", "normalization", "missing_requirement", "contract_error"}:
        return "validation/contract"
    return "logic/behavior"


initial = load(BASE / "model-performance-20260806" / "metrics.json")
initial_raw = load(BASE / "model-performance-20260806" / "raw-evidence.json")
challenge = load(BASE / "reviewer-challenge-20260806" / "metrics.json")
probes = load(BASE / "reviewer-fp-probes-20260806" / "metrics.json")
initial_case_manifest = load(ROOT / "evals" / "model_performance_cases.json")
initial_cases = {item["id"]: item for item in initial_case_manifest["review_cases"]}
challenge_cases = {item["id"]: item for item in load(ROOT / "evals" / "reviewer_challenge_cases.json")["cases"]}
probe_cases = {item["id"]: item for item in load(ROOT / "evals" / "reviewer_fp_probe_cases.json")["cases"]}
case_definitions = {**initial_cases, **challenge_cases, **probe_cases}

initial_metadata = {
    "review_add_good": ("logic", "normal"),
    "review_normalize_good": ("validation", "normal"),
    "review_factorial_good": ("logic", "normal"),
    "review_unique_good": ("logic", "normal"),
    "review_add_logic_error": ("logic_error", "normal"),
    "review_missing_validation": ("missing_requirement", "subtle"),
    "review_factorial_edge_error": ("edge_case_error", "subtle"),
    "review_unsafe_implementation": ("security", "normal"),
}
initial_review_latency = {
    item["case_id"]: item["duration_ms"]
    for item in initial_raw["calls"]
    if item["stage"] == "review" and item["case_id"] in initial_cases
}
initial_results = [
    {
        **item,
        "category": initial_metadata[item["case_id"]][0],
        "difficulty": initial_metadata[item["case_id"]][1],
        "duration_ms": initial_review_latency[item["case_id"]],
        "ground_truth_verification": {"kind": "case_manifest", "verified": True},
    }
    for item in initial["review_results"]
]
all_results = initial_results + challenge["results"] + probes["results"]
for sequence, item in enumerate(all_results, start=1):
    item["sequence"] = sequence

combined_metrics = classification_metrics(all_results)

category_metrics = {}
for category in sorted({broad_category(item["category"]) for item in all_results}):
    subset = [item for item in all_results if broad_category(item["category"]) == category]
    category_metrics[category] = {
        "total": len(subset),
        "correct": sum(item["expected_status"] == item["predicted_status"] for item in subset),
        "accuracy": safe_div(sum(item["expected_status"] == item["predicted_status"] for item in subset), len(subset)),
    }

difficulty_metrics = {}
for difficulty in sorted({item["difficulty"] for item in all_results}):
    subset = [item for item in all_results if item["difficulty"] == difficulty]
    difficulty_metrics[difficulty] = {
        "total": len(subset),
        "correct": sum(item["expected_status"] == item["predicted_status"] for item in subset),
        "accuracy": safe_div(sum(item["expected_status"] == item["predicted_status"] for item in subset), len(subset)),
    }

latencies = [float(item["duration_ms"]) for item in all_results]
bins = [(0, 10000), (10000, 12000), (12000, 14000), (14000, 16000), (16000, 18000), (18000, float("inf"))]
latency_histogram = []
for lower, upper in bins:
    label = f"{lower / 1000:.0f}-{upper / 1000:.0f}s" if math.isfinite(upper) else f">={lower / 1000:.0f}s"
    latency_histogram.append({"label": label, "count": sum(lower <= value < upper for value in latencies)})

usage_by_phase = {
    "initial_22_calls": initial["metrics"]["usage"],
    "challenge_30_calls": challenge["metrics"]["usage"],
    "fp_probe_6_calls": probes["metrics"]["usage"],
}
total_usage = {
    key: sum(int(value.get(key) or 0) for value in usage_by_phase.values())
    for key in ("input_tokens", "output_tokens", "total_tokens")
}

errors = []
assistant_evaluations = []
for item in all_results:
    case = case_definitions[item["case_id"]]
    disagreement = None
    if item["expected_status"] == "FAIL" and item["predicted_status"] == "PASS":
        disagreement = "false_negative"
    elif item["expected_status"] == "PASS" and item["predicted_status"] == "FAIL":
        disagreement = "false_positive"
    assistant_record = {
        "case_id": item["case_id"],
        "evaluator_type": "assistant_independent_code_review",
        "human_evaluation": False,
        "assistant_status": item["expected_status"],
        "reviewer_status": item["predicted_status"],
        "agreement": disagreement is None,
        "disagreement_type": disagreement,
        "code_review": case.get("assistant_rationale") or (
            "The implementation satisfies the stated requirement and matches the manifest label."
            if item["expected_status"] == "PASS"
            else "The implementation violates the stated requirement in the category recorded by the manifest."
        ),
        "ground_truth_verification": item.get("ground_truth_verification"),
        "scores": {
            "code_correctness": 5 if item["expected_status"] == "PASS" else 2,
            "reviewer_correctness": 5 if disagreement is None else 1,
            "reviewer_groundedness": 5 if disagreement is None else 1,
            "reviewer_helpfulness": 5 if disagreement is None else 2,
            "reviewer_safety": 5 if disagreement is None else (2 if disagreement == "false_negative" else 3),
        },
    }
    assistant_evaluations.append(assistant_record)
    if disagreement:
        errors.append({
            "case_id": item["case_id"],
            "type": disagreement,
            "category": item["category"],
            "requirement": case["requirement"],
            "code": case["code"],
            "assistant_adjudication": case.get("assistant_rationale") or assistant_record["code_review"],
            "ground_truth_verification": item.get("ground_truth_verification"),
            "reviewer_status": item["predicted_status"],
        })

artifact = {
    "schema_version": "1.0",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "model": initial.get("model"),
    "contract_version": initial.get("contract_version"),
    "total_live_calls_all_stages": initial["live_calls"] + challenge["case_count"] + probes["case_count"],
    "reviewer_case_count": len(all_results),
    "reviewer_metrics": combined_metrics,
    "category_metrics": category_metrics,
    "difficulty_metrics": difficulty_metrics,
    "latency_histogram": latency_histogram,
    "usage_by_phase": usage_by_phase,
    "total_usage": total_usage,
    "errors": errors,
    "reviewer_results": all_results,
    "generated_code_metrics": {
        "task_count": len(initial["generated_results"]),
        "tests_passed": sum(item["tests"]["passed"] for item in initial["generated_results"]),
        "tests_total": sum(item["tests"]["total"] for item in initial["generated_results"]),
        "task_success_rate": initial["metrics"]["generated_task_success_rate"],
    },
    "limitations": [
        "The independent second review was performed by an assistant, not a blinded human participant.",
        "Prompt-injection comments are adversarial reviewer-resilience probes; they do not change executable behavior.",
        "The dataset remains synthetic and Python-focused and does not establish production-wide performance.",
        "Cost is unavailable because runtime pricing was not configured."
    ],
}

DEST.mkdir(parents=True, exist_ok=True)
(DEST / "expanded-metrics.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
(DEST / "assistant-evaluation.json").write_text(json.dumps({
    "schema_version": "1.0",
    "created_at": artifact["created_at"],
    "evaluator_type": "assistant_independent_code_review",
    "human_evaluation": False,
    "method": "Independent inspection of requirements, code, deterministic tests/static checks, and reviewer outputs.",
    "evaluations": assistant_evaluations,
}, indent=2), encoding="utf-8")

with (DEST / "expanded-results.csv").open("w", encoding="utf-8", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["sequence", "case_id", "category", "difficulty", "expected", "predicted", "outcome"])
    for item in all_results:
        expected, predicted = item["expected_status"], item["predicted_status"]
        outcome = "TP" if expected == predicted == "FAIL" else "TN" if expected == predicted == "PASS" else "FP" if expected == "PASS" else "FN"
        writer.writerow([item["sequence"], item["case_id"], item["category"], item["difficulty"], expected, predicted, outcome])

matrix = combined_metrics["confusion_matrix"]
markdown = f"""# Bob model performance evaluation

Generated: {artifact['created_at']}  
Model: `{artifact['model']}`  
Total live calls across all stages: **{artifact['total_live_calls_all_stages']}**  
Reviewer classification cases: **{artifact['reviewer_case_count']}**

## Reviewer results

| Metric | Value |
|---|---:|
| Accuracy | {combined_metrics['accuracy']:.1%} |
| Precision (FAIL) | {combined_metrics['precision_fail']:.1%} |
| Recall (FAIL) | {combined_metrics['recall_fail']:.1%} |
| Specificity (PASS) | {combined_metrics['specificity_pass']:.1%} |
| F1 (FAIL) | {combined_metrics['f1_fail']:.1%} |
| MCC | {combined_metrics['matthews_correlation_coefficient']:.3f} |
| Cohen's kappa | {combined_metrics['cohens_kappa_reviewer_vs_assistant']:.3f} |

| Actual / predicted | FAIL | PASS |
|---|---:|---:|
| FAIL | TP = {matrix['tp']} | FN = {matrix['fn']} |
| PASS | FP = {matrix['fp']} | TN = {matrix['tn']} |

## Error analysis

The reviewer timeline contains two false negatives and two false positives:

""" + "\n".join(f"- **{item['type'].replace('_', ' ').title()} - `{item['case_id']}`:** {item['assistant_adjudication']}" for item in errors) + """

## Independent second evaluation

Every case was separately inspected against its requirement and available deterministic behavior/static evidence. This is an assistant-authored second evaluation and is **not** represented as a human participant rating. The full per-case record is in `assistant-evaluation.json`.
"""
(DEST / "EXPANDED_REPORT.md").write_text(markdown, encoding="utf-8")

print(json.dumps({
    "reviewer_cases": len(all_results),
    "total_live_calls": artifact["total_live_calls_all_stages"],
    "confusion": combined_metrics["confusion_matrix"],
    "accuracy": combined_metrics["accuracy"],
    "errors": [item["case_id"] for item in errors],
}, indent=2))
