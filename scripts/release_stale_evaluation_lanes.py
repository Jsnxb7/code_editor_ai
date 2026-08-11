"""Close known interrupted direct-code reservations without touching evaluation state."""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from verify_three_lane_runtime_isolation import request_json

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_RUN_ID = "three-track-20260810T133608Z-3bc621ae"
CANDIDATES = {
    1: "legacy_033__as_is",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("BOB_COLAB_BASE_URL", ""))
    parser.add_argument("--token", default=os.environ.get("BOB_COLAB_TOKEN", ""))
    parser.add_argument("--output", default=str(ROOT / "output" / "evals" / "three-approach-evaluation-20260810" / "stale-lane-release.json"))
    args = parser.parse_args()
    if not args.base_url or not args.token:
        raise SystemExit("BOB_COLAB_BASE_URL and BOB_COLAB_TOKEN are required")

    def release(item: tuple[int, str]) -> dict[str, Any]:
        lane, case_id = item
        pipeline_id = f"{EVALUATION_RUN_ID}:{case_id}:direct"
        function_name = f"release_stale_lane_{lane}"
        file_name = f"release_lane_{lane}.py"
        prompt = f"Create {file_name} with {function_name}() returning {lane}."
        plan = {
            "task_type": "stale lane cleanup",
            "summary": prompt,
            "coder_prompt": prompt,
            "files_needed": [file_name],
            "acceptance_criteria": [prompt],
            "output_mode": "ready_for_coder",
            "confidence": 1.0,
        }
        common = {
            "evaluation_run_id": "stale-lane-cleanup",
            "test_id": f"cleanup-lane-{lane}",
            "test_name": f"Cleanup lane {lane}",
            "prompt_category": "runtime_cleanup",
            "approach": "stale_lane_release",
            "pipeline_id": pipeline_id,
            "model_lane": lane,
            "run_id": f"cleanup-lane-{lane}",
            "trace_id": f"cleanup-lane-{lane}",
            "project": "bob_lane_cleanup",
            "user_prompt": prompt,
            "plan_id": f"cleanup-plan-{lane}",
            "plan": plan,
            "selected_plan": plan,
            "files": {},
            "forced_files": {},
        }
        started = time.perf_counter()
        code_status, code_body = request_json(args.base_url, args.token, "/code", {**common, "request_id": f"cleanup-code-{lane}"})
        record: dict[str, Any] = {
            "lane": lane,
            "case_id": case_id,
            "pipeline_id": pipeline_id,
            "code_http_status": code_status,
            "code_duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        if code_status != 200:
            record["code_error"] = code_body.get("error")
            return record
        started = time.perf_counter()
        review_status, review_body = request_json(args.base_url, args.token, "/review", {
            **common,
            "request_id": f"cleanup-review-{lane}",
            "code": code_body.get("code") or "",
            "files": code_body.get("files") or {},
        })
        record.update({
            "review_http_status": review_status,
            "review_duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "response_pipeline_id": review_body.get("pipeline_id"),
            "response_model_lane": review_body.get("model_lane"),
            "released": review_status == 200,
        })
        if review_status != 200:
            record["review_error"] = review_body.get("error")
        return record

    with ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(release, CANDIDATES.items()))
    health_status, health = request_json(args.base_url, args.token, "/health")
    active = (health.get("concurrency") or {}).get("active_pipeline_count")
    report = {
        "schema_version": "1.0",
        "records": records,
        "health_http_status": health_status,
        "active_pipeline_count_after": active,
        "passed": health_status == 200 and active == 0,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
