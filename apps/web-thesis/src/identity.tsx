import { useEffect, useState } from "react";
import { api, readUser, saveUser, type AppConfig } from "./api";

// A blocking "Welcome to Eigen" gate: everyone identifies before using the app — there is no dismiss.
// It shares the eigen_user token and the /auth + /config contract with the classic /app shell, so
// signing in on either surface carries to the other on the same device. No disclaimer paragraph
// (removed by product decision); public read-only routes (#view/#board) are never gated.
export function IdentityGate({ onReady }: { onReady?: () => void }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [need, setNeed] = useState(false);
  const [mode, setMode] = useState<"register" | "login">("register");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    const u = readUser();
    api.config().then((c) => {
      if (!alive) return;
      setCfg(c);
      const accounts = !!c.accounts_enabled;
      const ok = !!u && !!u.email && (!accounts || !!u.token);
      setNeed(!ok);
      if (ok) onReady?.();
    }).catch(() => {
      // /config unavailable → don't lock a returning reader out of an otherwise-working app
      if (!alive) return;
      const u2 = readUser();
      const ok = !!u2 && !!u2.email;
      setNeed(!ok);
      if (ok) onReady?.();
    });
    return () => { alive = false; };
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!need) return null;
  const accounts = !!cfg?.accounts_enabled;

  async function submit() {
    setErr("");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) { setErr("Please enter a valid email."); return; }
    if (accounts && !password) { setErr("Please enter a password."); return; }
    if ((!accounts || mode === "register") && name.trim().length < 2) { setErr("Please enter your name."); return; }
    setBusy(true);
    try {
      if (accounts) {
        const r = mode === "login"
          ? await api.authLogin({ email: email.trim(), password })
          : await api.authRegister({ email: email.trim(), password, name: name.trim() });
        saveUser({ name: r.user?.name || name.trim() || email.split("@")[0], email: email.trim(), token: r.token, verified: !!r.user?.verified, disclaimer_ack: true });
      } else {
        saveUser({ name: name.trim(), email: email.trim(), disclaimer_ack: true });
      }
      setNeed(false);
      onReady?.();
    } catch (e) {
      const m = (e as Error).message || "";
      setErr(mode === "login" ? (m || "Incorrect email or password.") : (m || "Could not create the account."));
    } finally { setBusy(false); }
  }

  const goLabel = accounts ? (mode === "login" ? "Sign in" : "Create account") : "Continue";
  return (
    <div className="idgate" role="dialog" aria-modal="true" aria-label="Welcome to Eigen">
      <div className="idgate-card">
        <span className="idgate-mark">EIG<b>E</b>N</span>
        <h2>Welcome to Eigen</h2>
        <p>Tell us who you are, so your work is saved to your name.</p>
        {accounts ? (
          <div className="idgate-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={mode === "login"} className={"idgate-tab" + (mode === "login" ? " on" : "")} onClick={() => { setMode("login"); setErr(""); }}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === "register"} className={"idgate-tab" + (mode === "register" ? " on" : "")} onClick={() => { setMode("register"); setErr(""); }}>Create account</button>
          </div>
        ) : null}
        {(!accounts || mode === "register") ? (
          <input className="idgate-in" type="text" placeholder="Full name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />
        ) : null}
        <input className="idgate-in" type="email" placeholder="Email" autoComplete="email" value={email}
          onChange={(e) => setEmail(e.target.value)} disabled={busy} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
        {accounts ? (
          <input className="idgate-in" type="password" placeholder="Password" autoComplete={mode === "login" ? "current-password" : "new-password"}
            value={password} onChange={(e) => setPassword(e.target.value)} disabled={busy} onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
        ) : null}
        {accounts ? (
          <div className="idgate-switch">
            <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "login" ? "register" : "login"); setErr(""); }}>
              {mode === "login" ? "New here? Create an account" : "Already have an account? Sign in"}
            </a>
          </div>
        ) : null}
        {err ? <div className="idgate-err">{err}</div> : null}
        <button className="idgate-go" type="button" onClick={submit} disabled={busy}>{busy ? "…" : goLabel}</button>
      </div>
    </div>
  );
}
