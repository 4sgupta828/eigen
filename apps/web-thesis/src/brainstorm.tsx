import { useState } from "react";
import { api, type Analysis, type Take } from "./api";
import { PageHead, plain } from "./ui";

// Brainstorm surfaces the take's own weak points to probe — rendered in the same lane/chip/card
// visual language as the Reasoning Map, grouped by kind. A gap no document settles → hand to Experts.
// Free-text thesis-native Q&A (the /turn endpoint) is the spec'd next step; wired here as the entry.
const LANES: { kind: string; title: string; hint: string; color: string }[] = [
  { kind: "tension", title: "Tensions to probe", hint: "findings that pull apart — press on where they conflict", color: "#c0563f" },
  { kind: "gap", title: "Gaps to close", hint: "what the record can't settle — take these to an expert", color: "#b8860b" },
  { kind: "assumption", title: "Assumptions to test", hint: "the load-bearing premises — challenge each one", color: "#6b5bd0" },
];

type QA = { q: string; a?: string; err?: boolean };

export function Brainstorm({ id, take, onExperts }: { id?: string; take?: Take; onExperts: () => void }) {
  const [q, setQ] = useState("");
  const [thread, setThread] = useState<QA[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask() {
    const text = q.trim();
    if (!text || !id || busy) return;
    setBusy(true); setQ("");
    setThread((t) => [...t, { q: text }]);
    try {
      const r = await api.ask(id, text);
      const a = plain(r.move?.text) || "The evidence for this thesis is shown in the brief.";
      setThread((t) => t.map((x, i) => (i === t.length - 1 && x.a === undefined ? { ...x, a } : x)));
    } catch (e) {
      const msg = (e as Error).message || "could not answer just now";
      setThread((t) => t.map((x, i) => (i === t.length - 1 && x.a === undefined ? { ...x, a: msg, err: true } : x)));
    } finally { setBusy(false); }
  }

  const by = new Map<string, Analysis[]>();
  (take?.sections || []).forEach((s) => (s.analysis || []).forEach((a) => {
    if (!(a.text || "").trim()) return; const k = a.kind || ""; by.set(k, [...(by.get(k) || []), a]);
  }));
  const lanes = LANES.filter((l) => by.get(l.kind)?.length);
  const total = lanes.reduce((n, l) => n + (by.get(l.kind)?.length || 0), 0);

  return (
    <>
      <PageHead title="Brainstorm" sub="Poke holes and explore angles over the thesis's own findings. Where it can't settle something, that's your cue to seek an expert." />
      <div className="card">
        <div className="kick">Ask this thesis</div>
        <div className="row" style={{ marginTop: ".45rem" }}>
          <input className="gtext" value={q} onChange={(e) => setQ(e.target.value)} disabled={!id || busy}
            placeholder="Ask or challenge — “where is this weakest?”, “who really signs?”…"
            onKeyDown={(e) => { if (e.key === "Enter") ask(); }} />
          <button className="btn" disabled={!id || busy || !q.trim()} onClick={ask}>{busy ? "…" : "Ask"}</button>
        </div>
        {thread.length ? (
          <div className="conv" style={{ marginTop: ".8rem" }}>
            {thread.map((x, i) => (
              <div key={i}>
                <div className="turn"><span className="av you">YOU</span><div className="bub">{x.q}</div></div>
                <div className="turn"><span className="av ai">E</span>
                  <div className={`bub${x.a === undefined ? " muted" : ""}`} style={x.err ? { color: "var(--p0)" } : undefined}>
                    {x.a === undefined ? "thinking…" : x.a}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
        <p className="muted" style={{ fontSize: ".8rem", margin: ".6rem 0 0" }}>
          Read-only Q&amp;A over the thesis's own findings — it explains the evidence, it never re-grades the verdict.
        </p>
      </div>

      <div className="th-rmap">
        <div className="th-rmap-top">
          <div className="th-rmap-base">💡 <b>{total}</b> weak point{total === 1 ? "" : "s"} the analysis surfaced — probe these before you decide</div>
        </div>
        {lanes.length === 0 ? (
          <p className="muted" style={{ fontSize: ".9rem" }}>Run the research to surface tensions, gaps and assumptions to probe.</p>
        ) : (
          <div className="th-rmap-lanes">
            {lanes.map((l) => (
              <div key={l.kind} className="th-rmap-lane" style={{ ["--rc" as string]: l.color }}>
                <div className="th-rmap-lane-h">
                  <span className="th-rmap-chip" style={{ background: l.color }}>{l.title}</span>
                  <span className="th-rmap-hint">{l.hint}</span>
                </div>
                <div className="th-rmap-cards">
                  {(by.get(l.kind) || []).map((a, i) => (
                    <div key={i} className="th-rmap-card" style={{ ["--rc" as string]: l.color }}>
                      <span className="th-rmap-dot" style={{ background: l.color }} />
                      <span className="th-rmap-ctext">
                        {plain(a.text)}
                        {l.kind === "gap" ? <> <span className="th-bs-expert" onClick={onExperts}>→ Experts</span></> : null}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="th-rmap-foot">A gap no document settles → <span className="th-bs-expert" onClick={onExperts}>take it to Experts</span>. Probing here is a reading of the evidence, not investment advice.</div>
      </div>
    </>
  );
}
