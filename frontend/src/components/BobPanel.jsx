import { Bot, CheckCircle2, FileDiff, ListChecks, MessageSquare, Play, Send, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { getSocket } from "../socket";
import { useIde } from "../context/IdeContext";

const MODES = [
  { id: "chat", label: "Chat", icon: MessageSquare },
  { id: "plan", label: "Plan", icon: ListChecks },
  { id: "agent", label: "Run", icon: Play },
];
let msgSeq = 0;
const nextId = () => ++msgSeq;

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

function RunDetails({ message, onOpenProposal }) {
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
        <div className="bob-proposal-list">
          {run.linked_files.map((path, index) => (
            <button key={path} onClick={() => onOpenProposal(run.linked_changes[index])}>
              <FileDiff size={13} /> {path}
            </button>
          ))}
        </div>
      )}
      {run?.error && <div className="bob-run-error">{run.error}</div>}
    </div>
  );
}

export default function BobPanel() {
  const {
    activePath, currentProject, pushToast, setSidebarView, setSidebarCollapsed, setDiffChange,
  } = useIde();
  const [messages, setMessages] = useState([{
    id: nextId(),
    role: "assistant",
    text: "Choose Chat, Plan, or Run. Model changes are always proposed for review before they touch your files.",
  }]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState("chat");
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);

  useEffect(() => {
    const socket = getSocket();
    const onRun = (event) => {
      if (event.project !== currentProject) return;
      setMessages((current) => {
        const found = current.some((item) => item.run_id === event.run_id);
        if (!found) return [...current, { id: nextId(), role: "assistant", kind: "run", ...event }];
        return current.map((item) => item.run_id === event.run_id ? { ...item, ...event, kind: "run" } : item);
      });
    };
    socket.on("model:run", onRun);
    return () => socket.off("model:run", onRun);
  }, [currentProject]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const openProposal = async (changeId) => {
    if (!changeId) return;
    try {
      setDiffChange(await api.worktreeDiff(currentProject, changeId));
      setSidebarView("sourceControl");
      setSidebarCollapsed(false);
    } catch (error) {
      pushToast(error.message, "error");
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
        const data = await api.bobChat(content, activePath);
        setMessages((current) => [...current, { id: nextId(), role: "assistant", text: data.reply }]);
      } else {
        const run = mode === "plan"
          ? await api.modelPlan(currentProject, content, activePath)
          : await api.modelRunAgent(currentProject, content, activePath);
        setMessages((current) => [...current, {
          id: nextId(), role: "assistant", kind: "run", run_id: run.run_id, status: "queued",
        }]);
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
              ? <RunDetails message={message} onOpenProposal={openProposal} />
              : <div className="bob-msg-text">{message.text}</div>}
          </div>
        ))}
        {sending && <div className="bob-msg bob-msg-assistant bob-msg-pending"><span className="bob-typing-dot" /><span className="bob-typing-dot" /><span className="bob-typing-dot" /></div>}
      </div>
      <div className="bob-input-row">
        <textarea
          className="bob-input"
          placeholder={mode === "chat" ? "Ask Bob..." : mode === "plan" ? "Describe what to plan..." : "Describe changes for Bob to propose..."}
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
          <Send size={16} />
        </button>
      </div>
    </aside>
  );
}
