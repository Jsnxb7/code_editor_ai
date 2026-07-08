import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { getSocket } from "../socket";

const IdeContext = createContext(null);

const EXT_TO_LANG = {
  bat: "bat",
  c: "c",
  cpp: "cpp",
  cs: "csharp",
  py: "python",
  html: "html",
  css: "css",
  go: "go",
  java: "java",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  json: "json",
  md: "markdown",
  php: "php",
  rb: "ruby",
  rs: "rust",
  sh: "shell",
  sql: "sql",
  toml: "toml",
  txt: "plaintext",
  xml: "xml",
  yaml: "yaml",
  yml: "yaml",
};

const EDITABLE_EXTENSIONS = new Set([
  "bat", "c", "cfg", "cpp", "cs", "css", "go", "h", "hpp", "html", "ini", "java",
  "js", "jsx", "json", "less", "lua", "md", "php", "ps1", "py", "rb", "rs",
  "sass", "scss", "sh", "sql", "svg", "toml", "ts", "tsx", "txt", "xml", "yaml", "yml",
]);
const EDITABLE_FILENAMES = new Set([".env", ".gitignore", "Dockerfile", "Makefile", "README"]);
const IGNORED_FOLDER_NAMES = new Set([
  ".git", "__pycache__", "node_modules", "venv", ".venv", ".pytest_cache", "dist", "build",
]);

function isEditableFileName(name = "") {
  const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
  return EDITABLE_EXTENSIONS.has(ext) || EDITABLE_FILENAMES.has(name);
}

function flattenTreeFiles(node, files = []) {
  if (!node) return files;
  if (node.type === "file") files.push(node.path);
  (node.children || []).forEach((child) => flattenTreeFiles(child, files));
  return files;
}

async function ensureDirectoryHandle(rootHandle, folderPath) {
  let handle = rootHandle;
  for (const part of folderPath.split("/").filter(Boolean)) {
    handle = await handle.getDirectoryHandle(part, { create: true });
  }
  return handle;
}

export function extToLang(path = "") {
  const ext = path.split(".").pop().toLowerCase();
  return EXT_TO_LANG[ext] || "plaintext";
}

let toastSeq = 0;
let terminalSeq = 0;
const realtimeClientId = crypto.randomUUID();

const STATUS_DECORATIONS = {
  conflicts: { label: "C", className: "status-conflict", title: "Conflict" },
  proposed: { label: "P", className: "status-proposed", title: "Bob proposal" },
  changes: { add: "A", modify: "M", delete: "D", rename: "R", className: "status-changed", title: "Changed" },
  staged: { add: "A", modify: "M", delete: "D", rename: "R", className: "status-staged", title: "Staged" },
};

function decorationFor(group, change) {
  const base = STATUS_DECORATIONS[group];
  if (!base) return null;
  return {
    label: base.label || base[change?.action] || "M",
    className: base.className,
    title: base.title,
    group,
    change,
  };
}

export function IdeProvider({ children }) {
  const [projects, setProjects] = useState([]);
  const [currentProject, setCurrentProject] = useState("");
  const [tree, setTree] = useState(null);
  const [treeLoading, setTreeLoading] = useState(false);

  // tabs: ordered array of { path, content, savedContent, dirty }
  const [tabs, setTabs] = useState([]);
  const [activePath, setActivePath] = useState(null);

  const [problems, setProblems] = useState([]);
  const [searchResults, setSearchResults] = useState(null);
  const [worktreeStatus, setWorktreeStatus] = useState(null);
  const [diffChange, setDiffChange] = useState(null);

  const [sidebarView, setSidebarView] = useState("explorer"); // explorer | search | bob
  const [bottomTab, setBottomTab] = useState("terminal"); // terminal | problems | search
  const [bottomCollapsed, setBottomCollapsed] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [bobCollapsed, setBobCollapsed] = useState(false);

  const [terminals, setTerminals] = useState([]); // { id, title }
  const [activeTerminalId, setActiveTerminalId] = useState(null);
  const terminalRunRef = useRef(null); // set by Terminal panel: (id, text) => void

  const [toasts, setToasts] = useState([]);
  const [dialog, setDialog] = useState(null); // { kind, message, defaultValue, resolve }
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [quickOpenOpen, setQuickOpenOpen] = useState(false);
  const editorVersionRef = useRef(0);

  const pushToast = useCallback((message, variant = "info") => {
    const id = ++toastSeq;
    setToasts((t) => [...t, { id, message, variant }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }, []);

  const confirmDialog = useCallback(
    (message) =>
      new Promise((resolve) => {
        setDialog({ kind: "confirm", message, resolve });
      }),
    []
  );

  const promptDialog = useCallback(
    (message, defaultValue = "") =>
      new Promise((resolve) => {
        setDialog({ kind: "prompt", message, defaultValue, resolve });
      }),
    []
  );

  const resolveDialog = useCallback(
    (value) => {
      if (dialog?.resolve) dialog.resolve(value);
      setDialog(null);
    },
    [dialog]
  );

  // ---- workspaces ----
  const loadWorkspaces = useCallback(async (preferProject) => {
    const data = await api.workspaces();
    setProjects(data.projects);
    let next = preferProject && data.projects.includes(preferProject) ? preferProject : null;
    if (!next) next = data.projects.includes(currentProject) ? currentProject : data.projects[0] || "";
    setCurrentProject(next || "");
    return next || "";
  }, [currentProject]);

  const loadTree = useCallback(async (project) => {
    if (!project) {
      setTree(null);
      return;
    }
    setTreeLoading(true);
    try {
      const data = await api.tree(project);
      setTree(data);
    } finally {
      setTreeLoading(false);
    }
  }, []);

  const loadWorktree = useCallback(async (project) => {
    if (!project) {
      setWorktreeStatus(null);
      return null;
    }
    const status = await api.worktreeStatus(project);
    setWorktreeStatus(status);
    return status;
  }, []);

  const sourceControlIndex = useMemo(() => {
    const byPath = new Map();
    const folderCounts = new Map();
    for (const group of ["conflicts", "proposed", "changes", "staged"]) {
      for (const change of worktreeStatus?.[group] || []) {
        if (!byPath.has(change.path)) byPath.set(change.path, decorationFor(group, change));
        const parts = change.path.split("/");
        for (let index = 1; index < parts.length; index += 1) {
          const folder = parts.slice(0, index).join("/");
          folderCounts.set(folder, (folderCounts.get(folder) || 0) + 1);
        }
      }
    }
    return { byPath, folderCounts };
  }, [worktreeStatus]);

  const sourceControlTotal = useMemo(
    () => Object.values(worktreeStatus?.summary || {}).reduce((sum, value) => sum + value, 0),
    [worktreeStatus]
  );

  const getSourceDecoration = useCallback(
    (path) => sourceControlIndex.byPath.get(path) || null,
    [sourceControlIndex]
  );

  const getFolderChangeCount = useCallback(
    (path) => sourceControlIndex.folderCounts.get(path) || 0,
    [sourceControlIndex]
  );

  useEffect(() => {
    if (!currentProject) return undefined;
    const socket = getSocket();
    let refreshTimer;

    const join = () => socket.emit("workspace:join", { project: currentProject });
    const onWorkspaceChanged = ({ project, paths = [] }) => {
      if (project !== currentProject) return;
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => {
        loadTree(currentProject);
        loadWorktree(currentProject).catch(() => {});
      }, 40);
      setTabs((currentTabs) => {
        for (const tab of currentTabs) {
          if (!tab.dirty && paths.includes(tab.path)) {
            api.readFile(currentProject, tab.path).then((data) => {
              setTabs((latest) =>
                latest.map((item) =>
                  item.path === tab.path && !item.dirty
                    ? { ...item, content: data.content, savedContent: data.content }
                    : item
                )
              );
            }).catch(() => {});
          }
        }
        return currentTabs;
      });
    };
    const onWorktreeChanged = ({ project }) => {
      if (project === currentProject) loadWorktree(project).catch(() => {});
    };
    const onEditorChange = ({ project, path, content, clientId }) => {
      if (project !== currentProject || clientId === realtimeClientId) return;
      setTabs((currentTabs) =>
        currentTabs.map((tab) =>
          tab.path === path
            ? { ...tab, content, dirty: content !== tab.savedContent }
            : tab
        )
      );
    };

    join();
    socket.on("connect", join);
    socket.on("workspace:changed", onWorkspaceChanged);
    socket.on("worktree:changed", onWorktreeChanged);
    socket.on("editor:change", onEditorChange);
    return () => {
      clearTimeout(refreshTimer);
      socket.emit("workspace:leave", { project: currentProject });
      socket.off("connect", join);
      socket.off("workspace:changed", onWorkspaceChanged);
      socket.off("worktree:changed", onWorktreeChanged);
      socket.off("editor:change", onEditorChange);
    };
  }, [currentProject, loadTree, loadWorktree]);

  const selectProject = useCallback(
    async (project) => {
      const dirty = tabs.some((t) => t.dirty);
      if (dirty && !(await confirmDialog("You have unsaved changes. Switch workspace anyway?"))) {
        return;
      }
      setCurrentProject(project);
      setTabs([]);
      setActivePath(null);
      setProblems([]);
      setSearchResults(null);
      setDiffChange(null);
      await loadTree(project);
      await loadWorktree(project);
    },
    [tabs, confirmDialog, loadTree, loadWorktree]
  );

  const createWorkspace = useCallback(async (name) => {
    const data = await api.createWorkspace(name);
    await loadWorkspaces(data.project);
    await loadTree(data.project);
    await loadWorktree(data.project);
    setTabs([]);
    setActivePath(null);
    pushToast(`Created workspace "${data.project}"`);
    return data.project;
  }, [loadWorkspaces, loadTree, loadWorktree, pushToast]);

  const openWorkspaceFolder = useCallback(async () => {
    if (!window.showDirectoryPicker) {
      pushToast("Your browser does not support opening folders here.", "error");
      return;
    }
    const dirty = tabs.some((t) => t.dirty);
    if (dirty && !(await confirmDialog("You have unsaved changes. Open another folder anyway?"))) {
      return;
    }

    const dirHandle = await window.showDirectoryPicker({ mode: "read" });
    const files = [];
    const folders = [];

    const walk = async (handle, prefix = "") => {
      for await (const entry of handle.values()) {
        const relPath = prefix ? `${prefix}/${entry.name}` : entry.name;
        if (entry.kind === "directory") {
          if (IGNORED_FOLDER_NAMES.has(entry.name)) continue;
          folders.push(relPath);
          await walk(entry, relPath);
        } else if (isEditableFileName(entry.name)) {
          const file = await entry.getFile();
          files.push({ path: relPath, content: await file.text() });
        }
      }
    };

    await walk(dirHandle);
    const data = await api.importWorkspace(dirHandle.name, files, folders);
    await loadWorkspaces(data.project);
    await loadTree(data.project);
    await loadWorktree(data.project);
    setTabs([]);
    setActivePath(null);
    setProblems([]);
    setSearchResults(null);
    pushToast(`Opened folder "${data.project}" (${data.files} files)`);
  }, [tabs, confirmDialog, loadWorkspaces, loadTree, loadWorktree, pushToast]);

  // ---- tabs / files ----
  const openFile = useCallback(
    async (path) => {
      const existing = tabs.find((t) => t.path === path);
      if (existing) {
        setActivePath(path);
        return;
      }
      const data = await api.readFile(currentProject, path);
      setTabs((prev) => [
        ...prev,
        { path, content: data.content, savedContent: data.content, dirty: false },
      ]);
      setActivePath(path);
      setDiffChange(null);
    },
    [tabs, currentProject]
  );

  const closeTab = useCallback(
    async (path) => {
      const tab = tabs.find((t) => t.path === path);
      if (tab?.dirty) {
        const choice = await confirmDialog(`"${path}" has unsaved changes. Close without saving?`);
        if (!choice) return;
      }
      setTabs((prev) => {
        const idx = prev.findIndex((t) => t.path === path);
        const next = prev.filter((t) => t.path !== path);
        if (activePath === path) {
          const fallback = next[idx] || next[idx - 1] || next[next.length - 1];
          setActivePath(fallback ? fallback.path : null);
        }
        return next;
      });
    },
    [tabs, activePath, confirmDialog]
  );

  const updateTabContent = useCallback((path, content) => {
    setTabs((prev) =>
      prev.map((t) => (t.path === path ? { ...t, content, dirty: content !== t.savedContent } : t))
    );
    if (currentProject) {
      getSocket().emit("editor:change", {
        project: currentProject,
        path,
        content,
        clientId: realtimeClientId,
        version: ++editorVersionRef.current,
      });
    }
  }, [currentProject]);

  const saveTab = useCallback(
    async (path) => {
      const tab = tabs.find((t) => t.path === path);
      if (!tab) return;
      await api.saveFile(currentProject, path, tab.content);
      await loadWorktree(currentProject);
      setTabs((prev) =>
        prev.map((t) => (t.path === path ? { ...t, savedContent: t.content, dirty: false } : t))
      );
      pushToast(`Saved ${path}`);
    },
    [tabs, currentProject, loadWorktree, pushToast]
  );

  const saveActiveTab = useCallback(() => {
    if (activePath) return saveTab(activePath);
    return Promise.resolve();
  }, [activePath, saveTab]);

  const saveAllTabs = useCallback(async () => {
    const dirtyTabs = tabs.filter((t) => t.dirty);
    for (const tab of dirtyTabs) {
      await api.saveFile(currentProject, tab.path, tab.content);
    }
    if (dirtyTabs.length) {
      await loadWorktree(currentProject);
      setTabs((prev) =>
        prev.map((t) => (t.dirty ? { ...t, savedContent: t.content, dirty: false } : t))
      );
      pushToast(`Saved ${dirtyTabs.length} file${dirtyTabs.length === 1 ? "" : "s"}`);
    }
  }, [tabs, currentProject, loadWorktree, pushToast]);

  const saveWorkspaceToFolder = useCallback(async () => {
    if (!window.showDirectoryPicker) {
      pushToast("Your browser does not support saving to folders here.", "error");
      return;
    }
    if (!currentProject || !tree) return;

    const dirHandle = await window.showDirectoryPicker({ mode: "readwrite" });
    const openTabs = new Map(tabs.map((tab) => [tab.path, tab.content]));
    const filePaths = flattenTreeFiles(tree);

    for (const path of filePaths) {
      const content = openTabs.has(path)
        ? openTabs.get(path)
        : (await api.readFile(currentProject, path)).content;
      const parts = path.split("/");
      const fileName = parts.pop();
      const parentHandle = await ensureDirectoryHandle(dirHandle, parts.join("/"));
      const fileHandle = await parentHandle.getFileHandle(fileName, { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(content);
      await writable.close();
    }

    pushToast(`Saved workspace "${currentProject}" to selected folder`);
  }, [currentProject, tree, tabs, pushToast]);

  const createFile = useCallback(
    async (path) => {
      await api.createFile(currentProject, path);
      await loadTree(currentProject);
      await loadWorktree(currentProject);
      await openFile(path);
      pushToast(`Created ${path}`);
    },
    [currentProject, loadTree, loadWorktree, openFile, pushToast]
  );

  const createFolder = useCallback(
    async (path) => {
      await api.createFolder(currentProject, path);
      await loadTree(currentProject);
      pushToast(`Created folder ${path}`);
    },
    [currentProject, loadTree, pushToast]
  );

  const deleteEntry = useCallback(
    async (path) => {
      await api.deleteFile(currentProject, path);
      setTabs((prev) => prev.filter((t) => t.path !== path && !t.path.startsWith(path + "/")));
      if (activePath === path || activePath?.startsWith(path + "/")) setActivePath(null);
      await loadTree(currentProject);
      await loadWorktree(currentProject);
      pushToast(`Deleted ${path}`);
    },
    [currentProject, activePath, loadTree, loadWorktree, pushToast]
  );

  const renameEntry = useCallback(
    async (path, newPath) => {
      await api.renameFile(currentProject, path, newPath);
      setTabs((prev) => prev.map((t) => (t.path === path ? { ...t, path: newPath } : t)));
      if (activePath === path) setActivePath(newPath);
      await loadTree(currentProject);
      await loadWorktree(currentProject);
      pushToast(`Renamed to ${newPath}`);
    },
    [currentProject, activePath, loadTree, loadWorktree, pushToast]
  );

  const refreshTree = useCallback(() => loadTree(currentProject), [loadTree, currentProject]);

  // ---- validate / tests ----
  const validateActiveFile = useCallback(async () => {
    if (!activePath) return;
    const tab = tabs.find((t) => t.path === activePath);
    const data = await api.validate(activePath, tab?.content ?? "");
    setProblems(data.problems);
    setBottomTab("problems");
    setBottomCollapsed(false);
    return data.problems;
  }, [activePath, tabs]);

  const runTests = useCallback(async () => {
    setBottomTab("problems");
    setBottomCollapsed(false);
    const data = await api.runPytest(currentProject);
    const lines = `${data.stdout}\n${data.stderr}`.trim().split("\n").filter(Boolean);
    const summary = [
      {
        line: 0,
        severity: data.failed > 0 ? "error" : "info",
        message: `pytest: ${data.passed} passed, ${data.failed} failed`,
      },
      ...lines.slice(-12).map((message) => ({ line: 0, severity: "info", message })),
    ];
    setProblems(summary);
    return data;
  }, [currentProject]);

  const runSearch = useCallback(
    async (query) => {
      const data = await api.search(currentProject, query);
      setSearchResults({ query, matches: data.matches });
      setBottomTab("search");
      setBottomCollapsed(false);
      return data.matches;
    },
    [currentProject]
  );

  // ---- terminals ----
  const createTerminal = useCallback((title) => {
    const id = `term-${++terminalSeq}`;
    setTerminals((prev) => [...prev, { id, title: title || `Terminal ${terminalSeq}` }]);
    setActiveTerminalId(id);
    setBottomTab("terminal");
    setBottomCollapsed(false);
    return id;
  }, []);

  const closeTerminal = useCallback((id) => {
    setTerminals((prev) => {
      const idx = prev.findIndex((t) => t.id === id);
      const next = prev.filter((t) => t.id !== id);
      setActiveTerminalId((cur) => {
        if (cur !== id) return cur;
        const fallback = next[idx] || next[idx - 1];
        return fallback ? fallback.id : null;
      });
      return next;
    });
  }, []);

  const runInTerminal = useCallback(
    (text) => {
      let id = activeTerminalId;
      if (!id || !terminals.some((t) => t.id === id)) {
        id = createTerminal();
      }
      setBottomTab("terminal");
      setBottomCollapsed(false);
      // give the terminal a tick to mount/connect before sending input
      setTimeout(() => terminalRunRef.current?.(id, text), terminals.length ? 0 : 250);
    },
    [activeTerminalId, terminals, createTerminal]
  );

  const value = useMemo(
    () => ({
      projects,
      currentProject,
      tree,
      treeLoading,
      tabs,
      activePath,
      problems,
      searchResults,
      worktreeStatus,
      sourceControlTotal,
      getSourceDecoration,
      getFolderChangeCount,
      diffChange,
      setDiffChange,
      sidebarView,
      setSidebarView,
      bottomTab,
      setBottomTab,
      bottomCollapsed,
      setBottomCollapsed,
      sidebarCollapsed,
      setSidebarCollapsed,
      bobCollapsed,
      setBobCollapsed,
      terminals,
      activeTerminalId,
      setActiveTerminalId,
      terminalRunRef,
      toasts,
      pushToast,
      dialog,
      confirmDialog,
      promptDialog,
      resolveDialog,
      commandPaletteOpen,
      setCommandPaletteOpen,
      quickOpenOpen,
      setQuickOpenOpen,
      loadWorkspaces,
      loadTree,
      loadWorktree,
      selectProject,
      createWorkspace,
      openWorkspaceFolder,
      openFile,
      closeTab,
      setActivePath,
      updateTabContent,
      saveTab,
      saveActiveTab,
      saveAllTabs,
      saveWorkspaceToFolder,
      createFile,
      createFolder,
      deleteEntry,
      renameEntry,
      refreshTree,
      validateActiveFile,
      runTests,
      runSearch,
      createTerminal,
      closeTerminal,
      runInTerminal,
    }),
    [
      projects,
      currentProject,
      tree,
      treeLoading,
      tabs,
      activePath,
      problems,
      searchResults,
      worktreeStatus,
      sourceControlTotal,
      getSourceDecoration,
      getFolderChangeCount,
      diffChange,
      sidebarView,
      bottomTab,
      bottomCollapsed,
      sidebarCollapsed,
      bobCollapsed,
      terminals,
      activeTerminalId,
      toasts,
      pushToast,
      dialog,
      confirmDialog,
      promptDialog,
      resolveDialog,
      commandPaletteOpen,
      quickOpenOpen,
      loadWorkspaces,
      loadTree,
      loadWorktree,
      selectProject,
      createWorkspace,
      openWorkspaceFolder,
      openFile,
      closeTab,
      updateTabContent,
      saveTab,
      saveActiveTab,
      saveAllTabs,
      saveWorkspaceToFolder,
      createFile,
      createFolder,
      deleteEntry,
      renameEntry,
      refreshTree,
      validateActiveFile,
      runTests,
      runSearch,
      createTerminal,
      closeTerminal,
      runInTerminal,
    ]
  );

  return <IdeContext.Provider value={value}>{children}</IdeContext.Provider>;
}

export function useIde() {
  const ctx = useContext(IdeContext);
  if (!ctx) throw new Error("useIde must be used inside IdeProvider");
  return ctx;
}
