import { useState } from "react";
import { api, type ThesisDoc } from "./api";
import { PageHead } from "./ui";

const boardUrl = (entryId: string) => `${location.origin}/w#board/${encodeURIComponent(entryId)}`;
const viewUrl = (id: string, token: string) => `${location.origin}/w#view/${encodeURIComponent(id)}/${encodeURIComponent(token)}`;

export function Share({ id, doc, onChanged }: { id: string; doc: ThesisDoc; onChanged: () => void }) {
  const [board, setBoard] = useState<string>(doc.board_entry || "");
  const [shareTok, setShareTok] = useState("");
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState("");

  const copy = async (url: string, which: string) => {
    try { await navigator.clipboard.writeText(url); setCopied(which); setTimeout(() => setCopied(""), 1500); }
    catch { setErr("Copy this link: " + url); }
  };
  async function act(label: string, fn: () => Promise<void>) {
    setBusy(label); setErr("");
    try { await fn(); onChanged(); } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  }

  return (
    <>
      <PageHead title="Share" sub="Publish a clean, anonymized brief to the public ThesisBoard, or send a private read-only link to your full thesis." />
      <div className="sharebox">
        <div className="kick">Publish to the ThesisBoard</div>
        <p style={{ fontSize: ".88rem", margin: ".35rem 0 .6rem" }}>A frozen, <b>anonymized</b> snapshot — answered lines only, your identity removed. Anyone can open it, no login.</p>
        {board ? (
          <>
            <div className="linkfield"><span>{boardUrl(board)}</span>
              <button className="btn sec" style={{ padding: ".35rem .6rem" }} onClick={() => copy(boardUrl(board), "board")}>{copied === "board" ? "✓ copied" : "🔗 Copy link"}</button></div>
            <div className="row" style={{ marginTop: ".7rem" }}>
              <button className="btn" disabled={!!busy} onClick={() => act("pub", async () => { setBoard(await api.publish(id)); })}>{busy === "pub" ? "…" : "Update on ThesisBoard"}</button>
              <button className="btn sec" disabled={!!busy} onClick={() => act("unpub", async () => { await api.unpublish(id); setBoard(""); })}>{busy === "unpub" ? "…" : "Unpublish"}</button>
            </div>
          </>
        ) : (
          <button className="btn" disabled={!!busy} onClick={() => act("pub", async () => { setBoard(await api.publish(id)); })}>{busy === "pub" ? "Publishing…" : "Publish to ThesisBoard"}</button>
        )}
      </div>

      <div className="sharebox">
        <div className="kick">Private read-only link</div>
        <p style={{ fontSize: ".88rem", margin: ".35rem 0 .6rem" }}>Your full, non-anonymized thesis — for someone specific. Not listed on the board.</p>
        {shareTok ? (
          <div className="linkfield"><span>{viewUrl(id, shareTok)}</span>
            <button className="btn sec" style={{ padding: ".35rem .6rem" }} onClick={() => copy(viewUrl(id, shareTok), "view")}>{copied === "view" ? "✓ copied" : "🔗 Copy"}</button></div>
        ) : (
          <button className="btn sec" disabled={!!busy} onClick={() => act("share", async () => { setShareTok(await api.share(id)); })}>{busy === "share" ? "…" : "Create read-only link"}</button>
        )}
      </div>
      {err ? <p className="state" style={{ color: "var(--p0)" }}>{err}</p> : null}
    </>
  );
}
