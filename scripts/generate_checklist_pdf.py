from __future__ import annotations

from pathlib import Path
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, LongTable, KeepTogether,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf" / "bob_ide_assignment_checklist_audit_updated.pdf"

NAVY = colors.HexColor("#14213D")
BLUE = colors.HexColor("#2563EB")
GREEN = colors.HexColor("#16845B")
GREEN_BG = colors.HexColor("#E9F7F1")
AMBER = colors.HexColor("#A45C00")
AMBER_BG = colors.HexColor("#FFF4DD")
GRAY = colors.HexColor("#586174")
GRAY_BG = colors.HexColor("#EEF1F5")
INK = colors.HexColor("#202636")
LIGHT = colors.HexColor("#F6F8FB")
LINE = colors.HexColor("#D9DFE8")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="CoverTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=28, leading=32, textColor=NAVY, spaceAfter=12))
styles.add(ParagraphStyle(name="CoverSub", parent=styles["Normal"], fontSize=12, leading=18, textColor=GRAY, spaceAfter=20))
styles.add(ParagraphStyle(name="Section", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceAfter=9))
styles.add(ParagraphStyle(name="Subsection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=NAVY, spaceBefore=7, spaceAfter=5))
styles.add(ParagraphStyle(name="BodySmall", parent=styles["BodyText"], fontSize=8.3, leading=11, textColor=INK))
styles.add(ParagraphStyle(name="Body", parent=styles["BodyText"], fontSize=9.4, leading=13.2, textColor=INK, spaceAfter=6))
styles.add(ParagraphStyle(name="Table", parent=styles["BodyText"], fontSize=7.1, leading=9.1, textColor=INK))
styles.add(ParagraphStyle(name="TableHead", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.1, leading=8.7, textColor=colors.white))
styles.add(ParagraphStyle(name="StatusP", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=8.5, alignment=TA_CENTER, textColor=GREEN))
styles.add(ParagraphStyle(name="StatusA", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=8.5, alignment=TA_CENTER, textColor=AMBER))
styles.add(ParagraphStyle(name="StatusN", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=8.5, alignment=TA_CENTER, textColor=GRAY))
styles.add(ParagraphStyle(name="Metric", parent=styles["BodyText"], fontSize=8, leading=11, textColor=GRAY, leftIndent=7, borderColor=LINE, borderWidth=0.5, borderPadding=6, backColor=LIGHT))


def row(item: str, status: str, finding: str, evidence: str = "") -> dict:
    return {"item": item, "status": status, "finding": finding, "evidence": evidence}


sections = [
    ("1. Agentic AI Foundations", [
        row("Has a planner", "P", "A dedicated plan stage produces a selectable plan before code generation.", "bob_core/model_service.py; capabilities.py"),
        row("Has at least two tools", "P", "The MCP catalogue exposes file, Git, worktree, model, context, test and workspace tools.", "capabilities.py; mcp_server.py"),
        row("Memory", "P", "Plans, runs, model stages, proposals, ownership and workflow artifacts persist in JSON stores.", "bob_core/*_store.py; node-server/auth-store.js"),
        row("Retry", "P", "Transient connection, timeout, HTTP 429 and HTTP 5xx failures retry at most three times with bounded exponential backoff and jitter.", "bob_core/colab_adapter.py"),
        row("Reflection", "P", "Replanning and a distinct reviewer stage inspect intermediate plans and code and return PASS or FAIL.", "bob_core/model_service.py"),
        row("Human approval", "P", "Reviewer-failed proposals are server-blocked from normal apply. Force Apply and Stage requires a reason, confirmation and one-time approval.", "bob_core/proposal_store.py; node-server/server.js"),
        row("Structured output", "P", "MCP and gateway responses use JSON, while external model boundaries use Pydantic v2 contracts.", "bob_core/contracts.py; mcp_server.py"),
        row("Error handling", "P", "Invalid input, model, tool and transport failures become structured errors, failed runs or DLQ records.", "bob_core/model_service.py; node-server/dev-store.js"),
        row("Logging", "P", "Request, model, tool, authentication, approval, evaluation and audit events are persisted with redaction.", "node-server/dev-store.js"),
    ], "Tool selection and step-efficiency metrics still require labeled expected decisions; reliability and operational outcomes are now captured."),

    ("2. LangChain, LangGraph and CrewAI", [
        row("Tool abstraction", "P", "Capabilities have stable names, generated descriptions, typed inputs and MCP schemas.", "capabilities.py; scripts/verify-api-contract.mjs"),
        row("Prompt templates", "P", "Planner, coder and reviewer templates are reusable and every run carries a prompt-set version.", "Untitled28_lightning_ai_bob_runtime.ipynb; bob_core/model_config.py"),
        row("State management", "P", "Run, plan, proposal, session, DLQ, correction, evaluation and feedback state uses versioned JSON with atomic updates.", "bob_core/json_store.py; node-server/*.js"),
        row("Retry", "P", "Transient Colab nodes use a fixed three-attempt retry policy and preserve attempt history.", "bob_core/colab_adapter.py"),
        row("Conditional routing", "P", "Execution branches through plan/replan, PASS/FAIL review, conflict handling, retry exhaustion and DLQ resolution.", "bob_core/model_service.py; node-server/dev-store.js"),
        row("Human node", "P", "Users review and apply proposals; Admins score failures and create correction/evaluation cases.", "frontend/src/components/DeveloperPanel.jsx"),
        row("Parallel execution", "P", "Independent background activity and realtime channels remain asynchronous; model notebook requests are intentionally serialized for GPU safety.", "node-server/server.js; Untitled28_lightning_ai_bob_runtime.ipynb"),
        row("Multi-agent design", "P", "Planner, coder and reviewer have distinct responsibilities and linked handoff artifacts.", "bob_core/model_service.py"),
    ], "Workflow completion, handoff accuracy and node-latency inputs are now stored; labeled quality baselines remain the next measurement step."),

    ("3. Practical Agent Integration", [
        row("Every tool documented", "P", "Every registered capability receives a non-empty description; contract tests fail when documentation is missing.", "capabilities.py; scripts/verify-api-contract.mjs"),
        row("Input schema", "P", "FastMCP generates typed input schemas and the server validates ownership and high-risk approvals.", "mcp_server.py; node-server/server.js"),
        row("Output schema", "P", "Tools return structured JSON and gateway responses consistently use ok/data or ok/error envelopes.", "mcp_server.py; node-server/server.js"),
        row("Retry", "P", "The external Colab tool boundary retries only transient failures and preserves exact transport attempts.", "bob_core/colab_adapter.py"),
        row("Timeout", "P", "Model and execution calls retain bounded timeouts; long model stages do not inherit a short gateway timeout.", "bob_core/colab_adapter.py; node-server/config.js"),
        row("Authentication", "P", "REST, MCP gateway, Socket.IO, LSP and terminal application access require a valid server session.", "node-server/server.js; lsp.js; terminal.js"),
        row("Cost", "A", "Model token cost can be calculated from configured pricing, but generalized per-tool and infrastructure cost attribution is not implemented.", "bob_core/model_config.py; node-server/dev-store.js"),
        row("Latency", "P", "Gateway tools and model stages record start/end timestamps, durations and attempt counts.", "node-server/server.js; bob_core/model_service.py"),
        row("Security", "P", "Ownership, path containment, CSRF, RBAC, one-time approvals and input validation protect application tools.", "node-server/server.js; auth-store.js"),
    ], "API success, retry recovery, duration and error-rate inputs are available. Semantic argument-accuracy scoring still belongs in the evaluation dataset."),

    ("4. Retrieval-Augmented Generation", [
        row("Chunking", "N", "The current agent uses selected workspace files rather than document chunk retrieval."),
        row("Metadata", "N", "No retrieval index exists; context metadata is used for diagnostics, not semantic retrieval."),
        row("Embedding", "N", "No embedding model is required for the current staged coding workflow."),
        row("Vector database", "N", "A vector store is unnecessary at the current repository scale and product scope."),
        row("Citation", "N", "The workflow produces code proposals rather than evidence-linked RAG answers."),
        row("Source display", "N", "The IDE already displays selected files and diffs, not retrieved document sources."),
        row("Hybrid search", "N", "Hybrid semantic/keyword retrieval is only useful after an indexed corpus is introduced."),
        row("Re-ranking", "N", "No retrieval candidate list exists to re-rank."),
    ], "RAG metrics remain out of scope until Bob gains large-corpus repository or document question-answering."),

    ("5. Structured Outputs", [
        row("JSON output", "P", "MCP, gateway, run, DLQ, correction, evaluation and notebook responses are JSON."),
        row("Validation", "P", "Invalid status, score, model, usage, header and configuration values are rejected."),
        row("Pydantic model", "P", "Pydantic v2 models validate plan, code, review, usage, error, DLQ, correction and evaluation shapes.", "bob_core/contracts.py"),
        row("Required fields", "P", "Authentication, approvals, corrections and human evaluations enforce required values server-side.", "node-server/auth-store.js; dev-store.js"),
        row("Error messages", "P", "Clients receive safe, understandable errors while sensitive technical details remain out of HTTP responses."),
    ], "Contract tests cover the complete tool catalogue; additional malformed external-model fixtures can deepen field-accuracy measurement."),

    ("6. Classification Evaluation", [
        row("Confusion matrix", "P", "The consolidated three-approach evaluation contains 534 scored results: TP 62, FN 164, FP 10 and TN 298.", "output/evals/consolidated/consolidated_verification.json"),
        row("Accuracy", "P", "Reviewer accuracy is 67.4% across the consolidated approach results."),
        row("Precision", "P", "FAIL-class precision is 86.1%, measuring how often a predicted defect is real."),
        row("Recall", "P", "FAIL-class recall is 27.4%, showing that missed defects are the dominant current error mode."),
        row("F1", "P", "FAIL-class F1 is 41.6%; the complete matrix and reproducible charts are retained in the consolidated evidence."),
        row("Macro average", "N", "The reviewer decision is binary; per-class metrics and balanced accuracy are more directly interpretable."),
        row("Weighted average", "N", "The binary evaluation reports class counts, precision, recall, specificity, F1 and MCC directly."),
    ], "The positive class is FAIL (a defect is present). Python-generated charts, per-case CSV evidence and detailed FP/FN adjudications are included in the evaluation appendix."),

    ("7. Agent Evaluation", [
        row("Tool selection", "A", "Tool calls are logged, but the current datasets do not yet label the expected tool for every scenario."),
        row("Tool arguments", "A", "Schemas validate shape; semantic argument correctness still needs expected-value assertions."),
        row("Planning", "A", "Offline cases validate deterministic plan contracts, but plan quality is not yet scored against gold steps."),
        row("Memory", "A", "Workflow memory persists, but useful recall versus unnecessary context is not benchmarked."),
        row("Hallucination", "A", "No automated unsupported-claim or invented-file detector is present."),
        row("Grounding", "A", "Human groundedness scores exist, but automatic evidence linkage is not yet evaluated."),
        row("Task success", "P", "Four generated-code tasks passed all nine deterministic tests; broader JavaScript, React and multi-file coverage remains addable."),
        row("Human approval", "P", "Protected force actions cannot bypass server-issued, user-, workspace-, operation- and target-bound approval tokens."),
    ], "Reviewer classification and generated-code task success are measured. Tool choice, semantic argument quality, plan scoring and memory quality remain the next agent-evaluation layer."),

    ("8. Human Evaluation", [
        row("Correctness", "P", "Admins assign a required integer score from 1 to 5 and revisions are preserved."),
        row("Helpfulness", "P", "The Admin evaluation rubric stores a 1-5 helpfulness score."),
        row("Completeness", "P", "The Admin evaluation rubric stores a 1-5 completeness score."),
        row("Safety", "P", "The rubric stores safety, severity, failure category and expected behavior."),
        row("Tone", "A", "Tone is not part of the current five-dimension rubric; add it if chat quality becomes a priority."),
        row("Groundedness", "P", "The rubric stores a required 1-5 groundedness score."),
        row("Citation quality", "N", "Formal citations are not part of the current coding-proposal workflow."),
    ], "Evaluations require verdict, category, severity, notes and expected behavior. Revisions remain append-only within the entity."),

    ("9. Debugging", [
        row("Trace", "P", "Request ID, run/trace ID and user identity propagate through gateway model calls, run records and notebook responses."),
        row("Prompt", "P", "Redacted original prompts, corrected prompts and prompt-set versions are stored for quality review."),
        row("Tool logs", "P", "Tool name, argument field names/sizes, identity, result, duration, request/trace IDs and retry count are logged."),
        row("Token logs", "P", "Input, output and total token usage is captured when the runtime/provider returns it."),
        row("Error logs", "P", "Typed errors include component, stage, time, request context, retryability and attempt history."),
        row("Stack trace", "A", "Safe errors are returned and redacted messages are logged; a restricted server-only traceback store is intentionally not yet implemented."),
        row("Root cause", "P", "Admin DLQ review requires a root-cause category and correction/dismissal remains auditable."),
    ], "The supported IDE path can now be diagnosed from request through model stages and DLQ. Sensitive tracebacks remain a deliberate follow-up control."),

    ("10. Observability", [
        row("Prompt logs", "P", "Redacted prompt records include prompt/model versions and linked run, DLQ, review and evaluation IDs."),
        row("Tool logs", "P", "A rotating JSONL event stream records redacted request and tool activity."),
        row("Token usage", "P", "Stage and aggregate input/output/total tokens are persisted."),
        row("Latency", "P", "Tool and stage durations feed the Developer Panel overview."),
        row("Errors", "P", "Error frequency, typed errors, retries, failed reviews and open DLQ items are visible."),
        row("Cost", "P", "USD estimates are calculated when input/output token prices are configured."),
        row("User feedback", "P", "Apply, discard and force-apply decisions are persisted as accepted, rejected or force-applied feedback."),
    ], "The Admin dashboard provides local/demo operational visibility. P50/P95/P99, alerting and external uptime monitoring remain production enhancements."),

    ("11. LLMOps", [
        row("Prompt version", "P", "Every model stage can carry BOB_PROMPT_SET_VERSION and stores the effective version."),
        row("Dataset version", "P", "The versioned canonical manifest contains 178 live variants, 74 source requirements, 74 as-is/naturalized pairs and 12 offline cases with stable IDs.", "evals/consolidated_cases.json"),
        row("Model version", "P", "Provider, model ID, model revision and runtime contract version are recorded."),
        row("Evaluation pipeline", "P", "npm test runs software tests, tool contracts, notebook validation, 12 offline evaluations, lint and build."),
        row("A/B testing", "A", "No paired prompt/model comparison or traffic split is implemented."),
        row("Rollback", "A", "Git can restore source, but there is no one-command release, model or prompt rollback workflow."),
        row("Monitoring", "A", "The Developer Panel tracks local events, but continuous quality sampling, alert thresholds and external monitoring are not implemented."),
    ], "Regression inputs, acceptance feedback and failure telemetry now exist. A/B comparison, quality thresholds and release rollback are the next LLMOps layer."),

    ("12. Cloud Deployment", [
        row("Docker", "A", "No Dockerfile or compose/orchestration package exists."),
        row("API", "P", "Node REST/Socket.IO, Python MCP and staged Lightning/Colab HTTP endpoints expose core functionality."),
        row("HTTPS", "P", "The public notebook runtime uses an HTTPS ngrok tunnel; local services remain loopback HTTP."),
        row("Secrets", "P", "Passwords are hashed and the Colab bearer token is environment-only; notebook output and pasted secret cells were removed."),
        row("Load balancer", "N", "A single trusted local/demo instance does not require traffic distribution."),
        row("Autoscaling", "N", "Autoscaling is unnecessary until hosted demand and service objectives justify it."),
        row("Monitoring", "A", "Application metrics exist, but no cloud resource monitoring or alert service consumes them."),
        row("Logging", "P", "Runtime and deployment-facing events are retained in rotating structured JSONL for the local deployment boundary."),
    ], "The notebook is suitable for a supervised Lightning/Colab demo. Containers, durable shared storage and cloud monitoring are still required for production hosting."),

    ("13. Privacy, Security and Responsible AI", [
        row("Authentication", "P", "First-run Admin setup, bcrypt cost 12, opaque server-side sessions, HttpOnly SameSite=Strict cookies and login throttling are implemented."),
        row("Authorization", "P", "Every non-public gateway route and realtime workspace join enforces identity and workspace ownership."),
        row("PII detection", "A", "Secrets are redacted, but configurable PII detection for names, contact details and identifiers is not implemented."),
        row("Encryption", "A", "HTTPS protects the tunnel, but local JSON state is not encrypted at rest."),
        row("Secret management", "P", "The Colab bearer is accepted only from BOB_COLAB_TOKEN; password/session secrets are hashed and never returned."),
        row("RBAC", "P", "Admin and User roles are enforced server-side for developer operations and hidden appropriately in the UI."),
        row("Human approval", "P", "High-risk force actions require a reason, explicit confirmation and a one-time server approval."),
        row("Audit logs", "P", "Authentication, user changes, ownership, approvals and developer actions are identity-linked in rotating append-only JSONL."),
    ], "The result is a strong trusted local/demo boundary, not hardened remote multi-tenancy. The integrated OS terminal remains outside tenant isolation."),
]


production = [
    row("Architecture - Diagram", "P", "README documents the frontend, Node gateway, Python MCP and Lightning/Colab runtime flow."),
    row("Architecture - Components", "P", "Code and docs separate UI, authentication/gateway, capability, model and persistence responsibilities."),
    row("Architecture - Workflow", "P", "Plan -> select/replan -> code -> review -> proposal -> apply/DLQ/evaluation is implemented."),
    row("AI - Agent", "P", "Bob provides supervised agentic coding inside a reviewable IDE workflow."),
    row("AI - Planner", "P", "Planning and replanning stages are explicit and persisted."),
    row("AI - Tools", "P", "A documented MCP capability registry exposes deterministic actions."),
    row("AI - Memory", "P", "Workflow, identity, ownership and quality records persist in versioned JSON."),
    row("AI - RAG", "N", "RAG is unnecessary for the current selected-file coding workflow."),
    row("Evaluation - Dataset", "P", "Forty-four reviewer cases share one ordered timeline, with generated-code and replan cases retained in versioned manifests."),
    row("Evaluation - Metrics", "P", "Confusion matrix, accuracy, precision, recall, specificity, F1, balanced accuracy, MCC, latency, token usage and task-test results are available."),
    row("Evaluation - Human evaluation", "P", "Admin evaluations preserve 1-5 rubric revisions and verdict metadata."),
    row("Debugging - Logs", "P", "Redacted request/tool/model/auth/audit events are persisted."),
    row("Debugging - Traces", "P", "Request, trace/run and user IDs link gateway, model and notebook stages."),
    row("Debugging - Errors", "P", "Structured errors and immutable DLQ attempt histories are retained."),
    row("Deployment - Docker", "A", "No reproducible container package exists."),
    row("Deployment - Cloud", "P", "Lightning/Colab plus authenticated HTTPS ngrok is implemented for supervised model compute."),
    row("Deployment - Monitoring", "A", "Local operational metrics exist; cloud resource monitoring and alerting do not."),
    row("Security - Authentication", "P", "State-safe user login, setup, sessions, CSRF and logout are implemented."),
    row("Security - Authorization", "P", "RBAC and workspace ownership are enforced at gateway and realtime boundaries."),
    row("Security - Secrets", "P", "Passwords/sessions are hashed and BOB_COLAB_TOKEN is environment-only."),
    row("Security - Encryption", "A", "At-rest encryption and a managed key lifecycle are not implemented."),
    row("Reliability - Retry", "P", "Transient Colab calls retry exactly three times before DLQ."),
    row("Reliability - Timeout", "P", "Model and command boundaries use bounded timeouts."),
    row("Reliability - Fallback", "P", "Safe unconfigured responses, chat fallback and recoverable proposal/Git flows remain available."),
    row("Reliability - Cache", "A", "No deterministic result cache exists; add only after invalidation and privacy rules are defined."),
    row("Cost - Tokens", "P", "Input/output/total tokens are captured by the v4 notebook and local adapter."),
    row("Cost - Latency", "P", "Stage/request/tool duration is recorded and summarized."),
    row("Cost - Model routing", "A", "A single configured model endpoint is used; routing needs comparative evaluation first."),
    row("Cost - Cache", "A", "No computation cache is implemented."),
    row("Documentation - README", "P", "Comprehensive setup, operation and troubleshooting documentation exists."),
    row("Documentation - API", "P", "MCP catalogue, schemas, routes and notebook capabilities are exposed and contract-tested."),
    row("Documentation - Architecture", "P", "Migration, integration and handoff documents explain system decisions."),
    row("Documentation - Demo", "P", "Sample workspaces, first-run setup UI and notebook run instructions support demonstrations."),
    row("Documentation - Future work", "P", "Explicit scope limitations and follow-up controls are documented in the audit and project docs."),
]


all_rows = [item for _, rows, _ in sections for item in rows] + production
counts = {code: sum(1 for item in all_rows if item["status"] == code) for code in ("P", "A", "N")}
assert len(all_rows) == 132, len(all_rows)
assert counts == {"P": 96, "A": 22, "N": 14}, counts


def status_label(code: str) -> str:
    return {"P": "CHECKED", "A": "CAN ADD", "N": "NOT NEEDED"}[code]


def status_style(code: str):
    return {"P": styles["StatusP"], "A": styles["StatusA"], "N": styles["StatusN"]}[code]


def status_bg(code: str):
    return {"P": GREEN_BG, "A": AMBER_BG, "N": GRAY_BG}[code]


def table_for(rows: list[dict], widths=None):
    widths = widths or [39 * mm, 24 * mm, 116 * mm]
    data = [[Paragraph("CHECKLIST ITEM", styles["TableHead"]), Paragraph("STATUS", styles["TableHead"]), Paragraph("PROJECT FINDING / EVIDENCE OR ACTION", styles["TableHead"])]]
    for item in rows:
        finding = item["finding"]
        if item.get("evidence"):
            finding += f"<br/><font color='#586174'><b>Evidence:</b> {item['evidence']}</font>"
        data.append([
            Paragraph(item["item"], styles["Table"]),
            Paragraph(status_label(item["status"]), status_style(item["status"])),
            Paragraph(finding, styles["Table"]),
        ])
    table = LongTable(data, colWidths=widths, repeatRows=1, splitByRow=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for index, item in enumerate(rows, 1):
        commands.append(("BACKGROUND", (1, index), (1, index), status_bg(item["status"])))
        if index % 2 == 0:
            commands.append(("BACKGROUND", (0, index), (0, index), LIGHT))
            commands.append(("BACKGROUND", (2, index), (2, index), LIGHT))
    table.setStyle(TableStyle(commands))
    return table


def header_footer(canvas, doc):
    canvas.saveState()
    width, height = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(16 * mm, height - 13 * mm, width - 16 * mm, height - 13 * mm)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(NAVY)
    canvas.drawString(16 * mm, height - 10 * mm, "BOB IDE - MODULE 10 CHECKLIST AUDIT - UPDATED")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(GRAY)
    canvas.drawRightString(width - 16 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def metric_cards():
    values = [
        ("CHECKED", counts["P"], GREEN, GREEN_BG),
        ("CAN ADD", counts["A"], AMBER, AMBER_BG),
        ("NOT NEEDED", counts["N"], GRAY, GRAY_BG),
        ("TOTAL REVIEWED", len(all_rows), BLUE, colors.HexColor("#EAF1FF")),
    ]
    cells = []
    for label, value, color, bg in values:
        cells.append(Paragraph(f"<font color='{color.hexval()}'><b>{value}</b></font><br/><font size='7'>{label}</font>", ParagraphStyle(name=f"card-{label}", parent=styles["Body"], alignment=TA_CENTER, fontSize=16, leading=18, textColor=INK)))
    table = Table([cells], colWidths=[43 * mm] * 4, rowHeights=[25 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), values[0][3]), ("BACKGROUND", (1, 0), (1, 0), values[1][3]), ("BACKGROUND", (2, 0), (2, 0), values[2][3]), ("BACKGROUND", (3, 0), (3, 0), values[3][3]), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    return table


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=18 * mm, bottomMargin=15 * mm, title="Bob IDE Module 10 Checklist Audit - Updated")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(PageTemplate(id="audit", frames=[frame], onPage=header_footer))
    story = []

    story += [Spacer(1, 18 * mm), Paragraph("Agentic AI, LLMOps, Cloud<br/>Deployment and Privacy", styles["CoverTitle"]), Paragraph("Updated project checklist audit for Bob IDE", styles["CoverSub"]), Spacer(1, 5 * mm)]
    story.append(Paragraph("A code-evidenced reassessment after implementing authentication, private workspace ownership, role-based developer operations, exhausted-retry DLQ handling, prompt correction, human evaluation, structured telemetry and the Lightning/Colab v4 runtime contract.", styles["Body"]))
    story.append(Spacer(1, 8 * mm))
    story.append(metric_cards())
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("Status key", styles["Subsection"]))
    story.append(Paragraph("<b><font color='#16845B'>CHECKED</font></b> - directly evidenced in the current repository. &nbsp;&nbsp; <b><font color='#A45C00'>CAN ADD</font></b> - relevant and feasible but absent or incomplete. &nbsp;&nbsp; <b><font color='#586174'>NOT NEEDED</font></b> - outside the current product scope; reconsider if scope changes.", styles["Body"]))
    today = date.today()
    story.append(Paragraph(f"Assessment date: {today.day} {today.strftime('%B %Y')}. Repository: code_editor_ai. Source: the supplied 20-page Module 10 checklist PDF.", styles["BodySmall"]))
    story.append(PageBreak())

    story += [Paragraph("Executive reassessment", styles["Section"]), Paragraph("Bob IDE now satisfies the planned local/demo authentication and governance boundary. The largest gains are server-side identity and ownership enforcement, retry/DLQ reliability, Admin-only quality operations, human evaluation, prompt/model/version telemetry, user feedback and a hardened Lightning/Colab notebook contract.", styles["Body"]), metric_cards(), Spacer(1, 5 * mm)]
    delta = Table([
        [Paragraph("MEASURE", styles["TableHead"]), Paragraph("PREVIOUS AUDIT", styles["TableHead"]), Paragraph("UPDATED", styles["TableHead"]), Paragraph("CHANGE", styles["TableHead"])],
        ["Checked", "40", "96", "+56"], ["Can add", "72", "22", "-50"], ["Not needed", "20", "14", "-6"],
    ], colWidths=[55 * mm, 38 * mm, 38 * mm, 38 * mm])
    delta.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("ALIGN", (1, 1), (-1, -1), "CENTER"), ("GRID", (0, 0), (-1, -1), 0.5, LINE), ("BACKGROUND", (0, 1), (-1, -1), LIGHT), ("FONTSIZE", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [delta, Spacer(1, 5 * mm), Paragraph("Newly completed controls", styles["Subsection"])]
    for text in [
        "First-run Admin setup, bcrypt password storage, opaque server sessions, CSRF, expiry/revocation and login throttling.",
        "Admin/User RBAC, owner-only workspaces and authenticated REST, MCP gateway, Socket.IO, LSP and terminal application boundaries.",
        "Three-attempt transient retry, dlq_pending runs, immutable attempt history and Admin correction/dismissal workflow.",
        "Failed-review quality records plus user-controlled Force Apply and Stage with a reason and one-time approval token.",
        "Five-dimension human evaluation with revisions, prompt corrections, exports and a versioned evaluation dataset.",
        "Redacted request/tool/model/auth/audit JSONL, usage/cost/latency summaries and accepted/rejected/force-applied feedback.",
        "Lightning/Colab v4 contract with mandatory bearer authentication, serialized GPU requests, usage, tracing and safe errors.",
    ]:
        story.append(Paragraph(f"- {text}", styles["Body"]))
    story.append(Paragraph("Verification", styles["Subsection"]))
    story.append(Paragraph("The repository verification command passed Python and Node tests, frontend/Python tool contracts, notebook validation, offline evaluations, frontend lint and the production build. The model evidence appendix separately records 44 live reviewer cases, nine generated-code assertions and redacted runtime telemetry.", styles["Body"]))
    story.append(PageBreak())

    for title, rows, metric in sections:
        story += [Paragraph(title, styles["Section"]), table_for(rows), Spacer(1, 4 * mm), Paragraph(f"<b>Metric coverage:</b> {metric}", styles["Metric"]), PageBreak()]

    story += [Paragraph("14. Production Readiness", styles["Section"]), Paragraph("This consolidates the source checklist's architecture, AI, evaluation, debugging, deployment, security, reliability, cost and documentation review.", styles["Body"]), table_for(production), PageBreak()]

    story += [Paragraph("Production AI design review", styles["Section"])]
    reviews = [
        ("1. Why does this need an LLM?", "The LLM interprets open-ended coding requests, plans multi-file changes, generates code and critiques it. Identity, ownership, schemas, path safety, retries, approval and Git staging remain deterministic."),
        ("2. What decisions are delegated?", "Delegated: plan content, generated code and reviewer judgment. Deterministic: access control, workspace ownership, retry policy, validation, proposal state, approval consumption and file/Git mutation."),
        ("3. Five likely failure modes", "Incorrect plan; missing context; unsafe or malformed code; Lightning/ngrok outage; and a reviewer-failed proposal being forced by a user. Each now has a visible control or audit record."),
        ("4. How are failures detected?", "Pydantic validation, structured errors, reviewer PASS/FAIL, hash conflicts, retry exhaustion, DLQ creation, feedback, health endpoints and Admin quality records."),
        ("5. How does the system recover?", "Replan, safe fallback, three transient attempts, DLQ classification/correction, proposal discard, Git restore and explicit user-owned Force Apply and Stage."),
        ("6. How do we know a version is better?", "The versioned reviewer dataset, confusion metrics, generated-code tests, human revisions, feedback and telemetry establish a measurable baseline. Paired A/B evaluation is still needed for causal model or prompt comparisons."),
        ("7. How are data and secrets protected?", "The app uses sessions, RBAC, ownership, CSRF, redaction and environment-only bearer configuration. PII detection and encryption at rest remain open."),
        ("8. Cost per successful task", "Token cost can now be estimated when prices are configured and acceptance feedback is stored. A report joining cost to accepted executable task success remains addable."),
        ("9. What breaks from 10 to 1 million users?", "Local JSON, single-process Node/Python services, the serialized GPU runtime, ngrok, provider quotas and lack of load balancing, autoscaling, databases and distributed queues."),
        ("10. Would a customer trust it?", "For a supervised local/demo workflow, substantially more than before. For remote production, Docker/cloud operations, PII controls, encryption, alerts, backups and hardened OS isolation remain required."),
    ]
    for heading, body in reviews:
        story += [Paragraph(heading, styles["Subsection"]), Paragraph(body, styles["Body"])]
    story.append(PageBreak())

    story += [Paragraph("Recommended next additions", styles["Section"])]
    roadmap = [
        ("1. Agent-quality evaluation", "Add gold tool selections, argument assertions, plan-quality anchors and broader executable acceptance tests to the reviewer and generated-code evidence."),
        ("2. Privacy and encrypted persistence", "Add configurable PII detection, data retention/deletion rules and encryption-at-rest key management."),
        ("3. Production monitoring", "Add percentile metrics, health/resource collection, alert thresholds, uptime checks and incident runbooks."),
        ("4. Reproducible deployment", "Containerize the frontend/gateway/MCP services, define durable storage/backups and add CI/CD plus rollback."),
        ("5. Comparative LLMOps", "Add paired prompt/model experiments, regression thresholds and cost-per-accepted-task reporting before model routing."),
    ]
    for heading, body in roadmap:
        story.append(KeepTogether([Paragraph(heading, styles["Subsection"]), Paragraph(body, styles["Body"])]))
    story += [Spacer(1, 7 * mm), Paragraph("Scope decisions", styles["Subsection"]), Paragraph("RAG, load balancing and autoscaling remain unnecessary for the current selected-file, trusted local/demo IDE. Binary classification metrics now apply to the reviewer PASS/FAIL decision. RBAC is implemented, while the integrated terminal remains explicitly outside hardened multi-tenant OS isolation.", styles["Body"])]

    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    build()
