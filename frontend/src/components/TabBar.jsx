import { fileIcon } from "../fileIcons";

export default function TabBar({ tabs, activePath, onSelect, onClose }) {
  if (!tabs.length) return null;
  return (
    <div className="tab-bar">
      {tabs.map((tab) => {
        const icon = fileIcon(tab.path);
        const name = tab.path.split("/").pop();
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
