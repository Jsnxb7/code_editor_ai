import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Clipboard,
  FileCode2,
  FileDiff,
  GitBranch,
  History,
  Minus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useIde } from "../context/IdeContext";

const ACTION_LABEL = { add: "A", modify: "M", delete: "D", rename: "R" };
const ACTION_TEXT = { add: "Added", modify: "Modified", delete: "Deleted", rename: "Renamed" };
const GROUPS = [
  { key: "conflicts", title: "MERGE CHANGES", icon: AlertTriangle, className: "conflict" },
  { key: "proposed", title: "PROPOSED BY BOB", icon: Sparkles, className: "proposed" },
  { key: "changes", title: "CHANGES", icon: FileDiff, className: "changed" },
  { key: "staged", title: "STAGED CHANGES", icon: Check, className: "staged" },
];

function IconButton({ title, onClick, children, danger = false, disabled = false }) {
  return (
    <button
      className={`scm-icon-btn ${danger ? "danger" : ""}`}
      title={title}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.();
      }}
    >
      {children}
    </button>
  );
}

function matchesFilter(change, filter) {
  const query = filter.trim().toLowerCase();
  if (!query) return true;
  if (query.startsWith("source:")) return change.source?.toLowerCase().includes(query.slice(7));
  if (query.startsWith("status:")) return change.status?.toLowerCase().includes(query.slice(7));
  if (query.startsWith("risk:")) return change.risk?.toLowerCase().includes(query.slice(5));
  if (query.startsWith("run:")) return change.run_id?.toLowerCase().includes(query.slice(4));
  return [change.path, change.status, change.source, change.run_id, change.action, change.review_status, change.risk]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

function sortChanges(items, sortMode) {
  const riskRank = { high: 0, medium: 1, low: 2 };
  return [...items].sort((a, b) => {
    if (sortMode === "source") return `${a.source || ""}${a.path}`.localeCompare(`${b.source || ""}${b.path}`);
    if (sortMode === "run") return `${a.run_id || ""}${a.path}`.localeCompare(`${b.run_id || ""}${b.path}`);
    if (sortMode === "risk") return (riskRank[a.risk] ?? 9) - (riskRank[b.risk] ?? 9) || a.path.localeCompare(b.path);
    if (sortMode === "status") return `${a.status}${a.path}`.localeCompare(`${b.status}${b.path}`);
    return a.path.localeCompare(b.path);
  });
}

function ChangeRow({ change, group, selected, onSelect, onRefresh, onHistory, onIgnore }) {
  const { currentProject, openFile, setDiffChange, pushToast, confirmDialog } = useIde();
  const marker = group === "proposed" ? "P" : group === "conflicts" ? "C" : ACTION_LABEL[change.action] || "M";
  const canApply = group === "proposed" && change.review_status !== "FAIL";
  const needsOverride = group === "conflicts" || (group === "proposed" && change.review_status === "FAIL");

  const run = async (operation, success) => {
    try {
      const result = await operation();
      await onRefresh();
      pushToast(success);
      return result;
    } catch (error) {
      pushToast(error.message, "error");
      return null;
    }
  };

  const openDiff = async () => {
    try {
      const diff = await api.worktreeDiff(currentProject, change.change_id);
      setDiffChange(diff);
      onSelect(change.change_id);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const discard = async () => {
    const ok = await confirmDialog(
      group === "proposed"
        ? `Discard Bob proposal for "${change.path}"?`
        : `Discard changes to "${change.path}"? This cannot be undone unless a checkpoint exists.`
    );
    if (!ok) return;
    run(() => api.worktreeDiscard(currentProject, change.change_id), `Discarded ${change.path}`);
  };

  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(change.path);
      pushToast(`Copied ${change.path}`);
    } catch {
      pushToast(change.path);
    }
  };

  return (
    <div
      className={`scm-change-row vscode-scm-row ${selected ? "selected" : ""}`}
      onClick={openDiff}
      onDoubleClick={() => openFile(change.path).catch((error) => pushToast(error.message, "error"))}
      title="Click to open diff. Double-click to open file."
    >
      <span className={`scm-decoration scm-row-marker status-${group === "conflicts" ? "conflict" : group === "proposed" ? "proposed" : group === "staged" ? "staged" : "changed"}`}>
        {marker}
      </span>
      <div className="scm-change-main">
        <div className="scm-change-path">{change.path}</div>
        <div className="scm-change-meta">
          <span>{ACTION_TEXT[change.action] || change.action}</span>
          {!!change.hunks?.length && <span>{change.hunks.length} hunk{change.hunks.length === 1 ? "" : "s"}</span>}
          {change.run_id && <span>{change.run_id}</span>}
          {change.review_status && <span className={`review-${change.review_status.toLowerCase()}`}>{change.review_status}</span>}
          {change.risk && <span className={`risk-${change.risk}`}>{change.risk}</span>}
          {change.partial_state && <span>{change.partial_state}</span>}
          {change.large_file && <span>large</span>}
          {change.binary_file && <span>binary</span>}
        </div>
      </div>
      <div className="scm-row-actions">
        <IconButton title="Open Diff" onClick={openDiff}><FileDiff size={14} /></IconButton>
        <IconButton title="Open File" onClick={() => openFile(change.path).catch((error) => pushToast(error.message, "error"))}><FileCode2 size={14} /></IconButton>
        {group === "changes" && (
          <IconButton title="Stage Change" onClick={() => run(() => api.worktreeStage(currentProject, change.change_id), `Staged ${change.path}`)}><Check size={14} /></IconButton>
        )}
        {group === "staged" && (
          <IconButton title="Unstage Change" onClick={() => run(() => api.worktreeUnstage(currentProject, change.change_id), `Unstaged ${change.path}`)}><Minus size={14} /></IconButton>
        )}
        {canApply && (
          <IconButton title="Apply Bob Proposal" onClick={() => run(() => api.worktreeApply(currentProject, change.change_id), `Applied ${change.path}`)}><Check size={14} /></IconButton>
        )}
        {needsOverride && (
          <IconButton title="Override Safeguards and Apply" onClick={async () => {
            const ok = await confirmDialog(`Override safeguards and apply "${change.path}"?`);
            if (!ok) return;
            run(() => api.worktreeOverrideApply(currentProject, change.change_id), `Override applied ${change.path}`);
          }}><ShieldAlert size={14} /></IconButton>
        )}
        <IconButton title="View File History" onClick={() => onHistory(change.path)}><History size={14} /></IconButton>
        <IconButton title="Copy Path" onClick={copyPath}><Clipboard size={14} /></IconButton>
        <IconButton title="Add to .bobignore" onClick={() => onIgnore(change.path)}><X size={14} /></IconButton>
        <IconButton title={group === "proposed" ? "Discard Proposal" : "Discard Change"} onClick={discard} danger><RotateCcw size={14} /></IconButton>
      </div>
    </div>
  );
}

function ChangeSection({ definition, items, selectedId, onSelect, onRefresh, onHistory, onIgnore }) {
  const [open, setOpen] = useState(true);
  const Icon = definition.icon;
  return (
    <section className={`scm-section scm-section-${definition.className}`}>
      <button className="scm-section-header" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <Icon size={13} />
        <span>{definition.title}</span>
        <span className="scm-count">{items.length}</span>
      </button>
      {open && items.length === 0 && <div className="scm-empty-group">No {definition.title.toLowerCase()}</div>}
      {open && items.map((change) => (
        <ChangeRow
          key={change.change_id}
          change={change}
          group={definition.key}
          selected={selectedId === change.change_id}
          onSelect={onSelect}
          onRefresh={onRefresh}
          onHistory={onHistory}
          onIgnore={onIgnore}
        />
      ))}
    </section>
  );
}

export default function SourceControlPanel() {
  const {
    currentProject,
    worktreeStatus,
    sourceControlTotal,
    loadWorktree,
    loadTree,
    pushToast,
    confirmDialog,
  } = useIde();
  const [history, setHistory] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [fileHistory, setFileHistory] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [sortMode, setSortMode] = useState("path");
  const [checkpointMessage, setCheckpointMessage] = useState("");
  const [selectedId, setSelectedId] = useState(null);

  const refresh = async () => {
    const status = await loadWorktree(currentProject);
    if (historyOpen) {
      setHistory(await api.worktreeHistory(currentProject));
      setTimeline(await api.worktreeTimeline(currentProject));
    }
    return status;
  };

  useEffect(() => {
    if (currentProject) refresh().catch((error) => pushToast(error.message, "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject]);

  useEffect(() => {
    if (!checkpointMessage && worktreeStatus?.staged?.length) {
      api.worktreeGenerateCheckpointMessage(currentProject)
        .then((data) => setCheckpointMessage(data.message))
        .catch(() => {});
    }
  }, [checkpointMessage, currentProject, worktreeStatus?.staged?.length]);

  const grouped = useMemo(() => {
    const result = {};
    for (const group of GROUPS) {
      result[group.key] = sortChanges((worktreeStatus?.[group.key] || []).filter((change) => matchesFilter(change, filter)), sortMode);
    }
    return result;
  }, [filter, sortMode, worktreeStatus]);

  const summary = worktreeStatus?.summary || {};
  const stagedCount = summary.staged || 0;
  const proposedPassing = (worktreeStatus?.proposed || []).filter((item) => item.review_status !== "FAIL").length;

  const runBulk = async (operation, success) => {
    try {
      await operation();
      await refresh();
      await loadTree(currentProject);
      pushToast(success);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const createCheckpoint = async () => {
    if (!stagedCount) return pushToast("Stage changes before creating a checkpoint.", "error");
    const message = checkpointMessage.trim();
    if (!message) return pushToast("Checkpoint message is required.", "error");
    await runBulk(() => api.worktreeSnapshot(currentProject, message), `Created checkpoint "${message}"`);
    setCheckpointMessage("");
    setHistory(await api.worktreeHistory(currentProject));
  };

  const discardAll = async () => {
    const ok = await confirmDialog("Discard all active Source Control changes and proposals?");
    if (!ok) return;
    await runBulk(() => api.worktreeDiscardAll(currentProject), "Discarded all changes");
  };

  const toggleHistory = async () => {
    if (!historyOpen || !history) {
      try {
        setHistory(await api.worktreeHistory(currentProject));
        setTimeline(await api.worktreeTimeline(currentProject));
      } catch (error) {
        pushToast(error.message, "error");
        return;
      }
    }
    setHistoryOpen((value) => !value);
  };

  const openFileHistory = async (path) => {
    try {
      setFileHistory(await api.worktreeFileHistory(currentProject, path));
      if (!historyOpen) setHistoryOpen(true);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const ignorePath = async (path) => {
    const ok = await confirmDialog(`Add "${path}" to .bobignore and hide it from Source Control?`);
    if (!ok) return;
    await runBulk(() => api.worktreeIgnorePath(currentProject, path), `Ignored ${path}`);
  };

  const restoreSnapshot = async (snapshotId) => {
    const ok = await confirmDialog(`Restore workspace files from ${snapshotId}? Current file contents may be overwritten.`);
    if (!ok) return;
    await runBulk(() => api.worktreeRestoreSnapshot(currentProject, snapshotId), `Restored ${snapshotId}`);
  };

  const restoreFile = async (path, snapshotId) => {
    const ok = await confirmDialog(`Restore "${path}" from ${snapshotId || "latest snapshot"}?`);
    if (!ok) return;
    await runBulk(() => api.worktreeRestoreFile(currentProject, path, snapshotId), `Restored ${path}`);
  };

  if (!currentProject) {
    return (
      <aside className="sidebar source-control-panel">
        <div className="sidebar-header">SOURCE CONTROL</div>
        <div className="empty-hint">Open or create a workspace first.</div>
      </aside>
    );
  }

  return (
    <aside className="sidebar source-control-panel vscode-scm-panel">
      <div className="sidebar-header scm-header">
        <span>SOURCE CONTROL</span>
        <div className="sidebar-header-actions">
          <button title="Refresh Source Control" onClick={() => refresh()}><RefreshCw size={14} /></button>
        </div>
      </div>

      <div className="scm-repo-row">
        <GitBranch size={14} />
        <span>main</span>
        <small>{worktreeStatus?.active_snapshot || "no checkpoint"}</small>
      </div>

      <div className="scm-summary vscode-scm-summary">
        <strong>{sourceControlTotal} file{sourceControlTotal === 1 ? "" : "s"}</strong>
        <span>{summary.proposed || 0} proposed</span>
        <span>{summary.changes || 0} changed</span>
        <span>{summary.staged || 0} staged</span>
        <span>{summary.conflicts || 0} conflicts</span>
      </div>

      <div className="scm-checkpoint-box vscode-checkpoint-box">
        <textarea
          value={checkpointMessage}
          onChange={(event) => setCheckpointMessage(event.target.value)}
          placeholder="Message (Ctrl+Enter to checkpoint staged changes)"
          rows={3}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") createCheckpoint();
          }}
        />
        <button onClick={createCheckpoint} disabled={!stagedCount || !checkpointMessage.trim()}>
          <Save size={14} /> Create Checkpoint
        </button>
      </div>

      <div className="scm-toolbar vscode-scm-toolbar">
        <button onClick={() => runBulk(() => api.worktreeStageAll(currentProject), "Staged all changes")} disabled={!summary.changes}>
          <Check size={14} /> Stage All
        </button>
        <button onClick={() => runBulk(() => api.worktreeUnstageAll(currentProject), "Unstaged all changes")} disabled={!summary.staged}>
          <Minus size={14} /> Unstage All
        </button>
        <button onClick={() => runBulk(() => api.worktreeApplyPassing(currentProject), "Applied passing proposals")} disabled={!proposedPassing}>
          <Sparkles size={14} /> Apply Passing
        </button>
        <button onClick={discardAll} disabled={!sourceControlTotal} className="danger">
          <X size={14} /> Discard All
        </button>
      </div>

      <div className="scm-filter-row">
        <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter: source:bob status:proposed risk:high" />
        <select value={sortMode} onChange={(event) => setSortMode(event.target.value)} title="Sort changes">
          <option value="path">Path</option>
          <option value="status">Status</option>
          <option value="source">Source</option>
          <option value="run">Run ID</option>
          <option value="risk">Risk</option>
        </select>
      </div>

      <div className="scm-scroll">
        {GROUPS.map((group) => (
          <ChangeSection
            key={group.key}
            definition={group}
            items={grouped[group.key] || []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onRefresh={refresh}
            onHistory={openFileHistory}
            onIgnore={ignorePath}
          />
        ))}
        {worktreeStatus?.state === "clean" && <div className="empty-hint scm-clean-state">No source-control changes. Edit or save a file to create a tracked change.</div>}
        {sourceControlTotal > 0 && GROUPS.every((group) => !grouped[group.key]?.length) && <div className="empty-hint">No changes match the filter.</div>}

        <button className="scm-history-toggle" onClick={toggleHistory}>
          {historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} <Clock3 size={13} /> Timeline, checkpoints, runs
        </button>
        {historyOpen && (
          <div className="scm-history">
            {fileHistory && (
              <section className="scm-history-panel">
                <div className="scm-history-panel-header">
                  <strong>File History</strong>
                  <button onClick={() => setFileHistory(null)}><X size={13} /></button>
                </div>
                <small>{fileHistory.path}</small>
                {(fileHistory.changes || []).slice().reverse().map((item) => (
                  <div key={item.change_id}>
                    <span>{item.change_id} · {item.source} · {item.status}</span>
                    <small>{item.action} {item.run_id ? `· ${item.run_id}` : ""} {item.snapshot_id ? `· ${item.snapshot_id}` : ""}</small>
                    <button className="scm-inline-action" onClick={() => restoreFile(item.path, item.snapshot_id)}>
                      <RotateCcw size={12} /> Restore
                    </button>
                  </div>
                ))}
              </section>
            )}
            {(history?.snapshots || []).slice().reverse().map((item) => (
              <div key={item.snapshot_id}>
                <span>{item.message || item.label}</span>
                <small>{item.snapshot_id}</small>
                <button className="scm-inline-action" onClick={() => restoreSnapshot(item.snapshot_id)}>
                  <RotateCcw size={12} /> Restore snapshot
                </button>
              </div>
            ))}
            {(history?.runs || []).slice().reverse().map((item) => (
              <div key={item.run_id}>
                <span>{item.user_prompt}</span>
                <small>{item.run_id} · {item.status}</small>
              </div>
            ))}
            {!!timeline?.events?.length && (
              <section className="scm-history-panel">
                <strong>Timeline</strong>
                {timeline.events.slice(0, 30).map((item, index) => (
                  <div key={`${item.type}-${item.id}-${index}`}>
                    <span>{item.label}</span>
                    <small>{item.type} · {item.id}</small>
                  </div>
                ))}
              </section>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
