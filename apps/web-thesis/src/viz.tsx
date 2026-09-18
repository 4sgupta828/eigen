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

export function BarChart({ v }: { v: BsVisual }) {
  const series = v.series || [];
  const max = Math.max(1, ...series.map((s) => Math.abs(s.value || 0)));
  const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/\.?0+$/, ""));
  return (
    <div className="bs-viz">
      {v.title ? <div className="bs-viz-h">📊 {v.title}{v.unit ? <span className="bs-viz-unit"> · {v.unit}</span> : null}</div> : null}
      <div className="bs-bar-rows">
        {series.map((s, i) => (
          <div key={i} className="bs-bar-row">
            <span className="bs-bar-lab">{s.label}</span>
            <span className="bs-bar-track"><span className="bs-bar-fill" style={{ width: `${Math.max(2, (Math.abs(s.value || 0) / max) * 100)}%` }} /></span>
            <span className="bs-bar-val">{fmt(s.value || 0)}{v.unit && v.unit.length <= 3 ? v.unit : ""}</span>
          </div>
        ))}
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
