import { useEffect, useRef, useState } from "react";
import { api, type Inquiry, type Question } from "./api";
import { PageHead, Working } from "./ui";

const verdictClass = (q: Question) => (q.target_status?.includes("contradict") ? "v-con" : q.target_status ? "v-sup" : "v-open");

function ScanStrip() {
  return (
    <div className="scanstrip">🛰 <b>Scanned the current landscape</b> · as of today — so the questions name what's real now, not the model's memory.
      <span className="schip">recent entrants</span><span className="schip">latest rules</span><span className="schip">incumbent moves</span>
      <span className="muted" style={{ fontSize: ".72rem" }}>(grounding step — see docs/specs/landscape-grounded-questions.md)</span>
    </div>
  );
}

export function Plan({ id, inquiries, onReload, onRun }: {
  id: string; inquiries?: Inquiry[]; onReload: () => void; onRun: () => void;
}) {
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState("");
  const [stage, setStage] = useState("");
  const runId = useRef<string | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  const has = (inquiries || []).length > 0;

  async function act(label: string, fn: () => Promise<unknown>) {
    setBusy(label); setErr("");
    try { await fn(); onReload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  }

  // Plan generation is a BACKGROUND run (scan → frame → draft → prioritize): kick it off, poll status,
  // and let it be stopped — so it never blocks or dangles if the user navigates away mid-generation.
  const STAGE_LABEL: Record<string, string> = { starting: "starting…", scanning: "scanning the current landscape…", drafting: "drafting the questions…", prioritizing: "setting priorities…" };
  function pollGen(rid: string) {
    api.inquiryStatus(id, rid).then((s) => {
      if (s.state === "completed" || s.state === "cancelled") { runId.current = null; setBusy(""); setStage(""); onReload(); return; }
      if (s.state === "failed") { runId.current = null; setBusy(""); setStage(""); setErr("generation failed — try again"); return; }
      setStage(STAGE_LABEL[s.stage || ""] || "working…");
      timer.current = window.setTimeout(() => pollGen(rid), 2500);
    }).catch(() => { timer.current = window.setTimeout(() => pollGen(rid), 3000); });
  }
  async function generate(label: string) {
    setBusy(label); setErr(""); setStage("starting…");
    try {
      const r = await api.generate(id);
      if (!r.run?.id) { onReload(); setBusy(""); setStage(""); return; }
      runId.current = r.run.id; pollGen(r.run.id);
    } catch (e) { setBusy(""); setStage(""); setErr((e as Error).message); }
  }
  async function stopGen() { setStage("stopping…"); try { await api.cancelRun(id, runId.current || undefined); } catch { /* poll settles it */ } }

  // Re-attach an in-flight generate/redraft run after a page refresh so its spinner comes back.
  useEffect(() => {
    let alive = true;
    api.activeRun(id).then((a) => {
      if (!alive || !a.run?.id || a.kind !== "generate" || runId.current) return;
      setBusy("gen"); setStage(STAGE_LABEL[a.run.stage || ""] || "generating…");
      runId.current = a.run.id; pollGen(a.run.id);
    }).catch(() => { /* nothing in flight */ });
    return () => { alive = false; };
  }, [id]);

  if (!has) {
    return (
      <>
        <PageHead title="Plan the inquiry" sub="Draft thesis-native lines of inquiry — pointed questions the evidence can settle." />
        <div className="card">
          <p style={{ margin: "0 0 .7rem", fontSize: ".9rem" }} className="muted">No lines of inquiry yet.</p>
          {busy === "gen" ? (
            <div className="row" style={{ alignItems: "center", gap: ".7rem" }}>
              <Working text={stage || "generating…"} />
              <button className="btn sec" onClick={stopGen}>■ Stop</button>
            </div>
          ) : (
            <button className="btn" disabled={!!busy} onClick={() => generate("gen")}>Generate lines of inquiry</button>
          )}
        </div>
        {err ? <p className="state" style={{ color: "var(--p0)" }}>{err}</p> : null}
      </>
    );
  }

  const priorityOf = (i: Inquiry) => {
    const ps = (i.questions || []).map((q) => (q as { priority?: number }).priority ?? 1);
    return ps.length ? Math.min(...ps) : 1;
  };
  const pLabel = (p: number) => (p === 0 ? "P0 crux" : `P${p}`);
  const pCls = (p: number) => (p === 0 ? "p-0" : p === 1 ? "p-1" : "p-2");

  return (
    <>
      <PageHead title="Plan the inquiry" sub="Edit the questions, set priorities, then run the ones you choose. P0 is the crux you'd run first." />
      <ScanStrip />
      <div className="row" style={{ marginBottom: 14, alignItems: "center" }}>
        {busy === "redraft" ? (
          <><Working text={stage || "redrafting…"} /><button className="btn sec" onClick={stopGen}>■ Stop</button></>
        ) : (
          <button className="btn sec" disabled={!!busy} onClick={() => generate("redraft")}>↻ Redraft questions</button>
        )}
        <button className="btn sec" disabled={!!busy} onClick={() => act("prio", () => api.prioritize(id))}>{busy === "prio" ? "…" : "◈ Set P0/P1/P2 priorities"}</button>
      </div>
      {(inquiries || []).map((i) => {
        const p = priorityOf(i);
        return (
          <div key={i.key} className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h3 style={{ fontSize: "1rem" }}>{i.name}</h3>
              <span className={`prio ${pCls(p)}`}>{pLabel(p)}</span>
            </div>
            {(i.questions || []).map((q) => (
              <div key={q.id} className="qline">
                <span className={`v ${verdictClass(q)}`} style={{ marginTop: ".1rem" }}>{q.target_status ? "answered" : "open"}</span>
                <span>{q.text}</span>
                <button className="qedit" title="delete" disabled={!!busy} onClick={() => act("del", () => api.deleteQuestion(id, q.id))}>✕</button>
              </div>
            ))}
          </div>
        );
      })}
      <div className="row"><button className="btn" onClick={onRun}>Continue to run →</button></div>
      {err ? <p className="state" style={{ color: "var(--p0)" }}>{err}</p> : null}
    </>
  );
}

type RunPhase = { k: "projecting" } | { k: "done_already" } | { k: "gate"; usd: number; claims: number }
  | { k: "running"; runId: string; done: number; total: number; stage: string } | { k: "finished" } | { k: "stopped" } | { k: "error"; msg: string };

export function Run({ id, onDone }: { id: string; onDone: () => void }) {
  const [phase, setPhase] = useState<RunPhase>({ k: "projecting" });
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      // Re-attach a research run that's already in flight (e.g. after a page refresh) instead of losing
      // its progress — the run keeps going server-side.
      try {
        const a = await api.activeRun(id);
        if (!alive) return;
        if (a.run?.id && a.kind === "research") {
          setPhase({ k: "running", runId: a.run.id, done: 0, total: 0, stage: a.run.stage || "" });
          poll(a.run.id); return;
        }
      } catch { /* fall through to projecting */ }
      try {
        const r = await api.projectRun(id);
        if (!alive) return;
        if (r.status === "synthesized" || r.status === "completed") setPhase({ k: "done_already" });
        else if (r.projection) setPhase({ k: "gate", usd: r.projection.projected_usd || 0, claims: r.projection.claims || 0 });
        else setPhase({ k: "gate", usd: 0, claims: 0 });
      } catch (e) { if (alive) setPhase({ k: "error", msg: (e as Error).message }); }
    })();
    return () => { alive = false; if (timer.current) window.clearTimeout(timer.current); };
  }, [id]);

  function poll(runId: string) {
    api.inquiryStatus(id, runId).then((s) => {
      if (s.state === "completed") { setPhase({ k: "finished" }); onDone(); return; }
      if (s.state === "cancelled") { setPhase({ k: "stopped" }); onDone(); return; }
      if (s.state === "failed") { setPhase({ k: "error", msg: "the run failed — you can retry" }); return; }
      setPhase({ k: "running", runId, done: s.done || 0, total: s.total || 0, stage: s.stage || "" });
      timer.current = window.setTimeout(() => poll(runId), 2500);
    }).catch(() => { timer.current = window.setTimeout(() => poll(runId), 3000); });
  }
  async function stop() {
    try { await api.cancelRun(id); } catch { /* the poll will settle to stopped */ }
  }

  async function start(critical: boolean) {
    const budget = phase.k === "gate" ? Math.max(1, phase.usd + 0.5) : 5;
    setPhase({ k: "running", runId: "", done: 0, total: 0, stage: "starting…" });
    try {
      const r = critical ? await api.runCritical(id, budget, 0) : await api.runAll(id, budget);
      if (r.status === "synthesized" || r.status === "completed") { setPhase({ k: "finished" }); onDone(); return; }
      if (r.run?.id) poll(r.run.id);
      else setPhase({ k: "error", msg: r.status === "refused" ? "cost exceeded the budget" : "could not start the run" });
    } catch (e) { setPhase({ k: "error", msg: (e as Error).message }); }
  }

  return (
    <>
      <PageHead title="Run the research" sub="Credits are shared and scarce, so every run is projected and gated. Approve the spend, or run just the P0 crux first." />
      {phase.k === "projecting" ? <div className="state">projecting cost…</div>
        : phase.k === "done_already" ? (
          <div className="gate"><div className="lbl">Research complete</div><p style={{ margin: ".4rem 0 0" }}>Every question is answered — the lines of inquiry are below. Re-run any single question there, or regenerate the read from the Brief.</p></div>
        ) : phase.k === "gate" ? (
          <div className="gate">
            <div className="lbl">Projected cost</div>
            <div className="big">${phase.usd.toFixed(2)}</div>
            <div className="breakdown">
              <div className="bd"><div className="lbl">Questions</div><div className="n">{phase.claims || "—"}</div></div>
              <div className="bd"><div className="lbl">Legs</div><div className="n">corpus + web</div></div>
            </div>
            <p className="muted" style={{ fontSize: ".84rem" }}>No partial answers: it runs end-to-end, then synthesizes the Take, Reasoning map, Competitive and Deck.</p>
            <div className="row" style={{ marginTop: ".9rem" }}>
              <button className="btn" onClick={() => start(false)}>Approve &amp; run · ${Math.max(1, phase.usd + 0.5).toFixed(2)}</button>
              <button className="btn sec" onClick={() => start(true)}>Run P0 crux only</button>
            </div>
          </div>
        ) : phase.k === "running" ? (
          <div className="gate">
            <div className="lbl" style={{ display: "flex", alignItems: "center", gap: ".4rem" }}><Working text="Researching" /></div>
            <div className="row" style={{ justifyContent: "space-between", margin: ".3rem 0 .6rem" }}>
              <span className="serif" style={{ fontSize: "1.05rem" }}>{phase.total ? `${phase.done} of ${phase.total} questions` : "starting…"} · then synthesizing</span>
              <span className="mono muted">{phase.stage}</span>
            </div>
            <div className="progress"><i style={{ width: `${phase.total ? Math.round((phase.done / phase.total) * 100) : 8}%` }} /></div>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginTop: ".7rem" }}>
              <p className="muted" style={{ fontSize: ".84rem", margin: 0 }}>Corpus + web · verbatim span-check on every claim · sentiment kept as signal.</p>
              <button className="btn sec" onClick={stop}>■ Stop</button>
            </div>
          </div>
        ) : phase.k === "finished" ? (
          <div className="gate"><div className="lbl">Done</div><p style={{ margin: ".4rem 0 0" }}>Research complete — the lines of inquiry are below. Open <b>Brief</b> for the synthesized read.</p></div>
        ) : phase.k === "stopped" ? (
          <div className="gate"><div className="lbl">Stopped</div><p style={{ margin: ".4rem 0 0" }}>Research stopped. The questions already answered are kept and shown below — re-run any of them to continue.</p></div>
        ) : (
          <div className="gate"><p style={{ color: "var(--p0)" }}>{phase.msg}</p><button className="btn sec" onClick={() => setPhase({ k: "projecting" })}>Retry</button></div>
        )}
    </>
  );
}
