import { useCallback, useEffect, useRef, useState } from "react";
import { useIde } from "./context/IdeContext";
import ActivityBar from "./components/ActivityBar";
import Sidebar from "./components/Sidebar";
import EditorArea from "./components/EditorArea";
import BottomPanel from "./components/BottomPanel";
import BobPanel from "./components/BobPanel";
import TopBar from "./components/TopBar";
import StatusBar from "./components/StatusBar";
import ToastStack from "./components/ToastStack";
import DialogModal from "./components/DialogModal";
import CommandPalette from "./components/CommandPalette";
import QuickOpen from "./components/QuickOpen";
import Resizer from "./components/Resizer";

export default function App() {
  const {
    loadWorkspaces,
    loadTree,
    sidebarCollapsed,
    bobCollapsed,
    bottomCollapsed,
    saveActiveTab,
    saveAllTabs,
    setQuickOpenOpen,
    setCommandPaletteOpen,
    setBottomCollapsed,
    setSidebarCollapsed,
  } = useIde();

  const [sidebarWidth, setSidebarWidth] = useState(240);
  const [bobWidth, setBobWidth] = useState(280);
  const [bottomHeight, setBottomHeight] = useState(260);
  const [booted, setBooted] = useState(false);

  const startSidebarWidth = useRef(sidebarWidth);
  const startBobWidth = useRef(bobWidth);
  const startBottomHeight = useRef(bottomHeight);

  useEffect(() => {
    (async () => {
      const project = await loadWorkspaces();
      if (project) await loadTree(project);
      setBooted(true);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handler = (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (!mod) return;
      if (e.key === "s" && e.shiftKey) {
        e.preventDefault();
        saveAllTabs();
      } else if (e.key === "s") {
        e.preventDefault();
        saveActiveTab();
      } else if (e.key.toLowerCase() === "p" && e.shiftKey) {
        e.preventDefault();
        setCommandPaletteOpen(true);
      } else if (e.key === "p") {
        e.preventDefault();
        setQuickOpenOpen(true);
      } else if (e.key === "`") {
        e.preventDefault();
        setBottomCollapsed((c) => !c);
      } else if (e.key.toLowerCase() === "b") {
        e.preventDefault();
        setSidebarCollapsed((c) => !c);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [saveActiveTab, saveAllTabs, setQuickOpenOpen, setCommandPaletteOpen, setBottomCollapsed, setSidebarCollapsed]);

  const onSidebarResize = useCallback(
    (dx) => setSidebarWidth(Math.min(480, Math.max(160, startSidebarWidth.current + dx))),
    []
  );
  const onBobResize = useCallback(
    (dx) => setBobWidth(Math.min(480, Math.max(200, startBobWidth.current - dx))),
    []
  );
  const onBottomResize = useCallback(
    (dy) =>
      setBottomHeight(
        Math.min(window.innerHeight - 160, Math.max(120, startBottomHeight.current - dy))
      ),
    []
  );

  if (!booted) {
    return (
      <div className="boot-screen">
        <div className="brand-icon large">B</div>
        <p>Starting Bob IDE…</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <TopBar />
      <div className="app-body">
        <ActivityBar />

        {!sidebarCollapsed && (
          <>
            <div className="sidebar-slot" style={{ width: sidebarWidth }}>
              <Sidebar />
            </div>
            <Resizer
              direction="vertical"
              onDragStart={() => (startSidebarWidth.current = sidebarWidth)}
              onResize={onSidebarResize}
            />
          </>
        )}

        <div className="center-column">
          <div className="editor-and-panel">
            <div className="editor-slot">
              <EditorArea />
            </div>
            <Resizer
              direction="horizontal"
              onDragStart={() => (startBottomHeight.current = bottomHeight)}
              onResize={onBottomResize}
            />
            <div
              className="bottom-slot"
              style={{ height: bottomCollapsed ? 36 : bottomHeight }}
            >
              <BottomPanel />
            </div>
          </div>
        </div>

        {!bobCollapsed && (
          <>
            <Resizer
              direction="vertical"
              onDragStart={() => (startBobWidth.current = bobWidth)}
              onResize={onBobResize}
            />
            <div className="bob-slot" style={{ width: bobWidth }}>
              <BobPanel />
            </div>
          </>
        )}
      </div>
      <StatusBar />
      <ToastStack />
      <DialogModal />
      <CommandPalette />
      <QuickOpen />
    </div>
  );
}
