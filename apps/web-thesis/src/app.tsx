import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { Brief } from "./brief";

// ── hash router (hash-compatible with the classic client: #thesis/#view/#board) ──
type Route =
  | { name: "home" }
  | { name: "board" }
  | { name: "boardEntry"; id: string }
  | { name: "view"; id: string; token: string }
  | { name: "thesis"; id: string; token: string };

function parseHash(hash: string): Route {
  const h = hash.replace(/^#/, "");
  if (h === "board") return { name: "board" };
  if (h.indexOf("board/") === 0) return { name: "boardEntry", id: decodeURIComponent(h.slice(6)) };
  if (h.indexOf("view/") === 0) {
    const raw = h.slice(5); const i = raw.lastIndexOf("/");
    return { name: "view", id: decodeURIComponent(i < 0 ? raw : raw.slice(0, i)), token: i < 0 ? "" : decodeURIComponent(raw.slice(i + 1)) };
  }
  if (h.indexOf("thesis/") === 0) {
    const raw = h.slice(7); const [id, qs] = raw.split("?");
    const share = new URLSearchParams(qs || "").get("share") || "";
    return { name: "thesis", id: decodeURIComponent(id || ""), token: share };
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
      <div className="foot">Eigen · new thesis-first client (beachhead) · Phase 1</div>
    </>
  );
}
const Loading = () => <div className="state">loading…</div>;
const Err = ({ e }: { e: unknown }) => <div className="state">{(e as Error)?.message || "something went wrong"}</div>;

// ── screens ──────────────────────────────────────────────────────────────────
function Home() {
  const q = useQuery({ queryKey: ["theses"], queryFn: api.theses });
  const theses = q.data || [];
  return (
    <Shell crumb={<>My theses</>}>
      <div className="pagehead"><h1>My theses</h1><p>Each thesis is a workspace and a shareable, sourced brief.</p></div>
      <div className="row" style={{ marginBottom: 14 }}>
        <button className="btn" disabled title="Coming in Phase 3">+ Test a new thesis</button>
        <button className="btn sec" onClick={() => go("#board")}>▤ Browse the ThesisBoard</button>
      </div>
      {q.isLoading ? <Loading /> : theses.length ? theses.map((t) => (
        <button key={t.id} className="tcard" onClick={() => go(`#thesis/${encodeURIComponent(t.id)}`)}>
          <h3>{t.title || t.thesis}</h3>
          <div className="meta"><span>{t.settled ?? 0}/{t.claims ?? 0} settled</span><span>·</span><span>{(t.updated_at || "").slice(0, 10)}</span></div>
        </button>
      )) : <p className="muted" style={{ fontSize: ".9rem" }}>No theses on this device. Browse the ThesisBoard, or sign in to see yours.</p>}
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

function ThesisView({ id, token }: { id: string; token: string }) {
  const t = useQuery({ queryKey: ["thesis", id, token], queryFn: () => api.thesis(id, token || undefined) });
  const i = useQuery({ queryKey: ["inq", id, token], queryFn: () => api.inquiries(id, token || undefined), enabled: !!t.data });
  if (t.isLoading) return <Shell><Loading /></Shell>;
  if (t.error) return <Shell><Err e={t.error} /></Shell>;
  return (
    <Shell crumb={<b>{t.data?.thesis?.slice(0, 40)}…</b>}>
      {t.data ? <Brief doc={t.data} inq={i.data || {}} anonymous={!t.data.is_owner && !!token} /> : null}
    </Shell>
  );
}

export function App() {
  const r = useRoute();
  switch (r.name) {
    case "board": return <BoardGallery />;
    case "boardEntry": return r.id ? <BoardEntryView id={r.id} /> : <BoardGallery />;
    case "view": return <ThesisView id={r.id} token={r.token} />;
    case "thesis": return <ThesisView id={r.id} token={r.token} />;
    default: return <Home />;
  }
}
