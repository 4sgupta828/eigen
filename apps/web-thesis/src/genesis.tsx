import { useState } from "react";
import { api, type ThesisDoc } from "./api";
import { PageHead, go } from "./ui";

type Msg = { role: "you" | "ai"; text: string };

export function Genesis({ id: initialId, doc }: { id?: string; doc?: ThesisDoc }) {
  const [id, setId] = useState(initialId || "");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [proposed, setProposed] = useState(doc?.proposed_thesis || doc?.thesis || "");
  const [ready, setReady] = useState(!!doc?.proposed_thesis);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function begin(text: string) {
    if (text.trim().length < 12) { setErr("State the thesis as a sentence (who buys it, and what they do today)."); return; }
    setBusy(true); setErr("");
    try {
      const c = await api.create(text, true);      // draft; persists owner_token
      setId(c.id);
      setMsgs([{ role: "you", text }]);
      const g = await api.genesis(c.id, "");        // agent opens / sharpens
      setMsgs((m) => [...m, { role: "ai", text: g.reply || "" }]);
      setProposed(g.proposed_thesis || text); setReady(!!g.ready);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function turn(text: string) {
    if (!text.trim()) return;
    if (!id) return begin(text);
    setBusy(true); setErr(""); setInput(""); setMsgs((m) => [...m, { role: "you", text }]);
    try {
      const g = await api.genesis(id, text);
      setMsgs((m) => [...m, { role: "ai", text: g.reply || "" }]);
      setProposed(g.proposed_thesis || proposed); setReady(!!g.ready);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function useThesis() {
    if (!id) return;
    setBusy(true); setErr("");
    try {
      const c = await api.confirm(id, proposed, 8);
      if (c.status === "ok") go(`#thesis/${encodeURIComponent(id)}`);
      else setErr(c.reason || "could not confirm — try a clearer sentence");
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function sample() {
    setBusy(true); setErr("");
    try { setInput(await api.sample()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  const started = !!id || msgs.length > 0;
  return (
    <>
      <PageHead title="State the thesis" sub="Say it in a sentence — the product, who buys it, what they do today. I sharpen it with you, then you commit it." />
      {!started ? (
        <div className="card">
          <div className="row" style={{ marginBottom: 10 }}>
            <input className="gtext" value={input} onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. A startup selling AI clinical decision support to mid-sized hospitals…"
              onKeyDown={(e) => { if (e.key === "Enter") begin(input); }} />
            <button className="btn" disabled={busy} onClick={() => begin(input)}>{busy ? "…" : "Start"}</button>
          </div>
          <button className="btn sec" disabled={busy} onClick={sample}>🎲 Generate a sample</button>
        </div>
      ) : (
        <div className="card">
          <div className="conv">
            {msgs.map((m, i) => (
              <div key={i} className="turn">
                <span className={`av ${m.role}`}>{m.role === "you" ? "YOU" : "E"}</span>
                <div className={`bub${m.role === "ai" ? " aiq" : ""}`}>{m.text}</div>
              </div>
            ))}
            {busy ? <div className="turn"><span className="av ai">E</span><div className="bub muted">thinking…</div></div> : null}
          </div>
          {ready && proposed ? (
            <div className="landed"><span className="kick">Landed thesis</span>
              <p className="serif" style={{ margin: ".35rem 0 0" }}>{proposed}</p>
              <div className="row" style={{ marginTop: ".7rem" }}>
                <button className="btn" disabled={busy} onClick={useThesis}>Use this thesis →</button>
                <span className="muted mono" style={{ fontSize: ".7rem" }}>or keep replying to sharpen it</span>
              </div>
            </div>
          ) : null}
          <div className="row" style={{ marginTop: ".8rem" }}>
            <input className="gtext" value={input} onChange={(e) => setInput(e.target.value)}
              placeholder="Answer, or add what you know — I'll keep sharpening it"
              onKeyDown={(e) => { if (e.key === "Enter") turn(input); }} />
            <button className="btn" disabled={busy} onClick={() => turn(input)}>Send</button>
          </div>
        </div>
      )}
      {err ? <p className="state" style={{ padding: "1rem", color: "var(--p0)" }}>{err}</p> : null}
    </>
  );
}
