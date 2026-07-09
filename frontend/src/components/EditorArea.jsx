import { useCallback, useRef, useState } from "react";
import Editor, { DiffEditor } from "@monaco-editor/react";
import { Check, Clipboard, Eye, FileCode2, Layers, Minus, RotateCcw, ShieldAlert, X } from "lucide-react";
import { api } from "../api";
import { useIde, extToLang } from "../context/IdeContext";
import { useLsp } from "../hooks/useLsp";
import TabBar from "./TabBar";
import Breadcrumbs from "./Breadcrumbs";

function defineBobTheme(monaco) {
  monaco.editor.defineTheme("bob-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "5a6070", fontStyle: "italic" },
      { token: "string", foreground: "98c379" },
      { token: "keyword", foreground: "f5a623", fontStyle: "bold" },
      { token: "number", foreground: "4dd9ec" },
    ],
    colors: {
      "editor.background": "#0d0e11",
      "editor.foreground": "#e8eaf0",
      "editor.lineHighlightBackground": "#15171d",
      "editorLineNumber.foreground": "#3a3f4f",
      "editorLineNumber.activeForeground": "#f5a623",
      "editor.selectionBackground": "#f5a62330",
      "editorCursor.foreground": "#f5a623",
      "editorIndentGuide.background": "#1f222b",
      "editorWhitespace.foreground": "#2a2d38",
      "scrollbarSlider.background": "#2a2d3899",
      "editorWidget.background": "#1a1d24",
      "editorSuggestWidget.background": "#1a1d24",
    },
  });
}

export default function EditorArea() {
  const {
    tabs,
    activePath,
    currentProject,
    setActivePath,
    closeTab,
    updateTabContent,
    saveActiveTab,
    saveAllTabs,
    diffChange,
    setDiffChange,
    loadWorktree,
    pushToast,
    openFile,
  } = useIde();
  const editorRef = useRef(null);
  const monacoRef = useRef(null);
  const [lspStatus, setLspStatus] = useState("idle");
  const [peekHunk, setPeekHunk] = useState(null);
  const activeTab = tabs.find((t) => t.path === activePath);

  const handleBeforeMount = useCallback((monaco) => defineBobTheme(monaco), []);
  const handleMount = useCallback((editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveActiveTab());
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyS, () => saveAllTabs());
    editor.addCommand(monaco.KeyCode.F12, () => editor.getAction("editor.action.revealDefinition")?.run());
    editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.F12, () => editor.getAction("editor.action.goToReferences")?.run());
    editor.addCommand(monaco.KeyCode.F2, () => editor.getAction("editor.action.rename")?.run());
    setLspStatus("connecting");
  }, [saveActiveTab, saveAllTabs]);

  const handleDiffMount = useCallback((editor, monaco) => {
    const modified = editor.getModifiedEditor?.();
    if (!modified || !diffChange?.hunks?.length) return;
    const decorations = diffChange.hunks.map((hunk) => ({
      range: new monaco.Range(hunk.new_start || 1, 1, Math.max(hunk.new_start || 1, (hunk.new_start || 1) + Math.max(0, (hunk.new_lines || 1) - 1)), 1),
      options: {
        isWholeLine: true,
        glyphMarginClassName: `hunk-glyph hunk-glyph-${diffChange.source === "bob_model" ? "proposal" : diffChange.status === "conflict" ? "conflict" : "modified"}`,
        linesDecorationsClassName: `hunk-line hunk-line-${diffChange.source === "bob_model" ? "proposal" : "modified"}`,
        hoverMessage: { value: `${hunk.hunk_id} - ${hunk.status || "pending"}` },
      },
    }));
    modified.createDecorationsCollection?.(decorations);
  }, [diffChange]);

  const runDiffAction = async (operation, message, closeAfter = false) => {
    if (!diffChange) return;
    try {
      await operation();
      await loadWorktree(currentProject);
      pushToast(message, "success");
      if (closeAfter) setDiffChange(null);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const runProposalAction = async (operation, message, closeAfter = false) => {
    try {
      await operation();
      await loadWorktree(currentProject);
      pushToast(message, "success");
      if (closeAfter) closeTab(activeTab.path);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const runHunkAction = async (operation, message) => {
    try {
      await operation();
      await loadWorktree(currentProject);
      pushToast(message, "success");
      setDiffChange(null);
    } catch (error) {
      pushToast(error.message, "error");
    }
  };

  const copyHunk = async (hunk) => {
    try {
      await navigator.clipboard.writeText(hunk.diff);
      pushToast(`Copied ${hunk.hunk_id}`);
    } catch {
      pushToast(hunk.diff);
    }
  };

  useLsp({
    monaco: monacoRef.current,
    editor: editorRef.current,
    project: currentProject,
    filePath: activeTab?.proposal ? null : activeTab?.path,
    fileContent: activeTab?.proposal ? null : activeTab?.content,
  });

  return (
    <section className="editor-column">
      <TabBar tabs={tabs} activePath={activePath} onSelect={setActivePath} onClose={closeTab} />
      <Breadcrumbs project={currentProject} path={activeTab?.proposal ? activeTab.realPath : activePath} />
      {lspStatus !== "idle" && !activeTab?.proposal && <div className={`lsp-badge lsp-${lspStatus}`} title="Language Server (Pyright)">⬤ LSP</div>}
      <div className="editor-host">
        {diffChange ? (
          <div className="diff-editor-shell" key={diffChange.change_id}>
            <div className="diff-editor-header">
              <span>{diffChange.path}</span>
              <span className={`review-verdict review-${(diffChange.review_status || "").toLowerCase()}`}>{diffChange.source === "bob_model" ? diffChange.review_status : diffChange.status}</span>
              <div className="diff-header-actions">
                {diffChange.status === "unstaged" && <button title="Stage Change" onClick={() => runDiffAction(() => api.worktreeStage(currentProject, diffChange.change_id), `Staged ${diffChange.path}`)}><Check size={14} /></button>}
                {diffChange.status === "staged" && <button title="Unstage Change" onClick={() => runDiffAction(() => api.worktreeUnstage(currentProject, diffChange.change_id), `Unstaged ${diffChange.path}`)}><Minus size={14} /></button>}
                {diffChange.status === "proposed" && diffChange.review_status !== "FAIL" && <button title="Apply Bob Proposal" onClick={() => runDiffAction(() => api.worktreeApply(currentProject, diffChange.change_id), `Applied ${diffChange.path}`, true)}><Check size={14} /></button>}
                {(diffChange.source === "bob_model" && (diffChange.status === "conflict" || diffChange.review_status === "FAIL")) && <button title="Override and Apply" onClick={() => runDiffAction(() => api.worktreeOverrideApply(currentProject, diffChange.change_id), `Override applied ${diffChange.path}`, true)}><ShieldAlert size={14} /></button>}
                {diffChange.status === "conflict" && diffChange.source === "git" && <><button title="Accept Current" onClick={() => runDiffAction(() => api.gitAcceptCurrent(currentProject, diffChange.path), `Accepted current ${diffChange.path}`)}>Current</button><button title="Accept Incoming" onClick={() => runDiffAction(() => api.gitAcceptIncoming(currentProject, diffChange.path), `Accepted incoming ${diffChange.path}`)}>Incoming</button></>}
                {diffChange.status && <button title="Discard" onClick={() => runDiffAction(() => api.worktreeDiscard(currentProject, diffChange.change_id), `Discarded ${diffChange.path}`, true)}><RotateCcw size={14} /></button>}
                <button title="Open File" onClick={() => { const path = diffChange.path; setDiffChange(null); openFile(path).catch((e) => pushToast(e.message, "error")); }}><FileCode2 size={14} /></button>
                <button title="Close Diff" onClick={() => setDiffChange(null)}><X size={15} /></button>
              </div>
            </div>
            {!!diffChange.hunks?.length && <div className="hunk-toolbar">{diffChange.hunks.map((hunk) => <div key={hunk.hunk_id} className={`hunk-chip hunk-${hunk.status || "pending"}`}><button title="Preview Hunk" onClick={() => setPeekHunk(hunk)}><Eye size={13} /> {hunk.hunk_id}</button>{diffChange.source === "bob_model" ? <button title="Apply All Hunks" onClick={() => runHunkAction(() => api.worktreeApplyAllHunks(currentProject, diffChange.change_id), "Applied proposal") }><Layers size={13} /></button> : <><button title="Stage Hunk" onClick={() => runHunkAction(() => api.worktreeStageHunk(currentProject, diffChange.change_id, hunk.hunk_id), `Staged ${hunk.hunk_id}`)}><Check size={13} /></button><button title="Discard Hunk" onClick={() => runHunkAction(() => api.worktreeDiscardHunk(currentProject, diffChange.change_id, hunk.hunk_id), `Discarded ${hunk.hunk_id}`)}><Minus size={13} /></button></>}<button title="Copy Hunk" onClick={() => copyHunk(hunk)}><Clipboard size={13} /></button></div>)}</div>}
            {peekHunk && <div className="hunk-peek"><div><strong>{peekHunk.hunk_id}</strong><button onClick={() => setPeekHunk(null)}><X size={13} /></button></div><pre>{peekHunk.diff}</pre></div>}
            <DiffEditor height="100%" original={diffChange.before_content || ""} modified={diffChange.after_content || ""} language={extToLang(diffChange.path)} theme="bob-dark" beforeMount={handleBeforeMount} onMount={handleDiffMount} options={{ readOnly: true, renderSideBySide: true, automaticLayout: true, fontSize: 13, minimap: { enabled: false }, scrollBeyondLastLine: false, glyphMargin: true }} />
          </div>
        ) : activeTab ? (
          <div className="editor-with-banner">
            {activeTab.proposal && <div className="proposal-preview-banner"><strong>Bob Proposal Preview</strong><span>{activeTab.realPath} · {activeTab.reviewStatus || "review"} · {activeTab.risk || "risk"}</span><button onClick={() => runProposalAction(() => api.proposalApply(currentProject, activeTab.proposalId, activeTab.realPath), `Applied ${activeTab.realPath}`, true)}><Check size={13} /> Apply</button><button onClick={() => runProposalAction(() => api.proposalDiscard(currentProject, activeTab.proposalId, activeTab.realPath), `Discarded ${activeTab.realPath}`, true)}><RotateCcw size={13} /> Discard</button></div>}
            <Editor key={activeTab.path} language={extToLang(activeTab.proposal ? activeTab.realPath : activeTab.path)} value={activeTab.content} theme="bob-dark" beforeMount={handleBeforeMount} onMount={handleMount} onChange={(value) => updateTabContent(activeTab.path, value ?? "")} options={{ readOnly: Boolean(activeTab.readOnly), fontSize: 14, fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace", fontLigatures: true, lineHeight: 22, minimap: { enabled: true, scale: 1 }, wordWrap: "on", tabSize: 4, scrollBeyondLastLine: false, renderLineHighlight: "gutter", smoothScrolling: true, cursorBlinking: "phase", cursorSmoothCaretAnimation: "on", bracketPairColorization: { enabled: true }, padding: { top: 12, bottom: 12 }, automaticLayout: true, hover: { enabled: true, delay: 300 }, parameterHints: { enabled: true }, suggestOnTriggerCharacters: true, quickSuggestions: { other: true, comments: false, strings: false }, acceptSuggestionOnCommitCharacter: true, snippetSuggestions: "inline", "semanticHighlighting.enabled": true }} />
          </div>
        ) : (
          <div className="editor-empty"><div className="editor-empty-icon">B</div><p>No file open</p><p className="editor-empty-hint">Use <kbd>Ctrl</kbd>+<kbd>P</kbd> to quick-open a file, or pick one from the Explorer.</p><div className="editor-shortcuts"><div className="shortcut-row"><kbd>F12</kbd> Go to Definition</div><div className="shortcut-row"><kbd>Shift+F12</kbd> Find References</div><div className="shortcut-row"><kbd>F2</kbd> Rename Symbol</div><div className="shortcut-row"><kbd>Hover</kbd> Inline docs</div></div></div>
        )}
      </div>
    </section>
  );
}
