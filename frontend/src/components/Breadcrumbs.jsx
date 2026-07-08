export default function Breadcrumbs({ project, path }) {
  if (!path) return <div className="breadcrumbs empty">Select a file to begin</div>;
  const parts = [project, ...path.split("/")];
  return (
    <div className="breadcrumbs">
      {parts.map((part, i) => (
        <span key={i} className="breadcrumb-part">
          {i > 0 && <span className="breadcrumb-sep">›</span>}
          {part}
        </span>
      ))}
    </div>
  );
}
