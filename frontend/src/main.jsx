import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { IdeProvider } from "./context/IdeContext.jsx";
import { AuthProvider, useAuth } from "./context/AuthContext.jsx";
import AuthScreen from "./components/AuthScreen.jsx";
import "./styles/index.css";

function Root() {
  const { state } = useAuth();
  if (state === "loading") return <div className="boot-screen"><div className="brand-icon large">B</div><p>Securing Bob IDE…</p></div>;
  if (state !== "authenticated") return <AuthScreen />;
  return <IdeProvider><App /></IdeProvider>;
}

createRoot(document.getElementById("root")).render(<StrictMode><AuthProvider><Root /></AuthProvider></StrictMode>);
