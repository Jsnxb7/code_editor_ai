import { useCallback, useRef } from "react";

export default function Resizer({ direction = "vertical", onResize, onDragStart, className = "" }) {
  const dragging = useRef(false);

  const handleMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      dragging.current = true;
      onDragStart?.();
      const start = direction === "vertical" ? e.clientX : e.clientY;

      const handleMove = (ev) => {
        if (!dragging.current) return;
        const pos = direction === "vertical" ? ev.clientX : ev.clientY;
        onResize(pos - start, ev);
      };
      const handleUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", handleMove);
        document.removeEventListener("mouseup", handleUp);
        document.body.classList.remove("resizing");
      };

      document.body.classList.add("resizing", direction === "vertical" ? "resizing-x" : "resizing-y");
      document.addEventListener("mousemove", handleMove);
      document.addEventListener("mouseup", handleUp);
    },
    [direction, onResize, onDragStart]
  );

  return (
    <div
      className={`resizer resizer-${direction} ${className}`}
      onMouseDown={handleMouseDown}
    />
  );
}
