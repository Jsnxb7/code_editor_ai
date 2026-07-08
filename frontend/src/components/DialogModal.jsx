import { useEffect, useRef, useState } from "react";
import { useIde } from "../context/IdeContext";

export default function DialogModal() {
  const { dialog, resolveDialog } = useIde();
  const [value, setValue] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    if (dialog?.kind === "prompt") {
      setValue(dialog.defaultValue || "");
      setTimeout(() => inputRef.current?.select(), 30);
    }
  }, [dialog]);

  if (!dialog) return null;

  const submit = () => resolveDialog(dialog.kind === "prompt" ? value : true);
  const cancel = () => resolveDialog(dialog.kind === "prompt" ? null : false);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && cancel()}>
      <div
        className="modal-box"
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") cancel();
        }}
      >
        <div className="modal-message">{dialog.message}</div>
        {dialog.kind === "prompt" && (
          <input
            ref={inputRef}
            className="modal-input"
            value={value}
            autoFocus
            onChange={(e) => setValue(e.target.value)}
          />
        )}
        <div className="modal-actions">
          <button className="btn" onClick={cancel}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={submit}>
            {dialog.kind === "prompt" ? "OK" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
