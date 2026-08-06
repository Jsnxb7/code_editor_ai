import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setCsrfToken, setUnauthorizedHandler } from "../api";
import { closeSocket } from "../socket";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [state, setState] = useState("loading");
  const [user, setUser] = useState(null);
  const [error, setError] = useState("");
  const [devPanelOpen, setDevPanelOpen] = useState(false);

  const clear = useCallback(() => {
    setCsrfToken(""); closeSocket(); setUser(null); setDevPanelOpen(false); setState("login");
  }, []);

  useEffect(() => { setUnauthorizedHandler(clear); return () => setUnauthorizedHandler(null); }, [clear]);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const status = await api.authStatus();
        if (!active) return;
        if (status.setup_required) { setState("setup"); return; }
        try {
          const session = await api.authMe(); if (!active) return; setCsrfToken(session.csrf_token); setUser(session.user); setState("authenticated");
        } catch { if (active) setState("login"); }
      } catch (err) { if (active) { setError(err.message); setState("login"); } }
    })();
    return () => { active = false; };
  }, []);

  const authenticate = useCallback((result) => { setCsrfToken(result.csrf_token); setUser(result.user); setError(""); setState("authenticated"); }, []);
  const login = useCallback(async (username, password) => { try { authenticate(await api.authLogin(username, password)); } catch (err) { setError(err.message); throw err; } }, [authenticate]);
  const setup = useCallback(async (payload) => { try { authenticate(await api.authSetup(payload)); } catch (err) { setError(err.message); throw err; } }, [authenticate]);
  const logout = useCallback(async () => { try { await api.authLogout(); } catch {} clear(); }, [clear]);
  const value = useMemo(() => ({ state, user, error, login, setup, logout, devPanelOpen, setDevPanelOpen }), [state, user, error, login, setup, logout, devPanelOpen]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const value = useContext(AuthContext); if (!value) throw new Error("useAuth must be used inside AuthProvider"); return value;
};
