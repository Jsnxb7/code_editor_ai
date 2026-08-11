import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const VERSION = "1.0";
function iso() { return new Date().toISOString(); }
function read(file, key) { try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch (error) { if (error.code === "ENOENT") return { schema_version: VERSION, revision: 0, [key]: [] }; throw error; } }
function write(file, data) { fs.mkdirSync(path.dirname(file), { recursive: true }); data.revision = Number(data.revision || 0) + 1; const temp = `${file}.${process.pid}.${Date.now()}.tmp`; fs.writeFileSync(temp, `${JSON.stringify(data, null, 2)}\n`, "utf8"); fs.renameSync(temp, file); }
function redact(value) {
  let text = String(value || "");
  const rules = [
    [/\bBearer\s+[A-Za-z0-9._~+\/-]+=*/gi, "Bearer [REDACTED]"],
    [/\b(sk-|ghp_|github_pat_|hf_|ngrok_)[A-Za-z0-9_-]{12,}\b/gi, "[REDACTED_TOKEN]"],
    [/(password|passwd|api[_-]?key|secret|token)\s*[:=]\s*[^\s,;]+/gi, "$1=[REDACTED]"],
  ];
  for (const [pattern, replacement] of rules) text = text.replace(pattern, replacement);
  for (const secret of [process.env.BOB_COLAB_TOKEN, ...(String(process.env.BOB_REDACT_VALUES || "").split(","))].filter((item) => String(item || "").length > 0)) text = text.split(secret).join("[REDACTED_CONFIGURED_SECRET]");
  return text.slice(0, 100_000);
}
function sanitize(value, key = "") {
  if (["authorization", "cookie", "session_token", "password_hash", "token_hash", "code", "content", "files"].includes(key.toLowerCase())) return undefined;
  if (typeof value === "string") return redact(value);
  if (Array.isArray(value)) return value.map((item) => sanitize(item)).filter((item) => item !== undefined);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, sanitize(item, name)]).filter(([, item]) => item !== undefined));
  return value;
}
function reviewCategories(review) {
  const text = String(review || "").toLowerCase(); const categories = [];
  for (const [category, pattern] of [["security", /security|unsafe|secret|credential/], ["correctness", /incorrect|wrong|bug|fail/], ["completeness", /missing|incomplete|omits/], ["tests", /test|assert|coverage/], ["grounding", /context|hallucin|not found/]]) if (pattern.test(text)) categories.push(category);
  return categories.length ? categories : ["reviewer_failure"];
}

export class DevStore {
  constructor({ dataRoot, emit }) {
    this.root = path.join(dataRoot, "dev"); this.runtimeRoot = path.join(dataRoot, "runtime"); this.emit = emit;
    this.files = { dlq: path.join(this.root, "dlq.json"), reviews: path.join(this.root, "failed-reviews.json"), evaluations: path.join(this.root, "evaluations.json"), corrections: path.join(this.root, "corrections.json"), feedback: path.join(this.root, "feedback.json"), usage: path.join(this.root, "usage.json") };
  }
  appendLog(type, payload = {}) {
    fs.mkdirSync(this.runtimeRoot, { recursive: true }); const file = path.join(this.runtimeRoot, "events.jsonl");
    try { if (fs.statSync(file).size > 10 * 1024 * 1024) { const prior = `${file}.1`; try { fs.rmSync(prior); } catch {} fs.renameSync(file, prior); } } catch {}
    const safe = sanitize({ timestamp: iso(), type, ...payload }); delete safe.prompt;
    fs.appendFileSync(file, `${JSON.stringify(safe)}\n`, "utf8"); this.emit?.("audit:changed", { type, timestamp: safe.timestamp });
  }
  logs(query = {}) {
    const limit = Math.max(1, Math.min(Number(query.limit) || 300, 1000));
    const sourceFiles = {
      app: "events.jsonl",
      model: "model-events.jsonl",
      ngrok: "ngrok-events.jsonl",
    };
    const requestedSource = String(query.source || "app").toLowerCase();
    const sources = requestedSource === "all" ? Object.keys(sourceFiles) : [requestedSource];
    if (sources.some((source) => !sourceFiles[source])) return [];
    const records = [];
    for (const source of sources) {
      try {
        const lines = fs.readFileSync(path.join(this.runtimeRoot, sourceFiles[source]), "utf8").trim().split(/\r?\n/).filter(Boolean);
        for (const line of lines) {
          try { records.push({ source, ...JSON.parse(line) }); } catch {}
        }
      } catch (error) { if (error.code !== "ENOENT") throw error; }
    }
    return records.filter((item) => {
      const event = item.type || item.event;
      return (!query.type || event === query.type)
        && (!query.event || event === query.event)
        && (!query.request_id || item.request_id === query.request_id)
        && (!query.trace_id || item.trace_id === query.trace_id)
        && (!query.run_id || item.run_id === query.run_id)
        && (!query.actor_user_id || item.actor_user_id === query.actor_user_id);
    }).sort((left, right) => String(right.timestamp || right.finished_at || "").localeCompare(String(left.timestamp || left.finished_at || ""))).slice(0, limit);
  }
  list(kind) { const key = kind === "reviews" ? "reviews" : kind; return read(this.files[kind], key); }
  detail(kind, id) { const key = kind === "reviews" ? "reviews" : kind; const item = this.list(kind)[key].find((value) => value.id === id); if (!item) throw Object.assign(new Error("Developer record not found"), { status: 404 }); return item; }
  add(kind, record) { const key = kind === "reviews" ? "reviews" : kind; const data = read(this.files[kind], key); data[key].push(record); write(this.files[kind], data); this.emit?.(`${kind === "reviews" ? "review" : kind}:changed`, { revision: data.revision, id: record.id }); return record; }
  update(kind, id, updates) { const key = kind === "reviews" ? "reviews" : kind; const data = read(this.files[kind], key); const item = data[key].find((value) => value.id === id); if (!item) throw Object.assign(new Error("Developer record not found"), { status: 404 }); Object.assign(item, updates, { updated_at: iso() }); write(this.files[kind], data); this.emit?.(`${kind === "reviews" ? "review" : kind}:changed`, { revision: data.revision, id }); return item; }
  createDlq(payload) { return this.add("dlq", { id: `dlq_${crypto.randomUUID()}`, status: "open", attempts: [], created_at: iso(), updated_at: iso(), ...sanitize(payload), prompt: redact(payload.prompt), error: payload.error ? sanitize(payload.error) : null }); }
  createFailedReview(payload) { return this.add("reviews", { id: `review_${crypto.randomUUID()}`, status: "open", force_stage: null, failure_categories: reviewCategories(payload.review), created_at: iso(), updated_at: iso(), ...sanitize(payload), prompt: redact(payload.prompt), review: redact(payload.review) }); }
  recordForce(reviewId, payload) { return this.update("reviews", reviewId, { status: "force_staged", force_stage: { ...payload, created_at: iso() } }); }
  claimDlq(id, admin, category) { const item = this.detail("dlq", id); if (!["open", "in_review"].includes(item.status)) throw new Error("Only open DLQ records can be claimed"); return this.update("dlq", id, { status: "in_review", assigned_admin_id: admin.id, root_cause: category || "unknown" }); }
  dismissDlq(id, admin, reason) { const item = this.detail("dlq", id); if (!["open", "in_review"].includes(item.status)) throw new Error("This DLQ record is already resolved"); if (!String(reason || "").trim()) throw new Error("Dismissal reason is required"); return this.update("dlq", id, { status: "dismissed", resolved_by: admin.id, resolution: redact(reason) }); }
  correctDlq(id, admin, payload) {
    const dlq = this.list("dlq").dlq.find((item) => item.id === id); if (!dlq) throw Object.assign(new Error("DLQ record not found"), { status: 404 });
    if (dlq.status !== "in_review") throw new Error("Claim the DLQ record before correcting it");
    for (const field of ["corrected_prompt", "expected_behavior", "notes"]) if (!String(payload[field] || "").trim()) throw new Error(`${field} is required`);
    const correction = this.add("corrections", { id: `correction_${crypto.randomUUID()}`, source_type: "dlq", source_id: id, original_prompt: dlq.prompt, corrected_prompt: redact(payload.corrected_prompt), expected_behavior: redact(payload.expected_behavior), notes: redact(payload.notes), root_cause: payload.root_cause || dlq.root_cause || "unknown", severity: payload.severity || "medium", tags: Array.isArray(payload.tags) ? payload.tags.map(redact) : [], author_user_id: admin.id, created_at: iso(), updated_at: iso() });
    const evaluation = this.add("evaluations", { id: `evaluation_${crypto.randomUUID()}`, source_type: "correction", source_id: correction.id, prompt: correction.corrected_prompt, expected_behavior: correction.expected_behavior, status: "pending", revisions: [], created_at: iso(), updated_at: iso() });
    this.update("dlq", id, { status: "resolved_evaluation_created", correction_id: correction.id, evaluation_id: evaluation.id, resolved_by: admin.id }); return { correction, evaluation };
  }
  correctReview(id, admin, payload) {
    const review = this.detail("reviews", id);
    for (const field of ["corrected_prompt", "expected_behavior", "notes"]) if (!String(payload[field] || "").trim()) throw new Error(`${field} is required`);
    const correction = this.add("corrections", { id: `correction_${crypto.randomUUID()}`, source_type: "failed_review", source_id: id, original_prompt: review.prompt, corrected_prompt: redact(payload.corrected_prompt), expected_behavior: redact(payload.expected_behavior), notes: redact(payload.notes), root_cause: payload.root_cause || "review_failure", severity: payload.severity || "medium", tags: Array.isArray(payload.tags) ? payload.tags.map(redact) : [], author_user_id: admin.id, created_at: iso(), updated_at: iso() });
    const evaluation = this.add("evaluations", { id: `evaluation_${crypto.randomUUID()}`, source_type: "correction", source_id: correction.id, prompt: correction.corrected_prompt, expected_behavior: correction.expected_behavior, status: "pending", revisions: [], created_at: iso(), updated_at: iso() });
    this.update("reviews", id, { status: review.force_stage ? "force_staged_corrected" : "corrected", correction_id: correction.id, evaluation_id: evaluation.id });
    return { correction, evaluation };
  }
  createEvaluation(admin, payload) {
    const scores = payload.scores || {}; const normalizedScores = {}; for (const name of ["correctness", "helpfulness", "completeness", "safety", "groundedness"]) { const value = Number(scores[name]); if (!Number.isInteger(value) || value < 1 || value > 5) throw new Error(`${name} must be an integer from 1 to 5`); normalizedScores[name] = value; }
    if (!["acceptable", "needs_correction", "invalid_failure"].includes(payload.verdict)) throw new Error("Invalid evaluation verdict");
    for (const field of ["failure_category", "severity", "notes", "expected_behavior"]) if (!String(payload[field] || "").trim()) throw new Error(`${field} is required`);
    const revision = { id: crypto.randomUUID(), scores: normalizedScores, verdict: payload.verdict, failure_category: redact(payload.failure_category), severity: redact(payload.severity), notes: redact(payload.notes), expected_behavior: redact(payload.expected_behavior), corrected_prompt: payload.corrected_prompt ? redact(payload.corrected_prompt) : null, author_user_id: admin.id, created_at: iso() };
    const existing = payload.evaluation_id ? this.list("evaluations").evaluations.find((item) => item.id === payload.evaluation_id) : null;
    if (existing) return this.update("evaluations", existing.id, { status: "completed", revisions: [...existing.revisions, revision] });
    return this.add("evaluations", { id: `evaluation_${crypto.randomUUID()}`, source_type: payload.source_type || "manual", source_id: payload.source_id || null, prompt: redact(payload.prompt), expected_behavior: redact(payload.expected_behavior), status: "completed", revisions: [revision], created_at: iso(), updated_at: iso() });
  }
  recordFeedback(payload) { return this.add("feedback", { id: `feedback_${crypto.randomUUID()}`, created_at: iso(), ...sanitize(payload) }); }
  recordUsage(payload) { return this.add("usage", { id: `usage_${crypto.randomUUID()}`, created_at: iso(), ...sanitize(payload) }); }
  exportEvaluations() {
    const evaluations = this.list("evaluations").evaluations;
    return { schema_version: VERSION, exported_at: iso(), cases: evaluations.filter((item) => item.status === "completed").map((item) => ({ id: item.id, source_type: item.source_type, source_id: item.source_id, prompt: item.prompt, expected_behavior: item.expected_behavior, latest_revision: item.revisions.at(-1) })) };
  }
  overview() {
    const dlq = this.list("dlq").dlq; const reviews = this.list("reviews").reviews; const evaluations = this.list("evaluations").evaluations; const usage = this.list("usage").usage; const logs = this.logs({ limit: 1000 });
    const requests = logs.filter((item) => ["tool.call", "tool.error"].includes(item.type)); const errors = requests.filter((item) => item.type === "tool.error"); const durations = requests.map((item) => Number(item.duration_ms)).filter(Number.isFinite);
    return { open_dlq: dlq.filter((x) => ["open", "in_review"].includes(x.status)).length, failed_reviews: reviews.filter((x) => x.status !== "resolved").length, pending_evaluations: evaluations.filter((x) => x.status !== "completed").length, dlq_total: dlq.length, review_total: reviews.length, evaluation_total: evaluations.length, request_count: requests.length, error_count: errors.length, error_rate: requests.length ? errors.length / requests.length : 0, retry_rate: requests.length ? dlq.reduce((sum, item) => sum + Math.max(0, (item.attempts?.length || 1) - 1), 0) / requests.length : 0, average_latency_ms: durations.length ? Math.round(durations.reduce((sum, value) => sum + value, 0) / durations.length) : 0, input_tokens: usage.reduce((sum, item) => sum + Number(item.usage?.input_tokens || 0), 0), output_tokens: usage.reduce((sum, item) => sum + Number(item.usage?.output_tokens || 0), 0), estimated_cost_usd: usage.reduce((sum, item) => sum + Number(item.estimated_cost_usd || 0), 0) };
  }
}

export { redact };
