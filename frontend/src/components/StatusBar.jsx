import { useIde } from "../context/IdeContext";
import { extToLang } from "../context/IdeContext";

export default function StatusBar() {
  const { currentProject, activePath, tabs, terminals } = useIde();
  const activeTab = tabs.find((t) => t.path === activePath);
  const lines = activeTab ? activeTab.content.split("\n").length : 0;

  return (
    <footer className="status-bar">
      <div className="status-left">
        <span className="status-chip">⎇ {currentProject || "no workspace"}</span>
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
