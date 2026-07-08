import { useState } from "react";
import { fileIcon } from "../fileIcons";

export default function TreeNode({
  item,
  depth,
  activePath,
  selectedFolder,
  onOpenFile,
  onContextMenu,
  onSelectFolder,
  inlineRename,
  inlineNew,
  inlineInputRef,
  onCommitRename,
  onCancelRename,
  onCommitNew,
  onCancelNew,
  onChangeRename,
  onChangeNew,
  getSourceDecoration,
  getFolderChangeCount,
}) {
  const [open, setOpen] = useState(true);

  const isRenamingThis = inlineRename && inlineRename.path === item.path;
  const isNewChildHere = inlineNew && inlineNew.parentPath === item.path;
  const isSelectedFolder = selectedFolder === item.path;

  if (item.type === "folder") {
    const folderCount = getFolderChangeCount?.(item.path) || 0;
    return (
      <div>
        <div
          className={`tree-row tree-folder ${isSelectedFolder ? "folder-selected" : ""}`}
          style={{ paddingLeft: 8 + depth * 14 }}
          onClick={() => {
            setOpen((o) => !o);
            onSelectFolder(item.path);
          }}
          onContextMenu={(e) => onContextMenu(e, item)}
        >
          <span className={`chevron ${open ? "open" : ""}`}>›</span>
          <span className="tree-icon folder-icon">▣</span>
          {isRenamingThis ? (
            <input
              ref={inlineInputRef}
              className="inline-rename-input"
              value={inlineRename.value}
              onChange={(e) => onChangeRename(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onCommitRename();
                if (e.key === "Escape") onCancelRename();
              }}
              onBlur={onCommitRename}
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span className="tree-label">{item.name}</span>
          )}
          {folderCount > 0 && <span className="tree-folder-badge">{folderCount}</span>}
        </div>

        {open && (
          <div>
            {/* Inline new entry input inside this folder */}
            {isNewChildHere && (
              <div
                className="tree-row tree-file inline-new-row"
                style={{ paddingLeft: 8 + (depth + 1) * 14 + 14 }}
              >
                <span className="tree-icon">
                  {inlineNew.kind === "file" ? "TXT" : "DIR"}
                </span>
                <input
                  ref={inlineInputRef}
                  className="inline-rename-input"
                  value={inlineNew.value}
                  placeholder={inlineNew.kind === "file" ? "file-name.ext" : "folder-name"}
                  onChange={(e) => onChangeNew(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onCommitNew();
                    if (e.key === "Escape") onCancelNew();
                  }}
                  onBlur={onCommitNew}
                />
              </div>
            )}
            {(item.children || []).map((child) => (
              <TreeNode
                key={child.path}
                item={child}
                depth={depth + 1}
                activePath={activePath}
                selectedFolder={selectedFolder}
                onOpenFile={onOpenFile}
                onContextMenu={onContextMenu}
                onSelectFolder={onSelectFolder}
                inlineRename={inlineRename}
                inlineNew={inlineNew}
                inlineInputRef={inlineInputRef}
                onCommitRename={onCommitRename}
                onCancelRename={onCancelRename}
                onCommitNew={onCommitNew}
                onCancelNew={onCancelNew}
                onChangeRename={onChangeRename}
                onChangeNew={onChangeNew}
                getSourceDecoration={getSourceDecoration}
                getFolderChangeCount={getFolderChangeCount}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  // File node
  const icon = fileIcon(item.name);
  const decoration = getSourceDecoration?.(item.path);
  return (
    <div
      className={`tree-row tree-file ${activePath === item.path ? "active" : ""}`}
      style={{ paddingLeft: 8 + depth * 14 + 14 }}
      onClick={() => onOpenFile(item.path)}
      onContextMenu={(e) => onContextMenu(e, item)}
    >
      <span className="tree-icon file-icon" style={{ color: icon.color }}>
        {icon.glyph}
      </span>
      {isRenamingThis ? (
        <input
          ref={inlineInputRef}
          className="inline-rename-input"
          value={inlineRename.value}
          onChange={(e) => onChangeRename(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onCommitRename();
            if (e.key === "Escape") onCancelRename();
          }}
          onBlur={onCommitRename}
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <span className="tree-label">{item.name}</span>
      )}
      {decoration && (
        <span className={`scm-decoration ${decoration.className}`} title={decoration.title}>
          {decoration.label}
        </span>
      )}
    </div>
  );
}
