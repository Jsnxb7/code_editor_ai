import {
  AlertTriangle, Check, ChevronDown, ChevronRight, FileDiff, Minus,
  RefreshCw, Save, ShieldAlert, X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { useIde } from "../context/IdeContext";

const ACTION_LABEL = { add: "A", modify: "M", delete: "D" };

function IconButton({ title, onClick, children, danger = false }) {
  return (
    <button className={`scm-icon-btn ${danger ? "danger" : ""}`} title={title} onClick={(event) => {
      event.stopPropagation();
      onClick();
    }}>
      {children}
    </button>
  );
}

function ChangeRow({ change, group, onRefresh }) {
  const { currentProject, setDiffChange, pushToast, confirmDialog } = useIde();
  const run = async (operation, success) => {
    try {
      await operation();
      await onRefresh();
      pushToast(success);
    } catch (error) {
      pushToast(error.message, "error");
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
    if (!(await confirmDialog(`Discard changes to "${change.path}"?`))) return;
    run(() => api.worktreeDiscard(currentProject, change.change_id), `Discarded ${change.path}`);
  };

  return (
    <div className="scm-change-row" onClick={openDiff} title={change.path}>
      <FileDiff size={15} />
      <span className="scm-change-path">{change.path}</span>
      <span className={`scm-action scm-action-${change.action}`}>{ACTION_LABEL[change.action] || "M"}</span>
      <div className="scm-row-actions">
        {group === "changes" && (
          <IconButton title="Stage Changes" onClick={() => run(
            () => api.worktreeStage(currentProject, change.change_id), `Staged ${change.path}`
          )}><Check size={14} /></IconButton>
        )}
        {group === "staged" && (
          <IconButton title="Unstage Changes" onClick={() => run(
            () => api.worktreeUnstage(currentProject, change.change_id), `Unstaged ${change.path}`
          )}><Minus size={14} /></IconButton>
        )}
        {group === "proposed" && change.review_status !== "FAIL" && (
          <IconButton title="Apply Proposal" onClick={() => run(
            () => api.worktreeApply(currentProject, change.change_id), `Applied ${change.path}`
          )}><Check size={14} /></IconButton>
        )}
        {(group === "conflicts" || (group === "proposed" && change.review_status === "FAIL")) && (
          <IconButton title="Override and Apply" onClick={async () => {
            if (!(await confirmDialog(`Override safeguards and apply "${change.path}"?`))) return;
            run(() => api.worktreeOverrideApply(currentProject, change.change_id), `Override applied ${change.path}`);
          }}><ShieldAlert size={14} /></IconButton>
        )}
        <IconButton title={group === "proposed" ? "Discard Proposal" : "Discard Changes"} onClick={discard} danger>
          <X size={14} />
        </IconButton>
      </div>
    </div>
  );
}

function ChangeSection({ title, group, items, onRefresh, warning = false }) {
  const [open, setOpen] = useState(true);
  if (!items?.length) return null;
  return (
    <section className="scm-section">
      <button className="scm-section-header" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {warning && <AlertTriangle size={13} />}
        <span>{title}</span>
        <span className="scm-count">{items.length}</span>
      </button>
      {open && items.map((change) => (
        <ChangeRow key={change.change_id} change={change} group={group} onRefresh={onRefresh} />
      ))}
    </section>
  );
}

export default function SourceControlPanel() {
  const { currentProject, worktreeStatus, loadWorktree, promptDialog, pushToast } = useIde();
  const [history, setHistory] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const refresh = () => loadWorktree(currentProject);

  useEffect(() => {
    if (currentProject) refresh().catch((error) => pushToast(error.message, "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProject]);

  const checkpoint = async () => {
    const label = await promptDialog("Checkpoint label:", "Checkpoint");
    if (!label) return;
    try {
      await api.worktreeSnapshot(currentProject, label);
      await refresh();
      pushToast(`Created checkpoint "${label}"`);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };
  const toggleHistory = async () => {
    if (!historyOpen && !history) {
      try {
        setHistory(await api.worktreeHistory(currentProject));
      } catch (error) {
        pushToast(error.message, "error");
        return;
      }
    }
    setHistoryOpen((value) => !value);
  };

  return (
    <aside className="sidebar source-control-panel">
      <div className="sidebar-header">
        <span>SOURCE CONTROL</span>
        <div className="sidebar-header-actions">
          <button title="Create Checkpoint" onClick={checkpoint}><Save size={14} /></button>
          <button title="Refresh" onClick={refresh}><RefreshCw size={14} /></button>
        </div>
      </div>
      <div className="workspace-name-row">{currentProject}</div>
      <div className="scm-scroll">
        <ChangeSection title="Conflicts" group="conflicts" items={worktreeStatus?.conflicts} onRefresh={refresh} warning />
        <ChangeSection title="Proposed by Bob" group="proposed" items={worktreeStatus?.proposed} onRefresh={refresh} />
        <ChangeSection title="Changes" group="changes" items={worktreeStatus?.changes} onRefresh={refresh} />
        <ChangeSection title="Staged Changes" group="staged" items={worktreeStatus?.staged} onRefresh={refresh} />
        {worktreeStatus?.state === "clean" && <div className="empty-hint">No source-control changes</div>}
        <button className="scm-history-toggle" onClick={toggleHistory}>
          {historyOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Checkpoints and Runs
        </button>
        {historyOpen && (
          <div className="scm-history">
            {(history?.snapshots || []).slice().reverse().map((item) => (
              <div key={item.snapshot_id}><span>{item.label}</span><small>{item.snapshot_id}</small></div>
            ))}
            {(history?.runs || []).slice().reverse().map((item) => (
              <div key={item.run_id}><span>{item.user_prompt}</span><small>{item.run_id} · {item.status}</small></div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
