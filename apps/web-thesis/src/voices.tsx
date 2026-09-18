import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ThesisDoc, type Voice, type VoiceBucket, type VoiceSummary } from "./api";
import { PageHead, Loading, Working } from "./ui";

// Voices — first-person founders & investors on this thesis's space (podcasts, talks, blogs, essays)
// from Eigen's Voices corpus, ranked to the thesis and ORGANIZED by how each piece bears on the
// investigation (dynamic buckets, an LLM pass that also prunes the off-topic hits). Playable pieces
// play inline; readable pieces expand to an AI summary. A signal to explore, never graded evidence.

const KIND_META: Record<string, { label: string; icon: string }> = {
  podcast: { label: "Podcast", icon: "🎧" },
  video: { label: "Talk / video", icon: "▶" },
  essay: { label: "Essay", icon: "✍" },
  blog: { label: "Blog", icon: "📝" },
  transcript: { label: "Transcript", icon: "🎙" },
  chapter: { label: "Moment", icon: "⏱" },
};

// A SHORT, topical query. Voices ranking is keyword-based: a long, many-term query over-constrains it
// and biases toward the longest documents (essays), starving podcasts and videos — so keep it to a few
// salient words from the subject (NOT the lines of inquiry, whose generic names dilute the topic).
function topicOf(doc: ThesisDoc): string {
  const subj = Object.values(doc.subject || {}).map((v) => String(v || "").trim()).filter(Boolean).join(" ");
  let q = subj.trim();
  if (q.split(/\s+/).filter(Boolean).length < 3) q = `${q} ${doc.thesis || ""}`.trim();
  return q.split(/\s+/).filter(Boolean).slice(0, 8).join(" ").slice(0, 90);
}

const compact = (m: Voice) => ({ id: m.id, kind: m.kind, title: m.title, snippet: m.text, speaker: m.speaker, show: m.show });

export function VoicesPanel({ id, doc }: { id?: string; doc: ThesisDoc }) {
  const q = useMemo(() => topicOf(doc), [doc]);
  const vq = useQuery({ queryKey: ["voices", q], queryFn: () => api.voices(q, 30), enabled: !!q });
  const moments = vq.data || [];
  const byId = useMemo(() => new Map(moments.map((m) => [m.id, m])), [moments]);

  // Organize into relevance-to-the-investigation buckets (LLM, cached server-side by the candidate set).
  const oq = useQuery({
    queryKey: ["voices-org", id, moments.map((m) => m.id).join(",")],
    queryFn: () => api.voicesOrganize(id!, moments.map(compact)),
    enabled: !!id && moments.length > 0,
  });
  const buckets: VoiceBucket[] = oq.data || [];
  const organized = buckets.length > 0;

  return (
    <>
      <PageHead title="Voices" sub="Founders & investors on this space — podcasts, talks, blogs and essays from Eigen's first-person index, ranked to your thesis and grouped by how each bears on the investigation. Play them inline or open the summary. A signal to explore, not graded evidence." />
      {vq.isLoading ? <Loading /> : null}
      {!vq.isLoading && moments.length === 0 ? (
        <p className="muted">No first-person voices matched this thesis's topic yet. As the Voices corpus grows, relevant podcasts, talks and essays will surface here.</p>
      ) : null}
      {moments.length > 0 && oq.isLoading ? <div style={{ margin: ".4rem 0 1rem" }}><Working text="organizing voices by how they bear on your thesis…" /></div> : null}

      {organized ? buckets.map((b, i) => {
        const items = b.items.map((it) => ({ m: byId.get(it.id), why: it.why })).filter((x) => x.m);
        if (!items.length) return null;
        return (
          <div key={i} className="vc-group">
            <div className="vc-bucket-h"><span className="vc-bucket-dot" />{b.label}</div>
            <div className="vc-grid">
              {items.map(({ m, why }) => <VoiceCard key={m!.id} m={m!} why={why} />)}
            </div>
          </div>
        );
      }) : moments.length > 0 && !oq.isLoading ? (
        // Fallback: organization unavailable → a flat, kind-grouped list.
        <div className="vc-group">
          <div className="vc-bucket-h"><span className="vc-bucket-dot" />Relevant voices</div>
          <div className="vc-grid">{moments.map((m) => <VoiceCard key={m.id} m={m} />)}</div>
        </div>
      ) : null}
    </>
  );
}

const KIND_TINT: Record<string, string> = {
  podcast: "#8a5a2b", video: "#b23", essay: "#2e6d5b", blog: "#3a6ea5", transcript: "#6b5bd0", chapter: "#8a6d3b",
};

function thumbUrl(m: Voice): string {
  if (m.media?.kind === "youtube" && m.media.id) return `https://i.ytimg.com/vi/${m.media.id}/hqdefault.jpg`;
  return m.image || "";
}

function VoiceCard({ m, why }: { m: Voice; why?: string }) {
  const [open, setOpen] = useState(false);
  const meta = KIND_META[m.kind] || { label: m.kind, icon: "•" };
  const yt = m.media?.kind === "youtube" ? m.media : undefined;
  const audio = m.media?.kind === "audio" ? m.media : undefined;
  const playable = !!(yt || audio);
  const who = [m.speaker, m.show].filter(Boolean).join(" · ");
  const date = String(m.published || m.year || "").slice(0, 10);
  const thumb = thumbUrl(m);
  const tint = KIND_TINT[m.kind] || "#8a6d3b";

  const sq = useQuery({
    queryKey: ["voice-summary", m.id],
    queryFn: () => api.voiceSummary(m.id),
    enabled: open && !playable,     // readable pieces summarize on expand; playable pieces embed a player
  });

  return (
    <div className={"vc-card" + (open ? " vc-open" : "")} style={{ ["--vt" as string]: tint }}>
      <button className="vc-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <div className={"vc-thumb" + (playable ? " vc-thumb-play" : "")}
          style={thumb ? { backgroundImage: `url(${thumb})` } : undefined}>
          {!thumb ? <span className="vc-thumb-icon">{meta.icon}</span> : null}
          {playable ? <span className="vc-thumb-btn">▶</span> : null}
          <span className="vc-thumb-badge">{meta.icon} {meta.label}</span>
        </div>
        <div className="vc-meta">
          {m.title ? <div className="vc-title">{m.title}</div> : null}
          {who ? <div className="vc-who">{who}</div> : null}
          {why ? <div className="vc-why">{why}</div> : (m.text ? <div className="vc-snip">{m.text}</div> : null)}
          <div className="vc-foot">
            <span className="vc-act">{playable ? (yt ? "▶ Watch here" : "▶ Listen here") : "⌄ Read summary"}</span>
            {date ? <span className="vc-date">{date}</span> : null}
          </div>
        </div>
      </button>

      {open ? (
        <div className="vc-body">
          {yt ? (
            <div className="vc-embed">
              <iframe src={`https://www.youtube-nocookie.com/embed/${yt.id}?start=${yt.t || 0}&autoplay=1&rel=0`}
                title={m.title || "video"} allow="accelerometer; autoplay; encrypted-media; picture-in-picture" allowFullScreen />
            </div>
          ) : audio ? (
            <audio className="vc-audio" controls autoPlay src={`${audio.url}${audio.t ? `#t=${audio.t}` : ""}`} />
          ) : (
            <VoiceSummaryView loading={sq.isLoading} error={!!sq.error} data={sq.data} />
          )}
          {m.url ? <a className="vc-link" href={m.url} target="_blank" rel="noreferrer noopener">{playable ? "Open on the source ↗" : "Read the full post ↗"}</a> : null}
        </div>
      ) : null}
    </div>
  );
}

function VoiceSummaryView({ loading, error, data }: { loading: boolean; error: boolean; data?: VoiceSummary }) {
  if (loading) return <Working text="summarizing…" />;
  if (error || !data) return <p className="muted" style={{ margin: 0 }}>Couldn't summarize this one — open the full post below.</p>;
  const points = (data.points || []).filter(Boolean);
  const paras = (data.sections || []).flatMap((s) => s.paragraphs || []).filter(Boolean);
  return (
    <div className="vc-summary">
      {data.heading ? <div className="vc-sum-h">{data.heading}</div> : null}
      {points.length ? <ul className="vc-sum-points">{points.slice(0, 6).map((p, i) => <li key={i}>{p}</li>)}</ul> : null}
      {!points.length && paras.length ? <p className="vc-sum-p">{paras[0].slice(0, 480)}</p> : null}
      {(data.quotes || []).length ? <blockquote className="vc-sum-q">“{(data.quotes || [])[0]}”</blockquote> : null}
    </div>
  );
}
