import { useIde } from "../context/IdeContext";

export default function SearchResultsPanel() {
  const { searchResults, openFile } = useIde();
  if (!searchResults) return <div className="empty-hint">Search the workspace from the sidebar.</div>;
  if (!searchResults.matches.length) {
    return <div className="empty-hint">No matches for "{searchResults.query}"</div>;
  }
  return (
    <div className="search-results-list">
      {searchResults.matches.map((m, i) => (
        <button key={i} className="search-hit" onClick={() => openFile(m.file)}>
          <span className="search-file">
            {m.file}:{m.line}
          </span>
          <span className="search-match">{m.match}</span>
        </button>
      ))}
    </div>
  );
}
