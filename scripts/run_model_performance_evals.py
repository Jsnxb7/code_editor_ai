from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bob_core.colab_adapter import ColabAdapter


SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:api[_-]?key|password|token)\s*[:=]\s*)[^\s,;\"']+"),
)


def redact_text(value: str) -> str:
    result = value
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(r"\1[REDACTED]", result)
    configured = os.getenv("BOB_COLAB_TOKEN", "")
    if configured:
        result = result.replace(configured, "[REDACTED]")
    return result


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items() if key.lower() not in {"authorization", "token"}}
    return value


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile_value
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def division(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def combined_plan_text(plan: dict[str, Any]) -> str:
    return json.dumps(plan, ensure_ascii=False).lower()


def safe_generated_python(code: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"syntax error: {exc.msg}"
    banned_nodes = (ast.Import, ast.With, ast.AsyncWith, ast.Global, ast.Nonlocal)
    banned_calls = {"eval", "exec", "open", "compile", "__import__", "input", "breakpoint"}
    banned_roots = {"os", "sys", "subprocess", "socket", "pathlib", "shutil", "requests", "urllib"}
    for node in ast.walk(tree):
        if isinstance(node, banned_nodes):
            return False, f"disallowed syntax: {type(node).__name__}"
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] not in {"typing", "collections"}:
            return False, f"disallowed import: {node.module}"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in banned_calls:
                return False, f"disallowed call: {node.func.id}"
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in banned_roots:
                return False, f"disallowed call root: {node.func.value.id}"
    return True, "passed restricted AST safety check"


def run_generated_tests(code: str, tests: list[dict[str, Any]]) -> dict[str, Any]:
    safe, safety_reason = safe_generated_python(code)
    if not safe:
        return {"safe_to_execute": False, "safety_reason": safety_reason, "passed": 0, "total": len(tests), "details": []}
    harness = ["namespace = {}", f"exec({code!r}, namespace)", "results = []"]
    for test in tests:
        expression = test["expression"]
        if "raises" in test:
            harness.extend([
                "try:",
                f"    eval({expression!r}, namespace)",
                f"    results.append({{'expression': {expression!r}, 'passed': False, 'detail': 'expected {test['raises']}'}})",
                "except Exception as exc:",
                f"    results.append({{'expression': {expression!r}, 'passed': type(exc).__name__ == {test['raises']!r}, 'detail': type(exc).__name__}})",
            ])
        else:
            harness.extend([
                f"actual = eval({expression!r}, namespace)",
                f"results.append({{'expression': {expression!r}, 'passed': actual == {test['expected']!r}, 'actual': actual, 'expected': {test['expected']!r}}})",
            ])
    harness.append("import json; print(json.dumps(results))")
    with tempfile.TemporaryDirectory(prefix="bob-eval-") as temporary:
        runner = Path(temporary) / "test_generated.py"
        runner.write_text("\n".join(harness), encoding="utf-8")
        try:
            completed = subprocess.run(
                [sys.executable, "-I", str(runner)],
                cwd=temporary,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            details = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.returncode == 0 and completed.stdout.strip() else []
            error = completed.stderr[-1000:] if completed.returncode else None
        except subprocess.TimeoutExpired:
            details, error = [], "execution timed out"
    return {
        "safe_to_execute": True,
        "safety_reason": safety_reason,
        "passed": sum(bool(item.get("passed")) for item in details),
        "total": len(tests),
        "details": details,
        "error": error,
    }


def svg_confusion(path: Path, matrix: dict[str, int]) -> None:
    maximum = max(1, *matrix.values())
    cells = [("TP", 210, 160), ("FN", 390, 160), ("FP", 210, 300), ("TN", 390, 300)]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="620" height="430" viewBox="0 0 620 430">',
        '<rect width="620" height="430" fill="#ffffff"/>',
        '<text x="310" y="35" text-anchor="middle" font-family="Arial" font-size="22" font-weight="bold">Reviewer confusion matrix</text>',
        '<text x="300" y="70" text-anchor="middle" font-family="Arial" font-size="14">Predicted class</text>',
        '<text x="210" y="100" text-anchor="middle" font-family="Arial" font-size="14">FAIL</text>',
        '<text x="390" y="100" text-anchor="middle" font-family="Arial" font-size="14">PASS</text>',
        '<text x="35" y="230" text-anchor="middle" transform="rotate(-90 35 230)" font-family="Arial" font-size="14">Actual class</text>',
        '<text x="105" y="165" text-anchor="middle" font-family="Arial" font-size="14">FAIL</text>',
        '<text x="105" y="305" text-anchor="middle" font-family="Arial" font-size="14">PASS</text>',
    ]
    for label, x, y in cells:
        value = matrix[label.lower()]
        opacity = 0.18 + 0.72 * value / maximum
        parts.extend([
            f'<rect x="{x - 75}" y="{y - 45}" width="150" height="110" rx="8" fill="#2563eb" fill-opacity="{opacity:.2f}" stroke="#1e3a8a"/>',
            f'<text x="{x}" y="{y - 5}" text-anchor="middle" font-family="Arial" font-size="16" font-weight="bold">{label}</text>',
            f'<text x="{x}" y="{y + 30}" text-anchor="middle" font-family="Arial" font-size="30">{value}</text>',
        ])
    parts.extend([
        '<text x="310" y="395" text-anchor="middle" font-family="Arial" font-size="12" fill="#444">Positive class = FAIL (defect present)</text>',
        '</svg>',
    ])
    path.write_text("\n".join(parts), encoding="utf-8")


def markdown_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    matrix = metrics["review_confusion_matrix"]
    return f"""# Bob model performance evaluation

Generated: {report['created_at']}  
Dataset: `{report['dataset_version']}`  
Runtime model: `{report.get('model', 'unknown')}`  
Live calls: **{report['live_calls']} / {report['call_limit']}**

## Executive results

| Metric | Result |
|---|---:|
| Endpoint success rate | {metrics['endpoint_success_rate']:.1%} |
| Plan required-file accuracy | {metrics['plan_required_file_accuracy']:.1%} |
| Plan keyword coverage | {metrics['plan_keyword_coverage']:.1%} |
| Replan constraint accuracy | {metrics['replan_constraint_accuracy']:.1%} |
| Generated test pass rate | {metrics['generated_test_pass_rate']:.1%} |
| Generated task success rate | {metrics['generated_task_success_rate']:.1%} |
| Reviewer accuracy | {metrics['review_accuracy']:.1%} |
| Reviewer precision (FAIL) | {metrics['review_precision']:.1%} |
| Reviewer recall (FAIL) | {metrics['review_recall']:.1%} |
| Reviewer specificity (PASS) | {metrics['review_specificity']:.1%} |
| Reviewer F1 (FAIL) | {metrics['review_f1']:.1%} |
| Balanced accuracy | {metrics['review_balanced_accuracy']:.1%} |

## Reviewer confusion matrix

The positive class is **FAIL**, meaning a defect is present.

| Actual / predicted | FAIL | PASS |
|---|---:|---:|
| FAIL | TP = {matrix['tp']} | FN = {matrix['fn']} |
| PASS | FP = {matrix['fp']} | TN = {matrix['tn']} |

![Reviewer confusion matrix](confusion-matrix.svg)

## Operational metrics

| Metric | Result |
|---|---:|
| Mean latency | {metrics['latency_ms']['mean']:.0f} ms |
| P50 latency | {metrics['latency_ms']['p50']:.0f} ms |
| P95 latency | {metrics['latency_ms']['p95']:.0f} ms |
| Input tokens reported | {metrics['usage']['input_tokens']} |
| Output tokens reported | {metrics['usage']['output_tokens']} |
| Total tokens reported | {metrics['usage']['total_tokens']} |
| Estimated cost | {metrics['usage']['estimated_cost_usd'] if metrics['usage']['estimated_cost_usd'] is not None else 'Not configured'} |

## Evidence and interpretation

- `raw-evidence.json` contains redacted inputs, outputs, timings, model metadata, and per-case judgments.
- `metrics.json` contains the machine-readable aggregate metrics.
- `results.csv` contains one row per evaluated stage/case for independent analysis.
- Generated code was executed only after the restricted AST safety gate passed.
- Reviewer metrics use eight balanced, deterministic examples: four correct and four defective.
- These results characterize this dataset and runtime version; they are not a universal model benchmark.
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "evals" / "model_performance_cases.json"))
    parser.add_argument("--output", default=str(ROOT / "output" / "evals" / "model-performance-20260806"))
    parser.add_argument("--call-limit", type=int, default=30)
    args = parser.parse_args()
    if os.getenv("BOB_ALLOW_LIVE_EVAL") != "1":
        raise SystemExit("Live evaluation is disabled. Set BOB_ALLOW_LIVE_EVAL=1 explicitly.")
    dataset = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    adapter = ColabAdapter()
    if not adapter.configured:
        raise SystemExit("A model endpoint must be configured.")

    evidence: list[dict[str, Any]] = []
    calls = 0

    def invoke(stage: str, case_id: str, payload: dict[str, Any], function) -> dict[str, Any]:
        nonlocal calls
        if calls >= args.call_limit:
            raise RuntimeError(f"Live-call limit of {args.call_limit} reached")
        calls += 1
        started = time.perf_counter()
        try:
            response = function(payload)
            ok, error = True, None
        except Exception as exc:
            response, ok, error = {}, False, f"{type(exc).__name__}: {exc}"
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        record = {
            "case_id": case_id,
            "stage": stage,
            "call_number": calls,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "ok": ok,
            "error": error,
            "request": payload,
            "response": response,
        }
        evidence.append(redact(record))
        print(f"[{calls:02d}/{args.call_limit}] {stage:<7} {case_id:<32} {'ok' if ok else 'ERROR'} {duration_ms:.0f} ms", flush=True)
        return response

    health = adapter.health()
    plan_results = []
    generated_results = []
    for case in dataset["code_tasks"]:
        payload = {
            "run_id": f"eval-{case['id']}",
            "project": "bob_model_evaluation_20260806",
            "user_prompt": case["prompt"],
            "files": {},
            "forced_files": {},
        }
        plan = invoke("plan", case["id"], payload, adapter.plan)
        text = combined_plan_text(plan)
        required_file_match = case["expected_file"].lower() in [str(item).lower() for item in plan.get("files_needed", [])]
        keyword_hits = sum(keyword.lower() in text for keyword in case["plan_keywords"])
        plan_results.append({"case_id": case["id"], "required_file_match": required_file_match, "keyword_hits": keyword_hits, "keyword_total": len(case["plan_keywords"])})
        code_payload = {**payload, "selected_plan": plan, "plan": plan, "plan_id": f"plan-{case['id']}"}
        code_result = invoke("code", case["id"], code_payload, adapter.code)
        files = code_result.get("files") if isinstance(code_result.get("files"), dict) else {}
        generated_code = files.get(case["expected_file"], "")
        if not generated_code and len(files) == 1:
            generated_code = next(iter(files.values())) or ""
        tests = run_generated_tests(str(generated_code or ""), case["tests"])
        review_payload = {**payload, "selected_plan": plan, "plan": plan, "plan_id": f"plan-{case['id']}", "code": code_result.get("code", ""), "files": files}
        review_result = invoke("review", case["id"], review_payload, adapter.review)
        generated_results.append({
            "case_id": case["id"],
            "expected_file": case["expected_file"],
            "returned_files": list(files),
            "tests": tests,
            "review_status": review_result.get("final_status", "ERROR"),
            "task_success": tests["total"] > 0 and tests["passed"] == tests["total"],
        })

    replan_results = []
    for case in dataset["replan_cases"]:
        payload = {
            "run_id": f"eval-{case['id']}",
            "project": "bob_model_evaluation_20260806",
            "user_prompt": case["prompt"],
            "previous_plan": case["previous_plan"],
            "selected_plan": case["previous_plan"],
            "forced_files": case["forced_files"],
            "files": {},
        }
        result = invoke("replan", case["id"], payload, adapter.replan)
        plan = result.get("plan", result)
        files_needed = [str(item).lower() for item in plan.get("files_needed", [])]
        required = all(item.lower() in files_needed for item in case["required_files"])
        forbidden = all(item.lower() not in files_needed for item in case["forbidden_files"])
        replan_results.append({"case_id": case["id"], "required_files_present": required, "forbidden_files_absent": forbidden, "passed": required and forbidden})

    review_results = []
    for case in dataset["review_cases"]:
        plan = {
            "task_type": "review evaluation",
            "summary": case["requirement"],
            "confidence": 1,
            "output_mode": "ready_for_coder",
            "files_needed": [case["file"]],
            "coder_prompt": case["requirement"],
        }
        payload = {
            "run_id": f"eval-{case['id']}",
            "project": "bob_model_evaluation_20260806",
            "plan": plan,
            "selected_plan": plan,
            "code": f"### `{case['file']}`\n```python\n{case['code']}\n```",
            "files": {case["file"]: case["code"]},
        }
        result = invoke("review", case["id"], payload, adapter.review)
        predicted = result.get("final_status", "ERROR")
        review_results.append({
            "case_id": case["id"],
            "expected_status": case["expected_status"],
            "predicted_status": predicted,
            "failure_category": case["failure_category"],
            "correct": predicted == case["expected_status"],
        })

    tp = sum(item["expected_status"] == "FAIL" and item["predicted_status"] == "FAIL" for item in review_results)
    fn = sum(item["expected_status"] == "FAIL" and item["predicted_status"] != "FAIL" for item in review_results)
    fp = sum(item["expected_status"] == "PASS" and item["predicted_status"] == "FAIL" for item in review_results)
    tn = sum(item["expected_status"] == "PASS" and item["predicted_status"] == "PASS" for item in review_results)
    latencies = [float(item["duration_ms"]) for item in evidence]
    successful = sum(bool(item["ok"]) for item in evidence)
    all_usage = [item.get("response", {}).get("usage", {}) for item in evidence]
    input_tokens = sum(int(item.get("input_tokens") or 0) for item in all_usage)
    output_tokens = sum(int(item.get("output_tokens") or 0) for item in all_usage)
    total_tokens = sum(int(item.get("total_tokens") or 0) for item in all_usage)
    costs = [item.get("response", {}).get("estimated_cost_usd") for item in evidence]
    configured_costs = [float(item) for item in costs if item is not None]
    total_tests = sum(item["tests"]["total"] for item in generated_results)
    passed_tests = sum(item["tests"]["passed"] for item in generated_results)
    keyword_total = sum(item["keyword_total"] for item in plan_results)
    keyword_hits = sum(item["keyword_hits"] for item in plan_results)
    metrics = {
        "endpoint_success_rate": division(successful, len(evidence)),
        "plan_required_file_accuracy": division(sum(item["required_file_match"] for item in plan_results), len(plan_results)),
        "plan_keyword_coverage": division(keyword_hits, keyword_total),
        "replan_constraint_accuracy": division(sum(item["passed"] for item in replan_results), len(replan_results)),
        "generated_test_pass_rate": division(passed_tests, total_tests),
        "generated_task_success_rate": division(sum(item["task_success"] for item in generated_results), len(generated_results)),
        "review_confusion_matrix": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
        "review_accuracy": division(tp + tn, tp + tn + fp + fn),
        "review_precision": division(tp, tp + fp),
        "review_recall": division(tp, tp + fn),
        "review_specificity": division(tn, tn + fp),
        "review_f1": division(2 * tp, 2 * tp + fp + fn),
        "review_balanced_accuracy": (division(tp, tp + fn) + division(tn, tn + fp)) / 2,
        "latency_ms": {
            "mean": statistics.fmean(latencies) if latencies else 0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "min": min(latencies, default=0),
            "max": max(latencies, default=0),
        },
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": sum(configured_costs) if configured_costs else None,
        },
    }
    report = {
        "schema_version": "1.0",
        "dataset_version": dataset["dataset_version"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": health.get("model", adapter.model_id),
        "contract_version": health.get("contract_version"),
        "live_calls": calls,
        "call_limit": args.call_limit,
        "plan_results": plan_results,
        "generated_results": generated_results,
        "replan_results": replan_results,
        "review_results": review_results,
        "metrics": metrics,
    }
    (output / "raw-evidence.json").write_text(json.dumps(redact({"runtime_health": health, "calls": evidence}), indent=2), encoding="utf-8")
    (output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    rows = ["case_id,stage,ok,duration_ms,expected,predicted"]
    review_by_id = {item["case_id"]: item for item in review_results}
    for item in evidence:
        classification = review_by_id.get(item["case_id"], {})
        rows.append(",".join([
            item["case_id"], item["stage"], str(item["ok"]).lower(), str(item["duration_ms"]),
            classification.get("expected_status", ""), classification.get("predicted_status", ""),
        ]))
    (output / "results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    svg_confusion(output / "confusion-matrix.svg", metrics["review_confusion_matrix"])
    (output / "REPORT.md").write_text(markdown_report(report), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
