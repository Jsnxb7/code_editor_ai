from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "evals" / "expanded-model-performance-20260806"

NAVY = colors.HexColor("#14213D")
BLUE = colors.HexColor("#2563EB")
GREEN = colors.HexColor("#16835D")
ORANGE = colors.HexColor("#D97706")
RED = colors.HexColor("#DC2626")
PALE_GREEN = colors.HexColor("#E7F6EF")
PALE_RED = colors.HexColor("#FDE8E8")
LIGHT = colors.HexColor("#F5F7FA")
MID = colors.HexColor("#64748B")
GRID = colors.HexColor("#D9E1EC")


def add_title(drawing: Drawing, heading: str, subtitle: str = "") -> None:
    drawing.add(String(drawing.width / 2, drawing.height - 27, heading, textAnchor="middle", fontName="Helvetica-Bold", fontSize=17, fillColor=NAVY))
    if subtitle:
        drawing.add(String(drawing.width / 2, drawing.height - 46, subtitle, textAnchor="middle", fontName="Helvetica", fontSize=9, fillColor=MID))


def outcome(item: dict[str, Any]) -> str:
    expected, predicted = item["expected_status"], item["predicted_status"]
    if expected == predicted == "FAIL":
        return "TP"
    if expected == predicted == "PASS":
        return "TN"
    return "FP" if expected == "PASS" else "FN"


def confusion_chart(matrix: dict[str, int]) -> Drawing:
    drawing = Drawing(760, 390)
    add_title(drawing, "Reviewer confusion matrix", "Positive class = FAIL (defect present)")
    cells = [
        ("TP", matrix["tp"], 250, 205, PALE_GREEN),
        ("FN", matrix["fn"], 450, 205, PALE_RED),
        ("FP", matrix["fp"], 250, 85, PALE_RED),
        ("TN", matrix["tn"], 450, 85, PALE_GREEN),
    ]
    drawing.add(String(350, 320, "Predicted", textAnchor="middle", fontName="Helvetica-Bold", fontSize=11, fillColor=MID))
    drawing.add(String(250, 292, "FAIL", textAnchor="middle", fontName="Helvetica-Bold", fontSize=11, fillColor=NAVY))
    drawing.add(String(450, 292, "PASS", textAnchor="middle", fontName="Helvetica-Bold", fontSize=11, fillColor=NAVY))
    drawing.add(String(100, 210, "Actual FAIL", textAnchor="middle", fontName="Helvetica-Bold", fontSize=11, fillColor=NAVY))
    drawing.add(String(100, 90, "Actual PASS", textAnchor="middle", fontName="Helvetica-Bold", fontSize=11, fillColor=NAVY))
    for label, value, x, y, fill in cells:
        drawing.add(Rect(x - 82, y - 40, 164, 90, rx=7, ry=7, fillColor=fill, strokeColor=GRID))
        drawing.add(String(x, y + 18, label, textAnchor="middle", fontName="Helvetica-Bold", fontSize=12, fillColor=MID))
        drawing.add(String(x, y - 18, str(value), textAnchor="middle", fontName="Helvetica-Bold", fontSize=27, fillColor=NAVY))
    drawing.add(String(570, 215, f"Correct: {matrix['tp'] + matrix['tn']}", fontName="Helvetica-Bold", fontSize=14, fillColor=GREEN))
    drawing.add(String(570, 180, f"Errors: {matrix['fp'] + matrix['fn']}", fontName="Helvetica-Bold", fontSize=14, fillColor=RED))
    return drawing


def percent_chart(heading: str, values: list[tuple[str, float, int | None]], subtitle: str) -> Drawing:
    drawing = Drawing(760, max(300, 105 + 48 * len(values)))
    add_title(drawing, heading, subtitle)
    start_y = drawing.height - 92
    for index, (label, value, count) in enumerate(values):
        y = start_y - index * 48
        drawing.add(String(18, y + 4, label, fontName="Helvetica", fontSize=10, fillColor=NAVY))
        drawing.add(Rect(205, y - 7, 420, 20, rx=4, ry=4, fillColor=LIGHT, strokeColor=GRID))
        color = GREEN if value >= 0.9 else ORANGE if value >= 0.75 else RED
        drawing.add(Rect(205, y - 7, 420 * value, 20, rx=4, ry=4, fillColor=color, strokeColor=None))
        suffix = f" (n={count})" if count is not None else ""
        drawing.add(String(640, y + 1, f"{value * 100:.1f}%{suffix}", fontName="Helvetica-Bold", fontSize=10, fillColor=NAVY))
    return drawing


def latency_chart(results: list[dict[str, Any]]) -> Drawing:
    drawing = Drawing(760, 365)
    seconds = [float(item["duration_ms"]) / 1000 for item in results]
    bins = [(0, 10), (10, 12), (12, 14), (14, 16), (16, 18), (18, 22), (22, 28)]
    counts = [sum(lower <= value < upper for value in seconds) for lower, upper in bins]
    add_title(drawing, "Reviewer latency distribution", f"{len(results)} reviewer decisions | median {median(seconds):.1f}s")
    left, baseline, height = 82, 72, 205
    drawing.add(Line(left, baseline, 710, baseline, strokeColor=GRID))
    drawing.add(Line(left, baseline, left, baseline + height, strokeColor=GRID))
    maximum = max(counts) or 1
    for index, ((lower, upper), count) in enumerate(zip(bins, counts)):
        x = left + 35 + index * 82
        bar_height = height * count / maximum
        drawing.add(Rect(x, baseline, 55, bar_height, fillColor=BLUE, strokeColor=None))
        drawing.add(String(x + 27.5, baseline + bar_height + 9, str(count), textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=NAVY))
        drawing.add(String(x + 27.5, baseline - 20, f"{lower}-{upper}s", textAnchor="middle", fontName="Helvetica", fontSize=8.5, fillColor=MID))
    drawing.add(String(25, baseline + height / 2, "Cases", angle=90, textAnchor="middle", fontName="Helvetica", fontSize=9, fillColor=MID))
    return drawing


def timeline_chart(results: list[dict[str, Any]]) -> Drawing:
    drawing = Drawing(920, 350)
    add_title(drawing, "Reviewer outcome timeline", "All cases shown in execution order")
    labels = ["TN", "TP", "FP", "FN"]
    palette = {"TN": BLUE, "TP": GREEN, "FP": ORANGE, "FN": RED}
    left, right, bottom, row_gap = 85, 875, 75, 58
    for row, label in enumerate(labels):
        y = bottom + row * row_gap
        drawing.add(Line(left, y, right, y, strokeColor=GRID, strokeWidth=0.7))
        drawing.add(String(55, y - 3, label, textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=palette[label]))
    step = (right - left) / (len(results) - 1)
    for item in results:
        label = outcome(item)
        x = left + (item["sequence"] - 1) * step
        y = bottom + labels.index(label) * row_gap
        drawing.add(Circle(x, y, 7, fillColor=palette[label], strokeColor=colors.white, strokeWidth=0.8))
    for sequence in range(1, len(results) + 1, 4):
        x = left + (sequence - 1) * step
        drawing.add(String(x, 38, str(sequence), textAnchor="middle", fontName="Helvetica", fontSize=8, fillColor=MID))
    drawing.add(String((left + right) / 2, 17, "Case sequence", textAnchor="middle", fontName="Helvetica", fontSize=9, fillColor=MID))
    return drawing


def token_chart(total_usage: dict[str, int]) -> Drawing:
    drawing = Drawing(760, 345)
    add_title(drawing, "Recorded token usage", f"Total: {total_usage['total_tokens']:,} tokens")
    values = [("Input tokens", total_usage["input_tokens"], BLUE), ("Output tokens", total_usage["output_tokens"], ORANGE)]
    maximum = max(value for _, value, _ in values)
    baseline, height = 70, 205
    for index, (label, value, color) in enumerate(values):
        x = 215 + index * 260
        bar_height = height * value / maximum
        drawing.add(Rect(x, baseline, 110, bar_height, fillColor=color, strokeColor=None))
        drawing.add(String(x + 55, baseline + bar_height + 12, f"{value:,}", textAnchor="middle", fontName="Helvetica-Bold", fontSize=12, fillColor=NAVY))
        drawing.add(String(x + 55, baseline - 22, label, textAnchor="middle", fontName="Helvetica", fontSize=10, fillColor=MID))
    return drawing


def class_distribution(results: list[dict[str, Any]]) -> Drawing:
    drawing = Drawing(760, 345)
    add_title(drawing, "Actual and predicted class distribution", "Positive class = FAIL")
    actual = [sum(item["expected_status"] == label for item in results) for label in ("PASS", "FAIL")]
    predicted = [sum(item["predicted_status"] == label for item in results) for label in ("PASS", "FAIL")]
    maximum = max(actual + predicted)
    baseline, height = 65, 205
    for group, label in enumerate(("PASS", "FAIL")):
        base_x = 185 + group * 300
        for offset, (series, value, color) in enumerate((("Actual", actual[group], GREEN), ("Predicted", predicted[group], BLUE))):
            x = base_x + offset * 75
            bar_height = height * value / maximum
            drawing.add(Rect(x, baseline, 58, bar_height, fillColor=color, strokeColor=None))
            drawing.add(String(x + 29, baseline + bar_height + 9, str(value), textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=NAVY))
        drawing.add(String(base_x + 66, baseline - 22, label, textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=NAVY))
    drawing.add(Rect(565, 265, 14, 14, fillColor=GREEN, strokeColor=None))
    drawing.add(String(587, 268, "Actual", fontName="Helvetica", fontSize=9, fillColor=NAVY))
    drawing.add(Rect(635, 265, 14, 14, fillColor=BLUE, strokeColor=None))
    drawing.add(String(657, 268, "Predicted", fontName="Helvetica", fontSize=9, fillColor=NAVY))
    return drawing


def build_all(metrics: dict[str, Any]) -> dict[str, Drawing]:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for obsolete in ("case-outcome-grid.svg", "combined-confusion-matrix.svg", "latency-histogram.svg"):
        (OUTPUT / obsolete).unlink(missing_ok=True)
    reviewer = metrics["reviewer_metrics"]
    results = metrics["reviewer_results"]
    drawings = {
        "confusion-matrix": confusion_chart(reviewer["confusion_matrix"]),
        "classification-metrics": percent_chart("Reviewer classification metrics", [
            ("Accuracy", reviewer["accuracy"], None),
            ("Precision (FAIL)", reviewer["precision_fail"], None),
            ("Recall (FAIL)", reviewer["recall_fail"], None),
            ("Specificity (PASS)", reviewer["specificity_pass"], None),
            ("F1 (FAIL)", reviewer["f1_fail"], None),
            ("Balanced accuracy", reviewer["balanced_accuracy"], None),
        ], f"{reviewer['case_count']} reviewer cases"),
        "category-accuracy": percent_chart("Accuracy by category", [(key, value["accuracy"], value["total"]) for key, value in metrics["category_metrics"].items()], "All reviewer cases grouped by requirement type"),
        "difficulty-accuracy": percent_chart("Accuracy by difficulty", [(key, value["accuracy"], value["total"]) for key, value in metrics["difficulty_metrics"].items()], "Difficulty labels defined in the case manifests"),
        "reviewer-latency": latency_chart(results),
        "reviewer-outcome-timeline": timeline_chart(results),
        "token-usage": token_chart(metrics["total_usage"]),
        "class-distribution": class_distribution(results),
    }
    for name, drawing in drawings.items():
        svg = OUTPUT / f"{name}.svg"
        pdf = OUTPUT / f"{name}.pdf"
        renderSVG.drawToFile(drawing, str(svg))
        renderPDF.drawToFile(drawing, str(pdf))
    return drawings


if __name__ == "__main__":
    metrics = json.loads((OUTPUT / "expanded-metrics.json").read_text(encoding="utf-8"))
    build_all(metrics)
    for chart_path in sorted(OUTPUT.glob("*.svg")):
        print(chart_path)
