import { type ReactNode } from "react";
import { type BsVisual } from "./api";

// Dependency-free visual renderers shared by the Brainstorm agent and the Pitch Deck: a CSS bar chart
// for comparable numbers, and an indented, connector-styled outline for a decision / dependency tree.
// Both degrade gracefully — an ill-formed visual renders nothing.

export function Visual({ v }: { v: BsVisual }) {
  if (v.kind === "bar" && (v.series || []).length) return <BarChart v={v} />;
  if (v.kind === "tree" && (v.nodes || []).length) return <TreeView v={v} />;
  return null;
}

// Fold verbose "X — low"/"X — high" (min/max/worst/best) pairs into ONE range row per subject, and drop
// a word repeated across every label (the title already carries the shared subject) — so a chart reads
// as a lean comparison, not a wall of near-duplicate bars.
type Row = { label: string; lo: number; hi: number; range: boolean };
const BOUND = /[\s—\-–,:(]+\s*(low|high|min|max|minimum|maximum|worst|best|floor|ceiling|est\.?|estimate)s?\)?\s*$/i;
function simplify(series: { label?: string; value?: number }[]): Row[] {
  const parsed = series.map((s) => {
    const raw = (s.label || "").trim(); const m = raw.match(BOUND);
    const base = (m ? raw.slice(0, m.index) : raw).replace(/[\s—\-–,:(]+$/, "").trim() || raw;
    return { base, value: Number(s.value) || 0 };
  });
  const groups = new Map<string, number[]>(); const order: string[] = [];
  for (const p of parsed) { if (!groups.has(p.base)) { groups.set(p.base, []); order.push(p.base); } groups.get(p.base)!.push(p.value); }
  let rows: Row[] = order.map((base) => { const vs = groups.get(base)!; const lo = Math.min(...vs), hi = Math.max(...vs); return { label: base, lo, hi, range: lo !== hi }; });
  // strip a word (≥4 chars) that appears in EVERY label, once — e.g. every "…interview loop…"
  if (rows.length > 1) {
    const words = (l: string): string[] => l.toLowerCase().match(/[a-z0-9]{4,}/g) || [];
    const common = words(rows[0].label).filter((w) => rows.every((r) => words(r.label).includes(w)));
    for (const w of common) {
      const stripped = rows.map((r) => ({ ...r, label: r.label.replace(new RegExp(`\\b${w}\\b`, "i"), "").replace(/\s{2,}/g, " ").replace(/^[\s—\-–,:]+|[\s—\-–,:]+$/g, "").trim() }));
      if (stripped.every((r) => r.label)) rows = stripped;   // only if no label becomes empty
    }
  }
  return rows;
}

export function BarChart({ v }: { v: BsVisual }) {
  const rows = simplify(v.series || []);
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.hi)));
  const fmt = (n: number) => (Number.isInteger(n) ? n.toLocaleString() : n.toFixed(2).replace(/\.?0+$/, ""));
  const u = v.unit && v.unit.length <= 3 ? v.unit : "";
  return (
    <div className="bs-viz">
      {v.title ? <div className="bs-viz-h">📊 {v.title}{v.unit ? <span className="bs-viz-unit"> · {v.unit}</span> : null}</div> : null}
      <div className="bs-bar-rows">
        {rows.map((r, i) => {
          const loPct = Math.max(0, (Math.abs(r.lo) / max) * 100);
          const hiPct = Math.max(2, (Math.abs(r.hi) / max) * 100);
          return (
            <div key={i} className="bs-bar-row">
              <span className="bs-bar-lab">{r.label}</span>
              <span className="bs-bar-track">
                {r.range
                  ? <span className="bs-bar-fill rng" style={{ left: `${loPct}%`, width: `${Math.max(3, hiPct - loPct)}%` }} />
                  : <span className="bs-bar-fill" style={{ width: `${hiPct}%` }} />}
              </span>
              <span className="bs-bar-val">{r.range ? `${fmt(r.lo)}–${fmt(r.hi)}` : fmt(r.hi)}{u}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function TreeView({ v }: { v: BsVisual }) {
  const nodes = v.nodes || []; const edges = v.edges || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const kids = new Map<string, { to: string; label?: string }[]>();
  edges.forEach((e) => { const a = kids.get(e.from) || []; a.push({ to: e.to, label: e.label }); kids.set(e.from, a); });
  const incoming = new Set(edges.map((e) => e.to));
  let roots = nodes.filter((n) => !incoming.has(n.id)).map((n) => n.id);
  if (!roots.length && nodes.length) roots = [nodes[0].id];

  const render = (nid: string, edgeLabel: string | undefined, seen: Set<string>): ReactNode => {
    const n = byId.get(nid); if (!n) return null;
    const repeat = seen.has(nid);
    const next = new Set(seen); next.add(nid);
    return (
      <li key={nid + (edgeLabel || "")} className="bs-tree-li">
        {edgeLabel ? <span className="bs-tree-edge">{edgeLabel}</span> : null}
        <div className="bs-tree-node">
          <span className="bs-tree-lab">{n.label}</span>
          {n.note ? <span className="bs-tree-note">{n.note}</span> : null}
        </div>
        {!repeat && (kids.get(nid) || []).length ? (
          <ul className="bs-tree">{(kids.get(nid) || []).map((c) => render(c.to, c.label, next))}</ul>
        ) : null}
      </li>
    );
  };
  return (
    <div className="bs-viz">
      {v.title ? <div className="bs-viz-h">🌳 {v.title}</div> : null}
      <ul className="bs-tree bs-tree-root">{roots.map((r) => render(r, undefined, new Set()))}</ul>
    </div>
  );
}
