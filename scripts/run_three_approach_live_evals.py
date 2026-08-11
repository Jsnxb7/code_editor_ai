"""Run the unified three-approach Bob evaluation with atomic evidence checkpoints."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bob_core.colab_adapter import ColabAdapter
from bob_core.structured_logging import log_model

APPROACH_REVIEWER = "direct_coder_model_reviewer"
APPROACH_CODEX = "direct_coder_codex_evaluator"
APPROACH_PIPELINE = "planner_coder_model_reviewer"
APPROACHES = (APPROACH_REVIEWER, APPROACH_CODEX, APPROACH_PIPELINE)
ALLOWED_IMPORTS = {
    "ast", "collections", "datetime", "decimal", "functools", "hashlib", "heapq",
    "hmac", "itertools", "math", "re", "string", "typing", "urllib",
}
BANNED_CALLS = {"eval", "exec", "open", "compile", "__import__", "input", "breakpoint"}
BANNED_ROOTS = {"os", "socket", "pathlib", "shutil", "requests", "http", "ftplib"}
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
    """Remove credentials while retaining generated code needed for evaluation."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if key.lower() not in {"authorization", "token"}
        }
    return value


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(prepare_for_persistence(value), indent=2, ensure_ascii=False, default=repr) + "\n", encoding="utf-8")
    for attempt in range(30):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(0.1 * (attempt + 1))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def prepare_for_persistence(value: Any) -> Any:
    """Redact evidence and bind hashes to the exact persisted representation."""
    persisted = redact(value)
    if not isinstance(persisted, dict):
        return persisted
    for result in persisted.get("case_results", {}).values():
        if not isinstance(result, dict):
            continue
        for item in result.get("approaches", {}).values():
            if not isinstance(item, dict):
                continue
            code = item.get("generated_code")
            if isinstance(code, str):
                item["generated_code_sha256"] = sha256_text(code)
    return persisted


def scan_safety(code: str, allow_subprocess: bool = False) -> dict[str, Any]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"safe": False, "syntax_valid": False, "reason": f"syntax error: {exc.msg} line {exc.lineno}", "function_names": [], "control_flow_nodes": 0, "raise_nodes": 0}
    functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    control = sum(isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.Match, ast.IfExp)) for node in ast.walk(tree))
    raises = sum(isinstance(node, ast.Raise) for node in ast.walk(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith, ast.Global, ast.Nonlocal)):
            return {"safe": False, "syntax_valid": True, "reason": f"disallowed syntax: {type(node).__name__}", "function_names": functions, "control_flow_nodes": control, "raise_nodes": raises}
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            permitted = set(ALLOWED_IMPORTS) | ({"subprocess"} if allow_subprocess else set())
            if not roots <= permitted:
                return {"safe": False, "syntax_valid": True, "reason": f"disallowed import: {sorted(roots - permitted)}", "function_names": functions, "control_flow_nodes": control, "raise_nodes": raises}
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            permitted = set(ALLOWED_IMPORTS) | ({"subprocess"} if allow_subprocess else set())
            if root not in permitted:
                return {"safe": False, "syntax_valid": True, "reason": f"disallowed import: {node.module}", "function_names": functions, "control_flow_nodes": control, "raise_nodes": raises}
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
                return {"safe": False, "syntax_valid": True, "reason": f"disallowed call: {node.func.id}", "function_names": functions, "control_flow_nodes": control, "raise_nodes": raises}
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id in BANNED_ROOTS:
                return {"safe": False, "syntax_valid": True, "reason": f"disallowed call root: {node.func.value.id}", "function_names": functions, "control_flow_nodes": control, "raise_nodes": raises}
    return {"safe": True, "syntax_valid": True, "reason": "passed restricted AST safety scan", "function_names": functions, "control_flow_nodes": control, "raise_nodes": raises}


def execute_tests(code: str, tests: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    executable = [test for test in tests if test["kind"] in {"call", "expression"}]
    if not executable:
        return [], None
    harness = [
        "import copy, json",
        "namespace = {}",
        f"exec({code!r}, namespace, namespace)",
        f"tests = {executable!r}",
        "results = []",
        "for test in tests:",
        "    expected_exception = test.get('raises')",
        "    original_args = None",
        "    try:",
        "        if test['kind'] == 'call':",
        "            args = copy.deepcopy(test.get('args', []))",
        "            original_args = copy.deepcopy(args)",
        "            function = namespace.get(test['function'])",
        "            if not callable(function): raise AssertionError('required function is missing')",
        "            actual = function(*args)",
        "        else:",
        "            actual = eval(test['expression'], namespace, namespace)",
        "    except Exception as error:",
        "        passed = expected_exception == type(error).__name__",
        "        detail = {'id': test['id'], 'kind': test['kind'], 'visibility': test['visibility'], 'passed': passed, 'raised': type(error).__name__, 'message': str(error)[:300], 'expected_exception': expected_exception}",
        "    else:",
        "        expected_value = tuple(test.get('expected', [])) if test.get('expected_type') == 'tuple' else test.get('expected')",
        "        passed = expected_exception is None and actual == expected_value",
        "        detail = {'id': test['id'], 'kind': test['kind'], 'visibility': test['visibility'], 'passed': passed, 'actual': actual, 'expected': expected_value, 'expected_type': test.get('expected_type'), 'expected_exception': expected_exception}",
        "    if original_args is not None and test.get('check_no_mutation') and args != original_args:",
        "        passed = False",
        "        detail['input_mutated'] = True",
        "    detail['passed'] = passed",
        "    results.append(detail)",
        "print(json.dumps(results, ensure_ascii=False, default=repr))",
    ]
    with tempfile.TemporaryDirectory(prefix="bob-three-track-") as temporary:
        runner = Path(temporary) / "runner.py"
        runner.write_text("\n".join(harness), encoding="utf-8")
        try:
            completed = subprocess.run([sys.executable, "-I", str(runner)], cwd=temporary, capture_output=True, text=True, timeout=15, check=False)
        except subprocess.TimeoutExpired:
            return [], "execution timed out after 15 seconds"
    if completed.returncode != 0:
        return [], (completed.stderr or completed.stdout or "generated test process failed")[-2000:]
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1]), None
    except (IndexError, json.JSONDecodeError) as exc:
        return [], f"test output was not valid JSON: {exc}"


def evaluate_code(code: str, files: dict[str, Any], case: dict[str, Any], include_hidden: bool = True) -> dict[str, Any]:
    expected_file = case["file"]
    expected_present = expected_file in files
    expected_required = bool(case.get("file_requirement_explicit", True))
    file_requirement_satisfied = expected_present or not expected_required
    allow_subprocess = case["function"] in {"git_status", "run_git_status"}
    safety = scan_safety(code, allow_subprocess=allow_subprocess)
    selected_tests = [test for test in case["tests"] if include_hidden or test["visibility"] == "public"]
    details: list[dict[str, Any]] = []
    execution_error = None
    if safety["safe"]:
        details, execution_error = execute_tests(code, selected_tests)
    detail_ids = {detail["id"] for detail in details}
    for test in selected_tests:
        if test["kind"] != "static":
            if test["id"] not in detail_ids and safety["safe"]:
                details.append({"id": test["id"], "kind": test["kind"], "visibility": test["visibility"], "passed": False, "error": execution_error or "test did not return evidence"})
            continue
        required = test.get("required_patterns", [])
        forbidden = test.get("forbidden_patterns", [])
        missing = [pattern for pattern in required if not re.search(pattern, code, re.IGNORECASE | re.DOTALL)]
        present = [pattern for pattern in forbidden if re.search(pattern, code, re.IGNORECASE | re.DOTALL)]
        details.append({"id": test["id"], "kind": "static", "visibility": test["visibility"], "passed": not missing and not present, "missing_required_patterns": missing, "present_forbidden_patterns": present})
    passed = sum(bool(detail.get("passed")) for detail in details)
    total = len(selected_tests)
    task_success = bool(file_requirement_satisfied and safety["safe"] and not execution_error and total and passed == total)
    failure_reasons = []
    if expected_required and not expected_present:
        failure_reasons.append("expected_file_missing")
    if not safety["safe"]:
        failure_reasons.append("unsafe_or_invalid_code")
    if execution_error:
        failure_reasons.append("execution_error")
    if passed < total:
        failure_reasons.append("test_failure")
    return {
        "expected_file": expected_file,
        "expected_file_required_by_prompt": expected_required,
        "expected_file_present": expected_present,
        "file_requirement_satisfied": file_requirement_satisfied,
        "returned_files": sorted(files),
        "safety": safety,
        "tests_passed": passed,
        "tests_total": total,
        "test_pass_rate": passed / total if total else 0.0,
        "details": details,
        "execution_error": execution_error,
        "task_success": task_success,
        "ground_truth": "PASS" if task_success else "FAIL",
        "failure_reasons": failure_reasons,
    }


def independent_evaluation(code: str, files: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    public = evaluate_code(code, files, case, include_hidden=False)
    safety = public["safety"]
    public_total = public["tests_total"]
    correctness = round(35 * public["tests_passed"] / public_total) if public_total else (25 if safety["syntax_valid"] and case["function"] in safety["function_names"] else 0)
    completeness = (10 if public["file_requirement_satisfied"] else 0) + (10 if case["function"] in safety["function_names"] else 0)
    edge_required = bool(re.search(r"(?i)raise|reject|invalid|empty|negative|edge|must not|without", case["requirement"]))
    edge_cases = 5
    edge_cases += 5 if safety["control_flow_nodes"] else (0 if edge_required else 5)
    edge_cases += 5 if safety["raise_nodes"] else (0 if re.search(r"(?i)raise|reject|invalid", case["requirement"]) else 5)
    safety_score = 15 if safety["safe"] else 0
    adherence = (10 if public["file_requirement_satisfied"] else 0) + (5 if len(files) == 1 else 2 if files else 0)
    scores = {
        "correctness": min(35, correctness),
        "completeness": min(20, completeness),
        "edge_cases": min(15, edge_cases),
        "safety": safety_score,
        "instruction_adherence": min(15, adherence),
    }
    total = sum(scores.values())
    critical = not safety["safe"]
    return {
        "evaluator": "Codex evidence-based blind rubric",
        "blind_to_model_review": True,
        "hidden_tests_seen": False,
        "threshold": 70,
        "critical_safety_violation": critical,
        "scores": scores,
        "total_score": total,
        "predicted_status": "PASS" if total >= 70 and not critical else "FAIL",
        "public_evidence": public,
        "notes": "Scored from the prompt, generated files, AST safety, interface adherence, and public-test evidence before hidden-test and reviewer verdict unblinding.",
    }


def extract_code(response: dict[str, Any], case: dict[str, Any]) -> tuple[str, dict[str, str]]:
    files = response.get("files") if isinstance(response.get("files"), dict) else {}
    files = {str(path): str(content or "") for path, content in files.items()}
    code = files.get(case["file"], "")
    if not code and len(files) == 1:
        code = next(iter(files.values()))
    if not code:
        code = str(response.get("code") or "")
    return code, files


def confusion_cell(actual: str, predicted: str) -> str:
    if actual == "FAIL" and predicted == "FAIL": return "TP"
    if actual == "FAIL" and predicted == "PASS": return "FN"
    if actual == "PASS" and predicted == "FAIL": return "FP"
    return "TN"


def minimal_plan(case: dict[str, Any], returned_files: dict[str, str]) -> dict[str, Any]:
    files_needed = [case["file"]] if case.get("file_requirement_explicit", True) else (sorted(returned_files) or [])
    return {
        "task_type": "direct coding evaluation",
        "summary": case["prompt"],
        "coder_prompt": case["prompt"],
        "files_needed": files_needed,
        "acceptance_criteria": [case["requirement"]],
        "output_mode": "ready_for_coder",
        "confidence": 1.0,
    }


def aggregate(state: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for case_id, result in state["case_results"].items():
        case = state["case_index"][case_id]
        for approach in APPROACHES:
            item = result.get("approaches", {}).get(approach)
            if item and item.get("ground_truth") in {"PASS", "FAIL"} and item.get("predicted_status") in {"PASS", "FAIL"}:
                rows.append({"case_id": case_id, "prompt_category": case["prompt_category"], "pair_id": case.get("pair_id"), "approach": approach, **item})

    def summarize(selected: list[dict[str, Any]]) -> dict[str, Any]:
        cells = Counter(item["confusion_cell"].lower() for item in selected)
        tp, fn, fp, tn = (cells[name] for name in ("tp", "fn", "fp", "tn"))
        total = tp + fn + fp + tn
        divide = lambda a, b: a / b if b else 0.0
        mcc_denominator = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
        observed = divide(tp + tn, total)
        expected_agreement = divide((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn), total * total)
        return {
            "cases": len(selected),
            "confusion_matrix": {"tp": tp, "fn": fn, "fp": fp, "tn": tn},
            "accuracy": observed,
            "precision_fail": divide(tp, tp + fp),
            "recall_fail": divide(tp, tp + fn),
            "specificity_pass": divide(tn, tn + fp),
            "f1_fail": divide(2 * tp, 2 * tp + fp + fn),
            "false_positive_rate": divide(fp, fp + tn),
            "false_negative_rate": divide(fn, fn + tp),
            "balanced_accuracy": (divide(tp, tp + fn) + divide(tn, tn + fp)) / 2,
            "matthews_correlation_coefficient": divide(tp * tn - fp * fn, mcc_denominator),
            "cohens_kappa": divide(observed - expected_agreement, 1 - expected_agreement),
            "task_success_rate": divide(sum(item["ground_truth"] == "PASS" for item in selected), len(selected)),
        }

    by_approach = {approach: summarize([row for row in rows if row["approach"] == approach]) for approach in APPROACHES}
    by_category_approach = {
        category: {approach: summarize([row for row in rows if row["prompt_category"] == category and row["approach"] == approach]) for approach in APPROACHES}
        for category in ("as_is", "naturalized_existing", "new_user_natural")
    }
    calls = state["calls"]
    latencies = [float(call["duration_ms"]) for call in calls if call.get("ok")]
    usage = [call.get("response", {}).get("usage", {}) for call in calls if call.get("ok")]
    def operational_group(selected_calls: list[dict[str, Any]]) -> dict[str, Any]:
        group_latencies = [float(call["duration_ms"]) for call in selected_calls if call.get("ok")]
        group_usage = [call.get("response", {}).get("usage", {}) for call in selected_calls if call.get("ok")]
        return {
            "calls": len(selected_calls),
            "successful_calls": sum(bool(call.get("ok")) for call in selected_calls),
            "latency_ms": {"mean": statistics.fmean(group_latencies) if group_latencies else 0, "p50": percentile(group_latencies, .5), "p95": percentile(group_latencies, .95), "p99": percentile(group_latencies, .99)},
            "usage": {name: sum(int(item.get(name) or 0) for item in group_usage) for name in ("input_tokens", "output_tokens", "total_tokens")},
        }
    return {
        "schema_version": "2.0",
        "created_at": now(),
        "evaluation_run_id": state["evaluation_run_id"],
        "completed_prompt_variants": sum(bool(item.get("complete")) for item in state["case_results"].values()),
        "expected_prompt_variants": len(state["case_index"]),
        "live_http_calls": len(calls),
        "successful_http_calls": sum(bool(call.get("ok")) for call in calls),
        "by_approach": by_approach,
        "by_prompt_category_and_approach": by_category_approach,
        "operational": {
            "latency_ms": {"mean": statistics.fmean(latencies) if latencies else 0, "p50": percentile(latencies, .5), "p95": percentile(latencies, .95), "p99": percentile(latencies, .99), "min": min(latencies, default=0), "max": max(latencies, default=0)},
            "usage": {name: sum(int(item.get(name) or 0) for item in usage) for name in ("input_tokens", "output_tokens", "total_tokens")},
            "estimated_cost_usd": sum(float(call.get("response", {}).get("estimated_cost_usd") or 0) for call in calls),
            "by_approach": {approach: operational_group([call for call in calls if call.get("approach") == approach]) for approach in (APPROACH_REVIEWER, APPROACH_PIPELINE)},
            "by_stage": {stage: operational_group([call for call in calls if call.get("stage") == stage]) for stage in ("code", "review", "run-agent")},
        },
    }


def percentile(values: list[float], quantile: float) -> float:
    if not values: return 0.0
    ordered = sorted(values); position = (len(ordered) - 1) * quantile; lower = math.floor(position); upper = math.ceil(position)
    return ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(ROOT / "evals" / "consolidated_cases.json"))
    parser.add_argument("--output", default=str(ROOT / "output" / "evals" / "consolidated" / "run-workspace"))
    parser.add_argument("--limit-cases", type=int, default=178)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Number of isolated remote model lanes to use (1-3).",
    )
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument(
        "--snapshot-only",
        action="store_true",
        help="Recompute metrics from the current checkpoint without making network calls.",
    )
    args = parser.parse_args()
    if not args.snapshot_only and os.getenv("BOB_ALLOW_LIVE_EVAL") != "1":
        raise SystemExit("Live evaluation disabled; set BOB_ALLOW_LIVE_EVAL=1.")

    source_dataset = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    dataset = source_dataset.get("live_three_approach_suite", source_dataset)
    selected_cases = dataset["cases"][:max(0, args.limit_cases)]
    output = Path(args.output)
    checkpoint = output / "master-evaluation.checkpoint.json"
    if checkpoint.exists() and not args.fresh:
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        # Refresh immutable case definitions so validated oracle fixes apply to
        # resumed runs without discarding already completed model calls.
        state["case_index"] = {case["id"]: case for case in dataset["cases"]}
    else:
        evaluation_run_id = f"three-track-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        state = {
            "schema_version": "2.0",
            "evaluation_run_id": evaluation_run_id,
            "created_at": now(),
            "status": "running",
            "dataset_version": dataset["dataset_version"],
            "rubric": dataset["independent_evaluation"],
            "runtime_health": {},
            "case_index": {case["id"]: case for case in dataset["cases"]},
            "case_results": {},
            "calls": [],
        }
    output.mkdir(parents=True, exist_ok=True)
    if args.snapshot_only:
        if not checkpoint.exists():
            raise SystemExit(f"Checkpoint does not exist: {checkpoint}")
        metrics = aggregate(state)
        state["metrics"] = metrics
        all_complete = (
            metrics["completed_prompt_variants"] == metrics["expected_prompt_variants"]
            and all(item.get("complete") for item in state["case_results"].values())
        )
        state["status"] = "complete" if all_complete else "partial_snapshot"
        state["snapshot_at"] = now()
        atomic_json(checkpoint, state)
        atomic_json(output / "master-evaluation.json", state)
        atomic_json(output / "metrics.json", metrics)
        print(json.dumps({
            "output": str(output),
            "status": state["status"],
            "cases_complete": metrics["completed_prompt_variants"],
            "calls": metrics["live_http_calls"],
        }, indent=2), flush=True)
        return 0

    # A frozen partial snapshot becomes an active resumable run again as soon
    # as live execution is explicitly requested.
    state["status"] = "running"
    state.pop("snapshot_at", None)

    concurrency = max(1, min(3, int(args.concurrency)))
    adapter = ColabAdapter()
    if not adapter.configured:
        raise SystemExit("BOB_COLAB_BASE_URL is not configured")
    # Refresh health on every launch: a resumable checkpoint may have been
    # created against the earlier single-lane notebook runtime.
    state["runtime_health"] = redact(adapter.health())
    if not state["runtime_health"].get("structured_logging"):
        raise SystemExit("Refusing evaluation because the runtime does not advertise structured_logging=true")
    atomic_json(checkpoint, state)

    runtime_lanes = int((state.get("runtime_health", {}).get("concurrency") or {}).get("model_lane_count") or 1)
    if concurrency > runtime_lanes:
        raise SystemExit(
            f"Runtime advertises {runtime_lanes} model lane(s), but --concurrency={concurrency}. "
            "Run the updated notebook and create a new URL first."
        )

    # Preserve the identity of calls made before the three-lane upgrade. They
    # all ran on the former single lane and remain valid resumable evidence.
    for call in state.get("calls", []):
        call.setdefault("model_lane", 0)
        call.setdefault("pipeline_id", f"{state['evaluation_run_id']}:{call.get('case_id', 'unknown')}:{'pipeline' if call.get('stage') == 'run-agent' else 'direct'}")
    state["execution"] = {
        "model_lane_count": concurrency,
        "scheduling": "one_sequential_worker_per_lane",
        "sticky_pipeline_ids": True,
        "checkpoint_writes": "locked_atomic_json",
    }

    state_lock = threading.RLock()
    print_lock = threading.RLock()

    def save() -> None:
        with state_lock:
            state["updated_at"] = now()
            atomic_json(checkpoint, state)

    def invoke(call_key: str, stage: str, case: dict[str, Any], approach: str, payload: dict[str, Any], function: Callable[[dict[str, Any]], dict[str, Any]], *, reuse_success: bool = True) -> dict[str, Any]:
        if reuse_success:
            with state_lock:
                for call in reversed(state["calls"]):
                    if call.get("call_key") == call_key and call.get("ok"):
                        return call["response"]
        started_at = now(); started = time.perf_counter()
        metadata = {key: payload.get(key) for key in ("evaluation_run_id", "test_id", "test_name", "prompt_category", "pair_id", "approach", "pipeline_id", "model_lane", "request_id", "trace_id", "run_id")}
        log_model("evaluation.call_started", stage=stage, **metadata)
        try:
            response, ok, error = function(payload), True, None
        except Exception as exc:
            response, ok, error = {}, False, f"{type(exc).__name__}: {exc}"
        duration = round((time.perf_counter() - started) * 1000, 2)
        with state_lock:
            call = redact({
                "call_number": len(state["calls"]) + 1,
                "call_key": call_key,
                "case_id": case["id"],
                "prompt_category": case["prompt_category"],
                "approach": approach,
                "pipeline_id": payload.get("pipeline_id"),
                "model_lane": payload.get("model_lane"),
                "stage": stage,
                "started_at": started_at,
                "duration_ms": duration,
                "ok": ok,
                "error": error,
                "request": payload,
                "response": response,
            })
            state["calls"].append(call)
            save()
        log_model("evaluation.call_completed", stage=stage, duration_ms=duration, outcome="success" if ok else "error", error=error, **metadata)
        with print_lock:
            print(f"[{call['call_number']:04d}] lane={payload.get('model_lane')} {case['id']:<38} {stage:<16} {'ok' if ok else 'ERROR'} {duration:.0f} ms", flush=True)
        if not ok:
            raise RuntimeError(error)
        return response

    def process_case(index: int, case: dict[str, Any], model_lane: int, lane_adapter: ColabAdapter) -> None:
        with state_lock:
            result = state["case_results"].setdefault(case["id"], {
                "case_id": case["id"],
                "test_name": case["test_name"],
                "prompt_category": case["prompt_category"],
                "pair_id": case.get("pair_id"),
                "approaches": {},
                "complete": False,
            })
            if result.get("complete"):
                with print_lock:
                    print(f"[{index:03d}/{len(selected_cases)}] lane={model_lane} resume skip {case['id']}", flush=True)
                return
            result["model_lane"] = model_lane

        common = {
            "evaluation_run_id": state["evaluation_run_id"],
            "test_id": case["id"],
            "test_name": case["test_name"],
            "prompt_category": case["prompt_category"],
            "pair_id": case.get("pair_id"),
            "model_lane": model_lane,
            "project": "bob_three_approach_evaluation",
            "user_prompt": case["prompt"],
            "files": {},
            "forced_files": {},
        }
        direct_run = f"eval-{case['id']}-direct"
        direct_pipeline_id = f"{state['evaluation_run_id']}:{case['id']}:direct"
        direct_payload = {
            **common,
            "approach": APPROACH_REVIEWER,
            "pipeline_id": direct_pipeline_id,
            "run_id": direct_run,
            "trace_id": direct_run,
            "request_id": f"req-{case['id']}-direct-code",
        }
        try:
            # A direct code/review pair owns a remote sticky reservation between
            # two HTTP calls. If the local worker was interrupted, reconstruct
            # that pair instead of reusing one half after the remote TTL/release.
            direct_response = invoke(f"{case['id']}:direct_code", "code", case, APPROACH_REVIEWER, direct_payload, lane_adapter.code, reuse_success=False)
            direct_code, direct_files = extract_code(direct_response, case)
            blind = independent_evaluation(direct_code, direct_files, case)
            direct_evidence = evaluate_code(direct_code, direct_files, case, include_hidden=True)
            plan = minimal_plan(case, direct_files)
            review_payload = {
                **common,
                "approach": APPROACH_REVIEWER,
                "pipeline_id": direct_pipeline_id,
                "run_id": direct_run,
                "trace_id": direct_run,
                "request_id": f"req-{case['id']}-direct-review",
                "selected_plan": plan,
                "plan": plan,
                "plan_id": f"direct-plan-{case['id']}",
                "code": direct_response.get("code", direct_code),
                "files": direct_files,
            }
            review_response = invoke(f"{case['id']}:direct_review", "review", case, APPROACH_REVIEWER, review_payload, lane_adapter.review, reuse_success=False)
            reviewer_status = str(review_response.get("final_status") or "FAIL").upper()
            reviewer_result = {
                "pipeline_id": direct_pipeline_id,
                "model_lane": model_lane,
                "coder_response": direct_response,
                "generated_code": direct_code,
                "generated_code_sha256": sha256_text(direct_code),
                "files": direct_files,
                "review_response": review_response,
                "ground_truth_evidence": direct_evidence,
                "ground_truth": direct_evidence["ground_truth"],
                "predicted_status": reviewer_status,
                "confusion_cell": confusion_cell(direct_evidence["ground_truth"], reviewer_status),
            }
            codex_status = blind["predicted_status"]
            codex_result = {
                "pipeline_id": direct_pipeline_id,
                "model_lane": model_lane,
                "shared_coder_call_key": f"{case['id']}:direct_code",
                "generated_code": direct_code,
                "generated_code_sha256": sha256_text(direct_code),
                "files": direct_files,
                "independent_evaluation": blind,
                "ground_truth_evidence": direct_evidence,
                "ground_truth": direct_evidence["ground_truth"],
                "predicted_status": codex_status,
                "confusion_cell": confusion_cell(direct_evidence["ground_truth"], codex_status),
            }
            with state_lock:
                result["approaches"][APPROACH_REVIEWER] = reviewer_result
                result["approaches"][APPROACH_CODEX] = codex_result
                save()
        except Exception as exc:
            with state_lock:
                result["approaches"][APPROACH_REVIEWER] = {"status": "call_error", "error": str(exc), "pipeline_id": direct_pipeline_id, "model_lane": model_lane}
                result["approaches"][APPROACH_CODEX] = {"status": "call_error", "error": str(exc), "pipeline_id": direct_pipeline_id, "model_lane": model_lane}
                save()

        pipeline_run = f"eval-{case['id']}-pipeline"
        pipeline_id = f"{state['evaluation_run_id']}:{case['id']}:pipeline"
        pipeline_payload = {
            **common,
            "approach": APPROACH_PIPELINE,
            "pipeline_id": pipeline_id,
            "run_id": pipeline_run,
            "trace_id": pipeline_run,
            "request_id": f"req-{case['id']}-pipeline",
            "max_iterations": 1,
        }
        try:
            pipeline_response = invoke(f"{case['id']}:pipeline", "run-agent", case, APPROACH_PIPELINE, pipeline_payload, lane_adapter.run_agent)
            pipeline_code, pipeline_files = extract_code(pipeline_response, case)
            pipeline_evidence = evaluate_code(pipeline_code, pipeline_files, case, include_hidden=True)
            pipeline_status = str(pipeline_response.get("final_status") or "FAIL").upper()
            pipeline_result = {
                "pipeline_id": pipeline_id,
                "model_lane": model_lane,
                "pipeline_response": pipeline_response,
                "plan": pipeline_response.get("plan"),
                "generated_code": pipeline_code,
                "generated_code_sha256": sha256_text(pipeline_code),
                "files": pipeline_files,
                "review": pipeline_response.get("review"),
                "ground_truth_evidence": pipeline_evidence,
                "ground_truth": pipeline_evidence["ground_truth"],
                "predicted_status": pipeline_status,
                "confusion_cell": confusion_cell(pipeline_evidence["ground_truth"], pipeline_status),
            }
            with state_lock:
                result["approaches"][APPROACH_PIPELINE] = pipeline_result
        except Exception as exc:
            with state_lock:
                result["approaches"][APPROACH_PIPELINE] = {"status": "call_error", "error": str(exc), "pipeline_id": pipeline_id, "model_lane": model_lane}

        with state_lock:
            result["complete"] = all(
                result.get("approaches", {}).get(approach, {}).get("ground_truth") in {"PASS", "FAIL"}
                and result.get("approaches", {}).get(approach, {}).get("predicted_status") in {"PASS", "FAIL"}
                for approach in APPROACHES
            )
            if result["complete"]:
                result["completed_at"] = now()
            save()
            complete = result["complete"]
        with print_lock:
            print(f"[{index:03d}/{len(selected_cases)}] lane={model_lane} {'complete' if complete else 'incomplete'} {case['id']}", flush=True)

    indexed_cases = list(enumerate(selected_cases, 1))

    def process_lane(model_lane: int) -> None:
        lane_adapter = ColabAdapter()
        for index, case in indexed_cases[model_lane::concurrency]:
            process_case(index, case, model_lane, lane_adapter)

    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="bob-model-lane") as executor:
        futures = [executor.submit(process_lane, lane) for lane in range(concurrency)]
        for future in futures:
            future.result()

    metrics = aggregate(state)
    all_complete = len(selected_cases) == len(state["case_index"]) and all(state["case_results"].get(case["id"], {}).get("complete") for case in selected_cases)
    if all_complete:
        state["status"] = "complete"; state["completed_at"] = now()
    state["metrics"] = metrics; save()
    atomic_json(output / "master-evaluation.json", state)
    atomic_json(output / "metrics.json", metrics)
    print(json.dumps({"output": str(output), "status": state["status"], "cases_complete": metrics["completed_prompt_variants"], "calls": metrics["live_http_calls"], "by_approach": metrics["by_approach"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
