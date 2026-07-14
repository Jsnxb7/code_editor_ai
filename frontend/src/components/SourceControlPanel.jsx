import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Eye,
  FileCode2,
  GitBranch,
  History,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  Sparkles,
  UserRoundCog,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useIde } from "../context/IdeContext";

const GROUPS = [
  { key: "conflicts", title: "Merge Changes", className: "conflict" },
  { key: "proposed", title: "Proposed by Bob", className: "proposed" },
  { key: "changes", title: "Changes", className: "changes" },
  { key: "untracked", title: "Untracked", className: "changes" },
  { key: "staged", title: "Staged Changes", className: "staged" },
];
const LETTERS = { add: "A", modify: "M", delete: "D", rename: "R" };
const rowLetter = (change, group) => group === "conflicts" ? "C" : group === "proposed" ? "P" : group === "untracked" ? "U" : change.letter || LETTERS[change.action] || "M";
const matches = (change, filter) => !filter.trim() || [change.path, change.action, change.status, change.run_id, change.review_status, change.risk, change.summary].filter(Boolean).join(" ").toLowerCase().includes(filter.trim().toLowerCase());

function ChangeRow({ change, group, selected, onDiff, onPreview, onRun, onHistory, onConfirm }) {
  const proposal = group === "proposed" || change.source === "bob_model";
  const conflict = group === "conflicts";
  const stage = () => onRun(() => api.gitStage(change.project, change.path), `Staged ${change.path}`, false);
  const unstage = () => onRun(() => api.gitUnstage(change.project, change.path), `Unstaged ${change.path}`, false);
  const discardGit = async () => {
    if (!(await onConfirm(`Discard Git changes in "${change.path}"? This cannot be undone.`))) return;
    await onRun(() => api.gitDiscard(change.project, change.path, group === "staged", group === "untracked"), `Discarded ${change.path}`);
  };
  const discardProposal = async () => {
    if (!(await onConfirm(`Discard Bob proposal for "${change.path}"?`))) return;
    await onRun(() => api.proposalDiscard(change.project, change.proposal_id, change.path), `Discarded proposal for ${change.path}`, false);
  };
  const forceProposal = async () => {
    if (!(await onConfirm(`Force apply Bob proposal for "${change.path}"? This can overwrite local edits and bypass a failed review.`))) return;
    await onRun(() => api.proposalOverrideApply(change.project, change.proposal_id, change.path), `Force applied ${change.path}`);
  };
  return (
    <div className={`scm-change-row vscode-scm-row ${selected ? "selected" : ""}`}>
      <button className={`scm-row-open status-${group}`} title="Open Diff" onClick={() => onDiff(change, group)}><span className="scm-decoration">{rowLetter(change, group)}</span></button>
      <button className="scm-change-main" onClick={() => onDiff(change, group)} title={change.path}>
        <span className="scm-change-path">{change.path}</span>
        <span className="scm-change-meta">{proposal ? change.run_id || "Bob" : change.action || change.status}{change.review_status ? ` · ${change.review_status}` : ""}{change.risk ? ` · ${change.risk} risk` : ""}</span>
      </button>
      <div className="scm-row-actions">
        {(group === "changes" || group === "untracked") && <button title="Stage" onClick={stage}><Plus size={14} /></button>}
        {group === "staged" && <button title="Unstage" onClick={unstage}><Minus size={14} /></button>}
        {proposal && <button title="Preview proposed file" onClick={() => onPreview(change)}><FileCode2 size={14} /></button>}
        {proposal && !conflict && change.review_status !== "FAIL" && <button title="Apply Proposal" onClick={() => onRun(() => api.proposalApply(change.project, change.proposal_id, change.path), `Applied proposal for ${change.path}`)}><Check size={14} /></button>}
        {proposal && (conflict || change.review_status === "FAIL") && <button title="Force Apply" onClick={forceProposal}><ShieldAlert size={14} /></button>}
        {conflict && !proposal && <><button title="Accept Current" onClick={() => onRun(() => api.gitAcceptCurrent(change.project, change.path), `Accepted current ${change.path}`)}>C</button><button title="Accept Incoming" onClick={() => onRun(() => api.gitAcceptIncoming(change.project, change.path), `Accepted incoming ${change.path}`)}>I</button></>}
        <button title="Open Diff" onClick={() => onDiff(change, group)}><Eye size={14} /></button>
        {!proposal && <button title="File History" onClick={() => onHistory(change.path)}><History size={14} /></button>}
        <button className="danger" title="Discard" onClick={proposal ? discardProposal : discardGit}><RotateCcw size={14} /></button>
      </div>
    </div>
  );
}

function Section({ definition, items, collapsed, onToggle, selectedId, ...rowProps }) {
  return (
    <section className={`scm-section scm-section-${definition.className}`}>
      <button className="scm-section-header" onClick={() => onToggle(definition.key)}>{collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}<span>{definition.title}</span><span className="scm-count">{items.length}</span></button>
      {!collapsed && <div className="scm-section-body">{items.map((change) => <ChangeRow key={change.change_id} change={change} group={definition.key} selected={selectedId === change.change_id} {...rowProps} />)}{!items.length && <div className="scm-empty-group">No items</div>}</div>}
    </section>
  );
}

export default function SourceControlPanel() {
  const { currentProject, worktreeStatus, loadWorktree, loadTree, sourceControlTotal, setDiffChange, pushToast, confirmDialog, promptDialog, openProposalPreview } = useIde();
  const [message, setMessage] = useState("");
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [collapsed, setCollapsed] = useState({});
  const [branches, setBranches] = useState([]);
  const [history, setHistory] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [fileHistory, setFileHistory] = useState(null);

  const refresh = async () => {
    if (!currentProject) return;
    await loadWorktree(currentProject);
    try { setBranches((await api.gitBranches(currentProject)).branches || []); } catch { setBranches([]); }
    if (historyOpen) setHistory((await api.gitLog(currentProject)).commits || []);
  };

  useEffect(() => { refresh().catch((e) => pushToast(e.message, "error")); /* eslint-disable-next-line */ }, [currentProject]);
  useEffect(() => { if (!message && worktreeStatus?.staged?.length) api.gitGenerateCommitMessage(currentProject).then((r) => setMessage(r.message || "")).catch(() => {}); }, [currentProject, message, worktreeStatus?.staged?.length]);

  const grouped = useMemo(() => Object.fromEntries(GROUPS.map((group) => [group.key, (worktreeStatus?.[group.key] || []).map((item) => ({ ...item, project: currentProject })).filter((item) => matches(item, filter)).sort((a, b) => a.path.localeCompare(b.path))])), [currentProject, filter, worktreeStatus]);
  const run = async (operation, success, reloadTree = true) => { try { await operation(); await refresh(); if (reloadTree) await loadTree(currentProject); pushToast(success, "success"); } catch (error) { pushToast(error.message, "error"); throw error; } };
  const openDiff = async (change, group) => { try { setSelectedId(change.change_id); const diff = change.source === "bob_model" ? await api.proposalDiff(currentProject, change.proposal_id, change.path) : await api.gitDiff(currentProject, change.path, group === "staged", group === "conflicts"); setDiffChange({ ...diff, change_id: change.change_id, status: change.status, git_group: group }); } catch (error) { pushToast(error.message, "error"); } };
  const previewProposal = async (change) => { try { await openProposalPreview(change.proposal_id, change.path); } catch (error) { pushToast(error.message, "error"); } };
  const configureIdentity = async () => { const current = await api.gitIdentity(currentProject); const name = await promptDialog("Git author name", current.name || ""); if (name === false || name === null) return false; const email = await promptDialog("Git author email", current.email || ""); if (email === false || email === null) return false; await api.gitSetIdentity(currentProject, name, email); pushToast("Git author configured", "success"); return true; };
  const commit = async () => { if (!message.trim()) return; try { await run(() => api.gitCommit(currentProject, message.trim()), `Committed: ${message.trim()}`, false); setMessage(""); setHistory((await api.gitLog(currentProject)).commits || []); } catch (error) { if (error.message.includes("GIT_IDENTITY_REQUIRED") && await configureIdentity()) { await run(() => api.gitCommit(currentProject, message.trim()), `Committed: ${message.trim()}`, false); setMessage(""); } } };
  const createBranch = async () => { const name = await promptDialog("New branch name", ""); if (name) await run(() => api.gitCreateBranch(currentProject, name, true), `Created branch ${name}`); };
  const changeBranch = async (event) => { const name = event.target.value; if (name && name !== worktreeStatus?.branch) await run(() => api.gitCheckout(currentProject, name), `Switched to ${name}`); };
  const openFileHistory = async (path) => { try { setFileHistory(await api.gitFileHistory(currentProject, path)); setHistoryOpen(true); } catch (error) { pushToast(error.message, "error"); } };
  const discardAll = async () => { if (!(await confirmDialog("Discard all Git changes, untracked files, and Bob proposals? This cannot be undone."))) return; await run(async () => { await api.gitDiscardAll(currentProject, true); await api.proposalDiscardAll(currentProject); }, "Discarded all source-control changes"); };
  const forceAllProposals = async () => { if (!(await confirmDialog("Force apply all Bob proposals? This can overwrite local edits and bypass failed reviews."))) return; await run(() => api.worktreeApplyAll(currentProject, true), "Force applied Bob proposals"); };

  if (!currentProject) return <aside className="sidebar source-control-panel"><div className="empty-hint">Open a workspace first.</div></aside>;
  return (
    <aside className="sidebar source-control-panel vscode-scm-panel">
      <div className="sidebar-header scm-header"><span>SOURCE CONTROL</span><div className="sidebar-header-actions"><button title="Refresh Git Status" onClick={() => refresh()}><RefreshCw size={14} /></button><button title="Configure Git Author" onClick={configureIdentity}><UserRoundCog size={14} /></button></div></div>
      <div className="scm-repo-row"><GitBranch size={14} /><select value={worktreeStatus?.branch || "main"} onChange={changeBranch}>{branches.length ? branches.map((b) => <option key={b.name} value={b.name}>{b.name}</option>) : <option value={worktreeStatus?.branch || "main"}>{worktreeStatus?.branch || "main"}</option>}</select><button title="Create Branch" onClick={createBranch}><Plus size={13} /></button>{(worktreeStatus?.ahead || worktreeStatus?.behind) ? <small>{worktreeStatus.ahead || 0} ahead, {worktreeStatus.behind || 0} behind</small> : null}</div>
      <div className="scm-summary vscode-scm-summary"><strong>{sourceControlTotal} item{sourceControlTotal === 1 ? "" : "s"}</strong><span>{worktreeStatus?.summary?.conflicts || 0} conflicts</span><span>{worktreeStatus?.summary?.proposed || 0} proposals</span><span>{worktreeStatus?.summary?.staged || 0} staged</span></div>
      <div className="scm-checkpoint-box vscode-checkpoint-box"><textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Commit message (Ctrl+Enter to commit)" rows={3} onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") commit(); }} /><button onClick={commit} disabled={!worktreeStatus?.summary?.staged || !message.trim()}><Save size={14} /> Commit</button></div>
      <div className="scm-toolbar vscode-scm-toolbar"><button onClick={() => run(() => api.gitStageAll(currentProject), "Staged all changes", false)}><Check size={14} /> Stage All</button><button onClick={() => run(() => api.gitUnstageAll(currentProject), "Unstaged all changes", false)}><Minus size={14} /> Unstage All</button><button onClick={() => run(() => api.proposalApplyAll(currentProject, true), "Applied passing proposals")}><Sparkles size={14} /> Apply Passing</button><button onClick={forceAllProposals}><ShieldAlert size={14} /> Force Changes</button><button className="danger" onClick={discardAll}><X size={14} /> Discard All</button></div>
      <div className="scm-filter-row"><input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter Git changes and proposals" /></div>
      <div className="scm-scroll">
        {GROUPS.map((definition) => <Section key={definition.key} definition={definition} items={grouped[definition.key]} collapsed={collapsed[definition.key]} onToggle={(key) => setCollapsed((v) => ({ ...v, [key]: !v[key] }))} selectedId={selectedId} onDiff={openDiff} onPreview={previewProposal} onRun={run} onHistory={openFileHistory} onConfirm={confirmDialog} />)}
        {worktreeStatus?.state === "clean" && <div className="empty-hint scm-clean-state">Working tree clean.</div>}
        <button className="scm-history-toggle" onClick={async () => { const next = !historyOpen; setHistoryOpen(next); if (next) setHistory((await api.gitLog(currentProject)).commits || []); }}>{historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<Clock3 size={13} /> Git History</button>
        {historyOpen && <div className="scm-history">{fileHistory && <section className="scm-history-panel"><div className="scm-history-panel-header"><strong>File History</strong><button onClick={() => setFileHistory(null)}><X size={13} /></button></div><small>{fileHistory.path}</small>{(fileHistory.commits || []).map((item) => <div key={item.hash}><span>{item.message}</span><small>{item.short_hash} · {item.author}</small></div>)}</section>}<section className="scm-history-panel"><strong>Commits</strong>{history.map((item) => <div key={item.hash}><span>{item.message}</span><small>{item.short_hash} · {item.author}</small></div>)}{!history.length && <div className="scm-empty-group">No commits yet</div>}</section></div>}
      </div>
    </aside>
  );
}
