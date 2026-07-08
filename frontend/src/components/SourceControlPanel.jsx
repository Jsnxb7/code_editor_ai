import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Clipboard,
  FileDiff,
  GitPullRequest,
  History,
  Minus,
  RotateCcw,
  RefreshCw,
  Save,
  ShieldAlert,
  Sparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useIde } from "../context/IdeContext";

const ACTION_LABEL = { add: "A", modify: "M", delete: "D", rename: "R" };
const GROUPS = [
  { key: "conflicts", title: "Conflicts", warning: true },
  { key: "proposed", title: "Proposed by Bob" },
  { key: "changes", title: "Changes" },
  { key: "staged", title: "Staged Changes" },
];

function IconButton({ title, onClick, children, danger = false, disabled = false }) {
  return (
    <button
      className={`scm-icon-btn ${danger ? "danger" : ""}`}
      title={title}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {children}
    </button>
  );
}

function matchesFilter(change, filter) {
  const query = filter.trim().toLowerCase();
  if (!query) return true;
  const fields = [
    change.path,
    change.status,
    change.source,
    change.run_id,
    change.action,
    change.review_status,
    change.risk,
  ].filter(Boolean).map((value) => String(value).toLowerCase());
  if (query.startsWith("source:")) return change.source?.toLowerCase().includes(query.slice(7));
  if (query.startsWith("status:")) return change.status?.toLowerCase().includes(query.slice(7));
  if (query.startsWith("risk:")) return change.risk?.toLowerCase().includes(query.slice(5));
  if (query.startsWith("run:")) return change.run_id?.toLowerCase().includes(query.slice(4));
  return fields.some((value) => value.includes(query));
}

function sortChanges(items, sortMode) {
  return [...items].sort((a, b) => {
    if (sortMode === "source") return `${a.source || ""}${a.path}`.localeCompare(`${b.source || ""}${b.path}`);
    if (sortMode === "run") return `${a.run_id || ""}${a.path}`.localeCompare(`${b.run_id || ""}${b.path}`);
    if (sortMode === "risk") return `${a.risk || "zz"}${a.path}`.localeCompare(`${b.risk || "zz"}${b.path}`);
    if (sortMode === "status") return `${a.status}${a.path}`.localeCompare(`${b.status}${b.path}`);
    return a.path.localeCompare(b.path);
  });
}

function ChangeRow({ change, group, onRefresh, onHistory, onIgnore }) {
  const { currentProject, openFile, setDiffChange, pushToast, confirmDialog } = useIde();

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
      setDiffChange(await api.worktreeDiff(currentProject, change.change_id));
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const discard = async () => {
    const ok = await confirmDialog(`Discard "${change.path}"? This cannot be undone unless a checkpoint exists.`);
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

  const canApply = group === "proposed" && change.review_status !== "FAIL";
  const needsOverride = group === "conflicts" || (group === "proposed" && change.review_status === "FAIL");

  return (
    <div className="scm-change-row" onClick={openDiff} onDoubleClick={() => openFile(change.path)} title={change.path}>
      <span className={`scm-decoration scm-row-marker ${group === "conflicts" ? "status-conflict" : group === "proposed" ? "status-proposed" : group === "staged" ? "status-staged" : "status-changed"}`}>
        {group === "proposed" ? "P" : group === "conflicts" ? "C" : ACTION_LABEL[change.action] || "M"}
      </span>
      <div className="scm-change-main">
        <div className="scm-change-path">{change.path}</div>
        <div className="scm-change-meta">
          <span>{change.action}</span>
          {change.run_id && <span>{change.run_id}</span>}
          {change.review_status && <span className={`review-${change.review_status.toLowerCase()}`}>{change.review_status}</span>}
        {change.risk && <span className={`risk-${change.risk}`}>{change.risk} risk</span>}
          {change.partial_state && <span>{change.partial_state}</span>}
          {change.large_file && <span>large file</span>}
          {change.binary_file && <span>binary file</span>}
        </div>
      </div>
      <div className="scm-row-actions">
        <IconButton title="Open Diff" onClick={openDiff}><FileDiff size={14} /></IconButton>
        {group === "changes" && (
          <IconButton title="Stage Change" onClick={() => run(
            () => api.worktreeStage(currentProject, change.change_id), `Staged ${change.path}`
          )}><Check size={14} /></IconButton>
        )}
        {group === "staged" && (
          <IconButton title="Unstage Change" onClick={() => run(
            () => api.worktreeUnstage(currentProject, change.change_id), `Unstaged ${change.path}`
          )}><Minus size={14} /></IconButton>
        )}
        {canApply && (
          <IconButton title="Apply Proposal" onClick={() => run(
            () => api.worktreeApply(currentProject, change.change_id), `Applied ${change.path}`
          )}><Check size={14} /></IconButton>
        )}
        {needsOverride && (
          <IconButton title="Override and Apply" onClick={async () => {
            const ok = await confirmDialog(`Override safeguards and apply "${change.path}"?`);
            if (!ok) return;
            run(() => api.worktreeOverrideApply(currentProject, change.change_id), `Override applied ${change.path}`);
          }}><ShieldAlert size={14} /></IconButton>
        )}
        <IconButton title="View File History" onClick={() => onHistory(change.path)}><History size={14} /></IconButton>
        <IconButton title="Ignore Path" onClick={() => onIgnore(change.path)}><X size={14} /></IconButton>
        <IconButton title="Copy Path" onClick={copyPath}><Clipboard size={14} /></IconButton>
        <IconButton title={group === "proposed" ? "Discard Proposal" : "Discard Change"} onClick={discard} danger>
          <X size={14} />
        </IconButton>
      </div>
    </div>
  );
}

function ChangeSection({ title, group, items, onRefresh, onHistory, onIgnore, warning = false }) {
  const [open, setOpen] = useState(true);
  if (!items.length) return null;
  return (
    <section className="scm-section">
      <button className="scm-section-header" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {warning && <AlertTriangle size={13} />}
        <span>{title}</span>
        <span className="scm-count">{items.length}</span>
      </button>
      {open && items.map((change) => (
        <ChangeRow
          key={change.change_id}
          change={change}
          group={group}
          onRefresh={onRefresh}
          onHistory={onHistory}
          onIgnore={onIgnore}
        />
      ))}
    </section>
  );
}

export default function SourceControlPanel() {
  const { currentProject, worktreeStatus, sourceControlTotal, loadWorktree, pushToast, confirmDialog } = useIde();
  const [history, setHistory] = useState(null);
  const [timeline, setTimeline] = useState(null);
  const [fileHistory, setFileHistory] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [sortMode, setSortMode] = useState("path");
  const [checkpointMessage, setCheckpointMessage] = useState("");

  const refresh = async () => {
    const status = await loadWorktree(currentProject);
    if (historyOpen) setHistory(await api.worktreeHistory(currentProject));
    if (historyOpen) setTimeline(await api.worktreeTimeline(currentProject));
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
      result[group.key] = sortChanges(
        (worktreeStatus?.[group.key] || []).filter((change) => matchesFilter(change, filter)),
        sortMode
      );
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
      pushToast(success);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const createCheckpoint = async () => {
    if (!stagedCount) {
      pushToast("Stage changes before creating a checkpoint.", "error");
      return;
    }
    const message = checkpointMessage.trim();
    if (!message) {
      pushToast("Checkpoint message is required.", "error");
      return;
    }
    await runBulk(() => api.worktreeSnapshot(currentProject, message), `Created checkpoint "${message}"`);
    setCheckpointMessage("");
    setHistory(await api.worktreeHistory(currentProject));
  };

  const discardAll = async () => {
    const ok = await confirmDialog("Discard all active Source Control changes and proposals?");
    if (!ok) return;
    runBulk(() => api.worktreeDiscardAll(currentProject), "Discarded all changes");
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
      setHistoryOpen(true);
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

  return (
    <aside className="sidebar source-control-panel">
      <div className="sidebar-header scm-header">
        <span>SOURCE CONTROL</span>
        <div className="sidebar-header-actions">
          <button title="Refresh Source Control" onClick={() => refresh()}><RefreshCw size={14} /></button>
        </div>
      </div>
      <div className="scm-summary">
        <strong>{sourceControlTotal} changes</strong>
        <span>{summary.proposed || 0} proposed</span>
        <span>{summary.staged || 0} staged</span>
        <span>{summary.conflicts || 0} conflicts</span>
      </div>

      <div className="scm-toolbar">
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

      <div className="scm-checkpoint-box">
        <textarea
          value={checkpointMessage}
          onChange={(event) => setCheckpointMessage(event.target.value)}
          placeholder="Checkpoint message"
          rows={3}
        />
        <button onClick={createCheckpoint} disabled={!stagedCount || !checkpointMessage.trim()}>
          <Save size={14} /> Create Checkpoint
        </button>
      </div>

      <div className="scm-filter-row">
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter changed files..."
        />
        <select value={sortMode} onChange={(event) => setSortMode(event.target.value)} title="Sort changes">
          <option value="path">Path</option>
          <option value="status">Status</option>
          <option value="source">Source</option>
          <option value="run">Run ID</option>
          <option value="risk">Risk</option>
        </select>
      </div>

      <div className="scm-git-placeholders">
        <button disabled title="Git integration not enabled yet"><GitPullRequest size={13} /> Sync</button>
        <button disabled title="Git integration not enabled yet">Push</button>
        <button disabled title="Git integration not enabled yet">Pull</button>
      </div>

      <div className="scm-scroll">
        {GROUPS.map((group) => (
          <ChangeSection
            key={group.key}
            title={group.title}
            group={group.key}
            items={grouped[group.key] || []}
            onRefresh={refresh}
            onHistory={openFileHistory}
            onIgnore={ignorePath}
            warning={group.warning}
          />
        ))}
        {worktreeStatus?.state === "clean" && <div className="empty-hint">No source-control changes</div>}
        {sourceControlTotal > 0 && GROUPS.every((group) => !grouped[group.key]?.length) && (
          <div className="empty-hint">No changes match the filter.</div>
        )}
        <button className="scm-history-toggle" onClick={toggleHistory}>
          {historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Checkpoints and Runs
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
                    <span>{item.change_id} - {item.source} - {item.status}</span>
                    <small>{item.action} {item.run_id ? `- ${item.run_id}` : ""} {item.snapshot_id ? `- ${item.snapshot_id}` : ""}</small>
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
                <small>{item.run_id} - {item.status}</small>
              </div>
            ))}
            {!!timeline?.events?.length && (
              <section className="scm-history-panel">
                <strong>Timeline</strong>
                {timeline.events.slice(0, 30).map((item, index) => (
                  <div key={`${item.type}-${item.id}-${index}`}>
                    <span>{item.label}</span>
                    <small>{item.type} - {item.id}</small>
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
