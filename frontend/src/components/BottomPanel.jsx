import { useIde } from "../context/IdeContext";
import TerminalPanel from "./TerminalPanel";
import ProblemsPanel from "./ProblemsPanel";
import SearchResultsPanel from "./SearchResultsPanel";

export default function BottomPanel() {
  const { bottomTab, setBottomTab, bottomCollapsed, setBottomCollapsed, problems } = useIde();

  return (
    <section className="bottom-panel">
      <div className="bottom-panel-bar">
        <div className="bottom-panel-tabs">
          <button
            className={bottomTab === "terminal" ? "active" : ""}
            onClick={() => {
              setBottomTab("terminal");
              setBottomCollapsed(false);
            }}
          >
            TERMINAL
          </button>
          <button
            className={bottomTab === "problems" ? "active" : ""}
            onClick={() => {
              setBottomTab("problems");
              setBottomCollapsed(false);
            }}
          >
            PROBLEMS{problems.length ? ` (${problems.length})` : ""}
          </button>
          <button
            className={bottomTab === "search" ? "active" : ""}
            onClick={() => {
              setBottomTab("search");
              setBottomCollapsed(false);
            }}
          >
            SEARCH
          </button>
        </div>
        <button className="panel-collapse-btn" onClick={() => setBottomCollapsed((c) => !c)} title="Toggle panel (Ctrl+`)">
          {bottomCollapsed ? "▲" : "▼"}
        </button>
      </div>
      <div className="bottom-panel-body" style={{ display: bottomCollapsed ? "none" : "flex" }}>
        <div style={{ display: bottomTab === "terminal" ? "flex" : "none", height: "100%", flex: 1 }}>
          <TerminalPanel />
        </div>
        <div style={{ display: bottomTab === "problems" ? "block" : "none", flex: 1, overflow: "auto" }}>
          <ProblemsPanel problems={problems} />
        </div>
        <div style={{ display: bottomTab === "search" ? "block" : "none", flex: 1, overflow: "auto" }}>
          <SearchResultsPanel />
        </div>
      </div>
    </section>
  );
}
