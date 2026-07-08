import { useEffect, useRef } from "react";

export default function ContextMenu({ x, y, items, onClose }) {
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("contextmenu", close);
    const escClose = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", escClose);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("contextmenu", close);
      document.removeEventListener("keydown", escClose);
    };
  }, [onClose]);

  const maxX = window.innerWidth - 200;
  const maxY = window.innerHeight - items.length * 30 - 20;

  return (
    <div
      ref={ref}
      className="context-menu"
      style={{ left: Math.min(x, maxX), top: Math.min(y, maxY) }}
    >
      {items.map((item, i) =>
        item.divider ? (
          <div key={i} className="context-menu-divider" />
        ) : (
          <button
            key={i}
            className={`context-menu-item ${item.danger ? "danger" : ""}`}
            onClick={() => {
              onClose();
              item.onClick();
            }}
          >
            {item.label}
          </button>
        )
      )}
    </div>
  );
}
