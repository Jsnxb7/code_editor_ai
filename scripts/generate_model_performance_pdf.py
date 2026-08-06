from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output" / "evals" / "model-performance-20260806"
DESTINATION = ROOT / "output" / "pdf" / "Bob_Model_Performance_Evaluation_2026-08-06.pdf"

report = json.loads((SOURCE / "metrics.json").read_text(encoding="utf-8"))
verification = json.loads((SOURCE / "verification.json").read_text(encoding="utf-8"))
qualitative = json.loads((SOURCE / "qualitative-evaluation.json").read_text(encoding="utf-8"))
metrics = report["metrics"]

NAVY = colors.HexColor("#14213D")
BLUE = colors.HexColor("#2563EB")
PALE_BLUE = colors.HexColor("#EAF1FF")
GREEN = colors.HexColor("#16835D")
PALE_GREEN = colors.HexColor("#E7F6EF")
ORANGE = colors.HexColor("#D97706")
LIGHT = colors.HexColor("#F5F7FA")
MID = colors.HexColor("#64748B")
INK = colors.HexColor("#172033")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=NAVY, alignment=TA_LEFT, spaceAfter=8))
styles.add(ParagraphStyle(name="Subtitle", parent=styles["Normal"], fontSize=11, leading=16, textColor=MID, spaceAfter=18))
styles.add(ParagraphStyle(name="H1x", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceBefore=8, spaceAfter=10))
styles.add(ParagraphStyle(name="H2x", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=BLUE, spaceBefore=8, spaceAfter=6))
styles.add(ParagraphStyle(name="Bodyx", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=14, textColor=INK, spaceAfter=7))
styles.add(ParagraphStyle(name="Smallx", parent=styles["BodyText"], fontName="Helvetica", fontSize=8, leading=11, textColor=MID))
styles.add(ParagraphStyle(name="Callout", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=10, leading=15, textColor=NAVY, leftIndent=8, rightIndent=8, spaceBefore=6, spaceAfter=6))


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MID)
    canvas.drawRightString(width - 18 * mm, 11 * mm, f"Page {doc.page}")
    canvas.restoreState()


def metric_cards(items):
    cells = []
    for label, value, color in items:
        cells.append(Paragraph(f'<font color="{color.hexval()}"><b>{value}</b></font><br/><font size="8" color="#64748B">{label}</font>', ParagraphStyle("MetricCell", parent=styles["Bodyx"], alignment=TA_CENTER, leading=15)))
    table = Table([cells], colWidths=[43 * mm] * len(cells), rowHeights=[28 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9E1EC")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9E1EC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def standard_table(rows, widths, header=True):
    cooked = []
    for row_index, row in enumerate(rows):
        style = styles["Smallx"] if row_index else ParagraphStyle("TableHeader", parent=styles["Smallx"], textColor=colors.white, fontName="Helvetica-Bold")
        cooked.append([Paragraph(str(value), style) for value in row])
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9E1EC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]
    if header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    table = Table(cooked, colWidths=widths, repeatRows=1 if header else 0)
    table.setStyle(TableStyle(commands))
    return table


def report_header():
    """A content-layer header that cannot be obscured by later flowables."""
    label = Paragraph("BOB IDE - MODEL PERFORMANCE EVALUATION", ParagraphStyle("HeaderLabel", parent=styles["Smallx"], fontName="Helvetica-Bold", textColor=NAVY))
    return Table([[label]], colWidths=[165 * mm], rowHeights=[11 * mm], style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9E1EC")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))


def section_heading(title: str):
    label = Paragraph("BOB IDE - MODEL PERFORMANCE EVALUATION", ParagraphStyle("SectionHeaderLabel", parent=styles["Smallx"], fontName="Helvetica-Bold", textColor=NAVY))
    heading = Paragraph(title, styles["H1x"])
    table = Table([[label], [""], [heading]], colWidths=[165 * mm], rowHeights=[11 * mm, 10 * mm, None], splitByRow=0, style=TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#D9E1EC")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([table])


def confusion_table():
    matrix = metrics["review_confusion_matrix"]
    data = [
        ["Actual / predicted", "FAIL", "PASS"],
        ["FAIL", f"TP = {matrix['tp']}", f"FN = {matrix['fn']}"],
        ["PASS", f"FP = {matrix['fp']}", f"TN = {matrix['tn']}"],
    ]
    table = standard_table(data, [55 * mm, 45 * mm, 45 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (1, 1), (1, 1), PALE_GREEN),
        ("BACKGROUND", (2, 2), (2, 2), PALE_GREEN),
        ("BACKGROUND", (2, 1), (2, 1), colors.HexColor("#FFF1F2")),
        ("BACKGROUND", (1, 2), (1, 2), colors.HexColor("#FFF1F2")),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("FONTSIZE", (1, 1), (-1, -1), 15),
    ]))
    return table


DESTINATION.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(DESTINATION), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=12 * mm, bottomMargin=18 * mm, title="Bob Model Performance Evaluation", author="Bob IDE evaluation suite")

story = []
story.append(report_header())
story.append(Spacer(1, 13 * mm))
story.append(Paragraph("Bob Model Performance Evaluation", styles["ReportTitle"]))
story.append(Paragraph("Qwen/Qwen2.5-Coder-7B-Instruct | Live Lightning/ngrok runtime | 6 August 2026", styles["Subtitle"]))
story.append(metric_cards([
    ("Live calls succeeded", "22 / 22", GREEN),
    ("Generated tests passed", "9 / 9", GREEN),
    ("Reviewer accuracy", pct(metrics["review_accuracy"]), GREEN),
    ("Total tokens", f"{metrics['usage']['total_tokens']:,}", BLUE),
]))
story.append(Spacer(1, 9 * mm))
story.append(Paragraph("Executive summary", styles["H1x"]))
story.append(Paragraph("The evaluated runtime completed every planned endpoint call. All four generated Python tasks passed their deterministic tests, and the reviewer correctly separated four valid implementations from four defective implementations. The strongest observed weakness was structured planning compliance: two plans mentioned the correct file in prose but omitted it from the files_needed field.", styles["Bodyx"]))
story.append(Table([[Paragraph("VERIFIED", styles["Callout"]), Paragraph("Call counts, stage distribution, confusion matrix, test totals, and secret redaction were independently recalculated from the saved raw evidence.", styles["Bodyx"])]], colWidths=[28 * mm, 137 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN), ("BOX", (0, 0), (-1, -1), 0.7, GREEN), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)])))
story.append(Spacer(1, 6 * mm))
story.append(Paragraph("Scope", styles["H2x"]))
story.append(standard_table([
    ["Evaluation area", "Cases / calls", "Evidence"],
    ["Plan -> code -> review", "4 tasks / 12 calls", "Saved plans, generated files, review text, 9 deterministic tests"],
    ["Replanning", "2 cases / 2 calls", "Required and forbidden target-file constraints"],
    ["Reviewer classification", "8 cases / 8 calls", "Balanced 4 PASS and 4 FAIL ground-truth set"],
], [46 * mm, 35 * mm, 84 * mm]))

story.append(PageBreak())
story.append(section_heading("Methodology and controls"))
story.append(Paragraph("The suite used deterministic prompts and explicit expected behavior. It invoked /plan, /code, /review, and /replan directly against the authenticated runtime. The health and capabilities checks were read-only and were not counted as generation calls.", styles["Bodyx"]))
story.append(Paragraph("Execution safety", styles["H2x"]))
story.append(Paragraph("Generated Python was parsed before execution. Imports and high-risk syntax or calls such as eval, exec, open, subprocess, socket, and file-system access were rejected. Approved snippets ran with Python isolated mode, in temporary directories, with a 10-second timeout.", styles["Bodyx"]))
story.append(Paragraph("Classification definition", styles["H2x"]))
story.append(Paragraph("For the reviewer confusion matrix, FAIL is the positive class because it represents detection of a defect. A true positive is defective code correctly marked FAIL; a false negative is defective code incorrectly marked PASS.", styles["Bodyx"]))
story.append(Paragraph("Test cases", styles["H2x"]))
story.append(standard_table([
    ["Group", "Cases", "Ground truth"],
    ["Generated code", "Addition; username normalization; factorial; stable deduplication", "Expected outputs and expected exceptions"],
    ["Replanning", "Forced validator reuse; README-only scope correction", "Required and forbidden file paths"],
    ["Valid review inputs", "4 known-correct implementations", "PASS"],
    ["Defective review inputs", "Logic; validation; edge case; unsafe eval", "FAIL"],
], [37 * mm, 76 * mm, 52 * mm]))
story.append(Spacer(1, 5 * mm))
story.append(Paragraph("Evidence policy", styles["H2x"]))
story.append(Paragraph("Requests, outputs, timings, tracing metadata, and token usage were saved as JSON. Automatic redaction removed configured tokens, bearer credentials, authorization headers, and common secret fields. The verification scan found no retained credential material.", styles["Bodyx"]))

story.append(PageBreak())
story.append(section_heading("Reviewer classification performance"))
story.append(metric_cards([
    ("Accuracy", pct(metrics["review_accuracy"]), GREEN),
    ("Precision (FAIL)", pct(metrics["review_precision"]), GREEN),
    ("Recall (FAIL)", pct(metrics["review_recall"]), GREEN),
    ("F1 (FAIL)", pct(metrics["review_f1"]), GREEN),
]))
story.append(Spacer(1, 8 * mm))
story.append(confusion_table())
story.append(Spacer(1, 8 * mm))
story.append(Paragraph("Interpretation", styles["H2x"]))
story.append(Paragraph("The reviewer produced no false approvals and no false rejections on this balanced eight-case set. It detected arithmetic logic errors, missing input validation, incorrect edge-case behavior, and unsafe eval usage. Each FAIL explanation identified the relevant requirement and provided evidence or a correction.", styles["Bodyx"]))
story.append(Paragraph("Per-case outcomes", styles["H2x"]))
rows = [["Case", "Expected", "Predicted", "Category"]]
for item in report["review_results"]:
    rows.append([item["case_id"].replace("review_", ""), item["expected_status"], item["predicted_status"], item["failure_category"]])
story.append(standard_table(rows, [52 * mm, 27 * mm, 28 * mm, 58 * mm]))

story.append(PageBreak())
story.append(section_heading("Planning and generated-code performance"))
story.append(metric_cards([
    ("Structured file field", pct(metrics["plan_required_file_accuracy"]), ORANGE),
    ("Semantic file ID", pct(verification["supplemental_metrics"]["plan_semantic_file_identification"]), GREEN),
    ("Replan constraints", pct(metrics["replan_constraint_accuracy"]), ORANGE),
    ("Task success", pct(metrics["generated_task_success_rate"]), GREEN),
]))
story.append(Spacer(1, 7 * mm))
story.append(Paragraph("Generated-code results", styles["H2x"]))
rows = [["Task", "Returned file", "Tests", "Reviewer", "Outcome"]]
for item in report["generated_results"]:
    rows.append([
        item["case_id"].replace("code_", ""),
        ", ".join(item["returned_files"]),
        f"{item['tests']['passed']}/{item['tests']['total']}",
        item["review_status"],
        "PASS" if item["task_success"] else "FAIL",
    ])
story.append(standard_table(rows, [39 * mm, 48 * mm, 22 * mm, 27 * mm, 29 * mm]))
story.append(Spacer(1, 5 * mm))
story.append(Paragraph("Planning finding", styles["H2x"]))
story.append(Paragraph("calculator.py and text_utils.py appeared in files_needed. math_utils.py and collections_utils.py were omitted from that structured field, although both appeared in coder_prompt and were produced correctly. This yields 50% strict schema accuracy but 100% semantic target-file identification.", styles["Bodyx"]))
story.append(Paragraph("Replanning finding", styles["H2x"]))
story.append(Paragraph("The validator-reuse replan satisfied both required and forbidden file constraints. The README-only replan correctly excluded server.py and test_server.py but omitted README.md from files_needed while naming it in prose. Strict replan constraint accuracy was therefore 50%.", styles["Bodyx"]))
story.append(Paragraph("Qualitative assessment", styles["H2x"]))
story.append(Paragraph("Assistant inspection rated all four code outputs acceptable. The stable-deduplication solution received a completeness score of 4/5 because its set-based approach assumes hashable inputs, a constraint not stated in the prompt. This assessment is not represented as independent human evaluation.", styles["Bodyx"]))

story.append(PageBreak())
story.append(section_heading("Operational metrics and reproducibility"))
latency = verification["supplemental_metrics"]["latency_by_stage"]
story.append(standard_table([
    ["Stage", "Calls", "Mean", "Minimum", "Maximum"],
    *[[stage.capitalize(), values["calls"], f"{values['mean_ms'] / 1000:.2f} s", f"{values['min_ms'] / 1000:.2f} s", f"{values['max_ms'] / 1000:.2f} s"] for stage, values in latency.items()],
], [35 * mm, 23 * mm, 35 * mm, 35 * mm, 37 * mm]))
story.append(Spacer(1, 7 * mm))
story.append(standard_table([
    ["Operational measure", "Result"],
    ["Endpoint success", pct(metrics["endpoint_success_rate"])],
    ["Overall mean latency", f"{metrics['latency_ms']['mean'] / 1000:.2f} s"],
    ["P50 / P95 latency", f"{metrics['latency_ms']['p50'] / 1000:.2f} s / {metrics['latency_ms']['p95'] / 1000:.2f} s"],
    ["Input / output / total tokens", f"{metrics['usage']['input_tokens']:,} / {metrics['usage']['output_tokens']:,} / {metrics['usage']['total_tokens']:,}"],
    ["Estimated USD cost", "Not calculated because model pricing was not configured"],
    ["Runtime contract", report.get("contract_version", "unknown")],
], [70 * mm, 95 * mm]))
story.append(Spacer(1, 7 * mm))
story.append(Paragraph("Saved artifacts", styles["H2x"]))
story.append(standard_table([
    ["Artifact", "Purpose"],
    ["raw-evidence.json", "Redacted per-call inputs, outputs, usage, timestamps, and latency"],
    ["metrics.json", "Aggregate and per-case machine-readable results"],
    ["results.csv", "Flat stage/case results for spreadsheet analysis"],
    ["confusion-matrix.svg", "Reusable confusion-matrix figure"],
    ["verification.json", "Independent recalculation and redaction checks"],
    ["qualitative-evaluation.json", "Assistant rubric scores with explicit limitations"],
], [55 * mm, 110 * mm]))

story.append(PageBreak())
story.append(section_heading("Conclusions and limitations"))
story.append(Paragraph("Within this controlled dataset, code generation and reviewer classification were strong: every generated task passed, functional tests agreed with reviewer decisions, and the reviewer achieved perfect balanced classification. The priority improvement is enforcing planner output contracts so files_needed consistently contains every intended target.", styles["Bodyx"]))
story.append(Paragraph("Recommended next evaluations", styles["H2x"]))
story.append(standard_table([
    ["Priority", "Expansion", "Reason"],
    ["1", "Increase reviewer cases to at least 30 with borderline defects", "Eight balanced cases are useful but too small for a stable general claim"],
    ["2", "Add JavaScript/React and multi-file code tasks", "Current generated-code tests cover small Python functions only"],
    ["3", "Add repeated runs with fixed decoding configuration", "Measures variance and reproducibility"],
    ["4", "Collect blinded ratings from at least two people", "Enables independent human scores and inter-rater agreement"],
    ["5", "Configure token pricing", "Enables cost per task and cost per successful task"],
], [20 * mm, 64 * mm, 81 * mm]))
story.append(Spacer(1, 7 * mm))
story.append(Paragraph("Limitations", styles["H2x"]))
for limitation in [
    "The reviewer confusion matrix contains eight examples and should not be generalized beyond this test distribution.",
    "The test suite intentionally favors deterministic, locally executable functions; repository-scale behavior remains unmeasured.",
    "No independent human evaluator participated in this run.",
    "No cost estimate is reported because pricing was not configured for the local model runtime.",
    "The ngrok endpoint and model state represent a single evaluation snapshot on 6 August 2026.",
]:
    story.append(Paragraph(f"- {limitation}", styles["Bodyx"]))
story.append(Spacer(1, 5 * mm))
story.append(Table([[Paragraph("Evidence status", styles["H2x"]), Paragraph("All automated verification checks passed. Raw evidence remains available for audit and re-analysis.", styles["Bodyx"])]], colWidths=[40 * mm, 125 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE), ("BOX", (0, 0), (-1, -1), 0.7, BLUE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)])))

doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print(DESTINATION)
