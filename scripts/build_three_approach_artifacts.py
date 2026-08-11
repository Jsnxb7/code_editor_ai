"""Build tables, failure attribution, charts, and hashes from the master evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "evals" / "consolidated" / "run-workspace"
NAVY = colors.HexColor("#142B4A")
BLUE = colors.HexColor("#3478C5")
ORANGE = colors.HexColor("#E8902F")
GREEN = colors.HexColor("#3B9B71")
RED = colors.HexColor("#C5535E")
LIGHT = colors.HexColor("#EEF3F8")
GRID = colors.HexColor("#C8D4E0")
MID = colors.HexColor("#61778D")

LABELS = {
    "direct_coder_model_reviewer": "Direct coder + model reviewer",
    "direct_coder_codex_evaluator": "Direct coder + Codex evaluator",
    "planner_coder_model_reviewer": "Planner + coder + model reviewer",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def title(drawing: Drawing, heading: str, subtitle: str) -> None:
    drawing.add(String(22, drawing.height - 30, heading, fontName="Helvetica-Bold", fontSize=18, fillColor=NAVY))
    drawing.add(String(22, drawing.height - 49, subtitle, fontName="Helvetica", fontSize=9, fillColor=MID))


def confusion_panel(name: str, matrix: dict[str, int]) -> Drawing:
    drawing = Drawing(820, 420)
    total = sum(matrix.values())
    title(drawing, f"Confusion matrix - {name}", f"Positive class = FAIL | n={total}")
    cells = [("TP", "tp", 220, 235, GREEN), ("FN", "fn", 440, 235, RED), ("FP", "fp", 220, 95, ORANGE), ("TN", "tn", 440, 95, BLUE)]
    drawing.add(String(330, 345, "Predicted class", textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=MID))
    drawing.add(String(220, 320, "FAIL", textAnchor="middle", fontName="Helvetica", fontSize=10, fillColor=NAVY))
    drawing.add(String(440, 320, "PASS", textAnchor="middle", fontName="Helvetica", fontSize=10, fillColor=NAVY))
    drawing.add(String(90, 205, "Actual class", angle=90, textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=MID))
    drawing.add(String(130, 250, "FAIL", textAnchor="middle", fontName="Helvetica", fontSize=10, fillColor=NAVY))
    drawing.add(String(130, 110, "PASS", textAnchor="middle", fontName="Helvetica", fontSize=10, fillColor=NAVY))
    for label, key, x, y, color in cells:
        drawing.add(Rect(x - 82, y - 50, 164, 105, rx=7, ry=7, fillColor=color, fillOpacity=.22, strokeColor=color))
        drawing.add(String(x, y + 15, label, textAnchor="middle", fontName="Helvetica-Bold", fontSize=12, fillColor=NAVY))
        drawing.add(String(x, y - 22, str(matrix[key]), textAnchor="middle", fontName="Helvetica-Bold", fontSize=30, fillColor=NAVY))
    accuracy = (matrix["tp"] + matrix["tn"]) / total if total else 0
    drawing.add(String(645, 220, f"Accuracy\n{accuracy:.1%}".replace("\n", " "), fontName="Helvetica-Bold", fontSize=12, fillColor=NAVY))
    return drawing


def grouped_percent(title_text: str, subtitle: str, groups: list[tuple[str, list[tuple[str, float]]]]) -> Drawing:
    drawing = Drawing(940, max(390, 115 + len(groups) * 80))
    title(drawing, title_text, subtitle)
    palette = [BLUE, ORANGE, GREEN]
    for index, (legend, _) in enumerate(groups[0][1] if groups else []):
        drawing.add(Rect(555 + index * 125, drawing.height - 52, 11, 11, fillColor=palette[index], strokeColor=None))
        drawing.add(String(571 + index * 125, drawing.height - 49, legend, fontName="Helvetica", fontSize=8, fillColor=NAVY))
    start = drawing.height - 100
    for row, (label, series) in enumerate(groups):
        y = start - row * 80
        drawing.add(String(18, y + 12, label, fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
        for index, (_, value) in enumerate(series):
            bar_y = y + 16 - index * 20
            drawing.add(Rect(210, bar_y, 560, 12, fillColor=LIGHT, strokeColor=GRID))
            drawing.add(Rect(210, bar_y, 560 * max(0, min(1, value)), 12, fillColor=palette[index], strokeColor=None))
            drawing.add(String(782, bar_y + 2, f"{value:.1%}", fontName="Helvetica-Bold", fontSize=8, fillColor=NAVY))
    return drawing


def count_bars(title_text: str, subtitle: str, counts: dict[str, int]) -> Drawing:
    rows = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    drawing = Drawing(940, max(360, 115 + len(rows) * 38))
    title(drawing, title_text, subtitle)
    maximum = max([value for _, value in rows], default=1)
    for index, (label, value) in enumerate(rows):
        y = drawing.height - 95 - index * 38
        drawing.add(String(18, y + 5, label.replace("_", " ").title(), fontName="Helvetica", fontSize=9, fillColor=NAVY))
        drawing.add(Rect(250, y, 570, 14, fillColor=LIGHT, strokeColor=GRID))
        drawing.add(Rect(250, y, 570 * value / maximum, 14, fillColor=BLUE, strokeColor=None))
        drawing.add(String(830, y + 3, str(value), fontName="Helvetica-Bold", fontSize=9, fillColor=NAVY))
    return drawing


def failure_mode(evidence: dict[str, Any]) -> str:
    reasons = evidence.get("failure_reasons", [])
    safety = evidence.get("safety", {})
    if "expected_file_missing" in reasons: return "expected_file_missing"
    if not safety.get("syntax_valid", True): return "syntax_error"
    if "unsafe_or_invalid_code" in reasons: return "unsafe_operation"
    if "execution_error" in reasons: return "execution_error"
    failed = [detail for detail in evidence.get("details", []) if not detail.get("passed")]
    if any(detail.get("kind") == "static" for detail in failed): return "security_or_static_contract"
    if any(detail.get("input_mutated") for detail in failed): return "input_mutation"
    if any(detail.get("raised") and not detail.get("expected_exception") for detail in failed): return "unexpected_exception"
    if any(detail.get("visibility") == "hidden" for detail in failed): return "hidden_edge_case"
    if failed: return "functional_logic"
    return "unknown"


def exact_mcnemar_p_value(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if not discordant:
        return 1.0
    smaller = min(left_only, right_only)
    tail = sum(math.comb(discordant, index) for index in range(smaller + 1)) / (2 ** discordant)
    return min(1.0, 2 * tail)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    master_path = output / "master-evaluation.json"
    checkpoint_path = output / "master-evaluation.checkpoint.json"
    if not master_path.exists() or (checkpoint_path.exists() and checkpoint_path.stat().st_mtime > master_path.stat().st_mtime):
        master_path = checkpoint_path
    master = json.loads(master_path.read_text(encoding="utf-8"))
    if master.get("status") != "complete" and not args.allow_partial:
        raise SystemExit("Master evaluation is not complete; use --allow-partial only for diagnostics")

    rows: list[dict[str, Any]] = []
    attributions: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()
    for case_id, result in master["case_results"].items():
        case = master["case_index"][case_id]
        for approach, item in result.get("approaches", {}).items():
            if item.get("ground_truth") not in {"PASS", "FAIL"}: continue
            evidence = item["ground_truth_evidence"]
            mode = "none" if item["ground_truth"] == "PASS" else failure_mode(evidence)
            failure_counts[mode] += item["ground_truth"] == "FAIL"
            row = {"case_id": case_id, "test_name": case["test_name"], "pair_id": case.get("pair_id"), "prompt_category": case["prompt_category"], "approach": approach, "ground_truth": item["ground_truth"], "predicted_status": item["predicted_status"], "confusion_cell": item["confusion_cell"], "task_success": item["ground_truth"] == "PASS", "tests_passed": evidence["tests_passed"], "tests_total": evidence["tests_total"], "failure_mode": mode}
            rows.append(row)
            if item["confusion_cell"] in {"FP", "FN"}:
                classifier = "Codex evaluator" if approach == "direct_coder_codex_evaluator" else "Bob reviewer"
                generator = "Planner + Bob coder" if approach == "planner_coder_model_reviewer" else "Bob coder"
                attributions.append({**row, "generator_component": generator, "classification_component": classifier, "generator_failure_mode": mode, "explanation": f"{generator} produced {'verified-correct' if item['ground_truth'] == 'PASS' else 'defective'} code; {classifier} returned {item['predicted_status']} against executable ground truth {item['ground_truth']}."})

    with (output / "results.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["case_id"]); writer.writeheader(); writer.writerows(rows)
    attribution = {"schema_version": "2.0", "created_at": now(), "positive_class": "FAIL", "disagreement_count": len(attributions), "by_classifier": dict(Counter(item["classification_component"] for item in attributions)), "by_generator": dict(Counter(item["generator_component"] for item in attributions)), "by_failure_mode": dict(Counter(item["generator_failure_mode"] for item in attributions)), "records": attributions}
    dump(output / "component-failure-attribution.json", attribution)

    pair_rows = []
    for pair_id in sorted({case.get("pair_id") for case in master["case_index"].values() if case.get("pair_id")}):
        members = [case for case in master["case_index"].values() if case.get("pair_id") == pair_id]
        by_category = {case["prompt_category"]: case for case in members}
        if not all(
            master["case_results"].get(by_category[category]["id"], {}).get("complete")
            for category in ("as_is", "naturalized_existing")
        ):
            continue
        record: dict[str, Any] = {"pair_id": pair_id, "as_is_case_id": by_category["as_is"]["id"], "naturalized_case_id": by_category["naturalized_existing"]["id"], "approaches": {}}
        for approach in LABELS:
            left = master["case_results"].get(record["as_is_case_id"], {}).get("approaches", {}).get(approach, {})
            right = master["case_results"].get(record["naturalized_case_id"], {}).get("approaches", {}).get(approach, {})
            record["approaches"][approach] = {"as_is_task_success": left.get("ground_truth") == "PASS", "naturalized_task_success": right.get("ground_truth") == "PASS", "as_is_classifier_correct": left.get("confusion_cell") in {"TP", "TN"}, "naturalized_classifier_correct": right.get("confusion_cell") in {"TP", "TN"}}
        pair_rows.append(record)
    paired_summary = {"schema_version": "2.0", "created_at": now(), "pair_count": len(pair_rows), "by_approach": {}, "pairs": pair_rows}
    for approach in LABELS:
        values = [row["approaches"][approach] for row in pair_rows]
        paired_summary["by_approach"][approach] = {
            "as_is_task_success_rate": sum(item["as_is_task_success"] for item in values) / len(values) if values else 0,
            "naturalized_task_success_rate": sum(item["naturalized_task_success"] for item in values) / len(values) if values else 0,
            "naturalized_task_uplift": (sum(item["naturalized_task_success"] for item in values) - sum(item["as_is_task_success"] for item in values)) / len(values) if values else 0,
            "as_is_classifier_accuracy": sum(item["as_is_classifier_correct"] for item in values) / len(values) if values else 0,
            "naturalized_classifier_accuracy": sum(item["naturalized_classifier_correct"] for item in values) / len(values) if values else 0,
            "task_success_discordance": {
                "as_is_only": sum(item["as_is_task_success"] and not item["naturalized_task_success"] for item in values),
                "naturalized_only": sum(item["naturalized_task_success"] and not item["as_is_task_success"] for item in values),
            },
        }
        discordance = paired_summary["by_approach"][approach]["task_success_discordance"]
        paired_summary["by_approach"][approach]["mcnemar_exact_p_value"] = exact_mcnemar_p_value(discordance["as_is_only"], discordance["naturalized_only"])
    dump(output / "paired-prompt-analysis.json", paired_summary)

    metrics = master.get("metrics") or json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    drawings: dict[str, Drawing] = {}
    for approach, label in LABELS.items():
        drawings[f"confusion-{approach}"] = confusion_panel(label, metrics["by_approach"][approach]["confusion_matrix"])
    consolidated_matrix = {
        cell: sum(metrics["by_approach"][approach]["confusion_matrix"][cell] for approach in LABELS)
        for cell in ("tp", "fn", "fp", "tn")
    }
    drawings["confusion-consolidated"] = confusion_panel(
        "Consolidated across all three approaches",
        consolidated_matrix,
    )
    drawings["approach-performance"] = grouped_percent("Approach performance", "Classifier accuracy and generated-code task success", [(LABELS[approach], [("Accuracy", metrics["by_approach"][approach]["accuracy"]), ("Task success", metrics["by_approach"][approach]["task_success_rate"])]) for approach in LABELS])
    category_groups = []
    for category, approaches in metrics["by_prompt_category_and_approach"].items():
        category_groups.append((category.replace("_", " ").title(), [("Direct reviewer", approaches["direct_coder_model_reviewer"]["accuracy"]), ("Codex evaluator", approaches["direct_coder_codex_evaluator"]["accuracy"]), ("Full pipeline", approaches["planner_coder_model_reviewer"]["accuracy"])]))
    drawings["category-accuracy"] = grouped_percent("Accuracy by prompt category", "As-is, paired naturalized, and new natural-user prompts", category_groups)
    paired_groups = [(LABELS[approach], [("As-is success", item["as_is_task_success_rate"]), ("Naturalized success", item["naturalized_task_success_rate"])]) for approach, item in paired_summary["by_approach"].items()]
    drawings["paired-prompt-success"] = grouped_percent("Paired prompt task success", "The same 74 requirements under as-is and naturalized wording", paired_groups)
    drawings["generated-failure-modes"] = count_bars("Generated-code failure modes", "Deterministic ground-truth failures across all approaches", {key: value for key, value in failure_counts.items() if key != "none"})
    drawings["fp-fn-attribution"] = count_bars("FP/FN classification attribution", "Incorrect decisions grouped by the responsible classifier", attribution["by_classifier"])

    chart_dir = output / "charts"; chart_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output / "three-approach-evaluation-charts.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    manifest = []
    for index, (name, drawing) in enumerate(drawings.items(), 1):
        svg = chart_dir / f"{name}.svg"; renderSVG.drawToFile(drawing, str(svg))
        pdf.setPageSize((drawing.width, drawing.height)); renderPDF.draw(drawing, pdf, 0, 0); pdf.showPage()
        manifest.append({"name": name, "svg": str(svg), "pdf_page": index, "width": drawing.width, "height": drawing.height})
    pdf.save(); dump(output / "chart-manifest.json", {"schema_version": "2.0", "created_at": now(), "pdf": str(pdf_path), "charts": manifest})

    runtime_logs = []
    for name in ("events.jsonl", "model-events.jsonl", "ngrok-events.jsonl"):
        path = ROOT / "data" / "runtime" / name
        if not path.exists(): continue
        matching = sum(master["evaluation_run_id"] in line for line in path.read_text(encoding="utf-8", errors="replace").splitlines())
        runtime_logs.append({"path": str(path), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "matching_evaluation_records": matching})
    dump(output / "runtime-log-index.json", {"schema_version": "2.0", "created_at": now(), "evaluation_run_id": master["evaluation_run_id"], "local_logs": runtime_logs, "remote_runtime_log_dir": master.get("runtime_health", {}).get("runtime_log_dir"), "remote_files": ["app-events.jsonl", "model-events.jsonl", "ngrok-events.jsonl"], "note": "Remote log contents remain on the Lightning runtime; prompts and code are excluded from operational JSONL and retained only in the restricted master evidence."})

    summary_lines = [
        "# Bob three-approach model evaluation",
        "",
        f"Evaluation run: `{master['evaluation_run_id']}`  ",
        f"Prompt variants: **{len(master['case_results'])}**  ",
        f"Live HTTP calls: **{len(master['calls'])}**  ",
        "",
        "## Approach results",
        "",
        "| Approach | Accuracy | Task success | TP | FN | FP | TN |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for approach, label in LABELS.items():
        item = metrics["by_approach"][approach]; matrix = item["confusion_matrix"]
        summary_lines.append(f"| {label} | {item['accuracy']:.1%} | {item['task_success_rate']:.1%} | {matrix['tp']} | {matrix['fn']} | {matrix['fp']} | {matrix['tn']} |")
    summary_lines.extend(["", "## Evidence", "", "- `master-evaluation.json`: prompts, responses, code, reviews, blind scores, tests, labels, latency and usage.", "- `component-failure-attribution.json`: generator and classifier attribution for every FP/FN.", "- `paired-prompt-analysis.json`: as-is versus naturalized comparisons for 74 requirement pairs.", "- `results.csv`: one row per prompt variant and approach.", "- `runtime-log-index.json`: local/remote structured log locations and hashes.", "- `verification-manifest.json`: SHA-256 evidence manifest.", ""])
    (output / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    generated_receipts = {"verification-manifest.json", "acceptance-verification.json"}
    artifacts = [
        path
        for path in output.rglob("*")
        if path.is_file() and not path.name.endswith(".tmp") and path.name not in generated_receipts
    ]
    verification = {"schema_version": "2.0", "created_at": now(), "evaluation_run_id": master["evaluation_run_id"], "master_status": master["status"], "artifacts": [{"path": str(path.relative_to(output)), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(artifacts)]}
    dump(output / "verification-manifest.json", verification)
    print(json.dumps({"output": str(output), "rows": len(rows), "disagreements": len(attributions), "pairs": len(pair_rows), "charts": len(drawings), "artifacts": len(verification["artifacts"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
