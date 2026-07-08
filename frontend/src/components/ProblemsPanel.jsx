export default function ProblemsPanel({ problems }) {
  if (!problems.length) {
    return <div className="problem clean">No problems found</div>;
  }
  return (
    <div className="problems-list">
      {problems.map((p, i) => (
        <div key={i} className={`problem ${p.severity}`}>
          <span className="prob-sev">{p.severity.toUpperCase()}</span>
          <div>
            <div className="prob-msg">{p.message}</div>
            {p.line ? <div className="prob-loc">Line {p.line}</div> : null}
          </div>
        </div>
      ))}
    </div>
  );
}
