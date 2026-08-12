import { useState } from "react";
import { KeyRound, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";

export default function AuthScreen() {
  const { state, error, login, setup } = useAuth();
  const [form, setForm] = useState({ username: "", display_name: "", password: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const isSetup = state === "setup";
  const submit = async (event) => {
    event.preventDefault(); if (busy) return;
    if (isSetup && form.password !== form.confirm) return;
    setBusy(true); try { if (isSetup) await setup(form); else await login(form.username, form.password); } catch {} finally { setBusy(false); }
  };
  return (
    <main className="auth-page">
      <section className="auth-hero">
        <div className="auth-brand"><span className="brand-icon large">B</span><span>Bob IDE</span></div>
        <h1>{isSetup ? "Secure your workspace" : "Build with Bob, safely"}</h1>
        <p>{isSetup ? "Create the first administrator. Existing workspaces will be assigned to this account." : "Sign in to your private coding workspace and supervised AI workflow."}</p>
        <div className="auth-points"><span><ShieldCheck size={16} /> Private workspace ownership</span><span><ShieldCheck size={16} /> Reviewable AI proposals</span><span><ShieldCheck size={16} /> Audited high-risk actions</span></div>
      </section>
      <section className="auth-card">
        <div><small>{isSetup ? "FIRST-RUN SETUP" : "WELCOME BACK"}</small><h2>{isSetup ? "Create administrator" : "Sign in"}</h2></div>
        {!isSetup && <div className="auth-owner-notice"><KeyRound size={17} /><span>Need login credentials? Contact the owner of this server for access.</span></div>}
        <form onSubmit={submit}>
          {isSetup && <label>Display name<input autoFocus value={form.display_name} onChange={(e) => setForm((v) => ({ ...v, display_name: e.target.value }))} minLength={2} required /></label>}
          <label>Username<input autoFocus={!isSetup} value={form.username} onChange={(e) => setForm((v) => ({ ...v, username: e.target.value }))} autoComplete="username" minLength={3} required /></label>
          <label>Password<input type="password" value={form.password} onChange={(e) => setForm((v) => ({ ...v, password: e.target.value }))} autoComplete={isSetup ? "new-password" : "current-password"} minLength={12} required /></label>
          {isSetup && <label>Confirm password<input type="password" value={form.confirm} onChange={(e) => setForm((v) => ({ ...v, confirm: e.target.value }))} autoComplete="new-password" minLength={12} required /></label>}
          {isSetup && form.confirm && form.password !== form.confirm && <div className="auth-error">Passwords do not match.</div>}
          {error && <div className="auth-error">{error}</div>}
          <button className="auth-submit" disabled={busy || (isSetup && form.password !== form.confirm)}>{busy ? "Please wait…" : isSetup ? "Create admin and continue" : "Sign in to Bob IDE"}</button>
        </form>
        <small className="auth-footnote">Sessions use an HttpOnly cookie and expire after eight idle hours.</small>
      </section>
    </main>
  );
}
