import { createContext, useContext, useMemo, useState } from "react";
import type {
  Analysis, Cited, Competitive, Deck, Evidence, InquiriesView, Question, Take, ThesisDoc,
} from "./api";

// ── citation numbering (first-seen, per Brief) ─────────────────────────────────
class Citer {
  private seen = new Map<string, number>();
  private _n = 0;
  num(id: string): number {
    if (!this.seen.has(id)) this.seen.set(id, ++this._n);
    return this.seen.get(id)!;
  }
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

const REG: Record<string, { c: string; l: string }> = {
  filed: { c: "var(--fact)", l: "Filed · fact" },
  stated: { c: "var(--intent)", l: "Stated · intent" },
  observed: { c: "var(--signal)", l: "Observed · signal" },
  coverage: { c: "var(--signal)", l: "Coverage · signal" },
};
const regOf = (r?: string) => REG[r || ""] || { c: "var(--muted)", l: r || "source" };

// ── the evidence drawer ─────────────────────────────────────────────────────────
function Drawer({ view }: { view: DrawerView }) {
  const { evidenceById, findingById, show } = useBrief();
  if (view.kind === "overview") {
    // group evidence by register
    const counts = new Map<string, number>();
    evidenceById.forEach((e) => counts.set(e.register || "other", (counts.get(e.register || "other") || 0) + 1));
    const total = evidenceById.size;
    return (
      <>
        <div className="rail-head"><span className="kick" style={{ color: "var(--muted)" }}>Evidence</span></div>
        <div className="rail-body">
          <div className="discipline">
            <b>{total} sources</b>, typed by register. Coverage/observed is <b>signal</b>, never counted as fact.
            Click any <span className="ref" style={{ position: "static" }}>n</span> in the memo to trace it.
          </div>
          <div className="tiles">
            {[...counts.entries()].map(([reg, n]) => {
              const meta = regOf(reg);
              return (
                <div key={reg} className="tile" style={{ ["--tc" as string]: meta.c }}>
                  <div className="t-top"><h4>{meta.l}</h4><span className="n">{n}</span></div>
                  <span className="reg"><span className="d" style={{ background: meta.c }} /> {reg}</span>
                </div>
              );
            })}
          </div>
        </div>
      </>
    );
  }
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
  const meta = regOf(e?.register);
  return (
    <>
      <div className="rail-head">
        <span className="kick" style={{ color: "var(--muted)" }}>Source</span>
        <button className="rail-back" onClick={() => show({ kind: "overview" })}>‹ Evidence</button>
      </div>
      <div className="rail-body">
        {!e ? <p className="muted">Source not in the snapshot.</p> : (
          <>
            <span className="reg"><span className="d" style={{ background: meta.c }} /> {meta.l}</span>
            {e.quote ? <div className="src-quote" style={{ ["--sc" as string]: meta.c }}>“{e.quote}”</div> : null}
            <div className="src-meta">
              {e.title ? <div><b>{e.title}</b></div> : null}
              {e.source_subject ? <div>subject: {e.source_subject}</div> : null}
              {e.evidence_kind ? <div>kind: {e.evidence_kind}</div> : null}
              {e.as_of ? <div>as of {e.as_of.slice(0, 10)}</div> : null}
              {e.source_url ? <div><a href={e.source_url} target="_blank" rel="noopener">source ↗</a></div> : null}
            </div>
          </>
        )}
      </div>
    </>
  );
}

// ── tab renderers ────────────────────────────────────────────────────────────────
function TakeTab({ take }: { take?: Take }) {
  const secs = (take?.sections || []).filter((s) => (s.grounded?.length || s.analysis?.length));
  if (!secs.length) return <p className="muted">No collective take yet.</p>;
  const KIND: Record<string, string> = { assumption: "Assumption", tension: "Tension", gap: "Gap", implication: "Implication", what_would_change_this: "What would change this" };
  return (
    <>
      {secs.map((s) => (
        <div key={s.key} className="card">
          <div className="kick">{s.title}</div>
          <div className="grounded">
            {(s.grounded || []).map((g, i) => <p key={i}><Cite value={g} kind="finding" /></p>)}
          </div>
          {(s.analysis || []).map((a: Analysis, i) => (
            <p key={`a${i}`} style={{ fontSize: ".88rem", margin: ".35rem 0" }}>
              <span className="kick" style={{ marginRight: ".3rem" }}>{KIND[a.kind] || a.kind}</span>
              <Cite value={a} kind="finding" />
            </p>
          ))}
        </div>
      ))}
    </>
  );
}
function ReasonTab({ take }: { take?: Take }) {
  const LANES = [
    { kind: "assumption", title: "What must be true", c: "#6b5bd0" },
    { kind: "tension", title: "Tensions", c: "#c0563f" },
    { kind: "gap", title: "Gaps", c: "#b8860b" },
    { kind: "implication", title: "What it implies", c: "#2e8b6f" },
  ];
  const byKind = new Map<string, Analysis[]>();
  (take?.sections || []).forEach((s) => (s.analysis || []).forEach((a) => {
    if (!a.text) return; const k = a.kind || ""; byKind.set(k, [...(byKind.get(k) || []), a]);
  }));
  const lanes = LANES.filter((l) => byKind.get(l.kind)?.length);
  if (!lanes.length) return <p className="muted">No reasoning blocks yet.</p>;
  return (
    <div className="card">
      <div className="kick" style={{ marginBottom: ".5rem" }}>How the reasoning converges on the read</div>
      <div className="rmap">
        {lanes.map((l) => (
          <div key={l.kind} className="lane" style={{ ["--lc" as string]: l.c }}>
            <b>{l.title}</b>
            {(byKind.get(l.kind) || []).map((a, i) => <div key={i} style={{ marginTop: i ? ".4rem" : 0 }}><Cite value={a} kind="finding" /></div>)}
          </div>
        ))}
      </div>
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
function CompTab({ comp }: { comp?: Competitive }) {
  const cols = comp?.columns || [];
  const players = comp?.players || [];
  if (!players.length) return <p className="muted">No competitive landscape yet.</p>;
  const show = cols.slice(0, 4);
  return (
    <div className="card">
      <div className="tablewrap">
        <table>
          <thead><tr><th>Player</th>{show.map((c) => <th key={c.key}>{c.label}</th>)}</tr></thead>
          <tbody>
            {players.map((p, i) => (
              <tr key={i}>
                <td><b>{p.name}</b></td>
                {show.map((c) => {
                  const cell = p.cells?.[c.key];
                  const t = (cell?.text || "").trim();
                  return <td key={c.key}>{t ? t.slice(0, 120) : <span className="muted">—</span>}{cell?.source_url ? <> <a href={cell.source_url} target="_blank" rel="noopener">↗</a></> : null}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted" style={{ fontSize: ".74rem", marginTop: ".5rem", fontFamily: "var(--mono)" }}>Empty cells where the record is silent — never invented.</p>
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

export function Brief({ doc, inq, anonymous }: { doc: ThesisDoc; inq: InquiriesView; anonymous?: boolean }) {
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

  const ctx: Ctx = { citer, evidenceById, findingById, show: setView, active };

  return (
    <BriefCtx.Provider value={ctx}>
      <div className="briefgrid">
        <div className="memo">
          <div className="mono muted" style={{ fontSize: ".7rem", marginBottom: ".3rem" }}>
            Thesis under test{anonymous ? " · anonymized board view" : ""}
          </div>
          <h1 style={{ fontSize: "1.35rem", lineHeight: 1.28, marginBottom: ".7rem" }}>{doc.thesis}</h1>
          {parse(bl).clean ? (
            <div className="card read"><div className="kick">The read</div><p><Cite value={bl} kind="finding" /></p></div>
          ) : null}
          <div className="tabs">
            {TABS.map(([t, label]) => (
              <button key={t} className={`tab${t === tab ? " on" : ""}`} onClick={() => setTab(t)}>{label}</button>
            ))}
          </div>
          {tab === "take" ? <TakeTab take={take} />
            : tab === "reason" ? <ReasonTab take={take} />
              : tab === "lines" ? <LinesTab inquiries={inq.inquiries} />
                : tab === "comp" ? <CompTab comp={comp} />
                  : <DeckTab deck={deck} />}
        </div>
        <aside className="rail"><Drawer view={view} /></aside>
      </div>
    </BriefCtx.Provider>
  );
}
