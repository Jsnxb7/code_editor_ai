import { FolderPlus, LogOut, Shield, UserCircle } from "lucide-react";
import { useState } from "react";
import { useIde } from "../context/IdeContext";
import { useAuth } from "../context/AuthContext";

export default function TopBar() {
  const { user, logout, setDevPanelOpen } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const { activePath, tabs, projects, currentProject, selectProject, createWorkspace, promptDialog, pushToast, openWorkspaceFolder, saveActiveTab, saveAllTabs, saveWorkspaceToFolder, validateActiveFile, runTests, runInTerminal, setQuickOpenOpen, setCommandPaletteOpen, setBottomCollapsed } = useIde();
  const activeTab = tabs.find((tab) => tab.path === activePath);
  const newWorkspace = async () => { const name = await promptDialog("New workspace name:"); if (!name) return; try { await createWorkspace(name); } catch (error) { pushToast(error.message, "error"); } };
  const runActiveFile = () => { if (activePath?.endsWith(".py")) runInTerminal(`python ${activePath}\r`); };
  return (
    <header className="topbar">
      <div className="brand"><div className="brand-icon">B</div>Bob IDE</div><div className="topbar-divider" />
      <div className="topbar-workspace"><span className="topbar-workspace-label">Workspace</span><select value={currentProject} onChange={(event) => selectProject(event.target.value)} title="Switch workspace">{projects.map((project) => <option key={project} value={project}>{project}</option>)}</select><button className="topbar-icon-btn" onClick={newWorkspace} title="Create new workspace"><FolderPlus size={15} /></button></div>
      <div className="topbar-divider" />
      <button className="topbar-btn" onClick={() => setQuickOpenOpen(true)} title="Quick Open (Ctrl+P)">Go to File...</button>
      <button className="topbar-btn" onClick={openWorkspaceFolder}>Open Folder</button><button className="topbar-btn" onClick={saveWorkspaceToFolder}>Save Folder</button>
      <div className="topbar-spacer" /><div className="topbar-actions">
        <button className="topbar-btn" disabled={!tabs.some((tab) => tab.dirty)} onClick={saveAllTabs}>Save All</button>
        <button className="topbar-btn" disabled={!activePath} onClick={saveActiveTab}>{activeTab?.dirty ? "Save *" : "Save"}</button>
        <button className="topbar-btn" disabled={!activePath} onClick={validateActiveFile}>Validate</button><button className="topbar-btn" onClick={runTests}>Tests</button>
        <button className="topbar-btn btn-primary" disabled={!activePath?.endsWith(".py")} onClick={runActiveFile}>Run</button>
        <button className="topbar-btn" onClick={() => setBottomCollapsed((value) => !value)}>Panel</button><button className="topbar-btn" onClick={() => setCommandPaletteOpen(true)}>More</button>
        <div className="profile-menu-wrap"><button className="profile-trigger" onClick={() => setProfileOpen((value) => !value)}><span className="profile-avatar">{user.display_name.slice(0, 2).toUpperCase()}</span><span><strong>{user.display_name}</strong><small>{user.role}</small></span></button>
          {profileOpen && <div className="profile-menu"><div className="profile-summary"><UserCircle size={20} /><span><strong>{user.display_name}</strong><small>@{user.username} · {user.role}</small></span></div>{user.role === "admin" && <button onClick={() => { setProfileOpen(false); setDevPanelOpen(true); }}><Shield size={15} /> Developer Panel</button>}<button onClick={logout}><LogOut size={15} /> Logout</button></div>}
        </div>
      </div>
    </header>
  );
}
