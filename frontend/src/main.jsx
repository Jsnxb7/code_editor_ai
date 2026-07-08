import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { IdeProvider } from "./context/IdeContext.jsx";
import "./styles/index.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <IdeProvider>
      <App />
    </IdeProvider>
  </StrictMode>
);
