import { Files, GitBranch, Search, TerminalSquare } from "lucide-react";
import { useIde } from "../context/IdeContext";

export default function ActivityBar() {
  const {
    sidebarView,
    setSidebarView,
    sidebarCollapsed,
    setSidebarCollapsed,
    bobCollapsed,
    setBobCollapsed,
    setCommandPaletteOpen,
    sourceControlTotal,
  } = useIde();

  const selectView = (view) => {
    if (sidebarView === view && !sidebarCollapsed) setSidebarCollapsed(true);
    else {
      setSidebarView(view);
      setSidebarCollapsed(false);
    }
  };

  return (
    <nav className="activity-bar">
      <button className={`activity-btn ${sidebarView === "explorer" && !sidebarCollapsed ? "active" : ""}`} title="Explorer" onClick={() => selectView("explorer")}>
        <Files size={22} />
      </button>
      <button className={`activity-btn ${sidebarView === "search" && !sidebarCollapsed ? "active" : ""}`} title="Search" onClick={() => selectView("search")}>
        <Search size={22} />
      </button>
      <button className={`activity-btn ${sidebarView === "sourceControl" && !sidebarCollapsed ? "active" : ""}`} title="Source Control" onClick={() => selectView("sourceControl")}>
        <GitBranch size={22} />
        {sourceControlTotal > 0 && <span className="activity-badge">{sourceControlTotal}</span>}
      </button>
      <button className="activity-btn" title="Command Palette (Ctrl+Shift+P)" onClick={() => setCommandPaletteOpen(true)}>
        <TerminalSquare size={21} />
      </button>
      <div className="activity-spacer" />
      <button className={`activity-btn ${!bobCollapsed ? "active" : ""}`} title="Bob Assistant" onClick={() => setBobCollapsed((value) => !value)}>
        B
      </button>
    </nav>
  );
}
