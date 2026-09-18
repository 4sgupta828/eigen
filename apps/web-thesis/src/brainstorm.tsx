import { useState } from "react";
import type { Analysis, Take } from "./api";
import { PageHead, plain } from "./ui";

// Brainstorm surfaces the take's own weak points (tension / gap reasoning blocks) to probe, and hands
// undocumentable gaps to Experts. Free-text thesis-native Q&A is the spec'd next step
// (docs/specs/landscape-grounded-questions.md + the /turn endpoint); wired here as the entry point.
const WEAK = new Set(["tension", "gap", "assumption"]);
const LABEL: Record<string, string> = { tension: "Tension", gap: "Gap", assumption: "Load-bearing assumption" };

export function Brainstorm({ take, onExperts }: { take?: Take; onExperts: () => void }) {
  const [q, setQ] = useState("");
  const weak: Analysis[] = [];
  (take?.sections || []).forEach((s) => (s.analysis || []).forEach((a) => { if (WEAK.has(a.kind || "") && a.text) weak.push(a); }));

  return (
    <>
      <PageHead title="Brainstorm" sub="Poke holes and explore angles over the thesis's own findings. Where it can't settle something, that's your cue to seek an expert." />
      <div className="card">
        <div className="kick">Ask this thesis</div>
        <div className="row" style={{ marginTop: ".45rem" }}>
          <input className="gtext" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask or challenge — “where is this weakest?”, “who really signs?”…" />
          <button className="btn">Ask</button>
        </div>
        <p className="muted" style={{ fontSize: ".8rem", margin: ".6rem 0 0" }}>
          Thesis-native Q&amp;A (answers over findings → corpus → web, cited) is the next backend step.
          Meanwhile, the weak points the analysis already surfaced are below.
        </p>
      </div>

      <div className="card">
        <div className="kick" style={{ marginBottom: ".5rem" }}>💡 Weak points it surfaces — probe these</div>
        {weak.length === 0 ? <p className="muted" style={{ fontSize: ".9rem" }}>Run the research to surface tensions, gaps and assumptions.</p>
          : weak.map((a, i) => (
            <p key={i} style={{ fontSize: ".9rem", margin: ".35rem 0", lineHeight: 1.55 }}>
              <span className="kick" style={{ marginRight: ".3rem" }}>{LABEL[a.kind || ""] || a.kind}</span>{plain(a.text)}
            </p>
          ))}
        <p className="muted" style={{ fontSize: ".82rem", marginTop: ".6rem" }}>
          A gap no document settles → <span style={{ color: "var(--gold-strong)", cursor: "pointer", textDecoration: "underline" }} onClick={onExperts}>take it to Experts</span>.
        </p>
      </div>
    </>
  );
}
