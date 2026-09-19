import { useEffect, useState } from "react";
import { api, rememberOwner, readUser, type SettingSpec, type ThesisListItem } from "./api";
import { PageHead } from "./ui";

const TOKEN_KEY = "eigen.admin.token";
const readToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } };
const saveToken = (t: string) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } };

export function Settings() {
  const [token, setToken] = useState(readToken());
  const [entry, setEntry] = useState("");
  const [settings, setSettings] = useState<Record<string, SettingSpec> | null>(null);
  const [theses, setTheses] = useState<ThesisListItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState("");
  const [err, setErr] = useState("");

  async function loadTheses(t: string) {
    try { setTheses(await api.adminAllTheses(t)); } catch { /* leave as-is; settings still usable */ }
  }
  async function load(t: string) {
    setBusy(true); setErr("");
    try {
      const r = await api.adminSettings(t);
      setSettings(r.settings); setToken(t); saveToken(t);
      loadTheses(t);
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
  const signedIn = !!readUser()?.token;
  async function adopt(id: string) {
    setRowBusy(id); setErr("");
    try {
      // Signed in → claim to the account (shows in My theses on any device). Otherwise mint a
      // device-only capability token for this browser.
      const r = await api.adminAdopt(token, id, signedIn);
      if (r.owner_token) rememberOwner(id, r.owner_token);
    } catch (e) { setErr((e as Error).message); } finally { setRowBusy(""); }
  }
  async function removeThesis(t: ThesisListItem) {
    if (!window.confirm(`Delete “${(t.title || t.thesis || "this thesis").slice(0, 80)}”? This permanently removes the thesis and all its research. This cannot be undone.`)) return;
    setRowBusy(t.id); setErr("");
    try { await api.adminDeleteThesis(token, t.id); setTheses((ts) => (ts || []).filter((x) => x.id !== t.id)); }
    catch (e) { setErr((e as Error).message); } finally { setRowBusy(""); }
  }
  function signOut() { saveToken(""); setToken(""); setSettings(null); setTheses(null); setEntry(""); }

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
          <div className="card" style={{ maxWidth: 620 }}>
            <div className="setting-h">All theses · recover or delete</div>
            <p className="muted" style={{ fontSize: ".84rem", margin: ".25rem 0 .7rem", lineHeight: 1.5 }}>
              Every thesis in the deployment. {signedIn
                ? <>You’re signed in — <b>Claim to my account</b> binds a thesis to your account so it shows in <b>My theses</b> on any device.</>
                : <>Not signed in — <b>Add to this device</b> mints a browser-only token. Sign in first to claim to your account instead.</>}
            </p>
            {theses === null ? <p className="muted" style={{ fontSize: ".85rem" }}>Loading…</p>
              : theses.length === 0 ? <p className="muted" style={{ fontSize: ".85rem" }}>No theses.</p> : (
                <div className="adm-theses">
                  {theses.map((t) => (
                    <div key={t.id} className="adm-thesis">
                      <div className="adm-thesis-main">
                        <div className="adm-thesis-title">{t.title || t.thesis || "Untitled"}</div>
                        <div className="adm-thesis-meta">
                          <span className="mono">{t.id}</span>
                          {t.claims ? <span>· {t.settled ?? 0}/{t.claims} settled</span> : <span>· draft</span>}
                          {t.on_board ? <span className="adm-onboard">· ▤ published</span> : null}
                          {t.updated_at ? <span>· {t.updated_at.slice(0, 10)}</span> : null}
                        </div>
                      </div>
                      <div className="adm-thesis-acts">
                        <button className="btn sec" disabled={!!rowBusy} onClick={() => adopt(t.id)}>{rowBusy === t.id ? "…" : (signedIn ? "Claim to my account" : "Add to this device")}</button>
                        <button className="btn sec adm-del" disabled={!!rowBusy} onClick={() => removeThesis(t)}>Delete</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
          </div>
          {err ? <p className="state" style={{ color: "var(--p0)" }}>{err}</p> : null}
          <button className="btn sec" onClick={signOut} style={{ marginTop: 6 }}>Lock settings</button>
        </>
      )}
    </>
  );
}
