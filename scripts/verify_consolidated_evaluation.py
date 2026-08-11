"""Verify the canonical consolidated Bob evaluation artifacts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "consolidated_cases.json"
OUTPUT = ROOT / "output" / "evals" / "consolidated"
EVALUATION = OUTPUT / "consolidated_evaluation.json"
VERIFICATION = OUTPUT / "consolidated_verification.json"
PDF = ROOT / "output" / "pdf" / "consolidated-evaluation-charts.pdf"


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_file(record: dict[str, Any], errors: list[str]) -> None:
    path = ROOT / record["path"]
    if not path.exists():
        errors.append(f"missing canonical artifact: {record['path']}")
        return
    if path.stat().st_size != record["bytes"]:
        errors.append(f"size mismatch: {record['path']}")
    if digest(path) != record["sha256"]:
        errors.append(f"hash mismatch: {record['path']}")


def main() -> int:
    errors: list[str] = []
    for path in (DATASET, EVALUATION, VERIFICATION, PDF):
        if not path.exists():
            errors.append(f"missing required file: {path.relative_to(ROOT)}")
    if errors:
        print(json.dumps({"status": "failed", "errors": errors}, indent=2))
        return 1

    dataset = read(DATASET)
    evaluation = read(EVALUATION)
    verification = read(VERIFICATION)
    expected_dataset = {
        "offline_cases": 12,
        "historical_code_cases": 4,
        "historical_replan_cases": 2,
        "historical_review_cases": 8,
        "source_requirements": 74,
        "live_prompt_variants": 178,
        "prompt_categories": {"as_is": 74, "naturalized_existing": 74, "new_user_natural": 30},
        "source_groups": {"baseline_reviewer": 8, "reviewer_challenge": 30, "reviewer_fp_probe": 6, "descriptive_sourced": 30},
        "paired_requirements": 74,
    }
    if dataset.get("inventory") != expected_dataset:
        errors.append(f"dataset inventory mismatch: {dataset.get('inventory')}")
    cases = dataset.get("live_three_approach_suite", {}).get("cases", [])
    if len(cases) != 178 or len({case.get("id") for case in cases}) != 178:
        errors.append("live prompt variants are missing or duplicated")
    categories = Counter(case.get("prompt_category") for case in cases)
    if dict(categories) != expected_dataset["prompt_categories"]:
        errors.append(f"prompt categories mismatch: {dict(categories)}")

    inventory = evaluation.get("inventory", {})
    expected_evaluation = verification.get("checks", {}).get("expected_inventory", {})
    for key, expected in expected_evaluation.items():
        if inventory.get(key) != expected:
            errors.append(f"evaluation inventory {key}: expected {expected}, found {inventory.get(key)}")
    current = evaluation.get("runs", {}).get("three_approach_20260810", {}).get("master", {})
    if current.get("status") != "complete":
        errors.append("latest run is not complete")
    if len(current.get("case_results", {})) != 178:
        errors.append("latest run does not contain 178 case results")
    if len(current.get("calls", [])) != 540:
        errors.append("latest run does not contain 540 call attempts")
    cells = Counter()
    approach_rows = 0
    for result in current.get("case_results", {}).values():
        for item in result.get("approaches", {}).values():
            cell = str(item.get("confusion_cell", "")).lower()
            if cell in {"tp", "fn", "fp", "tn"}:
                cells[cell] += 1
                approach_rows += 1
    matrix = {cell: cells[cell] for cell in ("tp", "fn", "fp", "tn")}
    expected_matrix = {"tp": 62, "fn": 164, "fp": 10, "tn": 298}
    if matrix != expected_matrix or approach_rows != 534:
        errors.append(f"recalculated matrix/results mismatch: rows={approach_rows}, matrix={matrix}")
    if evaluation.get("latest_analysis", {}).get("consolidated_confusion_matrix") != expected_matrix:
        errors.append("stored consolidated confusion matrix mismatch")

    for record in verification.get("canonical_artifacts", {}).values():
        if isinstance(record, dict) and "path" in record:
            verify_file(record, errors)
    backup = verification.get("backup")
    if not isinstance(backup, dict):
        errors.append("backup record missing")
    else:
        verify_file(backup, errors)
    for log in verification.get("canonical_artifacts", {}).get("logs", []):
        if not (ROOT / log).exists():
            errors.append(f"separate runtime log missing: {log}")

    encoded = EVALUATION.read_text(encoding="utf-8")
    patterns = {
        "authorization_bearer": r"(?i)authorization\s*[\"':=]+\s*bearer\s+(?!\[REDACTED\])",
        "github_token": r"github_pat_[A-Za-z0-9_]+",
        "huggingface_token": r"\bhf_[A-Za-z0-9]{8,}",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, encoded):
            errors.append(f"secret scan matched {name}")

    pdf_pages = None
    try:
        from pypdf import PdfReader

        pdf_pages = len(PdfReader(str(PDF)).pages)
        if pdf_pages != 9:
            errors.append(f"expected 9 PDF pages, found {pdf_pages}")
    except ImportError:
        pdf_pages = "not checked (pypdf unavailable)"

    report = {
        "schema_version": "1.0",
        "status": "passed" if not errors else "failed",
        "dataset_cases": len(cases),
        "offline_cases": len(dataset.get("offline_suite", {}).get("cases", [])),
        "accepted_runs": inventory.get("accepted_live_runs"),
        "recorded_call_attempts": inventory.get("recorded_live_call_attempts"),
        "latest_approach_results": approach_rows,
        "consolidated_confusion_matrix": matrix,
        "pdf_pages": pdf_pages,
        "source_manifest_entries": len(verification.get("source_manifest", [])),
        "errors": errors,
    }
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
