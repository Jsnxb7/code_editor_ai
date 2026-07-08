import { useIde } from "../context/IdeContext";

export default function ToastStack() {
  const { toasts } = useIde();
  if (!toasts.length) return null;
  return (
    <div className="toast-stack">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast-${t.variant}`}>
          {t.message}
        </div>
      ))}
    </div>
  );
}
