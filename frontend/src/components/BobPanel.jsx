import {
  Bot,
  Check,
  CheckCircle2,
  Code2,
  FilePlus2,
  FileText,
  FolderOpen,
  Layers,
  Link2,
  ListChecks,
  MessageSquare,
  Play,
  PlugZap,
  RefreshCw,
  Save,
  Send,
  Settings2,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useIde } from "../context/IdeContext";
import { getSocket } from "../socket";

const STAGE_MODES = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "plan", label: "Plan", icon: ListChecks },
  { id: "code", label: "Code", icon: Code2 },
  { id: "direct", label: "Direct", icon: Sparkles },
  { id: "review", label: "Review", icon: CheckCircle2 },
  { id: "agent", label: "Run All", icon: Play },
];

const PANEL_TABS = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "plans", label: "Plans", icon: ListChecks },
  { id: "context", label: "Context", icon: Layers },
  { id: "config", label: "Config", icon: Settings2 },
];

let msgSeq = 0;
const nextId = () => ++msgSeq;

const emptyConfig = {
  base_url: "",
  health_path: "/health",
  capabilities_path: "/capabilities",
  chat_path: "/chat",
  plan_path: "/plan",
  replan_path: "/replan",
  code_path: "/code",
  review_path: "/review",
  run_path: "/run-agent",
  stream_path: "/run-agent/stream",
  run_status_path: "/runs/{run_id}",
  cancel_path: "/runs/{run_id}/cancel",
  timeout: 600,
  max_iterations: 5,
  context_mode: "workspace",
  context_budget: 160000,
  prefer_streaming: true,
  keep_model_loaded: true,
  prompt_set_version: "unversioned",
  model_id: "unknown",
  model_revision: "unknown",
  input_token_price_per_million: 0,
  output_token_price_per_million: 0,
  headers_json: "{}",
  configured: false,
  token_set: false,
};

function normalizePath(path) {
  return String(path || "").replace(/\\\\/g, "/").trim().replace(/^\/+/, "");
}

function formatBytes(value = 0) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function FileChips({ files, onRemove }) {
  const entries = Object.entries(files || {});
  return (
    <div className="bob-context-chip-group">
      <span>Forced files sent as text</span>
      <div className="bob-context-chips">
        {entries.map(([path, meta]) => (
          <button key={path} className={`bob-context-chip ${meta.error ? "error" : ""}`} onClick={() => onRemove(path)} title={meta.error || "Remove from forced context"}>
            <FileText size={12} />
            <span className="bob-chip-path">{path}</span>
            <small>{meta.error ? "denied" : formatBytes(meta.content?.length || 0)}</small>
            <X size={11} />
          </button>
        ))}
        {!entries.length && <small>No forced files. Add active file, open tabs, or a picked path.</small>}
      </div>
    </div>
  );
}

function PlanCard({ record, selected, onSelect, onReplan, onCode, onDiscard, onAddRequested }) {
  const plan = record?.plan || {};
  const files = [...new Set([...(plan.files_needed || []), ...(plan.required_context || []), ...(plan.files_to_modify || []), ...(plan.files_to_create || [])])];
  return (
    <div className={`bob-plan-card ${selected ? "selected" : ""}`}>
      <div className="bob-plan-card-head">
        <strong>{record.plan_id}</strong>
        <span>{record.status}</span>
      </div>
      <p>{plan.summary || "Plan ready"}</p>
      <div className="bob-plan-meta">
        <span>{plan.task_type || "task"}</span>
        <span>{Math.round(Number(plan.confidence || 0) * 100)}% confidence</span>
        <span>{files.length} file{files.length === 1 ? "" : "s"}</span>
      </div>
      {!!files.length && <div className="bob-plan-files">{files.slice(0, 10).join(", ")}{files.length > 10 ? "..." : ""}</div>}
      <div className="bob-plan-actions">
        <button onClick={() => onSelect(record.plan_id)}><Check size={12} /> Select</button>
        <button onClick={() => onAddRequested(files)}><FilePlus2 size={12} /> Add requested</button>
        <button onClick={() => onReplan(record.plan_id)}><RefreshCw size={12} /> Replan</button>
        <button onClick={() => onCode(record.plan_id)}><Code2 size={12} /> Code</button>
        <button className="danger" onClick={() => onDiscard(record.plan_id)}><X size={12} /> Discard</button>
      </div>
    </div>
  );
}

function RunDetails({ message, onOpenProposal, onOpenSourceControl }) {
  const run = message.run || {};
  const finalStatus = run.final_status;
  return (
    <div className="bob-structured">
      <div className="bob-run-heading">
        <Bot size={15} />
        <strong>{message.status === "completed" ? "Run complete" : message.status}</strong>
        {finalStatus === "PASS" && <CheckCircle2 size={15} className="status-pass" />}
        {finalStatus === "FAIL" && <XCircle size={15} className="status-fail" />}
      </div>
      <small>{message.run_id}</small>
      {run.plan?.summary && <p>{run.plan.summary}</p>}
      {run.review && (
        <div className={`bob-review review-${finalStatus?.toLowerCase()}`}>
          <strong>Review: {finalStatus}</strong>
          <p>{run.review.replace(/^(PASS|FAIL)\s*/i, "")}</p>
        </div>
      )}
      {!!run.linked_files?.length && (
        <>
          <div className="bob-proposal-list">
            {run.linked_files.map((path, index) => (
              <button key={`${path}-${index}`} onClick={() => onOpenProposal(run.linked_changes?.[index])}>
                <Sparkles size={13} /> {path}
              </button>
            ))}
          </div>
          <button className="bob-open-scm" onClick={onOpenSourceControl}>Open proposed changes in Source Control</button>
        </>
      )}
      {run.error && <div className="bob-run-error">{run.error}</div>}
    </div>
  );
}

function ConnectionSettings({ config, setConfig, onSave, onHealth, saving, health }) {
  const statusLabel = health ? (health.ok ? "Connected" : "Health failed") : config.configured ? "Configured" : "Not configured";
  return (
    <section className="bob-connection-card bob-tab-card">
      <div className="bob-section-heading">
        <span><Settings2 size={14} /> Colab runtime</span>
        <span className={health?.ok ? "connection-ok" : config.configured ? "connection-warn" : "connection-off"}>{statusLabel}</span>
      </div>
      <div className="bob-connection-body bob-connection-body-tabbed">
        <label>Colab / ngrok base URL<input value={config.base_url || ""} placeholder="https://your-ngrok-url.ngrok-free.app" onChange={(e) => setConfig((v) => ({ ...v, base_url: e.target.value }))} /></label>
        <small className="bob-inline-help">Paste the ngrok HTTPS base URL only. Do not add <code>:8000</code>.</small>
        <div className="bob-connection-grid">
          <label>Health path<input value={config.health_path || "/health"} onChange={(e) => setConfig((v) => ({ ...v, health_path: e.target.value }))} /></label>
          <label>Capabilities path<input value={config.capabilities_path || "/capabilities"} onChange={(e) => setConfig((v) => ({ ...v, capabilities_path: e.target.value }))} /></label>
        </div>
        <div className="bob-connection-grid">
          <label>Plan path<input value={config.plan_path || "/plan"} onChange={(e) => setConfig((v) => ({ ...v, plan_path: e.target.value }))} /></label>
          <label>Replan path<input value={config.replan_path || "/replan"} onChange={(e) => setConfig((v) => ({ ...v, replan_path: e.target.value }))} /></label>
        </div>
        <div className="bob-connection-grid">
          <label>Code path<input value={config.code_path || "/code"} onChange={(e) => setConfig((v) => ({ ...v, code_path: e.target.value }))} /></label>
          <label>Review path<input value={config.review_path || "/review"} onChange={(e) => setConfig((v) => ({ ...v, review_path: e.target.value }))} /></label>
        </div>
        <div className="bob-connection-grid">
          <label>Run path<input value={config.run_path || "/run-agent"} onChange={(e) => setConfig((v) => ({ ...v, run_path: e.target.value }))} /></label>
          <label>Stream path<input value={config.stream_path || "/run-agent/stream"} onChange={(e) => setConfig((v) => ({ ...v, stream_path: e.target.value }))} /></label>
        </div>
        <div className="bob-connection-grid">
          <label>Timeout<input type="number" min="5" max="3600" value={config.timeout || 600} onChange={(e) => setConfig((v) => ({ ...v, timeout: e.target.value }))} /></label>
          <label>Context bytes<input type="number" min="10000" max="1000000" step="10000" value={config.context_budget || 160000} onChange={(e) => setConfig((v) => ({ ...v, context_budget: e.target.value }))} /></label>
        </div>
        <div className="bob-connection-grid"><label>Model ID<input value={config.model_id || "unknown"} onChange={(e) => setConfig((v) => ({ ...v, model_id: e.target.value }))} /></label><label>Model revision<input value={config.model_revision || "unknown"} onChange={(e) => setConfig((v) => ({ ...v, model_revision: e.target.value }))} /></label></div>
        <div className="bob-connection-grid"><label>Prompt set version<input value={config.prompt_set_version || "unversioned"} onChange={(e) => setConfig((v) => ({ ...v, prompt_set_version: e.target.value }))} /></label><label>Extra headers JSON<input value={config.headers_json || "{}"} spellCheck="false" onChange={(e) => setConfig((v) => ({ ...v, headers_json: e.target.value }))} /></label></div>
        <small className="bob-inline-help">Bearer tokens are environment-only. Set <code>BOB_COLAB_TOKEN</code> before starting Bob IDE. Status: {config.token_set ? "configured" : "not configured"}.</small>
        <label className="bob-checkbox-row"><input type="checkbox" checked={config.prefer_streaming !== false} onChange={(e) => setConfig((v) => ({ ...v, prefer_streaming: e.target.checked }))} /> Prefer streaming for Run All</label>
        <label className="bob-checkbox-row"><input type="checkbox" checked={config.keep_model_loaded !== false} onChange={(e) => setConfig((v) => ({ ...v, keep_model_loaded: e.target.checked }))} /> Keep Colab model loaded</label>
        {health && <div className={`bob-health-box ${health.ok ? "ok" : "fail"}`}>{health.ok ? `${health.model || "Colab runtime"} · ${health.contract_version || "contract"}` : health.message || "Health check failed."}</div>}
      </div>
      <div className="bob-connection-actions bob-sticky-actions">
        <button onClick={onSave} disabled={saving}><Save size={13} /> Save config</button>
        <button onClick={onHealth} disabled={!config.base_url || saving}><PlugZap size={13} /> Test</button>
        <button onClick={() => navigator.clipboard?.writeText(config.base_url || "")} disabled={!config.base_url}><Link2 size={13} /> Copy URL</button>
      </div>
    </section>
  );
}

export default function BobPanel() {
  const {
    activePath,
    currentProject,
    tabs,
    pushToast,
    setSidebarView,
    setSidebarCollapsed,
    setDiffChange,
    refreshWorktreeFromJson,
    promptDialog,
  } = useIde();

  const [messages, setMessages] = useState([{ id: nextId(), role: "assistant", text: "Use Plan for the staged workflow, or Direct to send a request straight to Coder. Every coded result must pass through Reviewer before it becomes a proposal." }]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("plan");
  const [activeTab, setActiveTab] = useState("chat");
  const [sending, setSending] = useState(false);
  const [config, setConfig] = useState(emptyConfig);
  const [savingConfig, setSavingConfig] = useState(false);
  const [health, setHealth] = useState(null);
  const [forcedFileTexts, setForcedFileTexts] = useState({});
  const [plans, setPlans] = useState([]);
  const [selectedPlanId, setSelectedPlanId] = useState(null);
  const [latestCode, setLatestCode] = useState(null);
  const [queueState, setQueueState] = useState(null);
  const listRef = useRef(null);

  const openPaths = useMemo(() => tabs.map((tab) => tab.path).filter(Boolean), [tabs]);
  const forcedPaths = useMemo(() => Object.keys(forcedFileTexts), [forcedFileTexts]);
  const forcedFilesPayload = useMemo(() => Object.fromEntries(Object.entries(forcedFileTexts).filter(([, meta]) => !meta.error).map(([path, meta]) => [path, meta.content || ""])), [forcedFileTexts]);
  const selectedPlan = useMemo(() => plans.find((item) => item.plan_id === selectedPlanId), [plans, selectedPlanId]);

  const openSourceControl = useCallback(() => {
    setSidebarView("sourceControl");
    setSidebarCollapsed(false);
  }, [setSidebarCollapsed, setSidebarView]);

  const loadConfig = useCallback(async () => {
    try { setConfig({ ...emptyConfig, ...(await api.modelGetConfig()) }); }
    catch (error) { pushToast(error.message, "error"); }
  }, [pushToast]);

  const loadPlans = useCallback(async () => {
    if (!currentProject) return;
    try {
      const data = await api.plansList(currentProject, true);
      setPlans(data.plans || []);
      setSelectedPlanId((current) => current || data.selected_plan_id || data.plans?.[0]?.plan_id || null);
    } catch {
      // Older workspaces simply have no plans yet.
    }
  }, [currentProject]);

  useEffect(() => { loadConfig(); }, [loadConfig]);
  useEffect(() => { loadPlans(); }, [loadPlans]);
  useEffect(() => {
    if (!sending) { setQueueState(null); return undefined; }
    let active = true;
    const poll = async () => { try { const status = await api.modelQueueStatus(); if (active) setQueueState(status); } catch {} };
    poll(); const timer = setInterval(poll, 500);
    return () => { active = false; clearInterval(timer); };
  }, [sending]);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" }); }, [messages, sending, activeTab]);

  useEffect(() => {
    if (!currentProject) return undefined;
    const socket = getSocket();
    const refresh = () => loadPlans();
    const updateRun = (run) => {
      if (run?.project && run.project !== currentProject) return;
      const runId = run?.run_id || run?.run?.run_id;
      if (!runId) return;
      setMessages((current) => current.map((item) => item.run_id === runId ? { ...item, kind: "run", status: run.status || item.status, run: run.run || run } : item));
      if (["completed", "failed", "coded"].includes(run.status)) {
        loadPlans();
        refreshWorktreeFromJson?.({ forceTree: true });
        if (run.status === "completed") openSourceControl();
      }
    };
    socket.on("plans:changed", refresh);
    socket.on("model:run", updateRun);
    return () => { socket.off("plans:changed", refresh); socket.off("model:run", updateRun); };
  }, [currentProject, loadPlans, openSourceControl, refreshWorktreeFromJson]);

  const addForced = useCallback(async (paths) => {
    if (!currentProject) return;
    const cleanPaths = [...new Set((paths || []).map(normalizePath).filter(Boolean))];
    if (!cleanPaths.length) return;
    const updates = {};
    for (const path of cleanPaths) {
      try {
        const result = await api.readFile(currentProject, path);
        updates[path] = { content: result.content || "", size: (result.content || "").length, addedAt: Date.now() };
      } catch (error) {
        // Keep the chip visible and send nothing for this file; user can see exactly what failed.
        updates[path] = { content: "", error: error.message || "Access denied", addedAt: Date.now() };
      }
    }
    setForcedFileTexts((current) => ({ ...current, ...updates }));
    const failed = Object.values(updates).filter((item) => item.error).length;
    pushToast(failed ? `${cleanPaths.length - failed} file(s) added, ${failed} failed.` : `${cleanPaths.length} file(s) added to Bob context as text.`, failed ? "error" : "success");
  }, [currentProject, pushToast]);

  const removeForced = useCallback((path) => setForcedFileTexts((current) => {
    const next = { ...current };
    delete next[path];
    return next;
  }), []);

  const addPickedFile = async () => {
    const path = await promptDialog("Add file path to Bob context", activePath || "");
    if (path) await addForced([path]);
  };

  const saveConfig = async () => {
    setSavingConfig(true); setHealth(null);
    try {
      const saved = await api.modelSetConfig({ ...config });
      setConfig({ ...emptyConfig, ...saved });
      pushToast("Saved Bob model connection", "success");
    } catch (error) { pushToast(error.message, "error"); }
    finally { setSavingConfig(false); }
  };

  const testHealth = async () => {
    setSavingConfig(true);
    try {
      const result = await api.modelHealth();
      const capabilities = result.ok ? await api.modelCapabilities() : {};
      const response = result.response || {};
      setHealth({ ...result, ...capabilities, model: response.model || capabilities.model, contract_version: response.contract_version || capabilities.contract_version });
      pushToast(result.ok ? "Colab health check passed" : "Colab health check failed", result.ok ? "success" : "error");
    } catch (error) { setHealth({ ok: false, message: error.message }); pushToast(error.message, "error"); }
    finally { setSavingConfig(false); }
  };

  const selectPlan = async (planId) => {
    const plan = await api.plansSelect(currentProject, planId);
    setSelectedPlanId(planId);
    await loadPlans();
    setActiveTab("chat");
    setMessages((current) => [...current, { id: nextId(), role: "assistant", text: `Selected ${planId}: ${plan.plan?.summary || "Plan selected"}` }]);
  };

  const runPlan = async (promptOverride) => {
    const prompt = (promptOverride || draft).trim();
    if (!prompt) return;
    setSending(true);
    setDraft("");
    setActiveTab("chat");
    setMessages((current) => [...current, { id: nextId(), role: "user", text: prompt, mode: "plan" }]);
    try {
      const result = await api.modelPlan(currentProject, prompt, activePath, forcedPaths, openPaths, config.context_budget, forcedFilesPayload);
      const record = result.plan_record;
      setSelectedPlanId(record.plan_id);
      await loadPlans();
      setMessages((current) => [...current, { id: nextId(), role: "assistant", kind: "plan", text: "Plan created", plan_record: record }]);
    } catch (error) { setMessages((current) => [...current, { id: nextId(), role: "assistant", text: `Plan failed: ${error.message}` }]); pushToast(error.message, "error"); }
    finally { setSending(false); }
  };

  const runReplan = async (planId = selectedPlanId) => {
    if (!planId) return pushToast("Select a plan first", "error");
    setSending(true);
    setActiveTab("chat");
    try {
      const prompt = draft.trim() || selectedPlan?.prompt || "Replan with the selected forced context files.";
      const result = await api.modelReplan(currentProject, prompt, planId, activePath, forcedPaths, openPaths, config.context_budget, forcedFilesPayload);
      const record = result.plan_record;
      setSelectedPlanId(record.plan_id);
      await loadPlans();
      setMessages((current) => [...current, { id: nextId(), role: "assistant", kind: "plan", text: "Replan created", plan_record: record }]);
    } catch (error) { pushToast(error.message, "error"); }
    finally { setSending(false); }
  };

  const runCode = async (planId = selectedPlanId) => {
    if (!planId) return pushToast("Select a plan first", "error");
    setSending(true);
    setActiveTab("chat");
    try {
      const result = await api.modelCode(currentProject, planId, activePath, forcedPaths, openPaths, config.context_budget, forcedFilesPayload);
      setLatestCode({ planId, code: result.code, files: result.files });
      setMessages((current) => [...current, { id: nextId(), role: "assistant", text: `Coder finished for ${planId}. ${Object.keys(result.files || {}).length} file proposal(s) ready for review.` }]);
    } catch (error) { pushToast(error.message, "error"); }
    finally { setSending(false); }
  };

  const runReview = async () => {
    if (!latestCode?.planId) return pushToast("Run coder first", "error");
    setSending(true);
    setActiveTab("chat");
    try {
      const result = await api.modelReview(currentProject, latestCode.planId, latestCode.code, latestCode.files);
      await refreshWorktreeFromJson?.({ forceTree: true });
      openSourceControl();
      setMessages((current) => [...current, { id: nextId(), role: "assistant", kind: "run", run_id: result.run?.run_id, status: "completed", run: result.run }]);
    } catch (error) { pushToast(error.message, "error"); }
    finally { setSending(false); }
  };

  const runDirect = async () => {
    const prompt = draft.trim();
    if (!prompt) return pushToast("Describe what the coder should implement", "error");
    setSending(true); setDraft(""); setActiveTab("chat");
    setMessages((current) => [...current, { id: nextId(), role: "user", text: prompt, mode: "direct coder + reviewer" }]);
    try {
      const result = await api.modelCodeDirect(currentProject, prompt, activePath, forcedPaths, openPaths, config.context_budget, forcedFilesPayload);
      await loadPlans(); await refreshWorktreeFromJson?.({ forceTree: true }); openSourceControl();
      setMessages((current) => [...current, { id: nextId(), role: "assistant", kind: "run", run_id: result.run?.run_id, status: result.run?.status || "completed", run: result.run }]);
    } catch (error) { pushToast(error.message, "error"); }
    finally { setSending(false); }
  };

  const runAll = async () => {
    const prompt = draft.trim();
    if (!prompt) return;
    setSending(true); setDraft("");
    setActiveTab("chat");
    setMessages((current) => [...current, { id: nextId(), role: "user", text: prompt, mode: "run all" }]);
    try {
      const result = await api.modelRunAgent(currentProject, prompt, activePath);
      const run = result.run || result;
      setMessages((current) => [...current, { id: nextId(), role: "assistant", kind: "run", run_id: run.run_id, status: run.status || "completed", run }]);
      openSourceControl();
    } catch (error) { pushToast(error.message, "error"); }
    finally { setSending(false); }
  };

  const send = async () => {
    const content = draft.trim();
    if (!content && !["code", "review"].includes(mode)) return;
    if (mode === "chat") {
      setSending(true);
      setMessages((current) => [...current, { id: nextId(), role: "user", text: content, mode }]);
      setDraft("");
      try {
        const data = await api.bobChat(currentProject, content, activePath);
        setMessages((current) => [...current, { id: nextId(), role: "assistant", text: data.reply, plan: data.plan }]);
      } catch (error) { pushToast(error.message, "error"); }
      finally { setSending(false); }
    } else if (mode === "plan") await runPlan();
    else if (mode === "code") await runCode();
    else if (mode === "direct") await runDirect();
    else if (mode === "review") await runReview();
    else await runAll();
  };

  const renderPlans = () => (
    <section className="bob-plans-panel bob-tab-card">
      <div className="bob-plan-toolbar">
        <strong>Plans</strong>
        <button onClick={loadPlans}><RefreshCw size={12} /> Refresh</button>
      </div>
      <div className="bob-plan-scroll bob-tab-scroll">
        {plans.map((record) => <PlanCard key={record.plan_id} record={record} selected={record.plan_id === selectedPlanId} onSelect={selectPlan} onReplan={runReplan} onCode={runCode} onDiscard={async (id) => { await api.plansDiscard(currentProject, id); await loadPlans(); }} onAddRequested={addForced} />)}
        {!plans.length && <small>No plans yet. Describe a change and press Plan.</small>}
      </div>
    </section>
  );

  const renderContext = () => (
    <section className="bob-context-card bob-tab-card">
      <div className="bob-section-heading"><span><Layers size={14} /> Context passed to Bob</span><small>{forcedPaths.length} forced</small></div>
      <div className="bob-context-actions">
        <button onClick={() => addForced([activePath])} disabled={!activePath}>+ Active file</button>
        <button onClick={() => addForced(openPaths)} disabled={!openPaths.length}>+ Open tabs</button>
        <button onClick={addPickedFile}><FolderOpen size={12} /> Pick file</button>
        <button onClick={() => setForcedFileTexts({})} disabled={!forcedPaths.length}>Clear</button>
      </div>
      <p className="bob-context-note">Forced files are read by the app and sent to Colab as text. Colab does not need filesystem access to your local paths.</p>
      <FileChips files={forcedFileTexts} onRemove={removeForced} />
      {!!selectedPlan && <button className="bob-full-width" onClick={() => addForced([...(selectedPlan.plan?.files_needed || []), ...(selectedPlan.plan?.required_context || [])])}><FilePlus2 size={13} /> Add files requested by selected plan</button>}
    </section>
  );

  const renderChat = () => (
    <>
      <div className="bob-mode-control bob-stage-strip">
        {STAGE_MODES.map(({ id, label, icon: Icon }) => <button key={id} className={mode === id ? "active" : ""} onClick={() => setMode(id)}><Icon size={14} /> {label}</button>)}
      </div>
      <div className="bob-selected-plan-pill">
        <span>{selectedPlanId ? `Selected plan: ${selectedPlanId}` : "No selected plan"}</span>
        <button onClick={() => setActiveTab("plans")}>Plans</button>
        <button onClick={() => setActiveTab("context")}>Context ({forcedPaths.length})</button>
      </div>
      {sending && queueState && <div className={`bob-queue-state queue-${queueState.status}`}><span>{queueState.status === "queued" ? `Waiting for the shared model${queueState.waiting?.[0]?.position ? ` · position ${queueState.waiting[0].position}` : ""}` : queueState.status === "running" ? "Your request is using the single model lane" : queueState.model_busy ? "The model is finishing another user's request" : "Submitting model request"}</span><small>{queueState.queue_depth || 0} waiting · 1 lane</small></div>}
      <div className="bob-chat-list" ref={listRef}>
        {messages.map((message) => (
          <div key={message.id} className={`bob-msg bob-msg-${message.role}`}>
            <div className="bob-msg-role">{message.role === "user" ? `You · ${message.mode || "chat"}` : "Bob"}</div>
            {message.kind === "run" ? <RunDetails message={message} onOpenProposal={async (changeId) => { if (!changeId) return openSourceControl(); try { setDiffChange(await api.worktreeDiff(currentProject, changeId)); openSourceControl(); } catch (e) { pushToast(e.message, "error"); } }} onOpenSourceControl={openSourceControl} />
              : message.kind === "plan" ? <PlanCard record={message.plan_record} selected={message.plan_record?.plan_id === selectedPlanId} onSelect={selectPlan} onReplan={runReplan} onCode={runCode} onDiscard={async (id) => { await api.plansDiscard(currentProject, id); await loadPlans(); }} onAddRequested={addForced} />
              : <div className="bob-msg-text">{message.text}</div>}
          </div>
        ))}
        {sending && <div className="bob-msg bob-msg-assistant bob-msg-pending"><span className="bob-typing-dot" /><span className="bob-typing-dot" /><span className="bob-typing-dot" /></div>}
      </div>
      <div className="bob-input-row">
        <textarea className="bob-input" placeholder={mode === "plan" ? "Describe what Bob should plan..." : mode === "code" ? "Send selected plan to coder..." : mode === "direct" ? "Describe the change for Coder → mandatory Reviewer..." : mode === "review" ? "Review latest coder output..." : "Ask Bob..."} value={draft} rows={3} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button className="bob-send-btn" onClick={send} disabled={sending || (!draft.trim() && !["code", "review"].includes(mode))} title="Send"><Send size={16} /></button>
      </div>
    </>
  );

  return (
    <aside className="bob-panel bob-panel-tabbed">
      <div className="sidebar-header">BOB ASSISTANT</div>
      <div className="bob-toolchain-note">MCP · staged plans · text context · proposal cache · Git source control</div>
      <div className="bob-main-tabs">
        {PANEL_TABS.map(({ id, label, icon: Icon }) => <button key={id} className={activeTab === id ? "active" : ""} onClick={() => setActiveTab(id)}><Icon size={14} /> {label}</button>)}
      </div>
      <div className="bob-tab-content">
        {activeTab === "chat" && renderChat()}
        {activeTab === "plans" && renderPlans()}
        {activeTab === "context" && renderContext()}
        {activeTab === "config" && <ConnectionSettings config={config} setConfig={setConfig} onSave={saveConfig} onHealth={testHealth} saving={savingConfig} health={health} />}
      </div>
    </aside>
  );
}
