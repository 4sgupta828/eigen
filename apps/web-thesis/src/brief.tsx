import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  Analysis, Cited, Competitive, CompPlayer, Deck, Evidence, InquiriesView, Question, Take, ThesisDoc,
} from "./api";

// ── citation numbering (first-seen, per Brief) ─────────────────────────────────
class Citer {
  private seen = new Map<string, number>();
  private _n = 0;
  num(id: string): number {
    if (!this.seen.has(id)) this.seen.set(id, ++this._n);
    return this.seen.get(id)!;
  }
  peek(id: string): number | undefined { return this.seen.get(id); }  // number if already cited, else undefined
}
const MARK = /\[\[e:([A-Za-z0-9_-]{1,80})\]\]/g;
function parse(value?: Cited): { clean: string; ids: string[] } {
  const raw = `${value?.text || ""} ${value?.markers || ""}`;
  const ids: string[] = [];
  const clean = raw.replace(MARK, (_m, id: string) => { ids.push(id); return ""; })
    .replace(/\s+([.,;:])/g, "$1").replace(/\s{2,}/g, " ").trim();
  return { clean, ids };
}

// ── drawer state ───────────────────────────────────────────────────────────────
type DrawerView = { kind: "overview" } | { kind: "finding"; id: string } | { kind: "evidence"; id: string };
type Ctx = {
  citer: Citer;
  evidenceById: Map<string, Evidence>;
  findingById: Map<string, Question>;
  show: (v: DrawerView) => void;
  active: string | null;
};
const BriefCtx = createContext<Ctx | null>(null);
const useBrief = () => {
  const c = useContext(BriefCtx);
  if (!c) throw new Error("Brief context missing");
  return c;
};

// ── a cited run of text: renders clean text + clickable [n] refs ────────────────
function Cite({ value, kind }: { value?: Cited; kind: "finding" | "evidence" }) {
  const { citer, show, active } = useBrief();
  const { clean, ids } = parse(value);
  if (!clean && !ids.length) return null;
  return (
    <>
      {clean}{" "}
      {ids.map((id, i) => (
        <span
          key={`${id}-${i}`}
          className={`ref${active === id ? " on" : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => show({ kind, id } as DrawerView)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") show({ kind, id } as DrawerView); }}
        >
          {citer.num(id)}
        </span>
      ))}
    </>
  );
}

// ── evidence text hygiene: raw scraped quotes carry markdown, nav boilerplate, inline URLs ──
function clean(s?: string): string {
  return (s || "")
    .replace(/\r/g, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")            // images
    .replace(/\[([^\]]+)\]\((?:[^)]*)\)/g, "$1")      // md links → text
    .replace(/`{1,3}/g, "")                            // code ticks
    .replace(/^[ \t]*#{1,6}[ \t]*/gm, "")             // ### headings
    .replace(/[*_]{1,3}(\S)/g, "$1").replace(/(\S)[*_]{1,3}/g, "$1")  // bold/italic
    .replace(/^[ \t>*\-•‣·★☆▪◦]+/gm, "")              // leading bullets / stars / quote marks
    .replace(/\s*\n[ \t.]*\n\s*/g, " — ")             // paragraph breaks → em separator
    .replace(/\s*\n\s*/g, " ")                         // stray newlines → space
    .replace(/\s*\.\.\.+\s*/g, " … ")                 // ... → ellipsis
    .replace(/https?:\/\/\S+/g, "")                   // bare URLs
    .replace(/\s+([.,;:])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .replace(/^[\s—…·-]+/, "")
    .trim();
}
const excerpt = (s?: string, max = 190) => { const c = clean(s); return c.length > max ? c.slice(0, max).replace(/\s+\S*$/, "") + "…" : c; };
function titleClean(t?: string): string {
  let s = clean(t);
  if (s && s === s.toLowerCase()) s = s.replace(/\b([a-z])/g, (m) => m.toUpperCase());  // all-lowercase names → Title Case
  return s;
}
function domainOf(url?: string): string {
  try { return new URL(url || "").hostname.replace(/^www\./, ""); } catch { return ""; }
}
// The honest tier: coverage / sentiment / press is SIGNAL regardless of the coarse `register` field.
function tierOf(e: Evidence): { rank: number; label: string; c: string } {
  const k = e.evidence_kind || "", rel = e.relation || "", reg = e.register || "";
  if (e.signal_only || k === "coverage" || k === "sentiment" || rel === "signal" || reg === "observed" || reg === "coverage")
    return { rank: 2, label: "Signal · coverage", c: "var(--signal)" };
  if (reg === "filed") return { rank: 0, label: "Filed · fact", c: "var(--fact)" };
  if (reg === "stated") return { rank: 1, label: "Stated · intent", c: "var(--intent)" };
  return { rank: 3, label: reg || "source", c: "var(--muted)" };
}

const TIER_ORDER: { key: string; label: string }[] = [
  { key: "0", label: "Fact" }, { key: "1", label: "Intent" }, { key: "2", label: "Signal" },
];

// Low-relevance heuristic: a signal-tier source whose stored excerpt is nav/marketing boilerplate
// (a span-check artifact, not a claim about the thesis) — e.g. a careers/salary directory. These are
// pruned from the default view (a span existed, but it supports nothing) and revealable on demand.
const BOILER = /(boost your|deep belief|learning resources|educational journey|trusted companion|sign ?up|subscribe|newsletter|cookie|privacy policy|all rights reserved|terms of (service|use)|log ?in|create an account|browse (jobs|courses|programs)|salary guide|find the (best|right)|©)/i;
function weakSignal(rank: number, body: string): boolean {
  if (rank < 2) return false;                 // only signal-tier can be pruned; fact/intent always shown
  if (clean(body).length < 45) return true;   // no substantive excerpt
  return BOILER.test(body);
}

// The evidence overview: every source cleaned + ranked (cited-in-memo first, then by authority tier —
// fact → intent → signal), searchable, each row clickable to trace it. Tier chips double as filters.
function EvidenceOverview() {
  const { evidenceById, citer, show } = useBrief();
  const [qy, setQy] = useState("");
  const [tier, setTier] = useState<string>("");
  const [showWeak, setShowWeak] = useState(false);
  const all = useMemo(() => [...evidenceById.values()].map((e, i) => {
    const t = tierOf(e); const body = excerpt(e.quote);
    return { e, i, t, title: titleClean(e.title), body, dom: domainOf(e.source_url), weak: weakSignal(t.rank, e.quote || "") };
  }), [evidenceById]);
  const total = all.length;
  const weakCount = all.filter((r) => r.weak).length;

  const counts = new Map<string, number>();
  all.forEach(({ t }) => counts.set(String(t.rank), (counts.get(String(t.rank)) || 0) + 1));

  const q = qy.trim().toLowerCase();
  const rows = all
    .map((r) => ({ ...r, cite: citer.peek(r.e.id) }))
    .filter((r) => showWeak || q || r.cite != null || !r.weak)   // hide low-relevance by default (unless searching / cited)
    .filter((r) => !tier || String(r.t.rank) === tier)
    .filter((r) => !q || `${r.title} ${r.body} ${r.e.source_subject || ""} ${r.dom}`.toLowerCase().includes(q))
    .sort((a, b) => {
      if ((a.cite != null) !== (b.cite != null)) return a.cite != null ? -1 : 1;   // cited first
      if (a.cite != null && b.cite != null) return a.cite - b.cite;                 // then memo order
      if (a.weak !== b.weak) return a.weak ? 1 : -1;                                 // substantive before weak
      if (a.t.rank !== b.t.rank) return a.t.rank - b.t.rank;                         // then fact→intent→signal
      return a.i - b.i;                                                              // then retrieval order
    });

  const relevant = total - weakCount;
  return (
    <>
      <div className="rail-head"><span className="kick" style={{ color: "var(--muted)" }}>Evidence · {relevant} sources</span></div>
      <div className="rail-body">
        <div className="discipline">
          Typed by tier — <b>fact</b> (filings), <b>intent</b> (stated plans), <b>signal</b> (press / sentiment, never counted as fact).
          Cited sources rank first; click any row (or a <span className="ref" style={{ position: "static" }}>n</span> in the memo) to trace it.
        </div>
        <input className="ev-search" placeholder={`Search ${total} sources — text, company, site…`} value={qy} onChange={(e) => setQy(e.target.value)} />
        <div className="ev-chips">
          <button className={`ev-chip${tier === "" ? " on" : ""}`} onClick={() => setTier("")}>All <b>{showWeak ? total : relevant}</b></button>
          {TIER_ORDER.filter((t) => counts.get(t.key)).map((t) => {
            const c = t.key === "0" ? "var(--fact)" : t.key === "1" ? "var(--intent)" : "var(--signal)";
            return <button key={t.key} className={`ev-chip${tier === t.key ? " on" : ""}`} style={{ ["--tc" as string]: c }} onClick={() => setTier(tier === t.key ? "" : t.key)}>
              <span className="d" style={{ background: c }} /> {t.label} <b>{counts.get(t.key)}</b></button>;
          })}
        </div>
        <div className="ev-list">
          {rows.length === 0 ? <p className="muted" style={{ fontSize: ".85rem" }}>No sources match “{qy}”.</p>
            : rows.map(({ e, t, title, body, dom, cite, weak }) => (
              <button key={e.id} className={`ev-row${weak ? " ev-weak" : ""}`} style={{ ["--tc" as string]: t.c }} onClick={() => show({ kind: "evidence", id: e.id })}>
                <span className="ev-num">{cite != null ? cite : "·"}</span>
                <span className="ev-main">
                  {title ? <span className="ev-title">{title}</span> : null}
                  {body ? <span className="ev-snip">{body}</span> : <span className="ev-snip muted">{title ? "" : "(no excerpt — open to view source)"}</span>}
                  <span className="ev-meta">
                    <span className="ev-tier" style={{ color: t.c }}><span className="d" style={{ background: t.c }} /> {t.label}</span>
                    {weak ? <> · <span className="ev-lowrel">low relevance</span></> : null}
                    {dom ? <> · {dom}</> : null}
                    {e.side === "for" || e.side === "against" ? <> · <span className={e.side === "against" ? "ev-against" : "ev-for"}>{e.side}</span></> : null}
                    {e.as_of ? <> · {e.as_of.slice(0, 10)}</> : null}
                  </span>
                </span>
              </button>
            ))}
        </div>
        {weakCount > 0 && !qy ? (
          <button className="ev-toggle" onClick={() => setShowWeak((s) => !s)}>
            {showWeak ? `Hide ${weakCount} low-relevance signal source${weakCount === 1 ? "" : "s"}` : `Show ${weakCount} low-relevance signal source${weakCount === 1 ? "" : "s"} (boilerplate / off-topic)`}
          </button>
        ) : null}
      </div>
    </>
  );
}

// ── the evidence drawer ─────────────────────────────────────────────────────────
function Drawer({ view }: { view: DrawerView }) {
  const { evidenceById, findingById, show } = useBrief();
  if (view.kind === "overview") return <EvidenceOverview />;
  if (view.kind === "finding") {
    const q = findingById.get(view.id);
    return (
      <>
        <div className="rail-head">
          <span className="kick" style={{ color: "var(--muted)" }}>Finding</span>
          <button className="rail-back" onClick={() => show({ kind: "overview" })}>‹ Evidence</button>
        </div>
        <div className="rail-body">
          {!q ? <p className="muted">This finding is not in the published snapshot.</p> : (
            <>
              <div className="src-meta" style={{ marginBottom: ".5rem" }}>
                <div><b>{q.inquiry_name || "Line of inquiry"}</b></div>
                <div>{(q.target_status || "").replace(/_/g, " ")}</div>
              </div>
              <div className="src-quote" style={{ ["--sc" as string]: "var(--gold)" }}>Q: {q.text}</div>
              <div className="loi-a">{parse({ text: q.answer }).clean || "—"}</div>
            </>
          )}
        </div>
      </>
    );
  }
  // evidence
  const e = evidenceById.get(view.id);
  const t = e ? tierOf(e) : { rank: 3, label: "source", c: "var(--muted)" };
  const body = clean(e?.quote);
  return (
    <>
      <div className="rail-head">
        <span className="kick" style={{ color: "var(--muted)" }}>Source</span>
        <button className="rail-back" onClick={() => show({ kind: "overview" })}>‹ Evidence</button>
      </div>
      <div className="rail-body">
        {!e ? <p className="muted">Source not in the snapshot.</p> : (
          <>
            <span className="reg"><span className="d" style={{ background: t.c }} /> {t.label}</span>
            {titleClean(e.title) ? <div className="src-title">{titleClean(e.title)}</div> : null}
            {body ? <div className="src-quote" style={{ ["--sc" as string]: t.c }}>“{body}”</div> : <p className="muted" style={{ fontSize: ".85rem" }}>No verbatim excerpt was stored for this source.</p>}
            <div className="src-meta">
              {e.said_by ? <div>said by <b>{e.said_by}</b>{e.said_role ? ` · ${e.said_role}` : ""}</div> : null}
              {e.source_subject ? <div>subject: <b>{e.source_subject}</b></div> : null}
              {e.evidence_kind ? <div>kind: {e.evidence_kind}{e.relation ? ` · ${e.relation.replace(/_/g, " ")}` : ""}</div> : null}
              {e.side === "for" || e.side === "against" ? <div>weighs <b className={e.side === "against" ? "ev-against" : "ev-for"}>{e.side}</b> the thesis</div> : null}
              {e.as_of || e.period ? <div>as of {(e.as_of || e.period || "").slice(0, 10)}</div> : null}
              {e.source_url ? <div>{domainOf(e.source_url)} · <a href={e.source_url} target="_blank" rel="noopener">open source ↗</a></div> : null}
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ── tab renderers ────────────────────────────────────────────────────────────────
const KIND_LABEL: Record<string, string> = { tension: "Tension", gap: "Gap", assumption: "Assumption", implication: "Implication", what_would_change_this: "What would change this" };
function TakeTab({ take }: { take?: Take }) {
  const secs = (take?.sections || []).filter((s) => (s.grounded?.length || s.analysis?.length));
  if (!secs.length) return <p className="muted">No collective take yet.</p>;
  return (
    <div className="card">
      {secs.map((s) => {
        const gr = (s.grounded || []).filter((g) => (g.text || "").trim());
        const an = (s.analysis || []).filter((a) => (a.text || "").trim());
        if (!gr.length && !an.length) return null;
        return (
          <div key={s.key} className="th-synth-sec">
            <h4 className="th-synth-h">{s.title || s.key}</h4>
            {gr.length ? <div className="th-memo-grounded">{gr.map((g, i) => <p key={i}><Cite value={g} kind="finding" /></p>)}</div> : null}
            {an.length ? <div className="th-reasons">{an.map((a: Analysis, i) => (
              <div key={i} className={`th-reason th-reason-${a.kind}`}>
                <span className="th-reason-tag">{KIND_LABEL[a.kind] || a.kind}</span>
                <span className="th-reason-text"><Cite value={a} kind="finding" /></span>
              </div>
            ))}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

// ── Reasoning Map: faithful lanes → SVG confluence → the read (ported from the classic client) ──
const RMAP_LANES = [
  { kind: "assumption", title: "What must be true", hint: "the load-bearing premises", color: "#6b5bd0" },
  { kind: "tension", title: "Tensions", hint: "findings that pull apart", color: "#c0563f" },
  { kind: "gap", title: "Gaps", hint: "what the record can't settle", color: "#b8860b" },
  { kind: "implication", title: "What it implies", hint: "the second-order read", color: "#2e8b6f" },
];
const RMAP_CHANGE = { kind: "what_would_change_this", title: "What would change the read", hint: "the highest-value next evidence", color: "#3a7bd0" };

function drawConfluence(root: HTMLElement) {
  const svg = root.querySelector<SVGSVGElement>(".th-rmap-links");
  const lanesWrap = root.querySelector(".th-rmap-lanes");
  const read = root.querySelector(".th-rmap-read");
  if (!svg || !lanesWrap) return;
  const rb = root.getBoundingClientRect();
  if (rb.width < 40 || root.offsetParent === null) { svg.innerHTML = ""; return; }
  svg.setAttribute("width", String(rb.width)); svg.setAttribute("height", String(rb.height));
  svg.setAttribute("viewBox", `0 0 ${rb.width} ${rb.height}`);
  const lanes = Array.from(lanesWrap.querySelectorAll(".th-rmap-lane"));
  if (!lanes.length || !read) { svg.innerHTML = ""; return; }
  const rr = read.getBoundingClientRect();
  const tx = rr.left + rr.width / 2 - rb.left, ty = rr.top - rb.top;
  const gold = (getComputedStyle(document.documentElement).getPropertyValue("--gold") || "#8A6A1F").trim();
  let out = "";
  lanes.forEach((l) => {
    const lr = l.getBoundingClientRect();
    const sx = lr.left + lr.width / 2 - rb.left, sy = lr.bottom - rb.top;
    const col = (getComputedStyle(l as Element).getPropertyValue("--rc") || "#888").trim();
    const my = (sy + ty) / 2;
    out += `<path d="M ${sx} ${sy} C ${sx} ${my} ${tx} ${my} ${tx} ${ty - 1}" fill="none" stroke="${col}" stroke-width="2" stroke-linecap="round" opacity="0.5"/><circle cx="${sx}" cy="${sy}" r="3" fill="${col}"/>`;
  });
  out += `<path d="M ${tx - 5} ${ty - 8} L ${tx} ${ty - 1} L ${tx + 5} ${ty - 8}" fill="none" stroke="${gold}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
  svg.innerHTML = out;
}

function ReasonTab({ take, lean }: { take?: Take; lean?: { t: string; d: string; c: string } | null }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const by = new Map<string, Analysis[]>();
  (take?.sections || []).forEach((s) => (s.analysis || []).forEach((a) => {
    if (!(a.text || "").trim()) return; const k = a.kind || ""; by.set(k, [...(by.get(k) || []), a]);
  }));
  const lanes = RMAP_LANES.filter((l) => by.get(l.kind)?.length);
  const bl = take?.bottom_line || {};
  const hasRead = !!(bl.text || "").trim();
  const change = by.get(RMAP_CHANGE.kind) || [];
  let grounded = 0, lines = 0;
  (take?.sections || []).forEach((s) => { const g = (s.grounded || []).filter((x) => (x.text || "").trim()).length; grounded += g; if (g) lines++; });

  useEffect(() => {
    const root = rootRef.current; if (!root) return;
    const draw = () => drawConfluence(root);
    const r1 = requestAnimationFrame(() => requestAnimationFrame(draw));
    const ro = new ResizeObserver(draw); ro.observe(root);
    return () => { cancelAnimationFrame(r1); ro.disconnect(); };
  });

  if (!lanes.length && !hasRead) return <p className="muted">No reasoning blocks yet — run the research first.</p>;
  const laneEl = (l: typeof RMAP_LANES[number], blocks: Analysis[], extra = "") => (
    <div className={`th-rmap-lane ${extra}`} style={{ ["--rc" as string]: l.color }}>
      <div className="th-rmap-lane-h"><span className="th-rmap-chip" style={{ background: l.color }}>{l.title}</span><span className="th-rmap-hint">{l.hint}</span></div>
      <div className="th-rmap-cards">{blocks.map((a, i) => (
        <div key={i} className="th-rmap-card" style={{ ["--rc" as string]: l.color }}>
          <span className="th-rmap-dot" style={{ background: l.color }} /><span className="th-rmap-ctext"><Cite value={a} kind="finding" /></span>
        </div>
      ))}</div>
    </div>
  );
  return (
    <div className="th-rmap" ref={rootRef}>
      {(grounded || lean) ? (
        <div className="th-rmap-top">
          {grounded ? <div className="th-rmap-base">Grounded in <b>{grounded}</b> cited {grounded === 1 ? "fact" : "facts"} across <b>{lines}</b> line{lines === 1 ? "" : "s"} of inquiry</div> : null}
          {lean ? <span className="th-rmap-lean" style={{ ["--lc" as string]: lean.c }}>{lean.t} <span>· {lean.d}</span></span> : null}
        </div>
      ) : null}
      <div className="th-rmap-lanes">{lanes.map((l) => <div key={l.kind} style={{ display: "contents" }}>{laneEl(l, by.get(l.kind) || [])}</div>)}</div>
      <svg className="th-rmap-links" aria-hidden="true" />
      {hasRead ? <div className="th-rmap-read"><div className="th-rmap-read-h">The read — where it converges</div><div className="th-rmap-read-text"><Cite value={bl} kind="finding" /></div></div> : null}
      {change.length ? <div className="th-rmap-changewrap">{laneEl(RMAP_CHANGE, change, "th-rmap-change")}</div> : null}
      <div className="th-rmap-foot">A reading of the evidence, not investment advice — the human owns the decision.</div>
    </div>
  );
}
function LinesTab({ inquiries }: { inquiries?: InquiriesView["inquiries"] }) {
  const verdict = (asp?: { verdict?: string }[]) => {
    const vs = (asp || []).map((a) => a.verdict);
    if (vs.includes("contradicted")) return { l: "Contradicted", cls: "v-con" };
    if (vs.length && vs.every((v) => v === "supported")) return { l: "Supported", cls: "v-sup" };
    if (vs.includes("supported")) return { l: "Mixed", cls: "v-sup" };
    return { l: "Open", cls: "v-open" };
  };
  const lines = (inquiries || []);
  if (!lines.length) return <p className="muted">No lines of inquiry yet.</p>;
  return (
    <div className="card">
      {lines.map((l) => {
        const answered = (l.questions || []).filter((q) => q.target_status && (q.answer || "").trim());
        const v = verdict(l.aspects);
        return (
          <div key={l.key} className="loi">
            <div className="loi-h"><span className={`v ${v.cls}`}>{v.l}</span>{l.name}</div>
            {answered.map((q) => (
              <div key={q.id} className="loi-a">
                <span className="qq">Q: {q.text} — </span><Cite value={{ text: q.answer }} kind="evidence" />
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
const truncate = (t?: string, max = 130) => { const s = (t || "").trim(); return s.length > max ? s.slice(0, max).replace(/\s+\S*$/, "") + "…" : s; };
function CompCard({ p, cols }: { p: CompPlayer; cols: { key: string; label: string }[] }) {
  const cell = (k: string) => p.cells?.[k];
  const has = (k: string) => { const c = cell(k); return !!(c && (c.text || "").trim()); };
  const labelOf = (k: string) => cols.find((c) => c.key === k)?.label || k;
  const src = (k: string) => { const c = cell(k); return c?.source_url ? <a className="th-comp-src" href={c.source_url} target="_blank" rel="noopener" title={c.source_title || "source"}>↗</a> : null; };
  const val = (k: string, max: number) => <span title={(cell(k)?.text || "").trim()}>{truncate(cell(k)?.text, max)} {src(k)}</span>;
  const statKeys = ["funding", "customers", "investors", "traction"].filter(has);
  const narr = cols.map((c) => c.key).filter((k) => k !== "central_idea" && !statKeys.includes(k) && has(k));
  const empty = !has("central_idea") && !statKeys.length && !narr.length;
  return (
    <div className="th-comp-card">
      <h5 className="th-comp-name">{p.name}{p.is_subject ? <span className="th-comp-you">thesis</span> : null}</h5>
      {empty ? <div className="th-cell-empty">Not found in the open record.</div> : (
        <>
          {has("central_idea") ? <div className="th-comp-lead">{val("central_idea", 150)}</div> : null}
          {statKeys.length ? <div className="th-comp-stats">{statKeys.map((k) => <span key={k} className="th-comp-stat"><span className="th-comp-stat-k">{labelOf(k)}</span>{val(k, 44)}</span>)}</div> : null}
          {narr.length ? <div className="th-comp-dims">{narr.map((k) => <div key={k} className="th-comp-dim"><span className="th-comp-dk">{labelOf(k)}</span>{val(k, 130)}</div>)}</div> : null}
        </>
      )}
    </div>
  );
}

function CompTab({ comp, id, owner, onDone }: { comp?: Competitive; id?: string; owner?: boolean; onDone?: () => void }) {
  const cols = comp?.columns || []; const players = comp?.players || [];
  const [busy, setBusy] = useState(false); const [err, setErr] = useState(""); const [note, setNote] = useState("");
  const timer = useRef<number | null>(null);
  const empty = !players.length;
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  function poll(runId: string) {
    if (!id) return;
    api.inquiryStatus(id, runId).then((s) => {
      if (s.state === "completed") { setBusy(false); setNote(""); onDone?.(); return; }
      if (s.state === "failed") { setBusy(false); setErr("the research run failed"); return; }
      setNote(s.total ? `researching the market… ${s.done || 0}/${s.total}` : "researching the market…");
      timer.current = window.setTimeout(() => poll(runId), 2500);
    }).catch(() => { timer.current = window.setTimeout(() => poll(runId), 3000); });
  }
  async function research() {
    if (!id) return; setErr("");
    try {
      const proj = await api.competitiveResearch(id, 0);
      const max = Number(proj.projection?.projected_usd || 0);
      if (!window.confirm(`Research the competitive landscape from the open web — profile the players across funding, customers, moats, tech edge and differentiation?\n\nProjected maximum: $${max.toFixed(3)}`)) return;
      setBusy(true); setNote("starting…");
      const r = await api.competitiveResearch(id, Math.max(max, 0.01));
      if (!r.run?.id) throw new Error(r.status === "refused" ? "cost exceeded the budget" : "could not start research");
      poll(r.run.id);
    } catch (e) { setBusy(false); setErr((e as Error).message); }
  }

  return (
    <div className="card">
      {comp?.space ? <div className="th-comp-cap">The market — {comp.space}</div> : null}
      {empty ? <p className="muted" style={{ fontSize: ".9rem" }}>No competitive landscape yet.{owner ? " Research it from the open web below." : ""}</p> : (
        <>
          <div className="th-comp-cards">{players.map((p, i) => <CompCard key={i} p={p} cols={cols} />)}</div>
          <details className="th-comp-tablewrap" open><summary>At-a-glance comparison</summary>
            <div className="tablewrap"><table>
              <thead><tr><th>Player</th>{cols.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
              <tbody>{players.map((p, i) => (
                <tr key={i}><th scope="row">{p.name}</th>{cols.map((c) => { const t = (p.cells?.[c.key]?.text || "").trim(); return <td key={c.key}>{t || <span className="th-cell-empty">—</span>}</td>; })}</tr>
              ))}</tbody>
            </table></div>
          </details>
          <div className="muted" style={{ fontSize: ".74rem", marginTop: ".5rem", fontFamily: "var(--mono)" }}>Open-web market intelligence (stated/reported) — verify funding &amp; traction against a primary source.</div>
        </>
      )}
      {owner && id ? <div className="th-comp-addbar"><button className="btn sec" disabled={busy} onClick={research}>{busy ? (note || "Researching…") : (empty ? "Research competitive landscape" : "Re-research landscape")}</button></div> : null}
      {err ? <p style={{ color: "var(--p0)", fontSize: ".85rem", marginTop: ".5rem" }}>{err}</p> : null}
    </div>
  );
}
function DeckTab({ deck }: { deck?: Deck }) {
  const spine = deck?.spine;
  const secs = (deck?.sections || []);
  if (!spine && !secs.length) return <p className="muted">No pitch deck yet.</p>;
  return (
    <>
      {spine && (parse(spine.one_liner).clean || parse(spine.insight).clean) ? (
        <div className="spine">
          <span className="kick">Founder pitch · the spine</span>
          <p className="one" style={{ margin: ".3rem 0 0" }}><Cite value={spine.one_liner} kind="finding" /></p>
          {parse(spine.insight).clean ? <><div className="lab">The insight</div><p style={{ margin: ".15rem 0 0", fontSize: ".92rem" }}><Cite value={spine.insight} kind="finding" /></p></> : null}
        </div>
      ) : null}
      <div className="card">
        {secs.map((s) => {
          const points = (s.points || []);
          const head = parse(s.headline).clean;
          if (!points.length && !head && !s.prose) return null;
          return (
            <div key={s.key} className="slide">
              <h4>{s.title}</h4>
              {head ? <p style={{ fontWeight: 600, margin: 0 }}><Cite value={s.headline} kind="finding" /></p> : null}
              {points.length ? <ul>{points.map((p, i) => <li key={i}><Cite value={p} kind="finding" /></li>)}</ul>
                : s.prose && !/^not established/i.test(s.prose) ? <p style={{ margin: ".25rem 0 0", fontSize: ".88rem" }}><Cite value={{ text: s.prose }} kind="finding" /></p> : null}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ── the Brief ─────────────────────────────────────────────────────────────────
type Tab = "take" | "reason" | "lines" | "comp" | "deck";
const TABS: [Tab, string][] = [["take", "The read"], ["reason", "Reasoning map"], ["lines", "Lines of inquiry"], ["comp", "Competitive"], ["deck", "Pitch deck"]];

export function Brief({ doc, inq, anonymous, id, owner, onRefetchInq }: {
  doc: ThesisDoc; inq: InquiriesView; anonymous?: boolean; id?: string; owner?: boolean; onRefetchInq?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("take");
  const [view, setView] = useState<DrawerView>({ kind: "overview" });
  const citer = useMemo(() => new Citer(), [doc, inq]);

  const evidenceById = useMemo(() => {
    const m = new Map<string, Evidence>();
    (doc.claims || []).forEach((c) => (c.evidence || []).forEach((e) => { if (e.id) m.set(e.id, e); }));
    return m;
  }, [doc]);
  const findingById = useMemo(() => {
    const m = new Map<string, Question>();
    (inq.inquiries || []).forEach((i) => (i.questions || []).forEach((q) => { if (q.id) m.set(q.id, q); }));
    return m;
  }, [inq]);

  const take = inq.take || doc.collective_take;
  const deck = inq.deck || doc.pitch_deck;
  const comp = inq.competitive || doc.competitive;
  const bl = take?.bottom_line;
  const active = view.kind === "overview" ? null : view.id;

  const lean = useMemo(() => {
    const inqs = (inq.inquiries || []).filter((i) => (i.aspects || []).length);
    if (!inqs.length) return null;
    const rolls = inqs.map((i) => {
      const vs = (i.aspects || []).map((a) => a.verdict);
      if (vs.includes("contradicted")) return "contradicted";
      if (vs.length && vs.every((v) => v === "supported")) return "supported";
      return "open";
    });
    if (rolls.includes("contradicted")) return { t: "Leans PASS", d: "contradicted on ≥1 aspect", c: "#c0392b" };
    if (rolls.every((v) => v === "supported")) return { t: "Leans FUND", d: "supported across every line", c: "#2e7d5b" };
    return { t: "CONTINUE diligence", d: "mixed / still under-tested", c: "#b5762a" };
  }, [inq]);

  const ctx: Ctx = { citer, evidenceById, findingById, show: setView, active };

  return (
    <BriefCtx.Provider value={ctx}>
      <div className="briefgrid">
        <div className="memo">
          <div className="mono muted" style={{ fontSize: ".7rem", marginBottom: ".3rem" }}>
            Thesis under test{anonymous ? " · anonymized board view" : ""}
          </div>
          <h1 className="memo-thesis">{doc.thesis}</h1>
          {parse(bl).clean ? (
            <div className="card read"><div className="kick">The read</div><p><Cite value={bl} kind="finding" /></p></div>
          ) : null}
          <div className="tabs">
            {TABS.map(([t, label]) => (
              <button key={t} className={`tab${t === tab ? " on" : ""}`} onClick={() => setTab(t)}>{label}</button>
            ))}
          </div>
          {tab === "take" ? <TakeTab take={take} />
            : tab === "reason" ? <ReasonTab take={take} lean={lean} />
              : tab === "lines" ? <LinesTab inquiries={inq.inquiries} />
                : tab === "comp" ? <CompTab comp={comp} id={id} owner={owner} onDone={onRefetchInq} />
                  : <DeckTab deck={deck} />}
        </div>
        <aside className="rail"><Drawer view={view} /></aside>
      </div>
    </BriefCtx.Provider>
  );
}
