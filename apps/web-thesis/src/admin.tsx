import { useEffect, useState } from "react";
import { api, type SettingSpec } from "./api";
import { PageHead } from "./ui";

const TOKEN_KEY = "eigen.admin.token";
const readToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
const saveToken = (t: string) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } };

export function Settings() {
  const [token, setToken] = useState(readToken());
  const [entry, setEntry] = useState("");
  const [settings, setSettings] = useState<Record<string, SettingSpec> | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function load(t: string) {
    setBusy(true); setErr("");
    try {
      const r = await api.adminSettings(t);
      setSettings(r.settings); setToken(t); saveToken(t);
    } catch (e) {
      setErr((e as Error).message.includes("403") || (e as Error).message.includes("admin token") ? "That admin token isn't valid." : (e as Error).message);
      setSettings(null);
    } finally { setBusy(false); }
  }
  useEffect(() => { if (token) load(token); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  async function set(key: string, value: string) {
    setBusy(true); setErr("");
    try { const r = await api.adminSetSetting(token, key, value); setSettings(r.settings); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  function signOut() { saveToken(""); setToken(""); setSettings(null); setEntry(""); }

  return (
    <>
      <PageHead title="Admin settings" sub="Runtime toggles for this deployment — change without a redeploy. Admin-only." />
      {!settings ? (
        <div className="card" style={{ maxWidth: 460 }}>
          <div className="kick" style={{ marginBottom: ".5rem" }}>Admin token</div>
          <div className="row">
            <input className="gtext" type="password" value={entry} onChange={(e) => setEntry(e.target.value)}
              placeholder="Enter the admin token" onKeyDown={(e) => { if (e.key === "Enter") load(entry.trim()); }} disabled={busy} />
            <button className="btn" disabled={busy || !entry.trim()} onClick={() => load(entry.trim())}>{busy ? "…" : "Unlock"}</button>
          </div>
          {err ? <p className="state" style={{ color: "var(--p0)", marginTop: ".6rem" }}>{err}</p> : null}
        </div>
      ) : (
        <>
          {Object.entries(settings).map(([key, s]) => (
            <div key={key} className="card" style={{ maxWidth: 620 }}>
              <div className="setting-h">{s.label}</div>
              <p className="muted" style={{ fontSize: ".84rem", margin: ".25rem 0 .7rem", lineHeight: 1.5 }}>{s.help}</p>
              <div className="setting-opts">
                {s.options.map((opt) => (
                  <button key={opt} className={"setting-opt" + (s.value === opt ? " on" : "")} disabled={busy}
                    onClick={() => set(key, opt)}>
                    {opt === "deepseek" ? "DeepSeek" : opt === "openai" ? "OpenAI" : opt}
                    {opt === s.default ? <span className="setting-def">default</span> : null}
                  </button>
                ))}
              </div>
              <p className="muted" style={{ fontSize: ".76rem", margin: ".6rem 0 0" }}>
                Active: <b>{s.value}</b> ({s.source === "override" ? "set here" : "from env default"}).
                {s.source === "override" ? <button className="setting-reset" disabled={busy} onClick={() => set(key, "")}>reset to default</button> : null}
              </p>
            </div>
          ))}
          {err ? <p className="state" style={{ color: "var(--p0)" }}>{err}</p> : null}
          <button className="btn sec" onClick={signOut} style={{ marginTop: 6 }}>Lock settings</button>
        </>
      )}
    </>
  );
}
