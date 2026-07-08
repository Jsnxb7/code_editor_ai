import { useCallback, useEffect, useRef } from "react";
import { useIde } from "../context/IdeContext";
import TerminalView from "./TerminalView";

export default function TerminalPanel() {
  const {
    terminals,
    activeTerminalId,
    setActiveTerminalId,
    createTerminal,
    closeTerminal,
    currentProject,
    terminalRunRef,
  } = useIde();

  useEffect(() => {
    if (!terminals.length) createTerminal();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const writersRef = useRef(new Map());
  const registerWriter = useCallback((id, fn) => {
    if (fn) writersRef.current.set(id, fn);
    else writersRef.current.delete(id);
  }, []);

  terminalRunRef.current = (id, text) => writersRef.current.get(id)?.(text);

  return (
    <div className="terminal-panel">
      <div className="terminal-tabs">
        {terminals.map((t) => (
          <div
            key={t.id}
            className={`terminal-tab ${activeTerminalId === t.id ? "active" : ""}`}
            onClick={() => setActiveTerminalId(t.id)}
          >
            <span className="terminal-tab-icon">&gt;_</span>
            <span>{t.title}</span>
            <span
              className="tab-close"
              onClick={(e) => {
                e.stopPropagation();
                closeTerminal(t.id);
              }}
            >
              ×
            </span>
          </div>
        ))}
        <button className="terminal-tab-new" title="New terminal" onClick={() => createTerminal()}>
          +
        </button>
      </div>
      <div className="terminal-views">
        {terminals.map((t) => (
          <TerminalView
            key={t.id}
            terminalId={t.id}
            project={currentProject}
            active={activeTerminalId === t.id}
            registerWriter={registerWriter}
          />
        ))}
        {!terminals.length && <div className="empty-hint">No terminal open</div>}
      </div>
    </div>
  );
}
