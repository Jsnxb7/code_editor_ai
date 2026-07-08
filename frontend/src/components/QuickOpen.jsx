import { useEffect, useMemo, useState } from "react";
import { useIde } from "../context/IdeContext";
import { fuzzyFilter, flattenFiles } from "../fuzzy";
import { fileIcon } from "../fileIcons";

export default function QuickOpen() {
  const { quickOpenOpen, setQuickOpenOpen, tree, openFile, getSourceDecoration } = useIde();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  const allFiles = useMemo(() => flattenFiles(tree), [tree]);
  const results = useMemo(() => fuzzyFilter(allFiles, query, (p) => p).slice(0, 40), [allFiles, query]);

  useEffect(() => {
    if (quickOpenOpen) {
      setQuery("");
      setIndex(0);
    }
  }, [quickOpenOpen]);

  if (!quickOpenOpen) return null;

  const choose = (path) => {
    if (path) openFile(path);
    setQuickOpenOpen(false);
  };

  return (
    <div className="palette-overlay" onMouseDown={(e) => e.target === e.currentTarget && setQuickOpenOpen(false)}>
      <div className="palette-box">
        <input
          autoFocus
          className="palette-input"
          placeholder="Go to file…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setIndex(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") setQuickOpenOpen(false);
            if (e.key === "ArrowDown") setIndex((i) => Math.min(i + 1, results.length - 1));
            if (e.key === "ArrowUp") setIndex((i) => Math.max(i - 1, 0));
            if (e.key === "Enter") choose(results[index]);
          }}
        />
        <div className="palette-list">
          {results.map((path, i) => {
            const icon = fileIcon(path);
            const decoration = getSourceDecoration(path);
            return (
              <div
                key={path}
                className={`palette-item ${i === index ? "active" : ""}`}
                onMouseEnter={() => setIndex(i)}
                onClick={() => choose(path)}
              >
                <span style={{ color: icon.color }}>{icon.glyph}</span>
                <span>{path}</span>
                {decoration && (
                  <span className={`scm-decoration palette-scm-decoration ${decoration.className}`} title={decoration.title}>
                    {decoration.label}
                  </span>
                )}
              </div>
            );
          })}
          {!results.length && <div className="palette-empty">No matching files</div>}
        </div>
      </div>
    </div>
  );
}
