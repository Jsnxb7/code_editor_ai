import {
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileDiff,
  Link2,
  ListChecks,
  MessageSquare,
  Play,
  PlugZap,
  Save,
  Send,
  Settings2,
  Sparkles,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useIde } from "../context/IdeContext";
import { getSocket } from "../socket";

const MODES = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "plan", label: "Plan", icon: ListChecks },
  { id: "agent", label: "Run", icon: Play },
];

let msgSeq = 0;
const nextId = () => ++msgSeq;

const emptyConfig = {
  base_url: "",
  health_path: "/health",
  capabilities_path: "/capabilities",
  chat_path: "/chat",
  plan_path: "/plan",
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
  headers_json: "{}",
  configured: false,
  token_set: false,
};

function PlanDetails({ plan }) {
  if (!plan) return null;
  return (
    <div className="bob-structured">
      <strong>{plan.summary || "Plan"}</strong>
      {!!plan.reasoning_steps?.length && (
        <ol>{plan.reasoning_steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
      )}
      {!!plan.files_needed?.length && <div className="bob-file-line">Files: {plan.files_needed.join(", ")}</div>}
      {typeof plan.confidence === "number" && <small>Confidence {Math.round(plan.confidence * 100)}%</small>}
    </div>
  );
}

function RunDetails({ message, onOpenProposal, onOpenSourceControl }) {
  const run = message.run;
  const finalStatus = run?.final_status;
  return (
    <div className="bob-structured">
      <div className="bob-run-heading">
        <Bot size={15} />
        <strong>{message.status === "completed" ? "Run complete" : message.status}</strong>
        {finalStatus === "PASS" && <CheckCircle2 size={15} className="status-pass" />}
        {finalStatus === "FAIL" && <XCircle size={15} className="status-fail" />}
      </div>
      <small>{message.run_id}</small>
      <PlanDetails plan={run?.plan || message.plan} />
      {run?.review && (
        <div className={`bob-review review-${finalStatus?.toLowerCase()}`}>
          <strong>Review: {finalStatus}</strong>
          <p>{run.review.replace(/^(PASS|FAIL)\s*/i, "")}</p>
        </div>
      )}
      {!!run?.linked_files?.length && (
        <>
          <div className="bob-proposal-list">
            {run.linked_files.map((path, index) => (
              <button key={`${path}-${index}`} onClick={() => onOpenProposal(run.linked_changes?.[index])}>
                <FileDiff size={13} /> {path}
              </button>
            ))}
          </div>
          <button className="bob-open-scm" onClick={onOpenSourceControl}>
            <Sparkles size={13} /> Open proposed changes in Source Control
          </button>
        </>
      )}
      {run?.error && <div className="bob-run-error">{run.error}</div>}
    </div>
  );
}

function ConnectionSettings({ config, setConfig, onSave, onHealth, saving, health, tokenInput, setTokenInput, clearToken, setClearToken }) {
  const [open, setOpen] = useState(true);
  const statusLabel = health
    ? health.ok ? "Connected" : "Health failed"
    : config.configured ? "Configured" : "Not configured";

  return (
    <section className="bob-connection-card">
      <button className="bob-connection-title" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Settings2 size={14} /> Colab runtime
        <span className={health?.ok ? "connection-ok" : config.configured ? "connection-warn" : "connection-off"}>{statusLabel}</span>
      </button>
      {open && (
        <div className="bob-connection-body">
          <label>
            Colab / ngrok base URL
            <input
              value={config.base_url || ""}
              placeholder="https://your-ngrok-url"
              onChange={(event) => setConfig((value) => ({ ...value, base_url: event.target.value }))}
            />
          </label>
          <div className="bob-connection-grid">
            <label>
              Health path
              <input
                value={config.health_path || "/health"}
                onChange={(event) => setConfig((value) => ({ ...value, health_path: event.target.value }))}
              />
            </label>
            <label>
              Capabilities path
              <input
                value={config.capabilities_path || "/capabilities"}
                onChange={(event) => setConfig((value) => ({ ...value, capabilities_path: event.target.value }))}
              />
            </label>
          </div>
          <div className="bob-connection-grid">
            <label>
              Chat path
              <input value={config.chat_path || "/chat"} onChange={(event) => setConfig((value) => ({ ...value, chat_path: event.target.value }))} />
            </label>
            <label>
              Plan path
              <input value={config.plan_path || "/plan"} onChange={(event) => setConfig((value) => ({ ...value, plan_path: event.target.value }))} />
            </label>
          </div>
          <div className="bob-connection-grid">
            <label>
              Run path
              <input value={config.run_path || "/run-agent"} onChange={(event) => setConfig((value) => ({ ...value, run_path: event.target.value }))} />
            </label>
            <label>
              Stream path
              <input value={config.stream_path || "/run-agent/stream"} onChange={(event) => setConfig((value) => ({ ...value, stream_path: event.target.value }))} />
            </label>
          </div>
          <div className="bob-connection-grid">
            <label>
              Timeout seconds
              <input
                type="number"
                min="5"
                max="3600"
                value={config.timeout || 600}
                onChange={(event) => setConfig((value) => ({ ...value, timeout: event.target.value }))}
              />
            </label>
            <label>
              Maximum iterations
              <input
                type="number"
                min="1"
                max="20"
                value={config.max_iterations || 5}
                onChange={(event) => setConfig((value) => ({ ...value, max_iterations: event.target.value }))}
              />
            </label>
          </div>
          <div className="bob-connection-grid">
            <label>
              Context
              <select value={config.context_mode || "workspace"} onChange={(event) => setConfig((value) => ({ ...value, context_mode: event.target.value }))}>
                <option value="active">Active file</option>
                <option value="open">Open files</option>
                <option value="workspace">Workspace</option>
              </select>
            </label>
            <label>
              Context byte budget
              <input
                type="number"
                min="10000"
                max="1000000"
                step="10000"
                value={config.context_budget || 160000}
                onChange={(event) => setConfig((value) => ({ ...value, context_budget: event.target.value }))}
              />
            </label>
          </div>
          <div className="bob-connection-grid">
            <label>
              Optional bearer token
              <input
                type="password"
                value={tokenInput}
                placeholder={config.token_set ? "Token saved — enter to replace" : "optional-secret"}
                onChange={(event) => setTokenInput(event.target.value)}
              />
            </label>
            <label>
              Extra headers JSON
              <input
                value={config.headers_json || "{}"}
                spellCheck="false"
                onChange={(event) => setConfig((value) => ({ ...value, headers_json: event.target.value }))}
              />
            </label>
          </div>
          <label className="bob-checkbox-row">
            <input type="checkbox" checked={clearToken} onChange={(event) => setClearToken(event.target.checked)} />
            Clear saved bearer token on save
          </label>
          <label className="bob-checkbox-row">
            <input type="checkbox" checked={config.prefer_streaming !== false} onChange={(event) => setConfig((value) => ({ ...value, prefer_streaming: event.target.checked }))} />
            Prefer realtime run events
          </label>
          <label className="bob-checkbox-row">
            <input type="checkbox" checked={config.keep_model_loaded !== false} onChange={(event) => setConfig((value) => ({ ...value, keep_model_loaded: event.target.checked }))} />
            Keep model loaded between requests
          </label>
          <div className="bob-connection-actions">
            <button onClick={onSave} disabled={saving}>
              <Save size={13} /> Save
            </button>
            <button onClick={onHealth} disabled={!config.base_url || saving}>
              <PlugZap size={13} /> Test /health
            </button>
            <button onClick={() => navigator.clipboard?.writeText(config.base_url || "")} disabled={!config.base_url}>
              <Link2 size={13} /> Copy URL
            </button>
          </div>
          {health && (
            <div className={`bob-health-box ${health.ok ? "ok" : "fail"}`}>
              {health.ok
                ? `${health.model || "Colab runtime"} · ${health.contract_version || "legacy contract"}${health.streaming ? " · streaming" : ""}`
                : health.message || "Health check failed."}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default function BobPanel() {
  const {
    activePath,
    currentProject,
    pushToast,
    setSidebarView,
    setSidebarCollapsed,
    setDiffChange,
    refreshWorktreeFromJson,
  } = useIde();
  const [messages, setMessages] = useState([{
    id: nextId(),
    role: "assistant",
    text: "Choose Chat, Plan, or Run. Bob routes through MCP, and generated edits appear as Source Control proposals before they touch your files.",
  }]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("chat");
  const [sending, setSending] = useState(false);
  const [config, setConfig] = useState(emptyConfig);
  const [tokenInput, setTokenInput] = useState("");
  const [clearToken, setClearToken] = useState(false);
  const [savingConfig, setSavingConfig] = useState(false);
  const [health, setHealth] = useState(null);
  const listRef = useRef(null);
  const messagesRef = useRef(messages);

  const openSourceControl = useCallback(() => {
    setSidebarView("sourceControl");
    setSidebarCollapsed(false);
  }, [setSidebarCollapsed, setSidebarView]);

  const loadConfig = async () => {
    try {
      setConfig({ ...emptyConfig, ...(await api.modelGetConfig()) });
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  useEffect(() => {
    loadConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
    messagesRef.current = messages;
  }, [messages, sending]);

  useEffect(() => {
    if (!currentProject) return undefined;
    const socket = getSocket();

    const updateRun = (run) => {
      if (run?.project && run.project !== currentProject) return;
      const runId = run?.run_id;
      if (!runId) return;
      setMessages((current) =>
        current.map((item) =>
          item.run_id === runId
            ? { ...item, kind: "run", status: run.status || item.status, run: run.run || run }
            : item
        )
      );
      if (["completed", "failed"].includes(run.status)) {
        refreshWorktreeFromJson?.({ forceTree: true });
        if (run.status === "completed") openSourceControl();
      }
    };

    const recoverRuns = async () => {
      const activeRuns = messagesRef.current.filter(
        (item) => item.run_id && !["completed", "failed"].includes(item.status)
      );
      for (const item of activeRuns) {
        try {
          updateRun(await api.modelRunStatus(currentProject, item.run_id));
        } catch {
          // A reconnect should not replace the user's chat with transport noise.
        }
      }
    };

    socket.on("model:run", updateRun);
    socket.on("connect", recoverRuns);
    if (socket.connected) recoverRuns();
    return () => {
      socket.off("model:run", updateRun);
      socket.off("connect", recoverRuns);
    };
  }, [currentProject, openSourceControl, refreshWorktreeFromJson]);

  const openProposal = async (changeId) => {
    if (!changeId) {
      openSourceControl();
      return;
    }
    try {
      setDiffChange(await api.worktreeDiff(currentProject, changeId));
      openSourceControl();
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const saveConfig = async () => {
    setSavingConfig(true);
    setHealth(null);
    try {
      const payload = {
        base_url: config.base_url || "",
        health_path: config.health_path || "/health",
        capabilities_path: config.capabilities_path || "/capabilities",
        chat_path: config.chat_path || "/chat",
        plan_path: config.plan_path || "/plan",
        run_path: config.run_path || "/run-agent",
        stream_path: config.stream_path || "/run-agent/stream",
        run_status_path: config.run_status_path || "/runs/{run_id}",
        cancel_path: config.cancel_path || "/runs/{run_id}/cancel",
        timeout: config.timeout || 600,
        max_iterations: config.max_iterations || 5,
        context_mode: config.context_mode || "workspace",
        context_budget: config.context_budget || 160000,
        prefer_streaming: config.prefer_streaming !== false,
        keep_model_loaded: config.keep_model_loaded !== false,
        headers_json: config.headers_json || "{}",
      };
      if (tokenInput) payload.token = tokenInput;
      if (clearToken) payload.token = "";
      const saved = await api.modelSetConfig(payload);
      setConfig({ ...emptyConfig, ...saved });
      setTokenInput("");
      setClearToken(false);
      pushToast("Saved Bob model connection");
    } catch (error) {
      pushToast(error.message, "error");
    } finally {
      setSavingConfig(false);
    }
  };

  const testHealth = async () => {
    setSavingConfig(true);
    try {
      const result = await api.modelHealth();
      const capabilities = result.ok ? await api.modelCapabilities() : {};
      const response = result.response || {};
      setHealth({
        ...result,
        ...capabilities,
        model: response.model || capabilities.model,
        contract_version: response.contract_version || capabilities.contract_version,
      });
      pushToast(result.ok ? "Colab health check passed" : "Colab health check failed", result.ok ? "success" : "error");
    } catch (error) {
      setHealth({ ok: false, message: error.message });
      pushToast(error.message, "error");
    } finally {
      setSavingConfig(false);
    }
  };

  const send = async () => {
    const content = draft.trim();
    if (!content || sending || !currentProject) return;
    setMessages((current) => [...current, { id: nextId(), role: "user", text: content, mode }]);
    setDraft("");
    setSending(true);
    try {
      if (mode === "chat") {
        const data = await api.bobChat(currentProject, content, activePath);
        setMessages((current) => [...current, {
          id: nextId(), role: "assistant", text: data.reply, plan: data.plan,
        }]);
      } else {
        const run = mode === "plan"
          ? await api.modelPlan(currentProject, content, activePath)
          : await api.modelRunAgent(currentProject, content, activePath);
        setMessages((current) => [...current, {
          id: nextId(), role: "assistant", kind: "run", run_id: run.run_id, status: "queued", run,
        }]);
        openSourceControl();
      }
    } catch (error) {
      setMessages((current) => [...current, { id: nextId(), role: "assistant", text: `Bob request failed: ${error.message}` }]);
      pushToast("Bob request failed", "error");
    } finally {
      setSending(false);
    }
  };

  return (
    <aside className="bob-panel">
      <div className="sidebar-header">BOB ASSISTANT</div>
      <div className="bob-toolchain-note">MCP tools · Git source control · reviewable proposals · Colab runtime</div>

      <ConnectionSettings
        config={config}
        setConfig={setConfig}
        onSave={saveConfig}
        onHealth={testHealth}
        saving={savingConfig}
        health={health}
        tokenInput={tokenInput}
        setTokenInput={setTokenInput}
        clearToken={clearToken}
        setClearToken={setClearToken}
      />

      <div className="bob-mode-control">
        {MODES.map(({ id, label, icon: Icon }) => (
          <button key={id} className={mode === id ? "active" : ""} onClick={() => setMode(id)} title={`${label} mode`}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>
      <div className="bob-chat-list" ref={listRef}>
        {messages.map((message) => (
          <div key={message.id} className={`bob-msg bob-msg-${message.role}`}>
            <div className="bob-msg-role">{message.role === "user" ? `You · ${message.mode || "chat"}` : "Bob"}</div>
            {message.kind === "run"
              ? <RunDetails message={message} onOpenProposal={openProposal} onOpenSourceControl={openSourceControl} />
              : <>
                  <div className="bob-msg-text">{message.text}</div>
                  <PlanDetails plan={message.plan} />
                </>}
          </div>
        ))}
        {sending && <div className="bob-msg bob-msg-assistant bob-msg-pending"><span className="bob-typing-dot" /><span className="bob-typing-dot" /><span className="bob-typing-dot" /></div>}
      </div>
      <div className="bob-input-row">
        <textarea
          className="bob-input"
          placeholder={mode === "chat" ? "Ask Bob about this workspace..." : mode === "plan" ? "Describe what Bob should plan..." : "Describe changes for Bob to propose..."}
          value={draft}
          rows={3}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              send();
            }
          }}
        />
        <button className="bob-send-btn" onClick={send} disabled={sending || !draft.trim()} title="Send">
          {mode === "agent" ? <Sparkles size={16} /> : <Send size={16} />}
        </button>
      </div>
    </aside>
  );
}
