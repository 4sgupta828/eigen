import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode, type CSSProperties } from "react";
import { api } from "./api";
import type {
  Analysis, Cited, Competitive, CompCandidate, CompPlayer, Deck, Evidence, InquiriesView, Question, Take, ThesisDoc,
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
// Stray finding-tokens the synthesis model sometimes inlines in prose (e.g. "[F1, F2, F3]"): a bracket
// group of only F-numbers/commas/spaces. Citations render as footnotes, so these raw tokens are noise.
const FTOK = /\s*\[[\sFf0-9,;]*?[Ff]\d+[\sFf0-9,;]*?\]/g;
const stripFTokens = (s: string) => s.replace(FTOK, "");
function parse(value?: Cited): { clean: string; ids: string[] } {
  const raw = `${value?.text || ""} ${value?.markers || ""}`;
  const ids: string[] = [];
  const clean = stripFTokens(raw.replace(MARK, (_m, id: string) => { ids.push(id); return ""; }))
    .replace(/\s+([.,;:])/g, "$1").replace(/\s{2,}/g, " ").trim();
  return { clean, ids };
}

// ── drawer state ───────────────────────────────────────────────────────────────
type DrawerView = { kind: "overview" } | { kind: "finding"; id: string } | { kind: "evidence"; id: string };
type Hover = { meta?: string; quote?: string; src?: string; rect: DOMRect } | null;
type Ctx = {
  citer: Citer;
  evidenceById: Map<string, Evidence>;
  findingById: Map<string, Question>;
  show: (v: DrawerView) => void;
  active: string | null;
  setHover: (h: Hover) => void;
};
const BriefCtx = createContext<Ctx | null>(null);
const useBrief = () => {
  const c = useContext(BriefCtx);
  if (!c) throw new Error("Brief context missing");
  return c;
};

// ── a cited run of text: renders clean text + clickable [n] refs (hover to preview) ────────────────
function Cite({ value, kind }: { value?: Cited; kind: "finding" | "evidence" }) {
  const { citer, show, active, evidenceById, findingById, setHover } = useBrief();
  const { clean, ids } = parse(value);
  if (!clean && !ids.length) return null;
  const payload = (id: string, rect: DOMRect): Hover => {
    if (kind === "evidence") {
      const e = evidenceById.get(id); if (!e) return null; const t = tierOf(e);
      return { meta: [t.label, domainOf(e.source_url)].filter(Boolean).join(" · "), quote: cleanText(e.quote).slice(0, 300), src: titleClean(e.title), rect };
    }
    const q = findingById.get(id); if (!q) return null;
    return { meta: q.inquiry_name || "Finding", quote: q.text, rect };
  };
  const enter = (id: string, el: HTMLElement) => setHover(payload(id, el.getBoundingClientRect()));
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
          onMouseEnter={(e) => enter(id, e.currentTarget)}
          onMouseLeave={() => setHover(null)}
          onFocus={(e) => enter(id, e.currentTarget)}
          onBlur={() => setHover(null)}
        >
          {citer.num(id)}
        </span>
      ))}
    </>
  );
}

// ── the floating citation preview card (styled hover, replaces the native title tooltip) ──
function CiteHover({ hover }: { hover: Hover }) {
  if (!hover) return null;
  const { rect } = hover;
  const below = rect.top < 180;
  const style: CSSProperties = {
    position: "fixed",
    left: Math.min(Math.max(rect.left + rect.width / 2, 160), (typeof window !== "undefined" ? window.innerWidth : 1000) - 160),
    top: below ? rect.bottom + 8 : rect.top - 8,
    transform: below ? "translate(-50%, 0)" : "translate(-50%, -100%)",
  };
  return (
    <div className="citehover" style={style} role="tooltip">
      {hover.meta ? <div className="ch-meta">{hover.meta}</div> : null}
      {hover.quote ? <blockquote className="ch-quote">“{hover.quote}”</blockquote> : null}
      {hover.src ? <div className="ch-src">{hover.src}</div> : null}
    </div>
  );
}

// ── evidence text hygiene: raw scraped quotes carry markdown, nav boilerplate, inline URLs ──
function cleanText(s?: string): string {
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
const excerpt = (s?: string, max = 190) => { const c = cleanText(s); return c.length > max ? c.slice(0, max).replace(/\s+\S*$/, "") + "…" : c; };
function titleClean(t?: string): string {
  let s = cleanText(t);
  if (s && s === s.toLowerCase()) s = s.replace(/\b([a-z])/g, (m) => m.toUpperCase());  // all-lowercase names → Title Case
  return s;
}
function domainOf(url?: string): string {
  try { return new URL(url || "").hostname.replace(/^www\./, ""); } catch { return ""; }
}
// A source reference for a piece of evidence: a link for web/URL sources, else a labeled reference for
// corpus/internal sources (which carry a source_key like "sec"/"arxiv" but no URL) — never a dead end.
const sourceLabel = (e: Evidence) => e.source_key || e.evidence_kind || (e.document_id ? "corpus" : "source");
function SourceRef({ e }: { e: Evidence }) {
  if (e.source_url) return <a className="th-cite-src" href={e.source_url} target="_blank" rel="noopener" onClick={(ev) => ev.stopPropagation()}>{domainOf(e.source_url) || e.source_key || "source"} ↗</a>;
  return <span className="th-cite-src th-cite-src-corpus">{sourceLabel(e)}</span>;
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
  if (cleanText(body).length < 45) return true;   // no substantive excerpt
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
              {q.answer ? <GroundedAnswer q={q} /> : <div className="loi-a">—</div>}
            </>
          )}
        </div>
      </>
    );
  }
  // evidence
  const e = evidenceById.get(view.id);
  const t = e ? tierOf(e) : { rank: 3, label: "source", c: "var(--muted)" };
  const body = cleanText(e?.quote);
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
              {e.source_url ? <div>{domainOf(e.source_url)} · <a href={e.source_url} target="_blank" rel="noopener">open source ↗</a></div>
                : <div>source: {sourceLabel(e)}{e.title && titleClean(e.title) !== sourceLabel(e) ? ` · ${titleClean(e.title)}` : ""}</div>}
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
// ── Lines of inquiry: an investigation AREA (purpose) → sub-dimensions → research questions ──
const LENS: Record<string, { label: string; glyph: string }> = {
  seek_support: { label: "Seeks support", glyph: "＋" },
  seek_contradiction: { label: "Seeks disconfirmation", glyph: "－" },
  seek_disconfirmation: { label: "Seeks disconfirmation", glyph: "－" },
  seek_disconfirm: { label: "Seeks disconfirmation", glyph: "－" },
  challenge_assumption: { label: "Challenges assumption", glyph: "◇" },
  test_assumption: { label: "Tests assumption", glyph: "◇" },
  probe: { label: "Probe", glyph: "◦" },
};
const VERDICT: Record<string, { l: string; cls: string }> = {
  supported: { l: "Supported", cls: "v-sup" },
  contradicted: { l: "Contradicted", cls: "v-con" },
  under_tested: { l: "Under-tested", cls: "v-mix" },
  mixed: { l: "Mixed", cls: "v-mix" },
  open: { l: "Open", cls: "v-open" },
};
const verdictOf = (v?: string) => VERDICT[v || "open"] || VERDICT.open;
const capitalize = (s?: string) => { const t = (s || "").trim(); return t ? t.charAt(0).toUpperCase() + t.slice(1) : ""; };
const humanize = (s?: string) => capitalize((s || "").replace(/_/g, " "));
function rollup(aspects?: { verdict?: string }[]) {
  const vs = (aspects || []).map((a) => a.verdict);
  if (vs.includes("contradicted")) return "contradicted";
  if (vs.length && vs.every((v) => v === "supported")) return "supported";
  if (vs.includes("supported")) return "mixed";
  return "open";
}
const CITE_MARK = /\[\[e:([A-Za-z0-9_-]{1,80})\]\]|\*\*([^*]+)\*\*/g;
function makeAnswerRun(numById: Record<string, number>, onCite: (id: string) => void,
                       onHover: (id: string, el: HTMLElement) => void, onLeave: () => void) {
  return (text: string) => {
    const out: ReactNode[] = []; let last = 0, k = 0, m: RegExpExecArray | null;
    CITE_MARK.lastIndex = 0;
    while ((m = CITE_MARK.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1] != null) {
        const id = m[1], n = numById[id];
        if (n) out.push(<sup key={k++} className="th-ref2" role="button" tabIndex={0}
          onClick={() => onCite(id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onCite(id); }}
          onMouseEnter={(e) => onHover(id, e.currentTarget)} onMouseLeave={onLeave}
          onFocus={(e) => onHover(id, e.currentTarget)} onBlur={onLeave}>{n}</sup>);
      } else if (m[2] != null) { out.push(<strong key={k++}>{m[2]}</strong>); }
      last = CITE_MARK.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  };
}
function GroundedAnswer({ q }: { q: Question }) {
  const { evidenceById, citer, show, setHover } = useBrief();
  const prose = stripFTokens((q.answer || "").trim()).replace(/[([]\s*[)\]]/g, "").replace(/\s+([.,;])/g, "$1").replace(/[ \t]{2,}/g, " ").trim();
  const ids: string[] = []; const seen = new Set<string>();
  prose.replace(/\[\[e:([A-Za-z0-9_-]{1,80})\]\]/g, (_m, id: string) => { if (!seen.has(id)) { seen.add(id); ids.push(id); } return _m; });
  ids.forEach((id) => citer.num(id));   // register cited evidence so the Evidence overview ranks it first
  const numById: Record<string, number> = {};
  ids.forEach((id, i) => { numById[id] = i + 1; });
  const onHover = (id: string, el: HTMLElement) => {
    const e = evidenceById.get(id); if (!e) return; const t = tierOf(e);
    setHover({ meta: [t.label, domainOf(e.source_url)].filter(Boolean).join(" · "), quote: cleanText(e.quote).slice(0, 300), src: titleClean(e.title), rect: el.getBoundingClientRect() });
  };
  const run = makeAnswerRun(numById, (id) => show({ kind: "evidence", id }), onHover, () => setHover(null));
  const hasMarkers = ids.length > 0;
  if (!prose) return <div className="th-answer-note">Not yet established in the record.</div>;

  const cellSplit = (r: string) => r.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((c) => c.trim());
  const blocks = prose.split(/\n{2,}/).map((block, bi) => {
    const ls = block.split(/\n/).filter((l) => l.trim());
    if (ls.length >= 2 && /^\s*\|.*\|\s*$/.test(ls[0]) && /^\s*\|[\s:|-]+\|\s*$/.test(ls[1])) {
      const head = cellSplit(ls[0]); const rows = ls.slice(2).filter((l) => /^\s*\|.*\|\s*$/.test(l)).map(cellSplit);
      return (
        <div key={bi} className="tablewrap"><table className="th-atable">
          <thead><tr>{head.map((c, i) => <th key={i}>{run(c)}</th>)}</tr></thead>
          <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci}>{run(c)}</td>)}</tr>)}</tbody>
        </table></div>
      );
    }
    if (ls.every((l) => /^\s*-\s+/.test(l))) return <ul key={bi} className="th-answer-list">{ls.map((l, i) => <li key={i}>{run(l.replace(/^\s*-\s+/, ""))}</li>)}</ul>;
    return <p key={bi}>{run(ls.join(" "))}</p>;
  });
  const sources = ids.map((id) => evidenceById.get(id)).filter(Boolean) as Evidence[];
  return (
    <>
      <div className={hasMarkers ? "th-answer-body" : "th-answer-note"}>{blocks}</div>
      {sources.length ? (
        <details className="th-cites-wrap">
          <summary className="th-cites-sum"><span className="th-cites-badge">{sources.length}</span> {sources.length === 1 ? "source" : "sources"} for this answer</summary>
          <ol className="th-cites">{sources.map((e, i) => {
            const t = tierOf(e);
            const meta = [t.label, e.source_subject, e.evidence_kind, (e.as_of || e.period || "").slice(0, 10)].filter(Boolean).join(" · ");
            return (
              <li key={e.id} className="th-cite" onClick={() => show({ kind: "evidence", id: e.id })}>
                <span className="th-cite-n" style={{ color: t.c }}>{i + 1}</span>
                <div className="th-cite-body">
                  <div className="th-cite-meta"><span className="d" style={{ background: t.c }} /> {meta || "source"}</div>
                  {cleanText(e.quote) ? <blockquote className="th-cite-q">“{excerpt(e.quote, 300)}”</blockquote> : null}
                  <SourceRef e={e} />
                </div>
              </li>
            );
          })}</ol>
        </details>
      ) : null}
    </>
  );
}
function QuestionCard({ q, id, owner, onDone }: { q: Question; id?: string; owner?: boolean; onDone?: () => void }) {
  const lens = LENS[q.kind || ""] || { label: (q.kind || "").replace(/_/g, " "), glyph: "" };
  const pr = Number(q.priority == null ? 1 : q.priority);
  const prCls = pr <= 0 ? "p-0" : pr === 1 ? "p-1" : "p-2";
  const answered = !!q.target_status;
  const [busy, setBusy] = useState(false); const [note, setNote] = useState(""); const [err, setErr] = useState("");
  const timer = useRef<number | null>(null); const runId = useRef<string | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  function poll(rid: string) {
    if (!id) return;
    api.inquiryStatus(id, rid).then((s) => {
      if (s.state === "completed") { setBusy(false); setNote(""); runId.current = null; onDone?.(); return; }
      if (s.state === "cancelled") { setBusy(false); setNote(""); runId.current = null; onDone?.(); return; }
      if (s.state === "failed") { setBusy(false); runId.current = null; setErr("the run failed — try again"); return; }
      setNote("researching…");
      timer.current = window.setTimeout(() => poll(rid), 2500);
    }).catch(() => { timer.current = window.setTimeout(() => poll(rid), 3000); });
  }
  async function run() {
    if (!id || busy) return; setErr("");
    try {
      const proj = await api.runQuestion(id, q.id, 0);
      const max = Number(proj.projection?.projected_usd || 0);
      if (!window.confirm(`Research this question against the corpus and the open web?\n\nProjected maximum: $${max.toFixed(3)}`)) return;
      setBusy(true); setNote("starting…");
      const r = await api.runQuestion(id, q.id, Math.max(max, 0.01));
      if (r.status === "completed") { setBusy(false); onDone?.(); return; }
      if (!r.run?.id) throw new Error(r.status === "refused" ? "cost exceeded the budget" : "could not start the run");
      runId.current = r.run.id; poll(r.run.id);
    } catch (e) { setBusy(false); setErr((e as Error).message); }
  }
  async function stop() {
    if (!id) return; setNote("stopping…");
    try { await api.cancelRun(id, runId.current || undefined); } catch { /* poll will settle it */ }
  }

  return (
    <div className={`th-qn2${answered ? "" : " th-qn2-open"}`}>
      <div className="th-qn2-top">
        <span className={`prio ${prCls}`} title={pr <= 0 ? "P0 — critical crux" : pr === 1 ? "P1 — important" : "P2 — completeness"}>P{pr <= 0 ? 0 : pr}</span>
        <span className="th-lens2">{lens.glyph ? <span className="th-lens2-g">{lens.glyph}</span> : null}{lens.label}</span>
        {!answered && !(owner && id) ? <span className="th-qn2-pending">Not yet run</span> : null}
        {owner && id && busy ? <button className="th-qn2-stop" onClick={stop}>■ Stop</button> : null}
        {owner && id && !busy ? <button className="th-qn2-run" onClick={run} title={answered ? "Re-run this question" : "Run this question"}>{answered ? "↻ Re-run" : "▶ Run"}</button> : null}
      </div>
      <div className="th-qn2-q">{q.text}</div>
      {answered ? <GroundedAnswer q={q} /> : <div className="th-answer-note">{busy ? (note || "researching…") : "Not yet researched — run it to fill this gap."}</div>}
      {err ? <p style={{ color: "var(--p0)", fontSize: ".8rem", margin: ".35rem 0 0" }}>{err}</p> : null}
    </div>
  );
}
function LinesTab({ inquiries, id, owner, onDone }: { inquiries?: InquiriesView["inquiries"]; id?: string; owner?: boolean; onDone?: () => void }) {
  const lines = (inquiries || []).filter((l) => (l.questions || []).length);
  if (!lines.length) return <p className="muted">No lines of inquiry yet.</p>;
  return (
    <>
      <p className="th-inqs-intro"><b>{lines.length} investigation area{lines.length === 1 ? "" : "s"}</b> — each a purpose the thesis has to survive, opened into sub-dimensions and the questions that test them.</p>
      <div className="th-inqs">
        {lines.map((l, li) => {
          const qs = l.questions || [];
          const answered = qs.filter((q) => q.target_status).length;
          const v = verdictOf(rollup(l.aspects));
          // group questions by aspect (sub-dimension), preserving the declared order (then any orphans)
          const byAspect = new Map<string, Question[]>();
          qs.forEach((q) => { const k = q.aspect_key || "_"; byAspect.set(k, [...(byAspect.get(k) || []), q]); });
          const aspects = (l.aspects || []).filter((a) => byAspect.get(a.key)?.length);
          const orphans = qs.filter((q) => !aspects.some((a) => a.key === q.aspect_key));
          // The AREA is a purpose, not a question: lead with the framing; the name is the guiding question.
          const area = capitalize(l.framing) || l.name;
          return (
            <details key={l.key} className="th-inq2" open={answered > 0}>
              <summary className="th-inq2-head">
                <span className="th-inq2-num">{li + 1}</span>
                <div className="th-inq2-titlewrap">
                  <div className="th-inq2-kick">Investigation area</div>
                  <h3 className="th-inq2-name">{area}</h3>
                  {l.name && l.name !== area ? <p className="th-inq2-q">Guiding question — {l.name}</p> : null}
                </div>
                <span className="th-inq2-side">
                  <span className={`v ${v.cls}`}>{v.l}</span>
                  <span className="th-inq2-count">{answered}/{qs.length} tested</span>
                </span>
              </summary>
              <div className="th-inq2-body">
                {aspects.map((a) => {
                  const av = verdictOf(a.verdict);
                  return (
                    <div key={a.key} className="th-aspect2">
                      <div className="th-aspect2-h">
                        <span className="th-aspect2-label">{humanize(a.key)}</span>
                        <span className={`v ${av.cls}`}>{av.l}</span>
                      </div>
                      {a.prompt ? <p className="th-aspect2-hint">{a.prompt}</p> : null}
                      {(byAspect.get(a.key) || []).map((q) => <QuestionCard key={q.id} q={q} id={id} owner={owner} onDone={onDone} />)}
                    </div>
                  );
                })}
                {orphans.length ? <div className="th-aspect2">{orphans.map((q) => <QuestionCard key={q.id} q={q} id={id} owner={owner} onDone={onDone} />)}</div> : null}
              </div>
            </details>
          );
        })}
      </div>
    </>
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

  // ── expand the map: suggest new/adjacent players, pick, then profile + append (gated) ──
  const [cands, setCands] = useState<CompCandidate[] | null>(null);
  const [candBusy, setCandBusy] = useState(false);
  const [sel, setSel] = useState<Set<string>>(new Set());
  async function loadCandidates() {
    if (!id) return; setErr(""); setCandBusy(true); setSel(new Set());
    try {
      const d = await api.competitiveCandidates(id);
      setCands(d.candidates || []);
    } catch (e) { setErr((e as Error).message); } finally { setCandBusy(false); }
  }
  function toggle(name: string) { setSel((s) => { const n = new Set(s); n.has(name) ? n.delete(name) : n.add(name); return n; }); }
  async function analyzeSelected() {
    if (!id) return; const names = [...sel]; if (!names.length) { setErr("Select at least one competitor."); return; }
    setErr("");
    try {
      const proj = await api.competitiveAdd(id, names, 0);
      const max = Number(proj.projection?.projected_usd || 0);
      if (!window.confirm(`Profile ${names.length} competitor${names.length === 1 ? "" : "s"} and add ${names.length === 1 ? "it" : "them"} to the map?\n\nProjected maximum: $${max.toFixed(3)}`)) return;
      setBusy(true); setNote("starting…"); setCands(null);
      const r = await api.competitiveAdd(id, names, Math.max(max, 0.01));
      if (!r.run?.id) throw new Error(r.status === "refused" ? "cost exceeded the budget" : "could not start");
      poll(r.run.id);
    } catch (e) { setBusy(false); setErr((e as Error).message); }
  }

  return (
    <div className="card">
      {comp?.space ? <div className="th-comp-cap">The market — {comp.space}</div> : null}
      {empty ? <p className="muted" style={{ fontSize: ".9rem" }}>{comp?.reason || "No competitive landscape yet."}{owner ? " Research it from the open web below." : ""}</p> : (
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
      {owner && id ? (
        <div className="th-comp-addbar">
          <button className="btn sec" disabled={busy} onClick={research}>{busy ? (note || "Researching…") : (empty ? "Research competitive landscape" : "Re-research landscape")}</button>
          {!empty && !busy ? <button className="btn sec" disabled={candBusy || cands !== null} onClick={loadCandidates}>{candBusy ? "Finding players…" : "+ Add competitors"}</button> : null}
        </div>
      ) : null}
      {cands !== null ? (
        <div className="th-comp-pick">
          {cands.length === 0 ? <div className="muted" style={{ fontSize: ".85rem" }}>No new candidates found. <button className="linklike" onClick={() => setCands(null)}>close</button></div> : (
            <>
              <div className="th-comp-pick-h">Pick competitors to profile &amp; add — direct or adjacent:</div>
              <div className="th-comp-cands">
                {cands.map((c) => (
                  <label key={c.name} className="th-comp-cand">
                    <input type="checkbox" checked={sel.has(c.name)} onChange={() => toggle(c.name)} />
                    <span className="th-comp-cand-n">{c.name}<span className={`th-comp-kind th-comp-kind-${c.kind || "direct"}`}>{c.kind || "direct"}</span></span>
                    {c.note ? <span className="th-comp-cand-note">{c.note}</span> : null}
                  </label>
                ))}
              </div>
              <div className="th-comp-pick-acts">
                <button className="btn" disabled={!sel.size} onClick={analyzeSelected}>Analyze {sel.size || ""} selected</button>
                <button className="btn sec" onClick={() => setCands(null)}>Cancel</button>
              </div>
            </>
          )}
        </div>
      ) : null}
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

// Owner control: after running new questions, rebuild the read (Collective Take) and its derivatives —
// the pitch deck (free) and, on confirm, the competitive landscape (gated web spend).
function RegenBar({ id, hasComp, onDone }: { id?: string; hasComp?: boolean; onDone?: () => void }) {
  const [busy, setBusy] = useState(false); const [note, setNote] = useState(""); const [err, setErr] = useState("");
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  function poll(runId: string) {
    if (!id) return;
    api.inquiryStatus(id, runId).then((s) => {
      if (s.state === "completed" || s.state === "cancelled") { setBusy(false); setNote(""); onDone?.(); return; }
      if (s.state === "failed") { setBusy(false); setErr("competitive research failed"); onDone?.(); return; }
      setNote("re-researching competitors…");
      timer.current = window.setTimeout(() => poll(runId), 2500);
    }).catch(() => { timer.current = window.setTimeout(() => poll(runId), 3000); });
  }
  async function regen() {
    if (!id || busy) return; setErr("");
    if (!window.confirm("Rebuild the read and pitch deck from the latest findings?")) return;
    setBusy(true);
    try {
      setNote("rebuilding the read…"); await api.synthesize(id);
      setNote("rebuilding the deck…"); await api.buildDeck(id);
      onDone?.();
      if (hasComp) {
        const proj = await api.competitiveResearch(id, 0);
        const max = Number(proj.projection?.projected_usd || 0);
        if (window.confirm(`Also re-research the competitive landscape from the open web?\n\nProjected maximum: $${max.toFixed(3)}`)) {
          setNote("starting competitive…");
          const r = await api.competitiveResearch(id, Math.max(max, 0.01));
          if (r.run?.id) { poll(r.run.id); return; }
        }
      }
      setBusy(false); setNote("");
    } catch (e) { setBusy(false); setErr((e as Error).message); }
  }
  if (!id) return null;
  return (
    <div className="th-regen">
      <button className="th-regen-btn" disabled={busy} onClick={regen}>{busy ? (note || "regenerating…") : "↻ Regenerate from latest findings"}</button>
      <span className="th-regen-note">rebuilds the read &amp; deck; competitive is re-researched on confirm</span>
      {err ? <span style={{ color: "var(--p0)", fontSize: ".78rem" }}>{err}</span> : null}
    </div>
  );
}

// ── the Brief ─────────────────────────────────────────────────────────────────
// Derivations shared by every panel (each brief view sources the same take/deck/comp + lean).
const takeOf = (doc: ThesisDoc, inq: InquiriesView) => inq.take || doc.collective_take;
const deckOf = (doc: ThesisDoc, inq: InquiriesView) => inq.deck || doc.pitch_deck;
const compOf = (doc: ThesisDoc, inq: InquiriesView) => inq.competitive || doc.competitive;
function leanOf(inq: InquiriesView) {
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
}

// The shared brief chrome: evidence context + the two-column memo/rail layout + the citation hover card.
// Every brief panel (The read, Reasoning map, Competitive, Pitch deck, Lines of inquiry) renders inside it.
function BriefShell({ doc, inq, anonymous, children }: { doc: ThesisDoc; inq: InquiriesView; anonymous?: boolean; children: ReactNode }) {
  const [view, setView] = useState<DrawerView>({ kind: "overview" });
  const [hover, setHover] = useState<Hover>(null);
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
  const active = view.kind === "overview" ? null : view.id;
  const ctx: Ctx = { citer, evidenceById, findingById, show: setView, active, setHover };
  return (
    <BriefCtx.Provider value={ctx}>
      <CiteHover hover={hover} />
      <div className="briefgrid">
        <div className="memo">
          <div className="mono muted" style={{ fontSize: ".7rem", marginBottom: ".3rem" }}>
            Thesis under test{anonymous ? " · anonymized board view" : ""}
          </div>
          <h1 className="memo-thesis">{doc.thesis}</h1>
          {children}
        </div>
        <aside className="rail"><Drawer view={view} /></aside>
      </div>
    </BriefCtx.Provider>
  );
}

type PanelProps = { doc: ThesisDoc; inq: InquiriesView; anonymous?: boolean; id?: string; owner?: boolean; onRefetchInq?: () => void };

// The Read — the collective take (implicitly "the brief"; no tab strip). Carries the read card + regen.
export function ReadPanel({ doc, inq, anonymous, id, owner, onRefetchInq }: PanelProps) {
  const take = takeOf(doc, inq); const bl = take?.bottom_line; const comp = compOf(doc, inq);
  return (
    <BriefShell doc={doc} inq={inq} anonymous={anonymous}>
      {parse(bl).clean ? <div className="card read"><div className="kick">The read</div><p><Cite value={bl} kind="finding" /></p></div> : null}
      {owner && id ? <RegenBar id={id} hasComp={!!(comp?.players || []).length} onDone={onRefetchInq} /> : null}
      <TakeTab take={take} />
    </BriefShell>
  );
}
export function ReasoningPanel({ doc, inq, anonymous }: PanelProps) {
  return <BriefShell doc={doc} inq={inq} anonymous={anonymous}><ReasonTab take={takeOf(doc, inq)} lean={leanOf(inq)} /></BriefShell>;
}
export function CompetitivePanel({ doc, inq, anonymous, id, owner, onRefetchInq }: PanelProps) {
  return <BriefShell doc={doc} inq={inq} anonymous={anonymous}><CompTab comp={compOf(doc, inq)} id={id} owner={owner} onDone={onRefetchInq} /></BriefShell>;
}
export function DeckPanel({ doc, inq, anonymous }: PanelProps) {
  return <BriefShell doc={doc} inq={inq} anonymous={anonymous}><DeckTab deck={deckOf(doc, inq)} /></BriefShell>;
}
export function LinesPanel({ doc, inq, anonymous, id, owner, onRefetchInq }: PanelProps) {
  return <BriefShell doc={doc} inq={inq} anonymous={anonymous}><LinesTab inquiries={inq.inquiries} id={id} owner={owner} onDone={onRefetchInq} /></BriefShell>;
}

// The board still shows ONE standalone read-only page with every section tabbed (no stepper there).
type Tab = "take" | "reason" | "lines" | "comp" | "deck";
const TABS: [Tab, string][] = [["take", "The read"], ["reason", "Reasoning map"], ["lines", "Lines of inquiry"], ["comp", "Competitive"], ["deck", "Pitch deck"]];
export function Brief({ doc, inq, anonymous, id, owner, onRefetchInq }: PanelProps) {
  const [tab, setTab] = useState<Tab>("take");
  const take = takeOf(doc, inq); const deck = deckOf(doc, inq); const comp = compOf(doc, inq); const bl = take?.bottom_line;
  return (
    <BriefShell doc={doc} inq={inq} anonymous={anonymous}>
      {parse(bl).clean ? <div className="card read"><div className="kick">The read</div><p><Cite value={bl} kind="finding" /></p></div> : null}
      <div className="tabs">
        {TABS.map(([t, label]) => <button key={t} className={`tab${t === tab ? " on" : ""}`} onClick={() => setTab(t)}>{label}</button>)}
      </div>
      {owner && id ? <RegenBar id={id} hasComp={!!(comp?.players || []).length} onDone={onRefetchInq} /> : null}
      {tab === "take" ? <TakeTab take={take} />
        : tab === "reason" ? <ReasonTab take={take} lean={leanOf(inq)} />
          : tab === "lines" ? <LinesTab inquiries={inq.inquiries} id={id} owner={owner} onDone={onRefetchInq} />
            : tab === "comp" ? <CompTab comp={comp} id={id} owner={owner} onDone={onRefetchInq} />
              : <DeckTab deck={deck} />}
    </BriefShell>
  );
}
