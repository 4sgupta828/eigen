import { useEffect, useRef, useState } from "react";
import { api, type Inquiry, type Question, type RunPlan } from "./api";
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
      if (s.state === "failed") { runId.current = null; setBusy(""); setStage(""); setErr((s.error?.reason as string) || "generation failed — try again"); return; }
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

type RunPhase = { k: "loading" } | { k: "idle" }
  | { k: "gate"; level: number | "all"; usd: number; count: number }
  | { k: "running"; done: number; total: number; stage: string } | { k: "error"; msg: string };

export function Run({ id, onDone }: { id: string; onDone: () => void }) {
  const [plan, setPlan] = useState<RunPlan | null>(null);
  const [phase, setPhase] = useState<RunPhase>({ k: "loading" });
  const timer = useRef<number | null>(null);

  async function loadPlan() { try { setPlan(await api.runPlan(id)); } catch { /* keep prior */ } }

  useEffect(() => {
    let alive = true;
    (async () => {
      await loadPlan();
      try {
        const a = await api.activeRun(id);   // re-attach an in-flight research run after a refresh
        if (!alive) return;
        if (a.run?.id && a.kind === "research") { setPhase({ k: "running", done: 0, total: 0, stage: a.run.stage || "" }); poll(); return; }
      } catch { /* nothing in flight */ }
      if (alive) setPhase({ k: "idle" });
    })();
    return () => { alive = false; if (timer.current) window.clearTimeout(timer.current); };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps

  function poll() {
    api.activeRun(id).then((a) => {
      if (!a.run?.id) return finish();   // run cleared → done
      api.inquiryStatus(id, a.run!.id).then((s) => {
        if (s.state === "completed" || s.state === "cancelled") return finish();
        if (s.state === "failed") { setPhase({ k: "error", msg: (s.error?.reason as string) || "the run failed — you can retry" }); return; }
        setPhase({ k: "running", done: s.done || 0, total: s.total || 0, stage: s.stage || "" });
        timer.current = window.setTimeout(poll, 2500);
      }).catch(() => { timer.current = window.setTimeout(poll, 3000); });
    }).catch(() => { timer.current = window.setTimeout(poll, 3000); });
  }
  async function finish() { await loadPlan(); setPhase({ k: "idle" }); onDone(); }
  async function stop() { try { await api.cancelRun(id); } catch { /* poll settles */ } }

  // Project the layer's cost (max_usd 0 → refused+projection), then show a compact confirm.
  async function projectLayer(level: number | "all") {
    setPhase({ k: "loading" });
    try {
      const r = level === "all" ? await api.projectRun(id) : await api.runCritical(id, 0, level);
      if (r.status === "synthesized" || r.status === "completed") { await finish(); return; }
      const count = r.selected ?? r.projection?.claims ?? 0;
      setPhase({ k: "gate", level, usd: r.projection?.projected_usd || 0, count });
    } catch (e) { setPhase({ k: "error", msg: (e as Error).message }); }
  }
  async function runLayer(level: number | "all", usd: number) {
    const budget = Math.max(1, usd + 0.5);
    setPhase({ k: "running", done: 0, total: 0, stage: "starting…" });
    try {
      const r = level === "all" ? await api.runAll(id, budget) : await api.runCritical(id, budget, level);
      if (r.status === "synthesized" || r.status === "completed") { await finish(); return; }
      if (r.run?.id) poll();
      else setPhase({ k: "error", msg: r.status === "refused" ? "cost exceeded the budget" : "could not start the run" });
    } catch (e) { setPhase({ k: "error", msg: (e as Error).message }); }
  }

  const levels = plan?.levels || [];
  const started = (plan?.answered || 0) > 0;
  const nextLevel = plan?.next_level ?? null;
  const nextLabel = nextLevel !== null ? (levels.find((l) => l.level === nextLevel)?.label || `P${nextLevel}`) : "";

  return (
    <>
      <PageHead title="Run the research" sub="Answer the lines of inquiry in layers — the P0 crux first, then broaden one layer at a time. Each layer only researches questions not yet run, then refreshes the Brief, Reasoning Map and Take." />

      {plan && plan.total > 0 ? (
        <div className="runplan">
          <div className="runplan-head">
            <span className="runplan-count"><b>{plan.answered}</b> of {plan.total} questions researched</span>
            {plan.remaining > 0 ? <span className="runplan-rem">{plan.remaining} not yet run</span> : <span className="runplan-done">✓ all researched</span>}
          </div>
          <div className="runplan-levels">
            {levels.map((l) => {
              const pct = l.total ? Math.round((l.answered / l.total) * 100) : 0;
              const isNext = l.level === nextLevel;
              return (
                <div key={l.level} className={"runplan-lvl" + (l.remaining === 0 ? " full" : "") + (isNext ? " next" : "")}>
                  <div className="runplan-lvl-h">
                    <span className="runplan-lvl-name">{l.remaining === 0 ? "✓ " : ""}{l.label}</span>
                    <span className="runplan-lvl-n">{l.answered}/{l.total}</span>
                  </div>
                  <div className="runplan-bar"><i style={{ width: `${pct}%` }} /></div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {phase.k === "loading" ? <div className="state">loading…</div>
        : phase.k === "running" ? (
          <div className="gate">
            <div className="lbl" style={{ display: "flex", alignItems: "center", gap: ".4rem" }}><Working text="Researching" /></div>
            <div className="row" style={{ justifyContent: "space-between", margin: ".3rem 0 .6rem" }}>
              <span className="serif" style={{ fontSize: "1.05rem" }}>{phase.total ? `${phase.done} of ${phase.total} questions this run` : "starting…"} · then refreshing the read</span>
              <span className="mono muted">{phase.stage}</span>
            </div>
            <div className="progress"><i style={{ width: `${phase.total ? Math.round((phase.done / phase.total) * 100) : 8}%` }} /></div>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginTop: ".7rem" }}>
              <p className="muted" style={{ fontSize: ".82rem", margin: 0 }}>Corpus + web · verbatim span-check on every claim · already-answered questions are skipped.</p>
              <button className="btn sec" onClick={stop}>■ Stop</button>
            </div>
          </div>
        ) : phase.k === "gate" ? (
          <div className="gate">
            <div className="lbl">{phase.level === "all" ? "Run everything remaining" : `Run ${levels.find((l) => l.level === phase.level)?.label || "the next layer"}`}</div>
            <p className="serif" style={{ fontSize: "1.05rem", margin: ".3rem 0 .1rem" }}>{phase.count} question{phase.count === 1 ? "" : "s"} not yet run · then the Brief, Reasoning Map &amp; Take refresh.</p>
            <p className="muted" style={{ fontSize: ".8rem", margin: ".2rem 0 0" }}>Already-answered questions are skipped. <span className="runplan-cost">est. ~${(phase.usd).toFixed(2)} · corpus + web</span></p>
            <div className="row" style={{ marginTop: ".8rem" }}>
              <button className="btn" onClick={() => runLayer(phase.level, phase.usd)}>Run these {phase.count} →</button>
              <button className="btn sec" onClick={() => setPhase({ k: "idle" })}>Cancel</button>
            </div>
          </div>
        ) : phase.k === "error" ? (
          <div className="gate"><p style={{ color: "var(--p0)" }}>{phase.msg}</p><button className="btn sec" onClick={() => { setPhase({ k: "idle" }); loadPlan(); }}>Retry</button></div>
        ) : plan && plan.all_answered ? (
          <div className="gate"><div className="lbl">✓ Research complete</div><p style={{ margin: ".4rem 0 0" }}>Every question has been researched (some may have found nothing in the record — that is a real result). The lines of inquiry are below; the synthesized read is in <b>Brief</b>. Re-run any single question below to refresh it.</p></div>
        ) : (
          <div className="gate">
            {nextLevel !== null ? (
              <>
                <div className="lbl">{started ? "Deepen the research" : "Start with the crux"}</div>
                <p className="serif" style={{ fontSize: "1.06rem", margin: ".3rem 0 .5rem" }}>
                  {started ? <>Next layer: <b>{nextLabel}</b> — {plan?.next_run} question{plan?.next_run === 1 ? "" : "s"} not yet run.</>
                    : <>Run the <b>P0 crux</b> first — the {plan?.next_run} question{plan?.next_run === 1 ? "" : "s"} whose answers most move the call.</>}
                </p>
                <div className="row">
                  <button className="btn" onClick={() => projectLayer(nextLevel)}>{started ? `Run ${nextLabel} →` : "Run the P0 crux →"}</button>
                  {plan && plan.remaining > (plan.next_run || 0) ? <button className="btn sec" onClick={() => projectLayer("all")}>Run all {plan.remaining} remaining</button> : null}
                </div>
                <p className="muted" style={{ fontSize: ".8rem", margin: ".6rem 0 0" }}>Each layer only researches questions not yet run, then refreshes the Brief, Reasoning Map &amp; Take — nothing already researched is re-run.</p>
              </>
            ) : <p className="muted">Draft the lines of inquiry first, on the Plan step.</p>}
          </div>
        )}
    </>
  );
}
