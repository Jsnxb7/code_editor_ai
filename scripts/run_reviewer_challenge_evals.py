from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bob_core.colab_adapter import ColabAdapter
from scripts.run_model_performance_evals import division, percentile, redact, run_generated_tests, svg_confusion


def validate_ground_truth(case: dict[str, Any]) -> dict[str, Any]:
    kind = case.get("verification_kind", "behavior")
    if kind.startswith("static_"):
        matched = bool(re.search(case["verification_pattern"], case["code"]))
        verified = matched
        return {"kind": kind, "pattern_matched": matched, "verified": verified}
    result = run_generated_tests(case["code"], case.get("tests", []))
    all_passed = result["total"] > 0 and result["passed"] == result["total"]
    verified = all_passed if case["expected_status"] == "PASS" else not all_passed
    return {"kind": kind, "all_spec_tests_passed": all_passed, "verified": verified, "test_result": result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "evals" / "reviewer_challenge_cases.json"))
    parser.add_argument("--output", default=str(ROOT / "output" / "evals" / "reviewer-challenge-20260806"))
    parser.add_argument("--call-limit", type=int, default=30)
    args = parser.parse_args()
    if os.getenv("BOB_ALLOW_LIVE_EVAL") != "1":
        raise SystemExit("Live evaluation is disabled. Set BOB_ALLOW_LIVE_EVAL=1 explicitly.")
    dataset = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    if not dataset["cases"]:
        raise SystemExit("The challenge dataset must contain at least one case.")
    if args.call_limit < len(dataset["cases"]):
        raise SystemExit("Call limit is lower than the case count.")
    ground_truth = {case["id"]: validate_ground_truth(case) for case in dataset["cases"]}
    invalid = [case_id for case_id, result in ground_truth.items() if not result["verified"]]
    if invalid:
        raise SystemExit(f"Ground truth verification failed: {invalid}")

    adapter = ColabAdapter()
    health = adapter.health()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    evidence = []
    results = []

    total_cases = len(dataset["cases"])
    for number, case in enumerate(dataset["cases"], start=1):
        plan = {
            "task_type": "review challenge evaluation",
            "summary": case["requirement"],
            "confidence": 1,
            "output_mode": "ready_for_coder",
            "files_needed": [case["file"]],
            "coder_prompt": case["requirement"],
        }
        payload = {
            "run_id": f"challenge-{case['id']}",
            "project": "bob_model_evaluation_20260806",
            "plan": plan,
            "selected_plan": plan,
            "code": f"### `{case['file']}`\n```python\n{case['code']}\n```",
            "files": {case["file"]: case["code"]},
        }
        started = time.perf_counter()
        try:
            response = adapter.review(payload)
            ok, error = True, None
        except Exception as exc:
            response, ok, error = {}, False, f"{type(exc).__name__}: {exc}"
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        predicted = response.get("final_status", "ERROR")
        result = {
            "case_id": case["id"],
            "category": case["category"],
            "difficulty": case["difficulty"],
            "expected_status": case["expected_status"],
            "predicted_status": predicted,
            "correct": predicted == case["expected_status"],
            "duration_ms": duration_ms,
            "usage": response.get("usage", {}),
            "assistant_rationale": case["assistant_rationale"],
            "ground_truth_verification": ground_truth[case["id"]],
        }
        results.append(result)
        evidence.append(redact({
            "call_number": number,
            "case": case,
            "request": payload,
            "response": response,
            "duration_ms": duration_ms,
            "ok": ok,
            "error": error,
        }))
        print(f"[{number:02d}/{total_cases}] {case['id']:<34} expected={case['expected_status']} predicted={predicted} {duration_ms:.0f} ms", flush=True)

    tp = sum(item["expected_status"] == "FAIL" and item["predicted_status"] == "FAIL" for item in results)
    fn = sum(item["expected_status"] == "FAIL" and item["predicted_status"] != "FAIL" for item in results)
    fp = sum(item["expected_status"] == "PASS" and item["predicted_status"] == "FAIL" for item in results)
    tn = sum(item["expected_status"] == "PASS" and item["predicted_status"] == "PASS" for item in results)
    latencies = [item["duration_ms"] for item in results]
    usage = {
        key: sum(int(item.get("usage", {}).get(key) or 0) for item in results)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    categories = {}
    for category in sorted({item["category"] for item in results}):
        subset = [item for item in results if item["category"] == category]
        categories[category] = {"total": len(subset), "correct": sum(item["correct"] for item in subset), "accuracy": division(sum(item["correct"] for item in subset), len(subset))}
    metrics = {
        "confusion_matrix": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "accuracy": division(tp + tn, tp + tn + fp + fn),
        "precision": division(tp, tp + fp),
        "recall": division(tp, tp + fn),
        "specificity": division(tn, tn + fp),
        "f1": division(2 * tp, 2 * tp + fp + fn),
        "false_positive_rate": division(fp, fp + tn),
        "false_negative_rate": division(fn, fn + tp),
        "balanced_accuracy": (division(tp, tp + fn) + division(tn, tn + fp)) / 2,
        "latency_ms": {"mean": statistics.fmean(latencies), "p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95), "min": min(latencies), "max": max(latencies)},
        "usage": usage,
        "categories": categories,
    }
    artifact = {
        "schema_version": "1.0",
        "dataset_version": dataset["dataset_version"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": health.get("model"),
        "contract_version": health.get("contract_version"),
        "case_count": len(results),
        "metrics": metrics,
        "results": results,
    }
    (output / "metrics.json").write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    (output / "raw-evidence.json").write_text(json.dumps({"runtime_health": health, "calls": evidence}, indent=2), encoding="utf-8")
    rows = ["case_id,category,difficulty,expected,predicted,correct,duration_ms"]
    for item in results:
        rows.append(",".join([item["case_id"], item["category"], item["difficulty"], item["expected_status"], item["predicted_status"], str(item["correct"]).lower(), str(item["duration_ms"])]))
    (output / "results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    svg_confusion(output / "confusion-matrix.svg", metrics["confusion_matrix"])
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
