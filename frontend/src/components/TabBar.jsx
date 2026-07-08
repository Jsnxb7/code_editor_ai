import { fileIcon } from "../fileIcons";
import { useIde } from "../context/IdeContext";

export default function TabBar({ tabs, activePath, onSelect, onClose }) {
  const { getSourceDecoration } = useIde();
  if (!tabs.length) return null;
  return (
    <div className="tab-bar">
      {tabs.map((tab) => {
        const icon = fileIcon(tab.path);
        const name = tab.path.split("/").pop();
        const decoration = getSourceDecoration(tab.path);
        return (
          <div
            key={tab.path}
            className={`editor-tab ${activePath === tab.path ? "active" : ""}`}
            onClick={() => onSelect(tab.path)}
          >
            <span className="tab-icon" style={{ color: icon.color }}>
              {icon.glyph}
            </span>
            <span className="tab-name">{name}</span>
            {tab.dirty && <span className="tab-dot" />}
            {decoration && (
              <span className={`scm-decoration tab-scm-decoration ${decoration.className}`} title={decoration.title}>
                {decoration.label}
              </span>
            )}
            <span
              className="tab-close"
              onClick={(e) => {
                e.stopPropagation();
                onClose(tab.path);
              }}
            >
              ×
            </span>
          </div>
        );
      })}
    </div>
  );
}
