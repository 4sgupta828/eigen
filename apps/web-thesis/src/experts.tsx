import { useEffect, useState } from "react";
import { api, type Candidate, type ExpertAspect, type Inquiry, type Insight } from "./api";
import { PageHead } from "./ui";

export function Experts({ id, inquiries }: { id: string; inquiries?: Inquiry[] }) {
  const [aspects, setAspects] = useState<ExpertAspect[] | null>(null);
  const [cands, setCands] = useState<Record<string, Candidate[]>>({});
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    let alive = true;
    api.experts(id).then((a) => alive && setAspects(a)).catch((e) => alive && setErr((e as Error).message));
    return () => { alive = false; };
  }, [id]);

  async function discover(aspect_key: string) {
    setBusy(aspect_key); setErr("");
    try { const r = await api.discoverExperts(id, aspect_key); setCands((c) => ({ ...c, [aspect_key]: r.candidates || [] })); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  }

  // transcript upload
  const lines = inquiries || [];
  const [line, setLine] = useState("");
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [insights, setInsights] = useState<Insight[] | null>(null);
  const [upBusy, setUpBusy] = useState(false);

  useEffect(() => { if (!line && lines.length) setLine(lines[0].key); }, [lines, line]);

  async function upload() {
    if (!line || text.trim().length < 20) { setErr("Pick a line of inquiry and paste a transcript."); return; }
    setUpBusy(true); setErr("");
    try { const r = await api.uploadTranscript(id, line, { transcript: text, expert_name: name }); setInsights(r.insights || []); setText(""); }
    catch (e) { setErr((e as Error).message); } finally { setUpBusy(false); }
  }

  return (
    <>
      <PageHead title="Seek experts & integrate their knowledge"
        sub="Some things no document settles — willingness-to-pay, switching cost, whether the buyer will sign. Find the people who lived them, then fold what they say back in as verbatim-gated evidence." />
      <div className="split">
        <div>
          <div className="kick" style={{ marginBottom: ".5rem" }}>1 · Seek experts — who can settle the gaps</div>
          {aspects === null ? <div className="state">loading…</div>
            : aspects.length === 0 ? <p className="muted" style={{ fontSize: ".9rem" }}>No expert-only gaps surfaced yet — run the research first.</p>
              : aspects.map((a) => (
                <div key={a.key} className="pcard">
                  <div className="role">{(a.roles || []).map((r) => r.label).join(" · ") || "expert"}</div>
                  <h3 style={{ fontSize: ".98rem" }}>{a.prompt}</h3>
                  {a.guidance ? <p className="muted" style={{ fontSize: ".83rem", margin: ".25rem 0 .5rem" }}>{a.guidance}</p> : null}
                  <button className="btn sec" style={{ padding: ".35rem .6rem" }} disabled={busy === a.key} onClick={() => discover(a.key)}>
                    {busy === a.key ? "Finding…" : "Find people →"}
                  </button>
                  {(cands[a.key] || []).slice(0, 4).map((c, i) => (
                    <div key={i} style={{ fontSize: ".84rem", marginTop: ".4rem" }}>
                      <b>{c.name || "candidate"}</b> {c.headline ? <span className="muted">· {c.headline}</span> : null}
                      {c.profile_url ? <> · <a href={c.profile_url} target="_blank" rel="noopener">profile ↗</a></> : null}
                    </div>
                  ))}
                </div>
              ))}
        </div>
        <div>
          <div className="kick" style={{ marginBottom: ".5rem" }}>2 · Integrate expert knowledge</div>
          <div className="card" style={{ borderStyle: "dashed", background: "var(--panel2)" }}>
            <p className="muted" style={{ fontSize: ".8rem", margin: "0 0 .5rem" }}>Paste a call transcript. We keep only what's said verbatim, tag each point validates / invalidates / context, and tie it to a line. Expert opinion is <b>stated</b> — never controlling.</p>
            <div className="row" style={{ marginBottom: ".4rem" }}>
              <select className="gtext" style={{ maxWidth: 260 }} value={line} onChange={(e) => setLine(e.target.value)}>
                {lines.map((l) => <option key={l.key} value={l.key}>{l.name}</option>)}
              </select>
              <input className="gtext" placeholder="Expert name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <textarea className="gtext" style={{ width: "100%", minHeight: 90, resize: "vertical" }} placeholder="Paste the transcript…" value={text} onChange={(e) => setText(e.target.value)} />
            <div className="row" style={{ marginTop: ".5rem" }}>
              <button className="btn" disabled={upBusy} onClick={upload}>{upBusy ? "Extracting…" : "Extract insights"}</button>
            </div>
          </div>
          {insights ? (
            <div className="pcard">
              <div className="kick">Extracted → tied to “{lines.find((l) => l.key === line)?.name}”</div>
              {insights.length === 0 ? <p className="muted" style={{ fontSize: ".85rem" }}>No verbatim insight could be tied to this line.</p>
                : insights.map((ins, i) => (
                  <div key={i} className={`ins t-${ins.stance || "context"}`}>
                    <span className="tag">{ins.stance || "context"}</span>{ins.quote ? `"${ins.quote}"` : ins.insight}
                  </div>
                ))}
              <p className="muted mono" style={{ fontSize: ".66rem", marginTop: ".35rem" }}>Verbatim-gated · folded in as stated evidence.</p>
            </div>
          ) : null}
        </div>
      </div>
      {err ? <p className="state" style={{ color: "var(--p0)" }}>{err}</p> : null}
    </>
  );
}
