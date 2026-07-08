import { useEffect, useMemo, useState } from "react";
import { useIde } from "../context/IdeContext";
import { api } from "../api";
import { fuzzyFilter } from "../fuzzy";

export default function CommandPalette() {
  const {
    commandPaletteOpen,
    setCommandPaletteOpen,
    openWorkspaceFolder,
    saveActiveTab,
    saveAllTabs,
    saveWorkspaceToFolder,
    validateActiveFile,
    runTests,
    createTerminal,
    setQuickOpenOpen,
    setBottomCollapsed,
    setSidebarCollapsed,
    setBobCollapsed,
    activePath,
    runInTerminal,
    setSidebarView,
    loadWorktree,
    currentProject,
    worktreeStatus,
    pushToast,
  } = useIde();

  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const commands = useMemo(
    () => [
      { label: "File: Save", run: saveActiveTab, enabled: !!activePath },
      { label: "File: Save All", run: saveAllTabs },
      { label: "File: Open Folder", run: openWorkspaceFolder },
      { label: "File: Save Workspace to Folder", run: saveWorkspaceToFolder },
      { label: "File: Quick Open…", run: () => setQuickOpenOpen(true) },
      { label: "Run: Validate Current File", run: validateActiveFile, enabled: !!activePath },
      { label: "Run: pytest", run: runTests },
      {
        label: "Run: Current Python File in Terminal",
        run: () => runInTerminal(`python ${activePath}\r`),
        enabled: !!activePath?.endsWith(".py"),
      },
      { label: "Terminal: New Terminal", run: () => createTerminal() },
      { label: "View: Toggle Panel", run: () => setBottomCollapsed((c) => !c) },
      { label: "View: Toggle Sidebar", run: () => setSidebarCollapsed((c) => !c) },
      { label: "View: Toggle Bob Assistant", run: () => setBobCollapsed((c) => !c) },
      { label: "Source Control: Open", run: () => { setSidebarView("sourceControl"); setSidebarCollapsed(false); } },
      { label: "Source Control: Refresh", run: () => loadWorktree(currentProject) },
      { label: "Source Control: Stage All", run: async () => { await api.worktreeStageAll(currentProject); await loadWorktree(currentProject); pushToast("Staged all changes"); }, enabled: !!worktreeStatus?.summary?.changes },
      { label: "Source Control: Apply Passing Bob Proposals", run: async () => { await api.worktreeApplyPassing(currentProject); await loadWorktree(currentProject); pushToast("Applied passing proposals"); }, enabled: !!worktreeStatus?.summary?.proposed },
      { label: "Bob: Run Agent on Current File", run: async () => { const prompt = window.prompt("What should Bob change?"); if (!prompt) return; await api.modelRunAgent(currentProject, prompt, activePath); pushToast("Bob run queued"); }, enabled: !!currentProject },
    ],
    [
      saveActiveTab,
      saveAllTabs,
      openWorkspaceFolder,
      saveWorkspaceToFolder,
      validateActiveFile,
      runTests,
      createTerminal,
      setQuickOpenOpen,
      setBottomCollapsed,
      setSidebarCollapsed,
      setBobCollapsed,
      activePath,
      runInTerminal,
      setSidebarView,
      loadWorktree,
      currentProject,
      worktreeStatus,
      pushToast,
    ]
  );

  const enabledCommands = commands.filter((c) => c.enabled !== false);
  const results = fuzzyFilter(enabledCommands, query, (c) => c.label);

  useEffect(() => {
    if (commandPaletteOpen) {
      setQuery("");
      setIndex(0);
    }
  }, [commandPaletteOpen]);

  if (!commandPaletteOpen) return null;

  const choose = (cmd) => {
    setCommandPaletteOpen(false);
    cmd?.run();
  };

  return (
    <div
      className="palette-overlay"
      onMouseDown={(e) => e.target === e.currentTarget && setCommandPaletteOpen(false)}
    >
      <div className="palette-box">
        <input
          autoFocus
          className="palette-input"
          placeholder="Type a command…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setCommandPaletteOpen(false);
            if (e.key === "ArrowDown") setIndex((i) => Math.min(i + 1, results.length - 1));
            if (e.key === "ArrowUp") setIndex((i) => Math.max(i - 1, 0));
            if (e.key === "Enter") choose(results[index]);
          }}
        />
        <div className="palette-list">
          {results.map((cmd, i) => (
            <div
              key={cmd.label}
              className={`palette-item ${i === index ? "active" : ""}`}
              onMouseEnter={() => setIndex(i)}
              onClick={() => choose(cmd)}
            >
              <span>{cmd.label}</span>
            </div>
          ))}
          {!results.length && <div className="palette-empty">No matching commands</div>}
        </div>
      </div>
    </div>
  );
}
