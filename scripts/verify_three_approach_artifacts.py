"""Acceptance checks for the completed three-approach evaluation package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "evals" / "consolidated" / "run-workspace"
APPROACHES = {"direct_coder_model_reviewer", "direct_coder_codex_evaluator", "planner_coder_model_reviewer"}


def expected_cell(actual: str, predicted: str) -> str:
    return {("FAIL", "FAIL"): "TP", ("FAIL", "PASS"): "FN", ("PASS", "FAIL"): "FP", ("PASS", "PASS"): "TN"}[(actual, predicted)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT))
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    errors: list[str] = []
    master_path = output / "master-evaluation.json"
    if not master_path.exists():
        raise SystemExit("master-evaluation.json is missing")
    master = json.loads(master_path.read_text(encoding="utf-8"))
    if master.get("status") != "complete" and not args.allow_partial: errors.append(f"master status is {master.get('status')}")
    if len(master.get("case_index", {})) != 178: errors.append("case_index does not contain 178 variants")
    complete_results = {case_id: result for case_id, result in master.get("case_results", {}).items() if result.get("complete")}
    if not args.allow_partial and len(complete_results) != 178: errors.append("case_results does not contain 178 completed variants")
    categories = Counter(case["prompt_category"] for case in master.get("case_index", {}).values())
    if categories != {"as_is": 74, "naturalized_existing": 74, "new_user_natural": 30}: errors.append(f"prompt categories differ: {dict(categories)}")
    calls = master.get("calls", [])
    successful_keys = {call.get("call_key") for call in calls if call.get("ok")}
    complete_successful_keys = {
        call.get("call_key")
        for call in calls
        if call.get("ok") and call.get("case_id") in complete_results
    }
    latest_by_key = {}
    for call in calls: latest_by_key[call.get("call_key")] = call
    expected_successful_keys = len(complete_results) * 3
    if len(complete_successful_keys) != expected_successful_keys: errors.append(f"expected {expected_successful_keys} completed-case successful call keys, found {len(complete_successful_keys)}")
    unresolved = [key for key, call in latest_by_key.items() if call.get("case_id") in complete_results and not call.get("ok")]
    if unresolved: errors.append(f"unresolved failed call keys: {unresolved[:10]}")

    rows = 0
    for case_id, result in complete_results.items():
        found = set(result.get("approaches", {}))
        if found != APPROACHES: errors.append(f"{case_id}: approach set differs: {sorted(found)}")
        direct = result.get("approaches", {}).get("direct_coder_model_reviewer", {})
        codex = result.get("approaches", {}).get("direct_coder_codex_evaluator", {})
        if direct.get("generated_code_sha256") != codex.get("generated_code_sha256"):
            errors.append(f"{case_id}: direct coder output was not shared")
        blind = codex.get("independent_evaluation", {})
        if blind.get("hidden_tests_seen") is not False or blind.get("blind_to_model_review") is not True:
            errors.append(f"{case_id}: independent evaluation was not blind")
        if blind.get("threshold") != 70: errors.append(f"{case_id}: incorrect threshold")
        for approach, item in result.get("approaches", {}).items():
            actual, predicted = item.get("ground_truth"), item.get("predicted_status")
            if actual not in {"PASS", "FAIL"} or predicted not in {"PASS", "FAIL"}:
                errors.append(f"{case_id}/{approach}: missing binary result"); continue
            if item.get("confusion_cell") != expected_cell(actual, predicted):
                errors.append(f"{case_id}/{approach}: incorrect confusion cell")
            code = item.get("generated_code", "")
            if hashlib.sha256(code.encode("utf-8")).hexdigest() != item.get("generated_code_sha256"):
                errors.append(f"{case_id}/{approach}: code hash mismatch")
            rows += 1
    expected_rows = len(complete_results) * 3
    if rows != expected_rows: errors.append(f"expected {expected_rows} approach rows, found {rows}")

    encoded = master_path.read_text(encoding="utf-8")
    for pattern in (r"(?i)authorization\s*[\":=]+\s*bearer", r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{6,}", r"github_pat_", r"\bhf_[A-Za-z0-9]{8,}"):
        if re.search(pattern, encoded): errors.append(f"potential credential found in master: {pattern}")

    required = ["metrics.json", "results.csv", "component-failure-attribution.json", "paired-prompt-analysis.json", "runtime-log-index.json", "summary.md", "chart-manifest.json", "three-approach-evaluation-charts.pdf", "verification-manifest.json"]
    for name in required:
        if not (output / name).exists(): errors.append(f"missing artifact: {name}")
    if (output / "results.csv").exists():
        with (output / "results.csv").open(encoding="utf-8", newline="") as stream:
            if sum(1 for _ in csv.DictReader(stream)) != expected_rows: errors.append(f"results.csv does not contain {expected_rows} rows")
    if (output / "chart-manifest.json").exists():
        charts = json.loads((output / "chart-manifest.json").read_text(encoding="utf-8")).get("charts", [])
        if len(charts) < 8: errors.append(f"expected at least 8 charts, found {len(charts)}")
        for chart in charts:
            if not Path(chart["svg"]).exists(): errors.append(f"missing chart: {chart['svg']}")

    runtime_logs = [ROOT / "data" / "runtime" / "model-events.jsonl", ROOT / "data" / "runtime" / "ngrok-events.jsonl"]
    for path in runtime_logs:
        if not path.exists(): errors.append(f"missing local structured log: {path.name}")
        elif master.get("evaluation_run_id") not in path.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"evaluation_run_id not found in {path.name}")

    report = {"schema_version": "2.0", "evaluation_run_id": master.get("evaluation_run_id"), "master_status": master.get("status"), "case_count": len(complete_results), "approach_rows": rows, "live_call_attempts": len(calls), "successful_call_keys": len(successful_keys), "completed_case_successful_call_keys": len(complete_successful_keys), "partial_case_successful_call_keys": len(successful_keys - complete_successful_keys), "prompt_categories": dict(categories), "errors": errors}
    (output / "acceptance-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
