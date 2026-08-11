"""Consolidate Bob evaluation datasets and accepted evidence into canonical JSON files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
OUTPUT = ROOT / "output" / "evals"
LEGACY_CURRENT = OUTPUT / "three-approach-evaluation-20260810"
CONSOLIDATED = OUTPUT / "consolidated"
PDF_OUTPUT = ROOT / "output" / "pdf" / "consolidated-evaluation-charts.pdf"
BACKUP = ROOT / "output" / "archive" / "evaluation-history-preconsolidation-20260810.zip"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def source_record(path: Path, role: str) -> dict[str, Any]:
    return {
        "path": relative(path),
        "role": role,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load_documents(specification: dict[str, dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    documents: dict[str, Any] = {}
    manifest: list[dict[str, Any]] = []
    for key, item in specification.items():
        path = ROOT / item["path"]
        if not path.exists():
            raise FileNotFoundError(f"Required consolidation source is missing: {path}")
        documents[key] = read_json(path)
        manifest.append(source_record(path, item["role"]))
    return documents, manifest


DATASET_SOURCES = {
    "offline_suite": {"path": "evals/cases.json", "role": "offline deterministic cases"},
    "historical_endpoint_suite": {"path": "evals/model_performance_cases.json", "role": "initial endpoint cases"},
    "reviewer_challenge_suite": {"path": "evals/reviewer_challenge_cases.json", "role": "reviewer challenge cases"},
    "reviewer_fp_probe_suite": {"path": "evals/reviewer_fp_probe_cases.json", "role": "reviewer false-positive probes"},
    "descriptive_sourced_suite": {"path": "evals/descriptive_sourced_cases.json", "role": "sourced descriptive cases"},
    "live_three_approach_suite": {"path": "evals/three_approach_cases.json", "role": "current live prompt variants"},
}


EVIDENCE_SOURCES = {
    "baseline_metrics": {"path": "output/evals/model-performance-20260806/metrics.json", "role": "initial metrics"},
    "baseline_raw": {"path": "output/evals/model-performance-20260806/raw-evidence.json", "role": "initial raw calls"},
    "baseline_qualitative": {"path": "output/evals/model-performance-20260806/qualitative-evaluation.json", "role": "initial qualitative evaluation"},
    "baseline_verification": {"path": "output/evals/model-performance-20260806/verification.json", "role": "initial verification"},
    "challenge_metrics": {"path": "output/evals/reviewer-challenge-20260806/metrics.json", "role": "challenge metrics and results"},
    "challenge_raw": {"path": "output/evals/reviewer-challenge-20260806/raw-evidence.json", "role": "challenge raw calls"},
    "fp_probe_metrics": {"path": "output/evals/reviewer-fp-probes-20260806/metrics.json", "role": "false-positive probe metrics"},
    "fp_probe_raw": {"path": "output/evals/reviewer-fp-probes-20260806/raw-evidence.json", "role": "false-positive probe raw calls"},
    "expanded_metrics": {"path": "output/evals/expanded-model-performance-20260806/expanded-metrics.json", "role": "first consolidated metrics"},
    "expanded_assistant_evaluation": {"path": "output/evals/expanded-model-performance-20260806/assistant-evaluation.json", "role": "assistant human-style evaluation"},
    "sourced_metrics": {"path": "output/evals/descriptive-sourced-live-20260807/metrics.json", "role": "sourced case metrics and results"},
    "sourced_raw": {"path": "output/evals/descriptive-sourced-live-20260807/raw-evidence.json", "role": "sourced raw calls"},
    "compiled_metrics": {"path": "output/evals/compiled-model-performance-20260807/compiled-metrics.json", "role": "historical compiled metrics"},
    "compiled_component_attribution": {"path": "output/evals/compiled-model-performance-20260807/component-failure-attribution.json", "role": "historical component attribution"},
    "compiled_failure_modes": {"path": "output/evals/compiled-model-performance-20260807/failure-mode-classification.json", "role": "historical failure modes"},
    "compiled_assistant_evaluation": {"path": "output/evals/compiled-model-performance-20260807/independent-assistant-evaluation.json", "role": "historical independent evaluation"},
    "compiled_verification": {"path": "output/evals/compiled-model-performance-20260807/verification.json", "role": "historical compiled verification"},
    "current_master": {"path": "output/evals/three-approach-evaluation-20260810/master-evaluation.json", "role": "final three-approach master evidence"},
    "current_metrics": {"path": "output/evals/three-approach-evaluation-20260810/metrics.json", "role": "final metrics"},
    "current_component_attribution": {"path": "output/evals/three-approach-evaluation-20260810/component-failure-attribution.json", "role": "final FP/FN attribution"},
    "current_paired_analysis": {"path": "output/evals/three-approach-evaluation-20260810/paired-prompt-analysis.json", "role": "paired prompt analysis"},
    "current_dataset_verification": {"path": "output/evals/three-approach-evaluation-20260810/dataset-verification.json", "role": "dataset verification"},
    "current_legacy_verification": {"path": "output/evals/three-approach-evaluation-20260810/legacy-normalization-verification.json", "role": "legacy oracle verification"},
    "current_natural_verification": {"path": "output/evals/three-approach-evaluation-20260810/new-natural-reference-verification.json", "role": "new natural reference verification"},
    "current_lane_verification": {"path": "output/evals/three-approach-evaluation-20260810/lane-isolation-verification.json", "role": "three-lane isolation verification"},
    "current_acceptance": {"path": "output/evals/three-approach-evaluation-20260810/acceptance-verification.json", "role": "final acceptance verification"},
    "current_chart_manifest": {"path": "output/evals/three-approach-evaluation-20260810/chart-manifest.json", "role": "final chart manifest"},
    "current_runtime_log_index": {"path": "output/evals/three-approach-evaluation-20260810/runtime-log-index.json", "role": "runtime log metadata only"},
}


TEXT_SOURCES = {
    "descriptive_sourced_documentation": {"path": "evals/DESCRIPTIVE_SOURCED_CASES.md", "role": "sourced case documentation"},
    "baseline_report": {"path": "output/evals/model-performance-20260806/REPORT.md", "role": "initial evaluation report"},
    "expanded_report": {"path": "output/evals/expanded-model-performance-20260806/EXPANDED_REPORT.md", "role": "expanded evaluation report"},
    "compiled_report": {"path": "output/evals/compiled-model-performance-20260807/COMPILED_REPORT.md", "role": "compiled evaluation report"},
    "compiled_component_report": {"path": "output/evals/compiled-model-performance-20260807/COMPONENT_FAILURE_ATTRIBUTION.md", "role": "historical component attribution report"},
    "compiled_failure_report": {"path": "output/evals/compiled-model-performance-20260807/FAILURE_MODE_REPORT.md", "role": "historical failure-mode report"},
    "human_evaluation_template": {"path": "output/evals/compiled-model-performance-20260807/human-evaluation-template.csv", "role": "human evaluation template"},
    "current_summary": {"path": "output/evals/three-approach-evaluation-20260810/summary.md", "role": "final evaluation summary"},
}


def load_text_documents(specification: dict[str, dict[str, str]]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    documents: dict[str, str] = {}
    manifest: list[dict[str, Any]] = []
    for key, item in specification.items():
        path = ROOT / item["path"]
        if not path.exists():
            raise FileNotFoundError(f"Required consolidation source is missing: {path}")
        documents[key] = path.read_text(encoding="utf-8")
        manifest.append(source_record(path, item["role"]))
    return documents, manifest


def consolidated_matrix(metrics: dict[str, Any]) -> dict[str, int]:
    return {
        cell: sum(metrics["by_approach"][approach]["confusion_matrix"][cell] for approach in metrics["by_approach"])
        for cell in ("tp", "fn", "fp", "tn")
    }


def build_dataset(documents: dict[str, Any], manifest: list[dict[str, Any]]) -> dict[str, Any]:
    live = documents["live_three_approach_suite"]
    offline = documents["offline_suite"]
    endpoint = documents["historical_endpoint_suite"]
    categories = Counter(case["prompt_category"] for case in live["cases"])
    source_groups = Counter(
        case["source_group"] for case in live["cases"] if case["prompt_category"] == "as_is"
    )
    return {
        "schema_version": "1.0",
        "dataset_version": "bob-consolidated-evaluations-20260810",
        "created_at": now(),
        "inventory": {
            "offline_cases": len(offline["cases"]),
            "historical_code_cases": len(endpoint.get("code_tasks", [])),
            "historical_replan_cases": len(endpoint.get("replan_cases", [])),
            "historical_review_cases": len(endpoint.get("review_cases", [])),
            "source_requirements": len({case.get("source_case_id") for case in live["cases"] if case.get("source_case_id")}),
            "live_prompt_variants": len(live["cases"]),
            "prompt_categories": dict(categories),
            "source_groups": dict(source_groups),
            "paired_requirements": len({case.get("pair_id") for case in live["cases"] if case.get("pair_id")}),
        },
        "offline_suite": offline,
        "historical_endpoint_suite": endpoint,
        "reviewer_challenge_suite": documents["reviewer_challenge_suite"],
        "reviewer_fp_probe_suite": documents["reviewer_fp_probe_suite"],
        "descriptive_sourced_suite": documents["descriptive_sourced_suite"],
        "live_three_approach_suite": live,
        "source_manifest": manifest,
    }


def build_evaluation(documents: dict[str, Any], text_documents: dict[str, str]) -> dict[str, Any]:
    current_master = documents["current_master"]
    current_metrics = documents["current_metrics"]
    call_keys = [call.get("call_key") for call in current_master["calls"] if call.get("ok") and call.get("call_key")]
    unique_call_keys = len(set(call_keys))
    historical_calls = {
        "initial_model_performance": len(documents["baseline_raw"].get("calls", [])),
        "reviewer_challenge": len(documents["challenge_raw"].get("calls", [])),
        "reviewer_fp_probe": len(documents["fp_probe_raw"].get("calls", [])),
        "descriptive_sourced": len(documents["sourced_raw"].get("calls", [])),
        "three_approach": len(current_master.get("calls", [])),
    }
    return {
        "schema_version": "1.0",
        "created_at": now(),
        "scope": "Accepted model evaluations from the first recorded live run through 2026-08-10. Operational logs remain separate JSONL files.",
        "inventory": {
            "accepted_live_runs": 5,
            "recorded_live_call_attempts": sum(historical_calls.values()),
            "live_calls_by_run": historical_calls,
            "latest_prompt_variants": len(current_master["case_results"]),
            "latest_scored_approach_results": sum(len(result.get("approaches", {})) for result in current_master["case_results"].values()),
            "latest_unique_successful_call_keys": unique_call_keys,
            "latest_duplicate_successful_attempts": len(call_keys) - unique_call_keys,
        },
        "runs": {
            "initial_model_performance_20260806": {
                "metrics": documents["baseline_metrics"],
                "raw_evidence": documents["baseline_raw"],
                "qualitative_evaluation": documents["baseline_qualitative"],
                "verification": documents["baseline_verification"],
            },
            "reviewer_challenge_20260806": {
                "metrics": documents["challenge_metrics"],
                "raw_evidence": documents["challenge_raw"],
            },
            "reviewer_fp_probes_20260806": {
                "metrics": documents["fp_probe_metrics"],
                "raw_evidence": documents["fp_probe_raw"],
            },
            "descriptive_sourced_20260807": {
                "metrics": documents["sourced_metrics"],
                "raw_evidence": documents["sourced_raw"],
            },
            "three_approach_20260810": {
                "master": current_master,
                "metrics": current_metrics,
                "component_failure_attribution": documents["current_component_attribution"],
                "paired_prompt_analysis": documents["current_paired_analysis"],
            },
        },
        "historical_aggregates": {
            "expanded_20260806": {
                "metrics": documents["expanded_metrics"],
                "assistant_evaluation": documents["expanded_assistant_evaluation"],
            },
            "compiled_20260807": {
                "metrics": documents["compiled_metrics"],
                "component_failure_attribution": documents["compiled_component_attribution"],
                "failure_mode_classification": documents["compiled_failure_modes"],
                "assistant_evaluation": documents["compiled_assistant_evaluation"],
                "verification": documents["compiled_verification"],
            },
        },
        "historical_text_artifacts": text_documents,
        "latest_analysis": {
            "metrics": current_metrics,
            "consolidated_confusion_matrix": consolidated_matrix(current_metrics),
            "component_failure_attribution": documents["current_component_attribution"],
            "paired_prompt_analysis": documents["current_paired_analysis"],
            "chart_manifest": documents["current_chart_manifest"],
        },
        "validation_evidence": {
            "dataset": documents["current_dataset_verification"],
            "legacy_normalization": documents["current_legacy_verification"],
            "new_natural_references": documents["current_natural_verification"],
            "lane_isolation": documents["current_lane_verification"],
            "acceptance": documents["current_acceptance"],
        },
        "separate_logs": documents["current_runtime_log_index"],
        "artifact_references": {
            "charts_pdf": "output/pdf/consolidated-evaluation-charts.pdf",
            "runtime_logs": [
                "data/runtime/events.jsonl",
                "data/runtime/model-events.jsonl",
                "data/runtime/ngrok-events.jsonl",
            ],
        },
    }


def exclusion_reason(path: Path, imported: set[str]) -> str:
    rel = relative(path)
    if rel in imported:
        return "imported"
    lowered = rel.lower()
    if "interim" in lowered:
        return "superseded interim snapshot"
    if "discarded" in lowered:
        return "rejected post-checkpoint state retained in backup only"
    if "smoke" in lowered:
        return "superseded smoke run"
    if path.name == "master-evaluation.checkpoint.json":
        return "byte-identical final checkpoint duplicate"
    if "stale-lane" in lowered:
        return "temporary lane cleanup receipt"
    if path.suffix.lower() in {".csv", ".md", ".svg", ".pdf"}:
        return "derived presentation artifact"
    if path.suffix.lower() == ".log":
        return "operational log kept outside consolidated JSON or removed when empty"
    return "derived or superseded artifact"


def build_verification(
    dataset_path: Path,
    evaluation_path: Path,
    source_manifest: list[dict[str, Any]],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    imported = {item["path"] for item in source_manifest}
    excluded = []
    for path in sorted((OUTPUT).rglob("*")):
        if not path.is_file() or CONSOLIDATED in path.parents:
            continue
        excluded.append({**source_record(path, exclusion_reason(path, imported)), "imported": relative(path) in imported})
    errors: list[str] = []
    inventory = evaluation["inventory"]
    expected = {
        "accepted_live_runs": 5,
        "recorded_live_call_attempts": 688,
        "latest_prompt_variants": 178,
        "latest_scored_approach_results": 534,
        "latest_unique_successful_call_keys": 534,
        "latest_duplicate_successful_attempts": 6,
    }
    for key, value in expected.items():
        if inventory.get(key) != value:
            errors.append(f"{key}: expected {value}, found {inventory.get(key)}")
    matrix = evaluation["latest_analysis"]["consolidated_confusion_matrix"]
    if matrix != {"tp": 62, "fn": 164, "fp": 10, "tn": 298}:
        errors.append(f"consolidated matrix mismatch: {matrix}")
    encoded = evaluation_path.read_text(encoding="utf-8")
    secret_patterns = {
        "authorization_bearer": r"(?i)authorization\s*[\"':=]+\s*bearer\s+(?!\[REDACTED\])",
        "github_token": r"github_pat_[A-Za-z0-9_]+",
        "huggingface_token": r"\bhf_[A-Za-z0-9]{8,}",
    }
    secret_scan = {name: bool(re.search(pattern, encoded)) for name, pattern in secret_patterns.items()}
    if any(secret_scan.values()):
        errors.append(f"potential secret patterns found: {[name for name, found in secret_scan.items() if found]}")
    backup_record = source_record(BACKUP, "recoverable pre-consolidation archive") if BACKUP.exists() else None
    if not backup_record:
        errors.append("pre-consolidation backup is missing")
    return {
        "schema_version": "1.0",
        "created_at": now(),
        "status": "passed" if not errors else "failed",
        "backup": backup_record,
        "source_manifest": source_manifest,
        "excluded_and_cleanup_candidates": excluded,
        "checks": {
            "expected_inventory": expected,
            "actual_inventory": inventory,
            "consolidated_confusion_matrix": matrix,
            "secret_scan": secret_scan,
            "source_files_imported": len(source_manifest),
            "excluded_files_recorded": len(excluded),
        },
        "canonical_artifacts": {
            "dataset": source_record(dataset_path, "canonical consolidated dataset"),
            "evaluation": source_record(evaluation_path, "canonical consolidated evaluation evidence"),
            "charts_pdf": source_record(PDF_OUTPUT, "canonical consolidated chart book"),
            "logs": [
                "data/runtime/events.jsonl",
                "data/runtime/model-events.jsonl",
                "data/runtime/ngrok-events.jsonl",
            ],
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(CONSOLIDATED))
    args = parser.parse_args()
    output = Path(args.output)
    if output.resolve() != CONSOLIDATED.resolve():
        raise SystemExit("Custom output is not supported for the canonical consolidation")
    missing_sources = [item["path"] for item in {**DATASET_SOURCES, **EVIDENCE_SOURCES, **TEXT_SOURCES}.values() if not (ROOT / item["path"]).exists()]
    canonical_files = [
        EVALS / "consolidated_cases.json",
        CONSOLIDATED / "consolidated_evaluation.json",
        CONSOLIDATED / "consolidated_verification.json",
        PDF_OUTPUT,
    ]
    if missing_sources:
        if all(path.exists() for path in canonical_files):
            print(json.dumps({
                "status": "already_consolidated",
                "canonical_files": [relative(path) for path in canonical_files],
                "legacy_sources_removed": len(missing_sources),
                "next_command": "python scripts/verify_consolidated_evaluation.py",
            }, indent=2))
            return 0
        raise SystemExit(f"Missing consolidation sources and canonical output is incomplete: {missing_sources}")
    dataset_documents, dataset_manifest = load_documents(DATASET_SOURCES)
    evidence_documents, evidence_manifest = load_documents(EVIDENCE_SOURCES)
    text_documents, text_manifest = load_text_documents(TEXT_SOURCES)
    source_manifest = dataset_manifest + evidence_manifest + text_manifest

    dataset_path = EVALS / "consolidated_cases.json"
    evaluation_path = output / "consolidated_evaluation.json"
    verification_path = output / "consolidated_verification.json"
    source_pdf = LEGACY_CURRENT / "three-approach-evaluation-charts.pdf"
    if not source_pdf.exists():
        raise FileNotFoundError(source_pdf)
    PDF_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_pdf, PDF_OUTPUT)

    dataset = build_dataset(dataset_documents, dataset_manifest)
    evaluation = build_evaluation(evidence_documents, text_documents)
    dump(dataset_path, dataset)
    dump(evaluation_path, evaluation)
    verification = build_verification(dataset_path, evaluation_path, source_manifest, evaluation)
    dump(verification_path, verification)
    print(json.dumps({
        "dataset": relative(dataset_path),
        "evaluation": relative(evaluation_path),
        "verification": relative(verification_path),
        "pdf": relative(PDF_OUTPUT),
        "dataset_bytes": dataset_path.stat().st_size,
        "evaluation_bytes": evaluation_path.stat().st_size,
        "verification_bytes": verification_path.stat().st_size,
        "status": verification["status"],
        "errors": verification["errors"],
    }, indent=2))
    return 1 if verification["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
