import { useEffect, useMemo, useRef, useState } from "react";
import { api, type BrainstormThread, type BrainstormMsg, type BsDirection, type BsCard, type Analysis, type Take } from "./api";
import { PageHead, Working, plain } from "./ui";
import { Visual } from "./viz";

// Brainstorm is a continuous, memory-bearing agent over the thesis's WHOLE context (thesis → lines of
// inquiry → collective take → competitive → everything). Each turn is an async, stoppable run: the agent
// reasons over the assembled context + the thread's running memory, answers, and opens up directions.
// The heavy, name-real-things moves (experts / related theses / media / deep-dive) are suggested as
// chips and fire only on click, each fetching REAL sources and appending a card. Threads are saveable —
// "past brainstorms" — so a line of thinking can be resumed later.

const SEC_META: Record<string, { title: string; color: string }> = {
  related_questions: { title: "Questions to pursue", color: "#3a6ea5" },
  adjacent_areas: { title: "Adjacent areas", color: "#2e8b74" },
  deep_dive: { title: "Worth a deep dive", color: "#8a6d3b" },
  gaps: { title: "Gaps & weak points", color: "#c0563f" },
};
const DIR_META: Record<string, { label: string; icon: string }> = {
  question: { label: "Ask", icon: "↳" },
  experts: { label: "Find experts", icon: "◎" },
  references: { label: "Related theses", icon: "❐" },
  media: { label: "Podcasts & talks", icon: "♪" },
  deepdive: { label: "Deep dive", icon: "⌖" },
};
const PROMPTS = [
  "Where is this thesis weakest?", "Who really has to say yes for this to work?",
  "What would a smart skeptic attack first?", "What adjacent bets does this open up?",
];
// The weak points the analysis already surfaced, in the same lane language as the Reasoning Map — a
// running "what to probe" the brainstorm reasons against. Tucked under a toggle at the top (not buried).
const WEAK_LANES: { kind: string; title: string; hint: string; color: string }[] = [
  { kind: "tension", title: "Tensions", hint: "findings that pull apart", color: "#c0563f" },
  { kind: "gap", title: "Gaps", hint: "what the record can't settle — take to an expert", color: "#b8860b" },
  { kind: "assumption", title: "Assumptions", hint: "the load-bearing premises to challenge", color: "#6b5bd0" },
];

export function Brainstorm({ id, take, onExperts }: { id?: string; take?: Take; onExperts: () => void }) {
  const [threads, setThreads] = useState<BrainstormThread[]>([]);
  const [tid, setTid] = useState<string>("");
  const [thread, setThread] = useState<BrainstormThread | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [showWeak, setShowWeak] = useState(false);
  const runId = useRef<string | null>(null);
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  // Weak points surfaced by the collective take, grouped into the lane language of the Reasoning Map.
  const weakLanes = useMemo(() => {
    const by = new Map<string, Analysis[]>();
    (take?.sections || []).forEach((s) => (s.analysis || []).forEach((a) => {
      if (!(a.text || "").trim()) return; const k = a.kind || ""; by.set(k, [...(by.get(k) || []), a]);
    }));
    return WEAK_LANES.map((l) => ({ ...l, items: by.get(l.kind) || [] })).filter((l) => l.items.length);
  }, [take]);
  const weakTotal = weakLanes.reduce((n, l) => n + l.items.length, 0);

  // Load the list of past brainstorms, and re-attach a run still in flight after a refresh.
  useEffect(() => {
    if (!id) return;
    let alive = true;
    api.bsThreads(id).then((ts) => { if (!alive) return; setThreads(ts); if (ts[0]?.id && !tid) select(ts[0].id); })
      .catch(() => { /* first visit: no threads yet */ });
    api.activeRun(id).then((a) => {
      if (!alive || !a.run?.id || a.kind !== "brainstorm" || runId.current) return;
      if (a.thread_id) { setTid(a.thread_id); loadThread(a.thread_id); }
      setBusy(true); setNote("thinking…"); runId.current = a.run.id; poll(a.run.id, a.thread_id || tid);
    }).catch(() => { /* nothing in flight */ });
    return () => { alive = false; };
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function loadThread(threadId: string) {
    if (!id || !threadId) return;
    try { const t = await api.bsThread(id, threadId); setThread(t); } catch { /* keep prior */ }
  }
  async function select(threadId: string) { setTid(threadId); setErr(""); await loadThread(threadId); }

  async function refreshThreads() { if (id) api.bsThreads(id).then(setThreads).catch(() => {}); }

  function poll(rid: string, threadId: string) {
    if (!id) return;
    api.inquiryStatus(id, rid).then((s) => {
      if (s.state === "completed" || s.state === "cancelled") {
        runId.current = null; setBusy(false); setNote("");
        loadThread(threadId); refreshThreads(); return;
      }
      if (s.state === "failed") {
        runId.current = null; setBusy(false); setNote("");
        setErr((s.error?.reason as string) || "that didn't go through — try again");
        loadThread(threadId); return;
      }
      timer.current = window.setTimeout(() => poll(rid, threadId), 2000);
    }).catch(() => { timer.current = window.setTimeout(() => poll(rid, threadId), 2800); });
  }

  async function ensureThread(): Promise<string> {
    if (tid) return tid;
    const t = await api.bsNewThread(id!);
    setTid(t.id); setThread({ ...t, messages: [] }); setThreads((xs) => [t, ...xs]);
    return t.id;
  }

  async function send(text: string) {
    const said = text.trim();
    if (!said || !id || busy) return;
    setErr(""); setInput("");
    const threadId = await ensureThread();
    // optimistic user bubble
    setThread((t) => t ? { ...t, messages: [...(Array.isArray(t.messages) ? t.messages : []), { id: Date.now(), role: "user", content: { text: said } }] } : t);
    setBusy(true); setNote("thinking…");
    try {
      const r = await api.bsMessage(id, threadId, said);
      if (!r.run?.id) { setBusy(false); setNote(""); loadThread(threadId); return; }
      runId.current = r.run.id; poll(r.run.id, threadId);
    } catch (e) { setBusy(false); setNote(""); setErr((e as Error).message); }
  }

  async function expand(dir: BsDirection) {
    if (!id || busy) return;
    if (dir.kind === "question") { send(dir.query || dir.label); return; }
    setErr(""); const threadId = await ensureThread();
    setBusy(true); setNote(`${DIR_META[dir.kind]?.label || "searching"}…`);
    try {
      const r = await api.bsExpand(id, threadId, dir.kind, dir.query || dir.label);
      if (!r.run?.id) { setBusy(false); setNote(""); loadThread(threadId); return; }
      runId.current = r.run.id; poll(r.run.id, threadId);
    } catch (e) { setBusy(false); setNote(""); setErr((e as Error).message); }
  }

  async function stop() { setNote("stopping…"); try { await api.cancelRun(id!, runId.current || undefined); } catch { /* poll settles it */ } }

  async function newThread() {
    if (!id || busy) return;
    const t = await api.bsNewThread(id);
    setThreads((xs) => [t, ...xs]); setTid(t.id); setThread({ ...t, messages: [] }); setErr("");
  }
  async function rename(threadId: string, cur: string) {
    const title = window.prompt("Rename this brainstorm", cur || "")?.trim();
    if (title === undefined || !id) return;
    await api.bsRenameThread(id, threadId, title);
    setThreads((xs) => xs.map((x) => x.id === threadId ? { ...x, title } : x));
    setThread((t) => t && t.id === threadId ? { ...t, title } : t);
  }
  async function del(threadId: string) {
    if (!id || !window.confirm("Delete this brainstorm thread?")) return;
    await api.bsDeleteThread(id, threadId);
    const left = threads.filter((x) => x.id !== threadId);
    setThreads(left);
    if (tid === threadId) { setTid(""); setThread(null); if (left[0]?.id) select(left[0].id); }
  }

  const msgs: BrainstormMsg[] = Array.isArray(thread?.messages) ? (thread!.messages as BrainstormMsg[]) : [];

  return (
    <>
      <PageHead title="Brainstorm" sub="Think out loud with an agent that holds your whole thesis — the findings, the read, the landscape — and remembers this conversation. Ask anything; pull on any thread; save it to come back to." />
      <div className="bs-wrap">
        <aside className="bs-side">
          <button className="bs-new" onClick={newThread} disabled={!id || busy}>+ New brainstorm</button>
          <div className="bs-side-h">Past brainstorms</div>
          {threads.length === 0 ? <p className="muted bs-empty">No saved brainstorms yet.</p> : (
            <ul className="bs-threads">
              {threads.map((t) => (
                <li key={t.id} className={"bs-thread" + (t.id === tid ? " on" : "")}>
                  <button className="bs-thread-pick" onClick={() => select(t.id)}>
                    <span className="bs-thread-t">{t.title || "Untitled brainstorm"}</span>
                    <span className="bs-thread-n">{typeof t.messages === "number" ? t.messages : ""} </span>
                  </button>
                  <span className="bs-thread-acts">
                    <button title="Rename" onClick={() => rename(t.id, t.title || "")}>✎</button>
                    <button title="Delete" onClick={() => del(t.id)}>🗑</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="bs-main">
          {weakTotal ? (
            <div className={"bs-weak" + (showWeak ? " open" : "")}>
              <button className="bs-weak-toggle" onClick={() => setShowWeak((v) => !v)} aria-expanded={showWeak}>
                <span className="bs-weak-tw">{showWeak ? "▾" : "▸"}</span>
                ⚠ Weak points the analysis surfaced <span className="bs-weak-n">{weakTotal}</span>
                <span className="bs-weak-sub">probe these — click one to brainstorm it</span>
              </button>
              {showWeak ? (
                <div className="bs-weak-lanes">
                  {weakLanes.map((l) => (
                    <div key={l.kind} className="bs-weak-lane" style={{ ["--wc" as string]: l.color }}>
                      <div className="bs-weak-h"><span className="bs-weak-chip" style={{ background: l.color }}>{l.title}</span><span className="bs-weak-hint">{l.hint}</span></div>
                      <ul className="bs-weak-items">
                        {l.items.map((a, i) => (
                          <li key={i}>
                            <button className="bs-weak-item" disabled={busy} onClick={() => send(`Probe this ${l.kind}: ${plain(a.text)}`)} title="Brainstorm this">
                              {plain(a.text)}
                            </button>
                            {l.kind === "gap" ? <button className="bs-inline-ask" onClick={onExperts}>→ Experts</button> : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="bs-conv">
            {msgs.length === 0 && !busy ? (
              <div className="bs-seed">
                <p className="muted">Start anywhere — a question, a doubt, a direction to explore.</p>
                <div className="bs-seed-chips">
                  {PROMPTS.map((p) => <button key={p} className="bs-chip" onClick={() => send(p)} disabled={!id}>{p}</button>)}
                </div>
              </div>
            ) : null}
            {msgs.map((m, i) => <MsgView key={m.id ?? i} m={m} onExpand={expand} busy={busy} onExperts={onExperts} />)}
            {busy ? <div className="bs-turn bs-agent"><span className="bs-av ai">E</span><div className="bs-bub"><Working text={note || "thinking…"} /></div></div> : null}
            {err ? <div className="bs-err">{err}</div> : null}
          </div>

          <div className="bs-composer">
            <textarea className="bs-input" value={input} rows={2} disabled={!id || busy}
              placeholder="Ask or challenge — “where is this weakest?”, “who really signs?”, “what adjacent bets does this open?”…"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
            {busy
              ? <button className="bs-send stop" onClick={stop}>■ Stop</button>
              : <button className="bs-send" onClick={() => send(input)} disabled={!id || !input.trim()}>Send</button>}
          </div>
          <p className="muted bs-foot">Exploration over your thesis's own context — it reasons and points you where to look; it never issues a buy/pass or gives investment advice. A gap no document can settle → <span className="bs-link" onClick={onExperts}>take it to Experts</span>.</p>
        </section>
      </div>
    </>
  );
}

function MsgView({ m, onExpand, busy, onExperts }: { m: BrainstormMsg; onExpand: (d: BsDirection) => void; busy: boolean; onExperts: () => void }) {
  const c = m.content || {};
  if (m.role === "user") {
    return <div className="bs-turn bs-you"><span className="bs-av you">YOU</span><div className="bs-bub">{c.text}</div></div>;
  }
  if (c.card) {
    return <div className="bs-turn bs-agent"><span className="bs-av ai">E</span><div className="bs-bub"><EnrichCard card={c.card} /></div></div>;
  }
  const sections = c.sections || [];
  const directions = c.directions || [];
  return (
    <div className="bs-turn bs-agent">
      <span className="bs-av ai">E</span>
      <div className="bs-bub">
        {c.reply ? <p className="bs-reply">{c.reply}</p> : null}
        {(c.visuals || []).map((v, i) => <Visual key={i} v={v} />)}
        {sections.map((s, i) => {
          const meta = SEC_META[s.kind] || { title: s.kind, color: "#6E6550" };
          if (!(s.items || []).length) return null;
          return (
            <div key={i} className="bs-sec" style={{ ["--sc" as string]: meta.color }}>
              <div className="bs-sec-h"><span className="bs-sec-chip" style={{ background: meta.color }}>{meta.title}</span></div>
              <ul className="bs-sec-items">
                {s.items.map((it, j) => (
                  <li key={j}>
                    <span className="bs-sec-row">
                      <span className="bs-sec-txt">{it}</span>
                      {s.kind === "related_questions" ? <button className="bs-inline-ask" onClick={() => onExpand({ kind: "question", label: it, query: it })} disabled={busy}>ask →</button> : null}
                      {s.kind === "gaps" ? <button className="bs-inline-ask" onClick={onExperts}>→ Experts</button> : null}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
        {directions.length ? (
          <div className="bs-dirs">
            {directions.map((d, i) => {
              const meta = DIR_META[d.kind] || { label: d.kind, icon: "→" };
              return <button key={i} className="bs-dir" onClick={() => onExpand(d)} disabled={busy} title={d.query}>
                <span className="bs-dir-ic">{meta.icon}</span>{d.label}</button>;
            })}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function EnrichCard({ card }: { card: BsCard }) {
  const kind = card.kind;
  if (kind === "experts") {
    const people = card.people || [];
    return (
      <div className="bs-enrich">
        <div className="bs-enrich-h">◎ People to engage <span className="muted">· {card.query}</span></div>
        {card.unavailable ? <p className="muted">Expert search isn't configured right now.</p>
          : people.length === 0 ? <p className="muted">No clear matches — try a narrower angle.</p>
            : <div className="bs-people">{people.map((p, i) => (
              <a key={i} className="bs-person" href={p.url} target="_blank" rel="noreferrer noopener">
                <span className="bs-person-n">{p.name}</span>
                {p.org ? <span className="bs-person-o">{p.org}</span> : null}
                {p.headline ? <span className="bs-person-h">{p.headline}</span> : null}
              </a>))}</div>}
      </div>
    );
  }
  const label = kind === "references" ? "❐ Related theses & references" : kind === "media" ? "♪ Podcasts, talks & posts" : "⌖ Deep dive";
  const cards = card.cards || [];
  return (
    <div className="bs-enrich">
      <div className="bs-enrich-h">{label} <span className="muted">· {card.query}</span></div>
      {kind === "deepdive" && (card.summary || []).length ? (
        <ul className="bs-dd-summary">{card.summary!.map((s, i) => <li key={i}>{s}</li>)}</ul>
      ) : null}
      {cards.length === 0 ? <p className="muted">Nothing solid came back — try a different angle.</p> : (
        <div className="bs-src-list">
          {cards.map((s, i) => (
            <a key={i} className="bs-src" href={s.url} target="_blank" rel="noreferrer noopener">
              <span className="bs-src-top">
                {s.tag ? <span className="bs-src-tag">{s.tag}</span> : null}
                <span className="bs-src-t">{s.title}</span>
              </span>
              {s.source ? <span className="bs-src-s">{s.source}</span> : null}
              {s.snippet ? <span className="bs-src-x">{s.snippet}</span> : null}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
