import { useEffect, useRef, useState } from "react";
import { api, type ThesisDoc, type TurnPayload, type Turn, type Version, type Evidence, type Deficiency, type ThesisPillar } from "./api";
import { PageHead, go, Working } from "./ui";

// An intake box that grows with the pasted thesis up to a readable height, then scrolls inside itself —
// so a one-liner stays compact but a full multi-page thesis is comfortable to review. Cmd/Ctrl+Enter submits.
function GrowText({ value, onChange, onSubmit, placeholder, disabled, minRows = 3, maxPx = 360 }:
  { value: string; onChange: (v: string) => void; onSubmit: () => void; placeholder?: string; disabled?: boolean; minRows?: number; maxPx?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const resize = () => { const el = ref.current; if (!el) return; el.style.height = "auto"; el.style.height = `${Math.min(el.scrollHeight, maxPx)}px`; };
  useEffect(resize, [value]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <textarea ref={ref} className="gtext gtext-area" value={value} disabled={disabled} rows={minRows}
      placeholder={placeholder}
      onChange={(e) => { onChange(e.target.value); resize(); }}
      onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); onSubmit(); } }} />
  );
}

// ── word-level redline (LCS on whitespace-split tokens) — ported from the classic client ──
function redline(prev: string, curr: string) {
  const a = String(prev || "").split(/(\s+)/), b = String(curr || "").split(/(\s+)/);
  const n = a.length, m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: { t: "eq" | "del" | "ins"; s: string }[] = [];
  let i = 0, j = 0;
  const push = (t: "eq" | "del" | "ins", s: string) => { if (s) out.push({ t: s.trim() ? t : "eq", s }); };
  while (i < n && j < m) {
    if (a[i] === b[j]) { push("eq", b[j]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push("del", a[i]); i++; }
    else { push("ins", b[j]); j++; }
  }
  while (i < n) { push("del", a[i]); i++; }
  while (j < m) { push("ins", b[j]); j++; }
  return out;
}
function Redline({ prev, curr }: { prev: string; curr: string }) {
  return <>{redline(prev, curr).map((seg, k) =>
    seg.t === "ins" ? <ins key={k}>{seg.s}</ins> : seg.t === "del" ? <del key={k}>{seg.s}</del> : <span key={k}>{seg.s}</span>)}</>;
}

// The agent's working MEMORY — open threads it's resolving + assumptions it rests on.
function Mem({ mem }: { mem?: TurnPayload["memory"] }) {
  const open = (mem?.open_threads || []).slice(0, 6);
  const assume = (mem?.assumptions || []).slice(0, 6);
  if (!open.length && !assume.length) return null;
  return (
    <div className="th-mem">
      {open.length ? <div className="th-mem-col"><div className="th-mem-h">Still resolving</div>
        <ul>{open.map((x, k) => <li key={k}>{x}</li>)}</ul></div> : null}
      {assume.length ? <div className="th-mem-col"><div className="th-mem-h">Assumptions it rests on</div>
        <ul>{assume.map((x, k) => <li key={k}>{x}</li>)}</ul></div> : null}
    </div>
  );
}

const REG_ICON: Record<string, string> = { filed: "✓", stated: "◇", coverage: "○", observed: "○" };
function Ev({ e }: { e: Evidence }) {
  const meta = [e.source_subject, e.evidence_kind, e.as_of ? e.as_of.slice(0, 10) : ""].filter(Boolean).join(" · ");
  const rel = (e.relation || (e.register === "coverage" || e.register === "observed" ? "signal" : "context")).replace(/_/g, " ");
  return (
    <div className="th-ev" data-side={e.side || ""}>
      <span title={e.register}>{REG_ICON[e.register || ""] || "▢"}</span>
      <span className="th-q">{(e.quote || "").slice(0, 400)} <span className="th-signal">{rel}</span>
        {meta ? <small className="th-note">{meta}</small> : null}</span>
      {e.source_url ? <a className="th-src" href={e.source_url} target="_blank" rel="noopener">source ↗</a> : <span className="th-src">{e.title || "source"}</span>}
    </div>
  );
}

const VER_SRC: Record<string, string> = { genesis: "drafted", directed: "your edit", self_improve: "self-improved", user_edit: "edited" };

export function Genesis({ id: initialId, doc: initialDoc, onCommitted }: { id?: string; doc?: ThesisDoc; onCommitted?: () => void }) {
  const [id, setId] = useState(initialId || "");
  const [doc, setDoc] = useState<ThesisDoc | undefined>(initialDoc);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [showRedline, setShowRedline] = useState(false);
  // Deficiency-driven sharpening: one identified gap + one proposal at a time.
  const [proposal, setProposal] = useState<Deficiency | null>(null);
  const [pillars, setPillars] = useState<ThesisPillar[]>([]);
  const [sharpening, setSharpening] = useState(false);

  const turns: Turn[] = doc?.turns || [];
  const agentTurns = turns.filter((t) => t.role === "agent" && t.payload?.proposed_thesis);
  const lastPay = agentTurns.length ? agentTurns[agentTurns.length - 1].payload : undefined;
  const prevThesis = agentTurns.length >= 2 ? (agentTurns[agentTurns.length - 2].payload?.proposed_thesis || "") : "";
  const proposed = lastPay?.proposed_thesis || doc?.proposed_thesis || doc?.thesis || "";
  const versions: Version[] = doc?.versions || [];
  const started = !!id || turns.length > 0;

  async function begin(text: string) {
    if (text.trim().length < 12) { setErr("State the thesis as a sentence (the product, who buys it, what they do today)."); return; }
    setBusy(true); setErr(""); setInput("");
    try {
      const c = await api.create(text, true);       // draft; persists owner_token
      setId(c.id);
      const g = await api.genesis(c.id, "");         // agent opens / sharpens; returns full doc
      setDoc(g.thesis || c.thesis);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function turn(text: string) {
    if (!text.trim()) return;
    if (!id) return begin(text);
    setBusy(true); setErr(""); setInput(""); setShowRedline(false);
    // Echo the author's message immediately (optimistic); the server's doc replaces it on response.
    setDoc((prev) => prev ? { ...prev, turns: [...(prev.turns || []), { role: "user", text }] } : prev);
    try {
      const g = await api.genesis(id, text);
      if (g.thesis) setDoc(g.thesis);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  // One sharpening round: send the action, then render the next identified deficiency + proposal.
  async function sharpen(body?: { action?: string; pillar?: string; proposed_thesis?: string }) {
    if (!id) return;
    setBusy(true); setErr(""); setShowRedline(false); setSharpening(true);
    try {
      const r = await api.improve(id, body);
      if (r.thesis) setDoc(r.thesis);
      setPillars(r.pillars || []);
      setProposal(r.proposal && !r.proposal.done && r.proposal.proposed_thesis ? r.proposal : null);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const startSharpen = () => sharpen();
  const acceptProposal = () => proposal && sharpen({ action: "accept", pillar: proposal.pillar, proposed_thesis: proposal.proposed_thesis });
  const rejectProposal = () => proposal && sharpen({ action: "reject", pillar: proposal.pillar });
  async function revert(vid: string) {
    if (!id || !vid) return;
    setBusy(true); setErr(""); setShowRedline(false);
    try {
      const g = await api.revert(id, vid);
      if (g.thesis) setDoc(g.thesis);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function useThesis() {
    if (!id) return;
    setBusy(true); setErr("");
    try {
      const c = await api.confirm(id, proposed, 5);
      if (c.status === "ok") { onCommitted?.(); go(`#thesis/${encodeURIComponent(id)}`); }
      else setErr(c.reason || "could not confirm — try a clearer sentence");
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function sample() {
    setBusy(true); setErr("");
    try { setInput(await api.sample()); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHead title="State the thesis" sub="Say it in a sentence — the product, who buys it, what they do today. I sharpen it with you, then you commit it." />
      {!started ? (
        <div className="card">
          <GrowText value={input} onChange={setInput} onSubmit={() => begin(input)} disabled={busy} minRows={4}
            placeholder="State your thesis — or paste it in full (a paragraph, or a multi-page memo). The macro shift and why-now, your edge, the scope, the return logic, the risks…  (⌘/Ctrl+Enter to start)" />
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" disabled={busy} onClick={() => begin(input)}>{busy ? "…" : "Start"}</button>
            <button className="btn sec" disabled={busy} onClick={sample}>🎲 Generate a sample</button>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="conv">
            {turns.map((t, i) => (
              <div key={i} className="turn">
                <span className={`av ${t.role === "agent" ? "ai" : "you"}`}>{t.role === "agent" ? "E" : "YOU"}</span>
                <div className={`bub${t.role === "agent" ? " aiq" : ""}`}>
                  {t.move ? <span className="th-move">{t.move.replace(/_/g, " ")}</span> : null}
                  {t.text}
                </div>
              </div>
            ))}
            {busy && !sharpening ? <div className="turn"><span className="av ai">E</span><div className="bub muted"><Working text="thinking…" /></div></div> : null}
          </div>

          {/* Working-thesis card — the agent restates the updated thesis every turn; redline shows what changed. */}
          {proposed ? (
            <div className={`th-landed${lastPay?.ready ? " ready" : ""}`}>
              <div className="th-landed-h">
                <span>{lastPay?.ready ? "The thesis I’d test" : "Working thesis"}</span>
                {prevThesis && prevThesis !== proposed ? (
                  <button type="button" className="th-redline-toggle" onClick={() => setShowRedline((s) => !s)}>
                    ⇄ {showRedline ? "hide" : "show"} changes
                  </button>
                ) : null}
              </div>
              {showRedline && prevThesis && prevThesis !== proposed ? (
                <blockquote className="th-landed-q">
                  <span className="th-redline-key"><ins>added</ins> <del>removed</del> since last turn</span>
                  <Redline prev={prevThesis} curr={proposed} />
                </blockquote>
              ) : (
                <blockquote className="th-landed-q">{proposed}</blockquote>
              )}
              <Mem mem={lastPay?.memory} />
              <div className="th-landed-row">
                <button type="button" className="th-use" disabled={busy} onClick={useThesis}>Use this thesis →</button>
                <span className="th-landed-hint">{lastPay?.ready ? "or keep refining it below." : "keep refining below, or use it now."}</span>
              </div>
            </div>
          ) : null}

          {/* Evidence the agent surfaced, and who to ask. */}
          {(lastPay?.evidence || []).length ? <div className="th-sides">{lastPay!.evidence!.map((e, k) => <Ev key={k} e={e} />)}</div> : null}
          {lastPay?.question ? (
            <div className="th-ask"><b>Ask them:</b> {lastPay.question}
              {(lastPay.people || []).map((p, k) => <div key={k} className="th-person"><b>{p.name}</b> <span>{p.why}</span></div>)}
              {lastPay.guidance ? <p className="th-note">{lastPay.guidance}</p> : null}
            </div>
          ) : null}

          {/* Sharpen toward a SOLID investment thesis — one identified deficiency + one proposal at a time. */}
          {proposed.trim().length >= 12 ? (
            <div className="th-sharpen">
              <div className="th-sharpen-h">
                <span className="th-sharpen-title">✨ Sharpen toward a solid thesis</span>
                <span className="th-sharpen-sub">one gap at a time — you accept or skip each proposal</span>
              </div>
              {pillars.length ? (
                <div className="th-pillars">
                  {pillars.map((p) => (
                    <span key={p.key} className={"th-pillar" + (p.addressed ? " done" : p.skipped ? " skip" : "") + (proposal?.pillar === p.key ? " active" : "")}
                      title={p.addressed ? "addressed" : p.skipped ? "skipped" : "not yet addressed"}>
                      <b>{p.addressed ? "✓" : p.skipped ? "–" : "○"}</b> {p.label}
                    </span>
                  ))}
                </div>
              ) : null}
              {busy && sharpening ? <div className="th-prop-wait"><Working text="identifying the next deficiency…" /></div>
                : proposal ? (
                  <div className="th-prop">
                    <div className="th-prop-top"><span className="th-prop-pill">{proposal.pillar_label}</span></div>
                    <div className="th-prop-def">{proposal.deficiency}</div>
                    {proposal.why ? <div className="th-prop-why"><b>Why it matters:</b> {proposal.why}</div> : null}
                    <blockquote className="th-prop-thesis">
                      <span className="th-redline-key"><ins>added</ins> <del>removed</del> — the proposed rewrite</span>
                      <Redline prev={proposed} curr={proposal.proposed_thesis} />
                    </blockquote>
                    {proposal.rationale ? <div className="th-prop-rat">{proposal.rationale}</div> : null}
                    <div className="th-prop-acts">
                      <button type="button" className="th-prop-accept" disabled={busy} onClick={acceptProposal}>✓ Accept this improvement</button>
                      <button type="button" className="th-prop-reject" disabled={busy} onClick={rejectProposal}>✗ Skip · show next gap</button>
                    </div>
                  </div>
                ) : sharpening ? (
                  <div className="th-prop-done">✓ Solid — the thesis covers all five pillars. Use it below, or keep refining.</div>
                ) : (
                  <button type="button" className="th-improve" disabled={busy} onClick={startSharpen}
                    title="I grade the thesis against the five pillars of a solid investment thesis and propose the highest-leverage fix">Find the next gap to close →</button>
                )}
            </div>
          ) : null}
          {versions.length >= 2 ? (
            <details className="th-versions">
              <summary>⟲ Versions ({versions.length}) — backtrack to an earlier thesis</summary>
              {versions.slice().reverse().map((v) => (
                <div key={v.id} className={`th-ver${v.active ? " active" : ""}`}>
                  <div className="th-ver-main">
                    <span className="th-ver-src">{VER_SRC[v.source || ""] || v.source || "version"}</span>
                    {v.rationale ? <div className="th-ver-rat">{v.rationale}</div> : null}
                    <div className="th-ver-txt">{(v.text || "").slice(0, 200)}</div>
                  </div>
                  {v.active ? <span className="th-ver-cur">current</span>
                    : <button type="button" className="th-ver-revert" disabled={busy} onClick={() => revert(v.id)}>Revert</button>}
                </div>
              ))}
            </details>
          ) : null}

          <div style={{ marginTop: ".8rem" }}>
            <GrowText value={input} onChange={setInput} onSubmit={() => turn(input)} disabled={busy} minRows={2}
              placeholder="Answer, or add what you know — paste anything relevant (⌘/Ctrl+Enter to send)" />
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn" disabled={busy} onClick={() => turn(input)}>Send</button>
            </div>
          </div>
        </div>
      )}
      {err ? <p className="state" style={{ padding: "1rem", color: "var(--p0)" }}>{err}</p> : null}
    </>
  );
}
