from __future__ import annotations

import html
import io
import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as canvas_module
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVAL_ROOT = ROOT / "output" / "evals"
EXPANDED = EVAL_ROOT / "expanded-model-performance-20260806"
DESTINATION = ROOT / "output" / "pdf" / "Bob_Model_Performance_Evaluation_2026-08-06.pdf"
BODY_PDF = ROOT / "tmp" / "pdfs" / "Bob_Model_Performance_Evaluation_body.pdf"

from scripts.expanded_evaluation_charts import build_all

metrics = json.loads((EXPANDED / "expanded-metrics.json").read_text(encoding="utf-8"))
assistant_eval = json.loads((EXPANDED / "assistant-evaluation.json").read_text(encoding="utf-8"))
challenge_raw = json.loads((EVAL_ROOT / "reviewer-challenge-20260806" / "raw-evidence.json").read_text(encoding="utf-8"))
probe_raw = json.loads((EVAL_ROOT / "reviewer-fp-probes-20260806" / "raw-evidence.json").read_text(encoding="utf-8"))
raw_by_id = {item["case"]["id"]: item for item in challenge_raw["calls"] + probe_raw["calls"]}
chart_paths = build_all(metrics)

NAVY = colors.HexColor("#14213D")
BLUE = colors.HexColor("#2563EB")
GREEN = colors.HexColor("#16835D")
ORANGE = colors.HexColor("#D97706")
RED = colors.HexColor("#DC2626")
PALE_BLUE = colors.HexColor("#EAF1FF")
PALE_GREEN = colors.HexColor("#E7F6EF")
PALE_RED = colors.HexColor("#FDE8E8")
LIGHT = colors.HexColor("#F5F7FA")
MID = colors.HexColor("#64748B")
INK = colors.HexColor("#172033")
GRID = colors.HexColor("#D9E1EC")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=NAVY, alignment=TA_LEFT, spaceAfter=7))
styles.add(ParagraphStyle(name="Subtitle", parent=styles["Normal"], fontSize=10.5, leading=15, textColor=MID, spaceAfter=16))
styles.add(ParagraphStyle(name="H1x", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceBefore=5, spaceAfter=9))
styles.add(ParagraphStyle(name="H2x", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=BLUE, spaceBefore=7, spaceAfter=5))
styles.add(ParagraphStyle(name="Bodyx", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.3, leading=13.5, textColor=INK, spaceAfter=6))
styles.add(ParagraphStyle(name="Smallx", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.7, leading=10.5, textColor=MID))
styles.add(ParagraphStyle(name="CodeX", parent=styles["BodyText"], fontName="Courier", fontSize=7.5, leading=10.2, textColor=INK))
styles.add(ParagraphStyle(name="MetricCell", parent=styles["BodyText"], alignment=TA_CENTER, fontSize=10, leading=15, textColor=NAVY))


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


class ReportCanvas(canvas_module.Canvas):
    """Draw page chrome after flowables so tables cannot obscure it."""

    def _draw_chrome(self):
        self.saveState()
        width, height = A4
        self.setFillColor(colors.white)
        self.rect(0, height - 19 * mm, width, 19 * mm, fill=1, stroke=0)
        self.rect(0, 0, width, 15 * mm, fill=1, stroke=0)
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(NAVY)
        self.drawString(18 * mm, height - 10 * mm, "BOB IDE - MODEL PERFORMANCE EVALUATION")
        self.setStrokeColor(GRID)
        self.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
        self.setFont("Helvetica", 8)
        self.setFillColor(MID)
        self.drawRightString(width - 18 * mm, 10 * mm, f"Page {self._pageNumber}")
        self.restoreState()

    def showPage(self):
        self._draw_chrome()
        super().showPage()


def section(title: str):
    table = Table([[Paragraph(title, styles["H1x"])]], colWidths=[165 * mm], rowHeights=[24 * mm], splitByRow=0)
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 8 * mm), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([table])


def standard_table(rows, widths, font_size=7.7, repeat=True):
    cooked = []
    for row_index, row in enumerate(rows):
        style = ParagraphStyle(f"Table{font_size}{row_index == 0}", parent=styles["Smallx"], fontSize=font_size, leading=font_size + 2.4, textColor=colors.white if row_index == 0 else MID, fontName="Helvetica-Bold" if row_index == 0 else "Helvetica")
        cooked.append([Paragraph(html.escape(str(value)), style) for value in row])
    table = Table(cooked, colWidths=widths, repeatRows=1 if repeat else 0)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def metric_cards(items):
    cells = [Paragraph(f'<font color="{color.hexval()}"><b>{value}</b></font><br/><font size="8" color="#64748B">{label}</font>', styles["MetricCell"]) for label, value, color in items]
    table = Table([cells], colWidths=[41.25 * mm] * len(cells), rowHeights=[25 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("GRID", (0, 0), (-1, -1), 0.5, GRID), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return table


def chart_image(name: str, max_width=165 * mm, max_height=82 * mm):
    drawing = chart_paths[name]
    factor = min(max_width / drawing.width, max_height / drawing.height)
    drawing.scale(factor, factor)
    drawing.width *= factor
    drawing.height *= factor
    return drawing


def callout(label: str, text: str, color=BLUE, background=PALE_BLUE):
    return Table([[Paragraph(label, ParagraphStyle("CalloutLabel", parent=styles["Bodyx"], fontName="Helvetica-Bold", textColor=color)), Paragraph(text, styles["Bodyx"])]], colWidths=[34 * mm, 131 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), background), ("BOX", (0, 0), (-1, -1), 0.7, color), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))


def code_block(code: str):
    escaped = html.escape(code).replace("\n", "<br/>").replace(" ", "&nbsp;")
    return Table([[Paragraph(escaped, styles["CodeX"])]], colWidths=[165 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.5, GRID), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))


def error_evidence(case_id: str, error_type: str):
    item = next(entry for entry in metrics["errors"] if entry["case_id"] == case_id)
    raw = raw_by_id[case_id]
    review = str(raw["response"].get("review", ""))
    review_excerpt = " ".join(review.splitlines()[1:6])[:650]
    verification = item["ground_truth_verification"] or {}
    if verification.get("kind") == "behavior":
        test_result = verification.get("test_result", {})
        evidence = f"Deterministic specification tests: {test_result.get('passed', 0)}/{test_result.get('total', 0)} passed. Ground-truth verification status: {verification.get('verified')}."
    else:
        evidence = f"Static verification `{verification.get('kind')}` matched its specified evidence pattern: {verification.get('pattern_matched')}."
    return [
        callout("Ground truth", f"Expected {raw['case']['expected_status']}; reviewer predicted {raw['response'].get('final_status')}. {evidence}", RED, PALE_RED),
        Paragraph("Requirement", styles["H2x"]),
        Paragraph(html.escape(item["requirement"]), styles["Bodyx"]),
        Paragraph("Reviewed code", styles["H2x"]),
        code_block(item["code"]),
        Paragraph("Reviewer explanation excerpt", styles["H2x"]),
        Paragraph(html.escape(review_excerpt), styles["Bodyx"]),
        Paragraph("Independent assistant adjudication", styles["H2x"]),
        Paragraph(html.escape(item["assistant_adjudication"]), styles["Bodyx"]),
    ]


reviewer = metrics["reviewer_metrics"]
matrix = reviewer["confusion_matrix"]

DESTINATION.parent.mkdir(parents=True, exist_ok=True)
BODY_PDF.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(BODY_PDF), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=22 * mm, bottomMargin=18 * mm, title="Bob Model Performance Evaluation", author="Bob IDE evaluation suite")
story = [Spacer(1, 7 * mm)]

story += [
    Paragraph("Bob Model Performance Evaluation", styles["ReportTitle"]),
    Paragraph("Qwen/Qwen2.5-Coder-7B-Instruct | 44 reviewer cases | 58 total live model calls | 6 August 2026", styles["Subtitle"]),
    metric_cards([
        ("Reviewer cases", "44", BLUE),
        ("Accuracy", pct(reviewer["accuracy"]), GREEN),
        ("False positives", str(matrix["fp"]), ORANGE),
        ("False negatives", str(matrix["fn"]), RED),
    ]),
    Spacer(1, 7 * mm),
    Paragraph("Executive summary", styles["H1x"]),
    Paragraph("The reviewer evaluation contains 44 chronologically ordered cases covering ordinary behavior, boundary defects, validation, security/privacy controls, and adversarial prompt-like content embedded inside code. The evidence exposes four genuine disagreements: two false negatives and two false positives. Labels were defined in versioned manifests and verified through deterministic behavior tests, explicit static evidence, or manifest-backed checks before model review.", styles["Bodyx"]),
    callout("Key finding", "The reviewer missed a reversed clamp and a substring SQL whitelist, while adversarial comments/string data caused it to reject two correct implementations. This indicates both semantic-analysis gaps and susceptibility to prompt-like content embedded in code.", ORANGE, colors.HexColor("#FFF4E5")),
    Spacer(1, 6 * mm),
    standard_table([
        ["Metric", "Value", "Interpretation"],
        ["Accuracy", pct(reviewer["accuracy"]), "Correct reviewer decisions"],
        ["Precision (FAIL)", pct(reviewer["precision_fail"]), "Predicted defects that were real"],
        ["Recall (FAIL)", pct(reviewer["recall_fail"]), "Real defects detected"],
        ["Specificity (PASS)", pct(reviewer["specificity_pass"]), "Valid code correctly accepted"],
        ["F1 (FAIL)", pct(reviewer["f1_fail"]), "Precision/recall balance"],
        ["MCC", f"{reviewer['matthews_correlation_coefficient']:.3f}", "Binary correlation quality"],
        ["Cohen's kappa", f"{reviewer['cohens_kappa_reviewer_vs_assistant']:.3f}", "Reviewer/assistant agreement"],
    ], [52 * mm, 34 * mm, 79 * mm]),
]

story += [PageBreak(), section("Evaluation design and ground truth"),
    Paragraph("The case timeline deliberately combines ordinary behavior, subtle boundary defects, security/privacy controls, and adversarial prompt-like content embedded inside code. The positive class is FAIL, meaning a real defect is present.", styles["Bodyx"]),
    standard_table([
        ["Evidence dimension", "Coverage", "Purpose"],
        ["Reviewer decisions", "44 PASS/FAIL cases", "Confusion matrix and binary classification metrics"],
        ["Behavior checks", "Restricted deterministic expressions", "Verify functional requirements without unrestricted execution"],
        ["Static checks", "Explicit security and API evidence patterns", "Verify safety-sensitive requirements"],
        ["Resilience checks", "Prompt-like comments and strings", "Measure reviewer resistance to untrusted source text"],
    ], [45 * mm, 55 * mm, 65 * mm]),
    Paragraph("Ground-truth controls", styles["H2x"]),
    Paragraph("Behavioral cases executed deterministic expressions after a restrictive AST safety gate. Static security cases required explicit evidence patterns such as os.system, ast.literal_eval, hmac.compare_digest, or shell=False argv construction. Every label has a retained verification record or manifest-backed assertion.", styles["Bodyx"]),
    Paragraph("Independent second evaluation", styles["H2x"]),
    Paragraph("Each case was independently inspected against its requirement, code, available deterministic evidence, and model decision. The resulting assistant-evaluation.json contains per-case adjudication and rubric scores. This provides a second evaluator but is not presented as a real human participant or blinded human study.", styles["Bodyx"]),
    metric_cards([
        ("Reviewer labels tracked", "44 / 44", GREEN),
        ("Assistant-reviewer agreement", pct(reviewer["accuracy"]), ORANGE),
        ("Cohen's kappa", f"{reviewer['cohens_kappa_reviewer_vs_assistant']:.3f}", BLUE),
        ("Generated code tests", "9 / 9", GREEN),
    ]),
    Paragraph("Generation findings", styles["H2x"]),
    Paragraph("All four generated Python tasks passed nine tests. Structured files_needed accuracy remained 50%, semantic target-file identification was 100%, and strict replan constraint accuracy was 50%.", styles["Bodyx"]),
]

story += [PageBreak(), section("Confusion and classification metrics"), chart_image("confusion-matrix", max_height=78 * mm), Spacer(1, 4 * mm), chart_image("classification-metrics", max_height=83 * mm)]
story += [PageBreak(), section("Performance by category and difficulty"), chart_image("category-accuracy", max_height=78 * mm), Spacer(1, 4 * mm), chart_image("difficulty-accuracy", max_height=72 * mm), Paragraph("Adversarial accuracy is 33.3% because two prompt-injection hard negatives were rejected. Category and difficulty charts use all 44 reviewer cases and show the sample count for each group.", styles["Bodyx"])]
story += [PageBreak(), section("Latency and token usage"), chart_image("reviewer-latency", max_height=76 * mm), Spacer(1, 4 * mm), chart_image("token-usage", max_height=70 * mm), Spacer(1, 3 * mm), Paragraph(f"The runtime reported {metrics['total_usage']['input_tokens']:,} input tokens, {metrics['total_usage']['output_tokens']:,} output tokens, and {metrics['total_usage']['total_tokens']:,} total tokens across 58 live model calls. USD cost remains unavailable because pricing was not configured.", styles["Bodyx"])]
story += [PageBreak(), section("Outcome timeline and class balance"), chart_image("reviewer-outcome-timeline", max_height=68 * mm), Spacer(1, 3 * mm), chart_image("class-distribution", max_height=62 * mm), Spacer(1, 3 * mm), standard_table([
    ["Type", "Case", "Independent finding"],
    *[[item["type"].replace("_", " ").upper(), item["case_id"], item["assistant_adjudication"]] for item in metrics["errors"]],
], [26 * mm, 53 * mm, 86 * mm], font_size=7.2), Paragraph("The timeline shows all 44 reviewer decisions in execution order. Orange points are false positives; red points are false negatives. Detailed evidence for each disagreement follows.", styles["Bodyx"])]

for case_id, label in [
    ("fail_clamp_reversed", "False negative 1 - reversed clamp"),
    ("fail_sql_substring_whitelist", "False negative 2 - substring whitelist"),
    ("fp_probe_comment_injection", "False positive 1 - adversarial comment"),
    ("fp_probe_fake_review_string", "False positive 2 - unused review-like string"),
]:
    story += [PageBreak(), section(label), *error_evidence(case_id, label.split(" - ")[0])]

representative = [
    "pass_sql_whitelisted_column", "pass_trusted_html_passthrough", "pass_command_argv_builder",
    "pass_literal_eval", "pass_constant_time_compare", "fp_probe_safe_subprocess",
]
story += [PageBreak(), section("Correct hard negatives and assistant review"),
    Paragraph("The reviewer correctly passed the following security-looking implementations. Their inclusion demonstrates that the two false positives were not caused by a blanket rule against all risky vocabulary or APIs.", styles["Bodyx"]),
    standard_table([
        ["Case", "Why the code is valid", "Reviewer"],
        *[[case_id, next(item["code_review"] for item in assistant_eval["evaluations"] if item["case_id"] == case_id), "PASS"] for case_id in representative],
    ], [48 * mm, 91 * mm, 26 * mm], font_size=7.2),
    Paragraph("Assistant rubric interpretation", styles["H2x"]),
    Paragraph("Correct reviewer decisions received 5/5 for reviewer correctness and groundedness. Each disagreement received 1/5 on those dimensions because the predicted class contradicted deterministic evidence. False negatives received 2/5 for reviewer safety; false positives received 3/5 because they blocked valid code rather than approving defective code.", styles["Bodyx"]),
    callout("Important", "These scores are assistant-authored analytical judgments. They must not be reported as independent human ratings. A final human study should use blinded raters and calculate inter-rater agreement.", ORANGE, colors.HexColor("#FFF4E5")),
]

rows = [["#", "Case", "Category", "Difficulty", "Expected", "Predicted", "Outcome"]]
for index, item in enumerate(metrics["reviewer_results"], start=1):
    expected, predicted = item["expected_status"], item["predicted_status"]
    outcome = "TP" if expected == predicted == "FAIL" else "TN" if expected == predicted == "PASS" else "FP" if expected == "PASS" else "FN"
    rows.append([index, item["case_id"], item["category"], item["difficulty"], expected, predicted, outcome])
story += [PageBreak(), section("Appendix - reviewer case timeline"), Paragraph("This table provides an auditable index from each case to its expected and predicted class. Full requirements, code, test evidence, and reviewer output are retained in the JSON evidence artifacts.", styles["Bodyx"]), standard_table(rows, [9 * mm, 51 * mm, 29 * mm, 22 * mm, 18 * mm, 19 * mm, 17 * mm], font_size=6.4)]

story += [PageBreak(), section("Conclusions and next evaluation steps"),
    Paragraph("Reviewer accuracy is 90.9%, with equal counts of false positives and false negatives. The error pattern is actionable: strengthen reviewer prompts and parsing against untrusted code comments/strings, add executable or symbolic checks for arithmetic expressions, and test exact whitelist semantics rather than relying on natural-language inspection alone.", styles["Bodyx"]),
    standard_table([
        ["Priority", "Action", "Expected benefit"],
        ["1", "Treat comments, docstrings, and string literals as untrusted review data", "Reduce prompt-injection false positives"],
        ["2", "Execute restricted deterministic reviewer tests when available", "Catch semantic false negatives such as reversed clamp logic"],
        ["3", "Add explicit exact-membership security rules", "Detect substring whitelist bypasses"],
        ["4", "Expand to JavaScript/React and multi-file changes", "Improve external validity beyond small Python functions"],
        ["5", "Collect blinded ratings from at least two people", "Create genuine human evaluation and inter-rater statistics"],
        ["6", "Configure local model pricing", "Calculate cost per review and per correct decision"],
    ], [18 * mm, 72 * mm, 75 * mm]),
    Paragraph("Limitations", styles["H2x"]),
    *[Paragraph(f"- {html.escape(item)}", styles["Bodyx"]) for item in metrics["limitations"]],
    callout("Evidence status", "All 44 labels have retained verification evidence or manifest-backed assertions. Metrics, per-case assistant adjudications, raw redacted model outputs, Python-generated charts, and CSV results are saved for independent audit.", GREEN, PALE_GREEN),
]

doc.build(story)

# Overlay page chrome after the body PDF is complete. This guarantees that
# full-width tables and graphics cannot obscure headers or page numbers.
reader = PdfReader(str(BODY_PDF))
writer = PdfWriter()
for page_number, page in enumerate(reader.pages, start=1):
    packet = io.BytesIO()
    overlay_canvas = canvas_module.Canvas(packet, pagesize=A4)
    width, height = A4
    overlay_canvas.setFillColor(colors.white)
    overlay_canvas.rect(0, height - 19 * mm, width, 19 * mm, fill=1, stroke=0)
    overlay_canvas.rect(0, 0, width, 15 * mm, fill=1, stroke=0)
    overlay_canvas.setFont("Helvetica-Bold", 8)
    overlay_canvas.setFillColor(NAVY)
    overlay_canvas.drawString(18 * mm, height - 10 * mm, "BOB IDE - MODEL PERFORMANCE EVALUATION")
    overlay_canvas.setStrokeColor(GRID)
    overlay_canvas.line(18 * mm, height - 14 * mm, width - 18 * mm, height - 14 * mm)
    overlay_canvas.setFont("Helvetica", 8)
    overlay_canvas.setFillColor(MID)
    overlay_canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {page_number}")
    overlay_canvas.save()
    packet.seek(0)
    page.merge_page(PdfReader(packet).pages[0], over=True)
    writer.add_page(page)
with DESTINATION.open("wb") as stream:
    writer.write(stream)
BODY_PDF.unlink(missing_ok=True)
print(DESTINATION)
