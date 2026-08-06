from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bob_core.colab_adapter import ColabAdapter

if os.getenv("BOB_ALLOW_LIVE_EVAL") != "1":
    raise SystemExit("Live evaluation is disabled. Set BOB_ALLOW_LIVE_EVAL=1 explicitly.")
dataset = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
adapter = ColabAdapter()
if not adapter.configured:
    raise SystemExit("A Colab endpoint must be configured before live evaluation.")
results = []
for case in dataset["cases"]:
    try:
        plan = adapter.plan({"run_id": f"eval-{case['id']}", "project": "evaluation", "user_prompt": case["prompt"], "files": {}, "forced_files": {}})
        results.append({"id": case["id"], "ok": bool(plan.get("summary")), "summary": plan.get("summary"), "confidence": plan.get("confidence")})
    except Exception as exc:
        results.append({"id": case["id"], "ok": False, "error": str(exc)})
output = ROOT / "output" / "evals"; output.mkdir(parents=True, exist_ok=True)
report = {"dataset_version": dataset["dataset_version"], "created_at": datetime.now(timezone.utc).isoformat(), "results": results}
path = output / "live-report.json"; path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(path)
