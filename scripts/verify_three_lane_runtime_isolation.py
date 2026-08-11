"""Live isolation probe for the notebook's three sticky model lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "evals" / "three-approach-evaluation-20260810" / "lane-isolation-verification.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_json(base_url: str, token: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json", "ngrok-skip-browser-warning": "true"}
    data = None
    method = "GET"
    if payload is not None:
        method = "POST"
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"raw": raw[:2000]}
        return int(exc.code), body


def error_message(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error or body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("BOB_COLAB_BASE_URL", ""))
    parser.add_argument("--token", default=os.environ.get("BOB_COLAB_TOKEN", ""))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    if not args.base_url or not args.token:
        raise SystemExit("BOB_COLAB_BASE_URL and BOB_COLAB_TOKEN are required")

    verification_id = f"lane-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    health_status, health_before = request_json(args.base_url, args.token, "/health")
    errors: list[str] = []
    concurrency = health_before.get("concurrency") or {}
    if health_status != 200 or health_before.get("ok") is not True:
        errors.append(f"health check failed: HTTP {health_status}")
    if concurrency.get("model_lane_count") != 3 or concurrency.get("loaded_model_lanes") != [0, 1, 2]:
        errors.append(f"runtime lanes are not ready: {concurrency}")
    if concurrency.get("active_pipeline_count") != 0:
        errors.append(f"runtime was not idle before probe: {concurrency.get('active_pipeline_count')}")

    probes = []
    for lane in range(3):
        sentinel = f"LANE_{lane}_ONLY_{uuid.uuid4().hex[:10].upper()}"
        function_name = f"lane_{lane}_isolation_probe"
        file_name = f"lane_{lane}_probe.py"
        pipeline_id = f"{verification_id}:lane-{lane}"
        run_id = f"{verification_id}-run-{lane}"
        prompt = (
            f"Create exactly one Python file named {file_name}. Define {function_name}() with no arguments. "
            f"It must return the exact string {sentinel!r}. Do not mention or create any other lane probe."
        )
        plan = {
            "task_type": "lane isolation verification",
            "summary": prompt,
            "coder_prompt": prompt,
            "files_needed": [file_name],
            "acceptance_criteria": [f"{function_name} returns {sentinel}"],
            "output_mode": "ready_for_coder",
            "confidence": 1.0,
        }
        probes.append({
            "lane": lane,
            "sentinel": sentinel,
            "function_name": function_name,
            "file_name": file_name,
            "pipeline_id": pipeline_id,
            "run_id": run_id,
            "prompt": prompt,
            "plan": plan,
        })

    def code_probe(probe: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "evaluation_run_id": verification_id,
            "test_id": f"lane-isolation-{probe['lane']}",
            "test_name": f"Lane {probe['lane']} isolation probe",
            "prompt_category": "runtime_isolation_probe",
            "approach": "lane_isolation_verification",
            "pipeline_id": probe["pipeline_id"],
            "model_lane": probe["lane"],
            "run_id": probe["run_id"],
            "trace_id": probe["run_id"],
            "request_id": f"{verification_id}-code-{probe['lane']}",
            "project": "bob_lane_isolation_probe",
            "user_prompt": probe["prompt"],
            "plan_id": f"probe-plan-{probe['lane']}",
            "plan": probe["plan"],
            "selected_plan": probe["plan"],
            "files": {},
            "forced_files": {},
        }
        started = time.perf_counter()
        status, body = request_json(args.base_url, args.token, "/code", payload)
        return {"status": status, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "body": body, "payload": payload}

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="lane-isolation-code") as executor:
        code_results = list(executor.map(code_probe, probes))

    all_sentinels = [probe["sentinel"] for probe in probes]
    all_functions = [probe["function_name"] for probe in probes]
    records = []
    for probe, result in zip(probes, code_results):
        body = result["body"]
        code = str(body.get("code") or "")
        files = body.get("files") if isinstance(body.get("files"), dict) else {}
        combined = code + "\n" + "\n".join(str(value) for value in files.values())
        foreign_sentinels = [value for value in all_sentinels if value != probe["sentinel"] and value in combined]
        foreign_functions = [value for value in all_functions if value != probe["function_name"] and value in combined]
        identity_ok = body.get("pipeline_id") == probe["pipeline_id"] and body.get("model_lane") == probe["lane"]
        content_ok = probe["sentinel"] in combined and probe["function_name"] in combined and not foreign_sentinels and not foreign_functions
        file_ok = probe["file_name"] in files
        if result["status"] != 200:
            errors.append(f"lane {probe['lane']} code returned HTTP {result['status']}: {error_message(body)}")
        if not identity_ok:
            errors.append(f"lane {probe['lane']} response identity mismatch")
        if not content_ok:
            errors.append(f"lane {probe['lane']} generated content failed sentinel isolation")
        if not file_ok:
            errors.append(f"lane {probe['lane']} expected file missing")
        records.append({
            "lane": probe["lane"],
            "pipeline_id": probe["pipeline_id"],
            "test_id": result["payload"]["test_id"],
            "code_http_status": result["status"],
            "code_duration_ms": result["duration_ms"],
            "response_pipeline_id": body.get("pipeline_id"),
            "response_model_lane": body.get("model_lane"),
            "expected_file_present": file_ok,
            "own_sentinel_present": probe["sentinel"] in combined,
            "own_function_present": probe["function_name"] in combined,
            "foreign_sentinels": foreign_sentinels,
            "foreign_functions": foreign_functions,
            "generated_code_sha256": sha256(code),
            "generated_files": sorted(files),
        })

    rejection_records = []
    for probe, result in zip(probes, code_results):
        body = result["body"]
        wrong_lane_payload = {
            **result["payload"],
            "request_id": f"{verification_id}-wrong-lane-{probe['lane']}",
            "model_lane": (probe["lane"] + 1) % 3,
            "code": body.get("code") or "",
            "files": body.get("files") or {},
        }
        status, rejected = request_json(args.base_url, args.token, "/review", wrong_lane_payload)
        message = error_message(rejected)
        accepted_rejection = status >= 400 and "lane" in message.lower() and "forbidden" in message.lower()
        if not accepted_rejection:
            errors.append(f"pipeline {probe['pipeline_id']} lane-switch was not rejected correctly: HTTP {status} {message}")
        rejection_records.append({"kind": "lane_switch", "pipeline_id": probe["pipeline_id"], "requested_lane": wrong_lane_payload["model_lane"], "http_status": status, "message": message, "rejected": accepted_rejection})

        foreign_payload = {
            **result["payload"],
            "pipeline_id": f"{verification_id}:intruder-{probe['lane']}",
            "run_id": f"{verification_id}-intruder-run-{probe['lane']}",
            "trace_id": f"{verification_id}-intruder-run-{probe['lane']}",
            "request_id": f"{verification_id}-intruder-{probe['lane']}",
        }
        status, rejected = request_json(args.base_url, args.token, "/code", foreign_payload)
        message = error_message(rejected)
        accepted_rejection = status >= 400 and "busy" in message.lower()
        if not accepted_rejection:
            errors.append(f"lane {probe['lane']} accepted an overlapping pipeline: HTTP {status} {message}")
        rejection_records.append({"kind": "same_lane_overlap", "pipeline_id": foreign_payload["pipeline_id"], "requested_lane": probe["lane"], "http_status": status, "message": message, "rejected": accepted_rejection})

    def review_probe(pair: tuple[dict[str, Any], dict[str, Any]]) -> dict[str, Any]:
        probe, code_result = pair
        code_body = code_result["body"]
        payload = {
            **code_result["payload"],
            "request_id": f"{verification_id}-review-{probe['lane']}",
            "code": code_body.get("code") or "",
            "files": code_body.get("files") or {},
        }
        started = time.perf_counter()
        status, body = request_json(args.base_url, args.token, "/review", payload)
        return {"status": status, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "body": body}

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="lane-isolation-review") as executor:
        review_results = list(executor.map(review_probe, zip(probes, code_results)))

    for probe, record, result in zip(probes, records, review_results):
        body = result["body"]
        identity_ok = body.get("pipeline_id") == probe["pipeline_id"] and body.get("model_lane") == probe["lane"]
        if result["status"] != 200:
            errors.append(f"lane {probe['lane']} review returned HTTP {result['status']}: {error_message(body)}")
        if not identity_ok:
            errors.append(f"lane {probe['lane']} review identity mismatch")
        record.update({
            "review_http_status": result["status"],
            "review_duration_ms": result["duration_ms"],
            "review_pipeline_id": body.get("pipeline_id"),
            "review_model_lane": body.get("model_lane"),
            "review_final_status": body.get("final_status"),
            "review_sha256": sha256(str(body.get("review") or "")),
        })

    health_after_status, health_after = request_json(args.base_url, args.token, "/health")
    active_after = (health_after.get("concurrency") or {}).get("active_pipeline_count")
    if health_after_status != 200 or active_after != 0:
        errors.append(f"pipelines were not fully released after probe: HTTP {health_after_status}, active={active_after}")

    report = {
        "schema_version": "1.0",
        "verification_id": verification_id,
        "created_at": now(),
        "base_host": args.base_url.split("//", 1)[-1].split("/", 1)[0],
        "runtime_contract": health_before.get("contract_version"),
        "model": health_before.get("model"),
        "health_before": health_before,
        "health_after": health_after,
        "probe_count": len(records),
        "records": records,
        "rejection_checks": rejection_records,
        "passed": not errors,
        "errors": errors,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({"output": str(output), "verification_id": verification_id, "passed": report["passed"], "errors": errors, "records": records, "rejection_checks": rejection_records}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
