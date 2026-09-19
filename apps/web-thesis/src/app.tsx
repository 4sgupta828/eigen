import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, forgetOwner, type ThesisListItem } from "./api";
import { Brief } from "./brief";
import { Workspace } from "./workspace";
import { Genesis } from "./genesis";
import { Settings } from "./admin";

// ── hash router (hash-compatible with the classic client: #thesis/#view/#board) ──
type Route =
  | { name: "home" }
  | { name: "new" }
  | { name: "settings" }
  | { name: "board" }
  | { name: "boardEntry"; id: string }
  | { name: "view"; id: string; token: string }
  | { name: "thesis"; id: string; token: string; step: string };

function parseHash(hash: string): Route {
  const h = hash.replace(/^#/, "");
  if (h === "new") return { name: "new" };
  if (h === "settings") return { name: "settings" };
  if (h === "board") return { name: "board" };
  if (h.indexOf("board/") === 0) return { name: "boardEntry", id: decodeURIComponent(h.slice(6)) };
  if (h.indexOf("view/") === 0) {
    const raw = h.slice(5); const i = raw.lastIndexOf("/");
    return { name: "view", id: decodeURIComponent(i < 0 ? raw : raw.slice(0, i)), token: i < 0 ? "" : decodeURIComponent(raw.slice(i + 1)) };
  }
  if (h.indexOf("thesis/") === 0) {
    const raw = h.slice(7); const [id, qs] = raw.split("?");
    const p = new URLSearchParams(qs || "");
    return { name: "thesis", id: decodeURIComponent(id || ""), token: p.get("share") || "", step: p.get("step") || "" };
  }
  return { name: "home" };
}
function useRoute(): Route {
  const [hash, setHash] = useState(() => location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parseHash(hash);
}
const go = (h: string) => { location.hash = h; };

// ── chrome ───────────────────────────────────────────────────────────────────
function Shell({ crumb, children }: { crumb?: ReactNode; children: ReactNode }) {
  return (
    <>
      <div className="top"><div className="top-in">
        <span className="mark" onClick={() => go("")}>EIG<b>E</b>N</span>
        {crumb ? <span className="crumb">{crumb}</span> : null}
        <span className="grow" />
      </div></div>
      <div className="wrap">{children}</div>
      <div className="foot">Eigen · new thesis-first client (beachhead) · full thesis lifecycle · <span style={{ cursor: "pointer" }} onClick={() => go("settings")}>⚙ admin</span></div>
    </>
  );
}
const Loading = () => <div className="state">loading…</div>;
const Err = ({ e }: { e: unknown }) => <div className="state">{(e as Error)?.message || "something went wrong"}</div>;

// ── screens ──────────────────────────────────────────────────────────────────
// The artifacts a thesis can accumulate, shown as on/off chips so progress reads at a glance.
const ARTIFACTS: { key: keyof ThesisListItem; label: string }[] = [
  { key: "has_brief", label: "Brief" },
  { key: "has_reasoning", label: "Reasoning map" },
  { key: "has_competitive", label: "Competitive" },
  { key: "has_deck", label: "Pitch deck" },
];

function ThesisCard({ t, onDelete }: { t: ThesisListItem; onDelete: (t: ThesisListItem) => void }) {
  const total = t.questions?.total ?? 0;
  const answered = t.questions?.answered ?? 0;
  const pct = total ? Math.round((100 * answered) / total) : 0;
  const open = () => go(`#thesis/${encodeURIComponent(t.id)}`);
  return (
    <div className="dcard" role="button" tabIndex={0} onClick={open}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }}>
      <div className="dcard-top">
        <h3 className="dcard-title">{t.title || t.thesis}</h3>
        <button className="dcard-del" title="Delete this thesis" aria-label="Delete this thesis"
          onClick={(e) => { e.stopPropagation(); onDelete(t); }}>🗑</button>
      </div>
      {t.thesis && t.title && t.thesis.trim() !== (t.title || "").trim() ? <p className="dcard-sub">{t.thesis}</p> : null}
      {t.draft ? (
        <div className="dcard-tags"><span className="dcard-status draft">Draft — not yet committed</span></div>
      ) : (
        <>
          <div className="dcard-prog">
            <div className="dcard-prog-h">
              <span>Questions researched</span>
              <span className="dcard-prog-n">{answered}<span className="dcard-prog-d"> / {total}</span> · {pct}%</span>
            </div>
            <div className="dcard-bar"><div className="dcard-bar-f" style={{ width: `${pct}%` }} /></div>
          </div>
          <div className="dcard-arts">
            {ARTIFACTS.map((a) => {
              const on = !!t[a.key];
              return <span key={a.label} className={"dcard-art" + (on ? " on" : "")}>{on ? "✓" : "○"} {a.label}</span>;
            })}
          </div>
        </>
      )}
      <div className="dcard-meta">
        {t.claims ? <span>{t.settled ?? 0}/{t.claims} claims settled</span> : null}
        {t.on_board ? <span className="dcard-board">▤ published</span> : null}
        {t.updated_at ? <span>{t.updated_at.slice(0, 10)}</span> : null}
      </div>
    </div>
  );
}

function Home() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["myTheses"], queryFn: api.myTheses });
  const theses = q.data || [];
  const [busy, setBusy] = useState("");
  async function del(t: ThesisListItem) {
    if (!window.confirm(`Delete “${(t.title || t.thesis || "this thesis").slice(0, 80)}”?\n\nThis permanently removes the thesis and all its research${t.on_board ? ", and unpublishes it from the ThesisBoard" : ""}. This cannot be undone.`)) return;
    setBusy(t.id);
    try {
      await api.deleteThesis(t.id);
      forgetOwner(t.id);
      await qc.invalidateQueries({ queryKey: ["myTheses"] });
    } catch (e) { alert((e as Error).message || "could not delete"); }
    finally { setBusy(""); }
  }
  return (
    <Shell crumb={<>My theses</>}>
      <div className="pagehead"><h1>My theses</h1><p>Each thesis is a workspace and a shareable, sourced brief.</p></div>
      <div className="row" style={{ marginBottom: 14 }}>
        <button className="btn" onClick={() => go("#new")}>+ Test a new thesis</button>
        <button className="btn sec" onClick={() => go("#board")}>▤ Browse the ThesisBoard</button>
      </div>
      {q.isLoading ? <Loading /> : theses.length ? (
        <div className={"dgrid" + (busy ? " dgrid-busy" : "")}>
          {theses.map((t) => <ThesisCard key={t.id} t={t} onDelete={del} />)}
        </div>
      ) : <p className="muted" style={{ fontSize: ".9rem" }}>No theses on this device yet. Test a new thesis, or browse the ThesisBoard.</p>}
    </Shell>
  );
}

function BoardGallery() {
  const q = useQuery({ queryKey: ["board"], queryFn: () => api.board(60) });
  const entries = q.data || [];
  return (
    <Shell crumb={<>ThesisBoard</>}>
      <div className="pagehead"><h1>ThesisBoard</h1><p>Theses the community published — anonymized, showing only settled findings.</p>
        <a className="mono" style={{ fontSize: ".72rem" }} onClick={() => go("")} href="#">← Back to my theses</a></div>
      {q.isLoading ? <Loading /> : q.error ? <Err e={q.error} /> : entries.length ? entries.map((e) => (
        <button key={e.id} className="tcard" onClick={() => go(`#board/${encodeURIComponent(e.id)}`)}>
          <h3>{e.summary || e.title || "Untitled thesis"}</h3>
          <div className="meta"><span className="st st-tested">Anonymous</span><span>·</span><span>{e.findings ?? 0} findings</span><span>·</span><span>{(e.published_at || "").slice(0, 10)}</span></div>
        </button>
      )) : <p className="muted">No theses have been published yet.</p>}
    </Shell>
  );
}

function BoardEntryView({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["boardEntry", id], queryFn: () => api.boardEntry(id) });
  return (
    <Shell crumb={<><a href="#board" style={{ textDecoration: "none" }}>ThesisBoard</a> · <b>brief</b></>}>
      {q.isLoading ? <Loading /> : q.error ? <Err e={q.error} /> : q.data
        ? <Brief doc={q.data.doc} inq={q.data.inq} anonymous />
        : <Err e={new Error("no such board entry")} />}
    </Shell>
  );
}

function NewThesis() {
  return <Shell crumb={<>New thesis</>}><Genesis /></Shell>;
}

function SettingsPage() {
  return <Shell crumb={<>Admin settings</>}><Settings /></Shell>;
}

export function App() {
  const r = useRoute();
  switch (r.name) {
    case "new": return <NewThesis />;
    case "settings": return <SettingsPage />;
    case "board": return <BoardGallery />;
    case "boardEntry": return r.id ? <BoardEntryView id={r.id} /> : <BoardGallery />;
    case "view": return <Workspace id={r.id} token={r.token} />;
    case "thesis": return <Workspace id={r.id} token={r.token} step={r.step} />;
    default: return <Home />;
  }
}
