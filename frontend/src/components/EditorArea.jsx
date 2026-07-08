import { useCallback, useRef, useState } from "react";
import Editor, { DiffEditor } from "@monaco-editor/react";
import { X } from "lucide-react";
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
  const { tabs, activePath, currentProject, setActivePath, closeTab, updateTabContent, saveActiveTab, saveAllTabs, diffChange, setDiffChange } =
    useIde();
  const editorRef = useRef(null);
  const monacoRef = useRef(null);
  const [lspStatus, setLspStatus] = useState("idle"); // idle | connecting | ready | error

  const activeTab = tabs.find((t) => t.path === activePath);

  const handleMount = useCallback(
    (editor, monaco) => {
      editorRef.current = editor;
      monacoRef.current = monaco;
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
        saveActiveTab();
      });
      editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyS, () => {
        saveAllTabs();
      });
      // F12 → Go to Definition (built-in Monaco action, enhanced by LSP provider)
      editor.addCommand(monaco.KeyCode.F12, () => {
        editor.getAction("editor.action.revealDefinition")?.run();
      });
      // Shift+F12 → Find References
      editor.addCommand(monaco.KeyMod.Shift | monaco.KeyCode.F12, () => {
        editor.getAction("editor.action.goToReferences")?.run();
      });
      // F2 → Rename Symbol
      editor.addCommand(monaco.KeyCode.F2, () => {
        editor.getAction("editor.action.rename")?.run();
      });
      setLspStatus("connecting");
    },
    [saveActiveTab, saveAllTabs]
  );

  const handleBeforeMount = useCallback((monaco) => {
    defineBobTheme(monaco);
  }, []);

  // Wire LSP — only active when Monaco + editor are mounted and a project is selected
  useLsp({
    monaco: monacoRef.current,
    editor: editorRef.current,
    project: currentProject,
    filePath: activeTab?.path,
    fileContent: activeTab?.content,
  });

  return (
    <section className="editor-column">
      <TabBar tabs={tabs} activePath={activePath} onSelect={setActivePath} onClose={closeTab} />
      <Breadcrumbs project={currentProject} path={activePath} />

      {/* LSP status badge */}
      {lspStatus !== "idle" && (
        <div className={`lsp-badge lsp-${lspStatus}`} title="Language Server (Pyright)">
          {lspStatus === "connecting" && "⬤ LSP"}
          {lspStatus === "ready" && "⬤ LSP"}
          {lspStatus === "error" && "⬤ LSP off"}
        </div>
      )}

      <div className="editor-host">
        {diffChange ? (
          <div className="diff-editor-shell">
            <div className="diff-editor-header">
              <span>{diffChange.path}</span>
              <span className={`review-verdict review-${(diffChange.review_status || "").toLowerCase()}`}>
                {diffChange.source === "bob_model" ? diffChange.review_status : diffChange.status}
              </span>
              <button title="Close Diff" onClick={() => setDiffChange(null)}><X size={15} /></button>
            </div>
            <DiffEditor
              original={diffChange.before_content}
              modified={diffChange.after_content}
              language={extToLang(diffChange.path)}
              theme="bob-dark"
              beforeMount={handleBeforeMount}
              options={{
                readOnly: true,
                renderSideBySide: true,
                automaticLayout: true,
                fontSize: 13,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
              }}
            />
          </div>
        ) : activeTab ? (
          <Editor
            key={activeTab.path}
            language={extToLang(activeTab.path)}
            value={activeTab.content}
            theme="bob-dark"
            beforeMount={handleBeforeMount}
            onMount={handleMount}
            onChange={(value) => updateTabContent(activeTab.path, value ?? "")}
            options={{
              fontSize: 14,
              fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
              fontLigatures: true,
              lineHeight: 22,
              minimap: { enabled: true, scale: 1 },
              wordWrap: "on",
              tabSize: 4,
              scrollBeyondLastLine: false,
              renderLineHighlight: "gutter",
              smoothScrolling: true,
              cursorBlinking: "phase",
              cursorSmoothCaretAnimation: "on",
              bracketPairColorization: { enabled: true },
              padding: { top: 12, bottom: 12 },
              automaticLayout: true,
              // LSP-powered features
              hover: { enabled: true, delay: 300 },
              parameterHints: { enabled: true },
              suggestOnTriggerCharacters: true,
              quickSuggestions: { other: true, comments: false, strings: false },
              acceptSuggestionOnCommitCharacter: true,
              snippetSuggestions: "inline",
              // Semantic tokens (Pyright provides these)
              "semanticHighlighting.enabled": true,
            }}
          />
        ) : (
          <div className="editor-empty">
            <div className="editor-empty-icon">B</div>
            <p>No file open</p>
            <p className="editor-empty-hint">
              Use <kbd>Ctrl</kbd>+<kbd>P</kbd> to quick-open a file, or pick one from the
              Explorer.
            </p>
            <div className="editor-shortcuts">
              <div className="shortcut-row"><kbd>F12</kbd> Go to Definition</div>
              <div className="shortcut-row"><kbd>Shift+F12</kbd> Find References</div>
              <div className="shortcut-row"><kbd>F2</kbd> Rename Symbol</div>
              <div className="shortcut-row"><kbd>Hover</kbd> Inline docs</div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
