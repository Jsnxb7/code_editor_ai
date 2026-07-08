import { useIde } from "../context/IdeContext";
import { extToLang } from "../context/IdeContext";

export default function StatusBar() {
  const {
    currentProject,
    activePath,
    tabs,
    terminals,
    worktreeStatus,
    sourceControlTotal,
    setSidebarView,
    setSidebarCollapsed,
  } = useIde();
  const activeTab = tabs.find((t) => t.path === activePath);
  const lines = activeTab ? activeTab.content.split("\n").length : 0;

  const openSourceControl = () => {
    setSidebarView("sourceControl");
    setSidebarCollapsed(false);
  };

  return (
    <footer className="status-bar">
      <div className="status-left">
        <span className="status-chip">Workspace {currentProject || "none"}</span>
        <button className="status-chip status-button" onClick={openSourceControl} title="Open Source Control">
          Bob SCM: {sourceControlTotal}
        </button>
        <span className="status-chip">Checkpoint {worktreeStatus?.active_snapshot || "none"}</span>
        <span className="status-chip">Worktree {worktreeStatus?.active_worktree || "main"}</span>
        <span className="status-chip">{terminals.length} terminal{terminals.length === 1 ? "" : "s"}</span>
      </div>
      <div className="status-right">
        {activePath && (
          <>
            <span>{lines} lines</span>
            <span>{extToLang(activePath)}</span>
            <span>UTF-8</span>
          </>
        )}
        <span className="status-brand">Bob IDE</span>
      </div>
    </footer>
  );
}
