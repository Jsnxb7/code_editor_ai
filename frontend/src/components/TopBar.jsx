import { useIde } from "../context/IdeContext";

export default function TopBar() {
  const {
    activePath,
    tabs,
    openWorkspaceFolder,
    saveActiveTab,
    saveAllTabs,
    saveWorkspaceToFolder,
    validateActiveFile,
    runTests,
    runInTerminal,
    setQuickOpenOpen,
    setCommandPaletteOpen,
    setBottomCollapsed,
  } = useIde();

  const activeTab = tabs.find((t) => t.path === activePath);

  const runActiveFile = () => {
    if (!activePath) return;
    if (!activePath.endsWith(".py")) return;
    runInTerminal(`python ${activePath}\r`);
  };

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-icon">B</div>
        Bob IDE
      </div>
      <div className="topbar-divider" />
      <button className="topbar-btn" onClick={() => setQuickOpenOpen(true)} title="Quick Open (Ctrl+P)">
        Go to File…
      </button>
      <button className="topbar-btn" onClick={openWorkspaceFolder} title="Open a local folder as a workspace">
        Open Folder
      </button>
      <button className="topbar-btn" onClick={saveWorkspaceToFolder} title="Save workspace files to a local folder">
        Save Folder
      </button>
      <div className="topbar-spacer" />
      <div className="topbar-actions">
        <button
          className="topbar-btn"
          disabled={!tabs.some((t) => t.dirty)}
          onClick={saveAllTabs}
          title="Save all open files"
        >
          Save All
        </button>
        <button
          className="topbar-btn"
          disabled={!activePath}
          onClick={saveActiveTab}
          title="Save (Ctrl+S)"
        >
          {activeTab?.dirty ? "Save •" : "Save"}
        </button>
        <button className="topbar-btn" disabled={!activePath} onClick={validateActiveFile} title="Validate current file">
          Validate
        </button>
        <button className="topbar-btn" onClick={runTests} title="Run pytest">
          Tests
        </button>
        <button
          className="topbar-btn btn-primary"
          disabled={!activePath?.endsWith(".py")}
          onClick={runActiveFile}
          title="Run Python file in terminal"
        >
          ▶ Run
        </button>
        <button
          className="topbar-btn"
          onClick={() => setBottomCollapsed((c) => !c)}
          title="Toggle panel (Ctrl+`)"
        >
          ⌽
        </button>
        <button className="topbar-btn" onClick={() => setCommandPaletteOpen(true)} title="Command Palette">
          ⋯
        </button>
      </div>
    </header>
  );
}
