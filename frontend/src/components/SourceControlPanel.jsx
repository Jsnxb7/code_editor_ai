import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Eye,
  GitBranch,
  History,
  MoreHorizontal,
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

const GROUPS = [
  { key: "conflicts", title: "Merge Changes", empty: "No merge conflicts", className: "conflict" },
  { key: "proposed", title: "Proposed by Bob", empty: "No Bob proposals", className: "proposed" },
  { key: "changes", title: "Changes", empty: "No unstaged changes", className: "changes" },
  { key: "staged", title: "Staged Changes", empty: "No staged changes", className: "staged" },
];

const STATUS_LABEL = {
  add: "A",
  modify: "M",
  delete: "D",
  rename: "R",
};

function changeLetter(change, group) {
  if (group === "conflicts") return "C";
  if (group === "proposed") return "P";
  return STATUS_LABEL[change.action] || "M";
}

function matchesFilter(change, filter) {
  const value = filter.trim().toLowerCase();
  if (!value) return true;
  const tokens = value.split(/\s+/).filter(Boolean);
  const haystack = [
    change.path,
    change.action,
    change.status,
    change.source,
    change.run_id,
    change.review_status,
    change.risk,
    change.change_id,
  ].filter(Boolean).join(" ").toLowerCase();
  return tokens.every((token) => {
    if (token.startsWith("source:")) return (change.source || "").toLowerCase().includes(token.slice(7));
    if (token.startsWith("status:")) return (change.status || "").toLowerCase().includes(token.slice(7));
    if (token.startsWith("risk:")) return (change.risk || "").toLowerCase().includes(token.slice(5));
    if (token.startsWith("run:")) return (change.run_id || "").toLowerCase().includes(token.slice(4));
    return haystack.includes(token);
  });
}

function sortChanges(items, sortMode) {
  const copy = [...items];
  const key = (item) => {
    if (sortMode === "status") return `${item.status}-${item.path}`;
    if (sortMode === "source") return `${item.source}-${item.path}`;
    if (sortMode === "run") return `${item.run_id || ""}-${item.path}`;
    if (sortMode === "risk") return `${item.risk || "low"}-${item.path}`;
    if (sortMode === "recent") return `${item.updated_at || item.created_at || ""}`;
    return item.path || "";
  };
  copy.sort((a, b) => key(a).localeCompare(key(b)));
  if (sortMode === "recent") copy.reverse();
  return copy;
}

function sourceLabel(change) {
  if (change.source === "bob_model") return change.run_id || "Bob";
  if (change.source === "manual") return "manual";
  return change.source || "tracked";
}

function ChangeRow({ group, change, selected, onOpenDiff, onAction, onHistory, onIgnore }) {
  const isProposal = group.key === "proposed" || group.key === "conflicts";
  const canApply = isProposal && change.review_status !== "FAIL" && change.status !== "conflict";
  const canOverride = isProposal && (change.review_status === "FAIL" || change.status === "conflict");
  return (
    <div className={`scm-change-row vscode-scm-row ${selected ? "selected" : ""}`} onDoubleClick={() => onOpenDiff(change)}>
      <button className={`scm-row-open status-${group.className}`} title="Open Diff" onClick={() => onOpenDiff(change)}>
        <span className="scm-decoration">{changeLetter(change, group.key)}</span>
      </button>
      <button className="scm-change-main" onClick={() => onOpenDiff(change)} title={change.path}>
        <span className="scm-change-path">{change.path}</span>
        <span className="scm-change-meta">
          {sourceLabel(change)}
          {change.review_status ? ` · ${change.review_status}` : ""}
          {change.risk ? ` · ${change.risk} risk` : ""}
          {change.partial_state ? ` · ${change.partial_state}` : ""}
        </span>
      </button>
      <div className="scm-row-actions">
        {group.key === "changes" && <button title="Stage Change" onClick={() => onAction(() => api.worktreeStage(change.project, change.change_id), `Staged ${change.path}`)}><Check size={14} /></button>}
        {group.key === "staged" && <button title="Unstage Change" onClick={() => onAction(() => api.worktreeUnstage(change.project, change.change_id), `Unstaged ${change.path}`)}><Minus size={14} /></button>}
        {canApply && <button title="Apply Bob Proposal" onClick={() => onAction(() => api.worktreeApply(change.project, change.change_id), `Applied ${change.path}`)}><Check size={14} /></button>}
        {canOverride && <button title="Override and Apply" onClick={() => onAction(() => api.worktreeOverrideApply(change.project, change.change_id), `Override applied ${change.path}`)}><ShieldAlert size={14} /></button>}
        <button title="Open Diff" onClick={() => onOpenDiff(change)}><Eye size={14} /></button>
        <button title="File History" onClick={() => onHistory(change.path)}><History size={14} /></button>
        <button title="Discard" className="danger" onClick={() => onAction(() => api.worktreeDiscard(change.project, change.change_id), `Discarded ${change.path}`)}><RotateCcw size={14} /></button>
        <button title="Add to .bobignore" onClick={() => onIgnore(change.path)}><MoreHorizontal size={14} /></button>
      </div>
    </div>
  );
}

function ChangeSection({ group, items, collapsed, onToggle, selectedId, onOpenDiff, onAction, onHistory, onIgnore }) {
  return (
    <section className={`scm-section scm-section-${group.className}`}>
      <button className="scm-section-header" onClick={() => onToggle(group.key)}>
        {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        <span>{group.title}</span>
        <span className="scm-count">{items.length}</span>
      </button>
      {!collapsed && (
        <div className="scm-section-body">
          {items.length === 0 ? (
            <div className="scm-empty-group">{group.empty}</div>
          ) : (
            items.map((change) => (
              <ChangeRow
                key={change.change_id}
                group={group}
                change={change}
                selected={selectedId === change.change_id}
                onOpenDiff={onOpenDiff}
                onAction={onAction}
                onHistory={onHistory}
                onIgnore={onIgnore}
              />
            ))
          )}
        </div>
      )}
    </section>
  );
}

export default function SourceControlPanel() {
  const {
    currentProject,
    worktreeStatus,
    loadWorktree,
    refreshWorktreeFromJson,
    loadTree,
    sourceControlTotal,
    setDiffChange,
    pushToast,
    confirmDialog,
  } = useIde();

  const [checkpointMessage, setCheckpointMessage] = useState("");
  const [filter, setFilter] = useState("");
  const [sortMode, setSortMode] = useState("path");
  const [selectedId, setSelectedId] = useState(null);
  const [collapsed, setCollapsed] = useState({});
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [fileHistory, setFileHistory] = useState(null);

  const refresh = async ({ scanDisk = false } = {}) => {
    if (!currentProject) return null;
    const status = scanDisk
      ? await refreshWorktreeFromJson({ forceTree: true, scanDisk: true })
      : await loadWorktree(currentProject);
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
    if (!checkpointMessage && currentProject && worktreeStatus?.staged?.length) {
      api.worktreeGenerateCheckpointMessage(currentProject).then((data) => setCheckpointMessage(data.message)).catch(() => {});
    }
  }, [checkpointMessage, currentProject, worktreeStatus?.staged?.length]);

  const grouped = useMemo(() => {
    const result = {};
    for (const group of GROUPS) {
      result[group.key] = sortChanges(
        (worktreeStatus?.[group.key] || []).map((item) => ({ ...item, project: currentProject })).filter((change) => matchesFilter(change, filter)),
        sortMode,
      );
    }
    return result;
  }, [currentProject, filter, sortMode, worktreeStatus]);

  const summary = worktreeStatus?.summary || {};
  const stagedCount = summary.staged || 0;
  const proposedPassing = (worktreeStatus?.proposed || []).filter((item) => item.review_status !== "FAIL").length;

  const runAction = async (operation, success, reloadTree = true) => {
    try {
      await operation();
      await refresh();
      if (reloadTree) await loadTree(currentProject);
      pushToast(success);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const openDiff = async (change) => {
    try {
      setSelectedId(change.change_id);
      const diff = await api.worktreeDiff(currentProject, change.change_id);
      setDiffChange(diff);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const createCheckpoint = async () => {
    if (!stagedCount) return pushToast("Stage changes before creating a checkpoint.", "error");
    const message = checkpointMessage.trim();
    if (!message) return pushToast("Checkpoint message is required.", "error");
    await runAction(() => api.worktreeSnapshot(currentProject, message), `Created checkpoint: ${message}`);
    setCheckpointMessage("");
  };

  const discardAll = async () => {
    const ok = await confirmDialog("Discard every active Source Control change and Bob proposal?");
    if (!ok) return;
    await runAction(() => api.worktreeDiscardAll(currentProject), "Discarded all Source Control changes");
  };

  const openHistory = async () => {
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
    const ok = await confirmDialog(`Add "${path}" to .bobignore?`);
    if (!ok) return;
    await runAction(() => api.worktreeIgnorePath(currentProject, path), `Ignored ${path}`);
  };

  const restoreSnapshot = async (snapshotId) => {
    const ok = await confirmDialog(`Restore ${snapshotId}? This can overwrite current files.`);
    if (!ok) return;
    await runAction(() => api.worktreeRestoreSnapshot(currentProject, snapshotId), `Restored ${snapshotId}`);
  };

  const restoreFile = async (path, snapshotId) => {
    const ok = await confirmDialog(`Restore "${path}" from ${snapshotId || "latest snapshot"}?`);
    if (!ok) return;
    await runAction(() => api.worktreeRestoreFile(currentProject, path, snapshotId), `Restored ${path}`);
  };

  const toggleGroup = (key) => setCollapsed((value) => ({ ...value, [key]: !value[key] }));

  if (!currentProject) {
    return (
      <aside className="sidebar source-control-panel vscode-scm-panel">
        <div className="sidebar-header scm-header">SOURCE CONTROL</div>
        <div className="empty-hint">Open or create a workspace first.</div>
      </aside>
    );
  }

  return (
    <aside className="sidebar source-control-panel vscode-scm-panel">
      <div className="sidebar-header scm-header">
        <span>SOURCE CONTROL</span>
        <div className="sidebar-header-actions">
          <button title="Refresh Source Control from JSON" onClick={() => refresh()}><RefreshCw size={14} /></button>
          <button title="Scan disk and update indexed JSON" onClick={() => refresh({ scanDisk: true })}>Scan</button>
        </div>
      </div>

      <div className="scm-repo-row">
        <GitBranch size={14} />
        <span>main</span>
        <small>{worktreeStatus?.active_snapshot || "no checkpoint"}</small>
      </div>

      <div className="scm-summary vscode-scm-summary">
        <strong>{sourceControlTotal} file{sourceControlTotal === 1 ? "" : "s"}</strong>
        <span>{summary.conflicts || 0} conflicts</span>
        <span>{summary.proposed || 0} proposed</span>
        <span>{summary.changes || 0} changes</span>
        <span>{summary.staged || 0} staged</span>
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
        <button onClick={() => runAction(() => api.worktreeStageAll(currentProject), "Staged all changes", false)} disabled={!summary.changes}><Check size={14} /> Stage All</button>
        <button onClick={() => runAction(() => api.worktreeUnstageAll(currentProject), "Unstaged all changes", false)} disabled={!summary.staged}><Minus size={14} /> Unstage All</button>
        <button onClick={() => runAction(() => api.worktreeApplyPassing(currentProject), "Applied passing Bob proposals")} disabled={!proposedPassing}><Sparkles size={14} /> Apply Passing</button>
        <button className="danger" onClick={discardAll} disabled={!sourceControlTotal}><X size={14} /> Discard All</button>
      </div>

      <div className="scm-filter-row">
        <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter changes… source:bob risk:high" />
        <select value={sortMode} onChange={(event) => setSortMode(event.target.value)} title="Sort changes">
          <option value="path">Path</option>
          <option value="recent">Recent</option>
          <option value="status">Status</option>
          <option value="source">Source</option>
          <option value="run">Run</option>
          <option value="risk">Risk</option>
        </select>
      </div>

      <div className="scm-scroll">
        {GROUPS.map((group) => (
          <ChangeSection
            key={group.key}
            group={group}
            items={grouped[group.key] || []}
            collapsed={collapsed[group.key]}
            onToggle={toggleGroup}
            selectedId={selectedId}
            onOpenDiff={openDiff}
            onAction={runAction}
            onHistory={openFileHistory}
            onIgnore={ignorePath}
          />
        ))}

        {worktreeStatus?.state === "clean" && <div className="empty-hint scm-clean-state">No source-control changes. Save a file or run Bob to create tracked changes.</div>}
        {sourceControlTotal > 0 && GROUPS.every((group) => !grouped[group.key]?.length) && <div className="empty-hint">No changes match the filter.</div>}

        <button className="scm-history-toggle" onClick={openHistory}>
          {historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Clock3 size={13} /> Timeline, checkpoints, runs
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
                    <button className="scm-inline-action" onClick={() => restoreFile(item.path, item.snapshot_id)}><RotateCcw size={12} /> Restore</button>
                  </div>
                ))}
              </section>
            )}
            <section className="scm-history-panel">
              <strong>Checkpoints</strong>
              {(history?.snapshots || []).slice().reverse().slice(0, 12).map((item) => (
                <div key={item.snapshot_id}>
                  <span>{item.message || item.label}</span>
                  <small>{item.snapshot_id}</small>
                  <button className="scm-inline-action" onClick={() => restoreSnapshot(item.snapshot_id)}><RotateCcw size={12} /> Restore snapshot</button>
                </div>
              ))}
            </section>
            <section className="scm-history-panel">
              <strong>Bob Runs</strong>
              {(history?.runs || []).slice().reverse().slice(0, 12).map((item) => (
                <div key={item.run_id}>
                  <span>{item.user_prompt || item.summary || item.mode}</span>
                  <small>{item.run_id} · {item.status}</small>
                </div>
              ))}
            </section>
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
