/**
 * useLsp — wires Monaco to a Pyright language server via Socket.IO.
 *
 * What it does
 * ────────────
 * 1. Connects to /lsp Socket.IO namespace (separate from the terminal namespace).
 * 2. On mount, sends `initialize` + `initialized` to Pyright.
 * 3. Forwards every editor change as `textDocument/didOpen` / `didChange`.
 * 4. Routes every server→client message to the right Monaco handler:
 *    - publishDiagnostics  → model markers (error squiggles)
 *    - hover               → (answered via pending request map)
 *    - completion          → (answered via pending request map)
 *    - definition          → (answered via pending request map)
 * 5. Adds Monaco commands: hover, go-to-definition, find-references.
 *
 * The hook is called once from EditorArea after both Monaco and a project
 * are available. It cleans up on unmount (sends shutdown/exit).
 */

import { useEffect, useRef } from "react";
import { io } from "socket.io-client";

let _seq = 1;
const nextId = () => _seq++;

export function useLsp({ monaco, editor, project, filePath, fileContent }) {
  const socketRef = useRef(null);
  const pendingRef = useRef({}); // id → { resolve, reject }
  const openedRef = useRef(new Set());
  const editorRef = useRef(editor);
  const projectRef = useRef(project);

  // keep refs fresh without re-running the heavy effect
  editorRef.current = editor;
  projectRef.current = project;

  // ── main effect: connect / disconnect ──────────────────────────────────
  useEffect(() => {
    if (!monaco || !editor || !project) return;

    const socket = io("/lsp", { transports: ["websocket"] });
    socketRef.current = socket;

    // ── helpers ──
    const send = (msg) => {
      socket.emit("lsp:message", { project, message: msg });
    };

    const request = (method, params) =>
      new Promise((resolve, reject) => {
        const id = nextId();
        pendingRef.current[id] = { resolve, reject };
        send({ jsonrpc: "2.0", id, method, params });
        // timeout after 5 s
        setTimeout(() => {
          if (pendingRef.current[id]) {
            delete pendingRef.current[id];
            reject(new Error("LSP timeout: " + method));
          }
        }, 5000);
      });

    const notify = (method, params) => {
      send({ jsonrpc: "2.0", method, params });
    };

    const toUri = (path) => `file://${project}/${path}`;

    // ── handle messages from Pyright ──
    socket.on("lsp:message", (msg) => {
      // Response to a request
      if (msg.id !== undefined && pendingRef.current[msg.id]) {
        const { resolve, reject } = pendingRef.current[msg.id];
        delete pendingRef.current[msg.id];
        if (msg.error) reject(new Error(msg.error.message));
        else resolve(msg.result);
        return;
      }
      // Server notification
      if (msg.method === "textDocument/publishDiagnostics") {
        handleDiagnostics(monaco, msg.params);
      }
    });

    // ── initialize ──
    socket.on("lsp:ready", async () => {
      try {
        await request("initialize", {
          processId: null,
          rootUri: `file://${project}`,
          capabilities: {
            textDocument: {
              synchronization: { dynamicRegistration: false, willSave: false, didSave: false, willSaveWaitUntil: false },
              completion: { completionItem: { snippetSupport: true, documentationFormat: ["markdown", "plaintext"] } },
              hover: { contentFormat: ["markdown", "plaintext"] },
              definition: {},
              references: {},
              publishDiagnostics: { relatedInformation: true },
            },
            workspace: { applyEdit: false },
          },
          initializationOptions: {},
        });
        notify("initialized", {});

        // Open the current file if there is one
        if (filePath && fileContent !== undefined) {
          openDoc(filePath, fileContent);
        }
      } catch (e) {
        console.warn("[LSP] initialize failed:", e);
      }
    });

    const openDoc = (path, content) => {
      if (!openedRef.current.has(path)) {
        openedRef.current.add(path);
        notify("textDocument/didOpen", {
          textDocument: { uri: toUri(path), languageId: langId(path), version: 1, text: content },
        });
      }
    };

    // ── hover provider ──
    const hoverDispose = monaco.languages.registerHoverProvider("python", {
      provideHover: async (model, position) => {
        try {
          const result = await request("textDocument/hover", {
            textDocument: { uri: model.uri.toString() },
            position: { line: position.lineNumber - 1, character: position.column - 1 },
          });
          if (!result || !result.contents) return null;
          const contents = normalizeMarkup(result.contents);
          return { contents, range: lspRangeToMonaco(result.range) };
        } catch {
          return null;
        }
      },
    });

    // ── completion provider ──
    const completionDispose = monaco.languages.registerCompletionItemProvider("python", {
      triggerCharacters: [".", "(", " "],
      provideCompletionItems: async (model, position) => {
        try {
          const result = await request("textDocument/completion", {
            textDocument: { uri: model.uri.toString() },
            position: { line: position.lineNumber - 1, character: position.column - 1 },
          });
          if (!result) return { suggestions: [] };
          const items = Array.isArray(result) ? result : result.items || [];
          return {
            suggestions: items.map((item) => ({
              label: item.label,
              kind: lspKindToMonaco(monaco, item.kind),
              detail: item.detail,
              documentation: item.documentation
                ? { value: typeof item.documentation === "string" ? item.documentation : item.documentation.value }
                : undefined,
              insertText: item.insertText || item.label,
              insertTextRules: item.insertTextFormat === 2
                ? monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet
                : undefined,
            })),
          };
        } catch {
          return { suggestions: [] };
        }
      },
    });

    // ── definition provider ──
    const definitionDispose = monaco.languages.registerDefinitionProvider("python", {
      provideDefinition: async (model, position) => {
        try {
          const result = await request("textDocument/definition", {
            textDocument: { uri: model.uri.toString() },
            position: { line: position.lineNumber - 1, character: position.column - 1 },
          });
          if (!result) return [];
          const locs = Array.isArray(result) ? result : [result];
          return locs.map((loc) => ({
            uri: monaco.Uri.parse(loc.uri),
            range: lspRangeToMonaco(loc.range),
          }));
        } catch {
          return [];
        }
      },
    });

    // ── references provider ──
    const referencesDispose = monaco.languages.registerReferenceProvider("python", {
      provideReferences: async (model, position) => {
        try {
          const result = await request("textDocument/references", {
            textDocument: { uri: model.uri.toString() },
            position: { line: position.lineNumber - 1, character: position.column - 1 },
            context: { includeDeclaration: true },
          });
          if (!result) return [];
          return result.map((loc) => ({
            uri: monaco.Uri.parse(loc.uri),
            range: lspRangeToMonaco(loc.range),
          }));
        } catch {
          return [];
        }
      },
    });

    socket.emit("lsp:join", { project });

    // ── sync file changes to Pyright ──
    let version = 1;
    const changeDispose = editor.onDidChangeModelContent(() => {
      const model = editor.getModel();
      if (!model) return;
      version += 1;
      notify("textDocument/didChange", {
        textDocument: { uri: model.uri.toString(), version },
        contentChanges: [{ text: model.getValue() }],
      });
    });

    const openedDocuments = openedRef.current;

    // ── cleanup ──
    return () => {
      try { notify("shutdown", {}); } catch {}
      try { notify("exit", {}); } catch {}
      hoverDispose.dispose();
      completionDispose.dispose();
      definitionDispose.dispose();
      referencesDispose.dispose();
      changeDispose.dispose();
      socket.disconnect();
      openedDocuments.clear();
    };
  // Re-run only when the core objects change
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monaco, editor, project]);

  // ── sync file open ──
  useEffect(() => {
    if (!socketRef.current || !filePath || fileContent === undefined) return;
    const socket = socketRef.current;
    const toUri = (path) => `file://${projectRef.current}/${path}`;
    if (!openedRef.current.has(filePath)) {
      openedRef.current.add(filePath);
      socket.emit("lsp:message", {
        project: projectRef.current,
        message: {
          jsonrpc: "2.0",
          method: "textDocument/didOpen",
          params: {
            textDocument: { uri: toUri(filePath), languageId: langId(filePath), version: 1, text: fileContent },
          },
        },
      });
    }
  }, [filePath, fileContent]);
}

// ── Utilities ────────────────────────────────────────────────────────────────

function handleDiagnostics(monaco, params) {
  const uri = monaco.Uri.parse(params.uri);
  const model = monaco.editor.getModel(uri);
  if (!model) return;
  const markers = (params.diagnostics || []).map((d) => ({
    severity: lspSeverityToMonaco(monaco, d.severity),
    startLineNumber: d.range.start.line + 1,
    startColumn: d.range.start.character + 1,
    endLineNumber: d.range.end.line + 1,
    endColumn: d.range.end.character + 1,
    message: d.message,
    source: d.source,
    code: String(d.code || ""),
  }));
  monaco.editor.setModelMarkers(model, "pyright", markers);
}

function lspSeverityToMonaco(monaco, severity) {
  // LSP: 1=Error 2=Warning 3=Information 4=Hint
  const map = [
    monaco.MarkerSeverity.Hint,    // 0 (unused)
    monaco.MarkerSeverity.Error,   // 1
    monaco.MarkerSeverity.Warning, // 2
    monaco.MarkerSeverity.Info,    // 3
    monaco.MarkerSeverity.Hint,    // 4
  ];
  return map[severity] ?? monaco.MarkerSeverity.Error;
}

function lspKindToMonaco(monaco, kind) {
  const CIK = monaco.languages.CompletionItemKind;
  const map = {
    1: CIK.Text, 2: CIK.Method, 3: CIK.Function, 4: CIK.Constructor,
    5: CIK.Field, 6: CIK.Variable, 7: CIK.Class, 8: CIK.Interface,
    9: CIK.Module, 10: CIK.Property, 11: CIK.Unit, 12: CIK.Value,
    13: CIK.Enum, 14: CIK.Keyword, 15: CIK.Snippet, 16: CIK.Color,
    17: CIK.File, 18: CIK.Reference, 19: CIK.Folder,
  };
  return map[kind] ?? CIK.Text;
}

function lspRangeToMonaco(range) {
  if (!range) return undefined;
  return {
    startLineNumber: range.start.line + 1,
    startColumn: range.start.character + 1,
    endLineNumber: range.end.line + 1,
    endColumn: range.end.character + 1,
  };
}

function normalizeMarkup(contents) {
  if (!contents) return [];
  if (typeof contents === "string") return [{ value: contents }];
  if (Array.isArray(contents)) {
    return contents.map((c) =>
      typeof c === "string" ? { value: c } : { value: c.value }
    );
  }
  return [{ value: contents.value || "" }];
}

function langId(path) {
  const ext = path.split(".").pop().toLowerCase();
  const map = { py: "python", js: "javascript", jsx: "javascript", ts: "typescript",
                tsx: "typescript", html: "html", css: "css", json: "json", md: "markdown" };
  return map[ext] || "plaintext";
}
