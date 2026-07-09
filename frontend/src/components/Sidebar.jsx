import { useState, useRef, useEffect, useCallback } from "react";
import { useIde } from "../context/IdeContext";
import { api } from "../api";
import TreeNode from "./TreeNode";
import ContextMenu from "./ContextMenu";
import SourceControlPanel from "./SourceControlPanel";

export default function Sidebar() {
  const {
    sidebarView,
    projects,
    currentProject,
    selectProject,
    createWorkspace,
    tree,
    treeLoading,
    activePath,
    openFile,
    createFile,
    createFolder,
    deleteEntry,
    renameEntry,
    refreshTree,
    promptDialog,
    confirmDialog,
    runSearch,
    searchResults,
    getSourceDecoration,
    getFolderChangeCount,
    setDiffChange,
    loadWorktree,
    pushToast,
    setSidebarView,
    setSidebarCollapsed,
  } = useIde();

  const [menu, setMenu] = useState(null); // { x, y, item }
  const [searchValue, setSearchValue] = useState("");
  // selectedFolder: the folder path that is "focused" in the tree.
  const [selectedFolder, setSelectedFolder] = useState("");
  // inline rename state: { path, value }
  const [inlineRename, setInlineRename] = useState(null);
  // inline new-entry state: { parentPath, kind:"file"|"folder", value }
  const [inlineNew, setInlineNew] = useState(null);

  const inlineInputRef = useRef(null);

  const activeInlineTarget = inlineRename
    ? `rename:${inlineRename.path}`
    : inlineNew
      ? `new:${inlineNew.kind}:${inlineNew.parentPath}`
      : "";

  useEffect(() => {
    if (activeInlineTarget && inlineInputRef.current) {
      inlineInputRef.current.focus();
      inlineInputRef.current.select();
    }
  }, [activeInlineTarget]);

  // Derive the "current folder" from activePath or selectedFolder
  const folderOf = useCallback((path) => {
    if (!path) return "";
    return path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  }, []);

  const contextFolderFor = useCallback(
    (item) => {
      if (!item || item.path === "") return "";
      if (item.type === "folder") return item.path;
      return folderOf(item.path);
    },
    [folderOf]
  );

  // The folder new files/folders will go into when using the toolbar buttons
  const activeFolder = selectedFolder !== null ? selectedFolder : folderOf(activePath || "");

  // ---- inline new entry ----
  const startInlineNew = (parentPath, kind) => {
    setInlineNew({ parentPath: parentPath ?? "", kind, value: "" });
    setMenu(null);
  };

  const commitInlineNew = async () => {
    if (!inlineNew) return;
    const { parentPath, kind, value } = inlineNew;
    const trimmed = value.trim();
    setInlineNew(null);
    if (!trimmed) return;
    if (trimmed.includes("/") || trimmed.includes("\\")) {
      alert("Use a file or folder name only. Create nested folders one level at a time.");
      return;
    }
    const fullPath = parentPath ? `${parentPath}/${trimmed}` : trimmed;
    try {
      if (kind === "file") await createFile(fullPath);
      else await createFolder(fullPath);
    } catch (err) {
      alert(err.message);
    }
  };

  const cancelInlineNew = () => setInlineNew(null);

  // ---- inline rename ----
  const startInlineRename = (item) => {
    setInlineRename({ path: item.path, value: item.name });
    setMenu(null);
  };

  const commitInlineRename = async () => {
    if (!inlineRename) return;
    const { path, value } = inlineRename;
    const trimmed = value.trim();
    setInlineRename(null);
    if (!trimmed || trimmed === path.split("/").pop()) return;
    if (trimmed.includes("/") || trimmed.includes("\\")) {
      alert("Use a file or folder name only. Move items by creating the target folder first.");
      return;
    }
    const newPath = path.includes("/")
      ? path.slice(0, path.lastIndexOf("/") + 1) + trimmed
      : trimmed;
    try {
      await renameEntry(path, newPath);
    } catch (err) {
      alert(err.message);
    }
  };

  const cancelInlineRename = () => setInlineRename(null);

  // ---- delete ----
  const doDelete = async (item) => {
    const ok = await confirmDialog(`Delete "${item.path}"? This cannot be undone.`);
    if (!ok) return;
    try {
      await deleteEntry(item.path);
    } catch (err) {
      alert(err.message);
    }
  };

  const openSourceDiff = async (path) => {
    try {
      const data = await api.worktreeStatus(currentProject);
      const match = [
        ...(data.conflicts || []),
        ...(data.proposed || []),
        ...(data.changes || []),
        ...(data.staged || []),
      ].find((change) => change.path === path);
      if (!match) {
        pushToast(`No source-control change for ${path}`);
        return;
      }
      setDiffChange(await api.worktreeDiff(currentProject, match.change_id));
      setSidebarView("sourceControl");
      setSidebarCollapsed(false);
    } catch (err) {
      pushToast(err.message, "error");
    }
  };

  const stageFromExplorer = async (path) => {
    try {
      const data = await api.worktreeStatus(currentProject);
      const match = (data.changes || []).find((change) => change.path === path);
      if (!match) {
        pushToast(`No unstaged change for ${path}`);
        return;
      }
      await api.worktreeStage(currentProject, match.change_id);
      await loadWorktree(currentProject);
      pushToast(`Staged ${path}`);
    } catch (err) {
      pushToast(err.message, "error");
    }
  };

  const compareWithBaseline = async (path) => {
    try {
      const diff = await api.worktreeCompareSnapshot(currentProject, path);
      setDiffChange({
        change_id: `compare-${path}`,
        path,
        status: "baseline",
        source: "snapshot",
        before_content: diff.before_content || "",
        after_content: diff.after_content || "",
        diff: diff.diff || "",
        hunks: [],
      });
      setSidebarView("sourceControl");
      setSidebarCollapsed(false);
    } catch (err) {
      pushToast(err.message, "error");
    }
  };

  const ignoreExplorerPath = async (path) => {
    const ok = await confirmDialog(`Add "${path}" to .gitignore?`);
    if (!ok) return;
    try {
      await api.worktreeIgnorePath(currentProject, path);
      await loadWorktree(currentProject);
      pushToast(`Ignored ${path}`);
    } catch (err) {
      pushToast(err.message, "error");
    }
  };

  // ---- context menu ----
  const handleContextMenu = (e, item) => {
    e.preventDefault();
    e.stopPropagation();
    setSelectedFolder(contextFolderFor(item));
    setMenu({ x: e.clientX, y: e.clientY, item });
  };

  const handleRootContextMenu = (e) => {
    e.preventDefault();
    setSelectedFolder("");
    setMenu({ x: e.clientX, y: e.clientY, item: { type: "folder", path: "" } });
  };

  const menuItems = menu
    ? menu.item.type === "folder"
      ? [
          { label: "New File Here", onClick: () => startInlineNew(menu.item.path, "file") },
          { label: "New Folder Here", onClick: () => startInlineNew(menu.item.path, "folder") },
          ...(menu.item.path
            ? [
                { divider: true },
                { label: "Compare Folder in Source Control", onClick: () => { setSidebarView("sourceControl"); setSidebarCollapsed(false); } },
                { label: "Add Folder to .gitignore", onClick: () => ignoreExplorerPath(menu.item.path) },
                { divider: true },
                { label: "Rename", onClick: () => startInlineRename(menu.item) },
                { label: "Delete", danger: true, onClick: () => doDelete(menu.item) },
              ]
            : [
                { divider: true },
                { label: "Open Source Control", onClick: () => { setSidebarView("sourceControl"); setSidebarCollapsed(false); } },
              ]),
        ]
      : [
          { label: "Open", onClick: () => openFile(menu.item.path) },
          { label: "Open Changes", onClick: () => openSourceDiff(menu.item.path) },
          { label: "Compare with Baseline", onClick: () => compareWithBaseline(menu.item.path) },
          { label: "Stage Change", onClick: () => stageFromExplorer(menu.item.path) },
          { divider: true },
          { label: "New File Here", onClick: () => startInlineNew(folderOf(menu.item.path), "file") },
          { label: "New Folder Here", onClick: () => startInlineNew(folderOf(menu.item.path), "folder") },
          { divider: true },
          { label: "Rename", onClick: () => startInlineRename(menu.item) },
          { label: "Add to .gitignore", onClick: () => ignoreExplorerPath(menu.item.path) },
          { label: "Delete", danger: true, onClick: () => doDelete(menu.item) },
        ]
    : [];

  if (sidebarView === "sourceControl") {
    return <SourceControlPanel />;
  }

  // ---- search view ----
  if (sidebarView === "search") {
    return (
      <aside className="sidebar">
        <div className="sidebar-header">SEARCH</div>
        <div className="search-box">
          <input
            placeholder="Search in workspace"
            value={searchValue}
            onChange={(e) => setSearchValue(e.target.value)}
            onKeyDown={(e) =>
              e.key === "Enter" && searchValue.trim() && runSearch(searchValue.trim())
            }
          />
        </div>
        <div className="search-sidebar-results">
          {searchResults &&
            searchResults.matches.map((m, i) => (
              <button
                key={i}
                className="search-hit"
                onClick={async () => {
                  await openFile(m.file);
                }}
              >
                <div className="search-file">
                  {m.file}:{m.line}
                </div>
                <div className="search-match">{m.match}</div>
              </button>
            ))}
          {searchResults && !searchResults.matches.length && (
            <div className="empty-hint">No matches for "{searchResults.query}"</div>
          )}
        </div>
      </aside>
    );
  }

  // ---- explorer view ----
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span>EXPLORER</span>
        <div className="sidebar-header-actions">
          <button
            title={`New File${activeFolder ? ` in ${activeFolder}` : " at root"}`}
            onClick={() => startInlineNew(activeFolder, "file")}
          >
            File
          </button>
          <button
            title={`New Folder${activeFolder ? ` in ${activeFolder}` : " at root"}`}
            onClick={() => startInlineNew(activeFolder, "folder")}
          >
            Dir
          </button>
          <button title="Refresh" onClick={refreshTree}>
            ↻
          </button>
        </div>
      </div>

      <div className="workspace-select-row">
        <select
          value={currentProject}
          onChange={(e) => selectProject(e.target.value)}
          title="Select workspace"
        >
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <button
          title="New workspace"
          onClick={async () => {
            const name = await promptDialog("New workspace name:");
            if (!name) return;
            try {
              await createWorkspace(name);
            } catch (err) {
              alert(err.message);
            }
          }}
        >
          +
        </button>
      </div>

      <div className="tree-scroll" onContextMenu={handleRootContextMenu}>
        {treeLoading && <div className="empty-hint">Loading…</div>}
        {!treeLoading && tree && (!tree.children || !tree.children.length) && !inlineNew && (
          <div className="empty-hint">No files yet. Right-click or use File above.</div>
        )}

        {/* Inline new entry at root level */}
        {!treeLoading && inlineNew && inlineNew.parentPath === "" && (
          <div className="tree-row tree-file inline-new-row" style={{ paddingLeft: 8 }}>
            <span className="tree-icon">{inlineNew.kind === "file" ? "TXT" : "DIR"}</span>
            <input
              ref={inlineInputRef}
              className="inline-rename-input"
              value={inlineNew.value}
              placeholder={inlineNew.kind === "file" ? "file-name.ext" : "folder-name"}
              onChange={(e) => setInlineNew((s) => ({ ...s, value: e.target.value }))}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitInlineNew();
                if (e.key === "Escape") cancelInlineNew();
              }}
              onBlur={commitInlineNew}
            />
          </div>
        )}

        {!treeLoading &&
          tree?.children?.map((item) => (
            <TreeNode
              key={item.path}
              item={item}
              depth={0}
              activePath={activePath}
              selectedFolder={selectedFolder}
              onOpenFile={openFile}
              onContextMenu={handleContextMenu}
              onSelectFolder={setSelectedFolder}
              inlineRename={inlineRename}
              inlineNew={inlineNew}
              inlineInputRef={inlineInputRef}
              onCommitRename={commitInlineRename}
              onCancelRename={cancelInlineRename}
              onCommitNew={commitInlineNew}
              onCancelNew={cancelInlineNew}
              onChangeRename={(v) => setInlineRename((s) => ({ ...s, value: v }))}
              onChangeNew={(v) => setInlineNew((s) => ({ ...s, value: v }))}
              getSourceDecoration={getSourceDecoration}
              getFolderChangeCount={getFolderChangeCount}
            />
          ))}
      </div>

      {menu && (
        <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={() => setMenu(null)} />
      )}
    </aside>
  );
}
