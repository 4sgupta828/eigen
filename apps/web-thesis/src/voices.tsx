import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type ThesisDoc, type Voice } from "./api";
import { PageHead, Loading } from "./ui";

// Voices — first-person founders & investors on this thesis's space: podcasts, talks, blog posts and
// essays drawn from Eigen's Voices corpus (the same first-person index the Voices mode reads), ranked
// to the thesis's own topic. Signal for how operators frame this market — never graded evidence.

const KIND_META: Record<string, { label: string; icon: string }> = {
  podcast: { label: "Podcast", icon: "🎧" },
  video: { label: "Talk / video", icon: "▶" },
  essay: { label: "Essay", icon: "✍" },
  blog: { label: "Blog", icon: "📝" },
  transcript: { label: "Transcript", icon: "🎙" },
  chapter: { label: "Moment", icon: "⏱" },
};
const GROUPS: { title: string; kinds: string[] }[] = [
  { title: "Podcasts & talks", kinds: ["podcast", "video", "transcript", "chapter"] },
  { title: "Blogs & essays", kinds: ["essay", "blog"] },
];

function topicOf(doc: ThesisDoc): string {
  const subj = Object.values(doc.subject || {}).map((v) => String(v || "").trim()).filter(Boolean).join(" ");
  const q = (subj || (doc.thesis || "").split(/\s+/).slice(0, 12).join(" ")).trim();
  return q.slice(0, 140);
}

export function VoicesPanel({ doc }: { doc: ThesisDoc }) {
  const q = useMemo(() => topicOf(doc), [doc]);
  const vq = useQuery({ queryKey: ["voices", q], queryFn: () => api.voices(q, 16), enabled: !!q });
  const moments = vq.data || [];
  const byGroup = GROUPS.map((g) => ({ ...g, items: moments.filter((m) => g.kinds.includes(m.kind)) })).filter((g) => g.items.length);
  const leftover = moments.filter((m) => !GROUPS.some((g) => g.kinds.includes(m.kind)));
  if (leftover.length) byGroup.push({ title: "More", kinds: [], items: leftover });

  return (
    <>
      <PageHead title="Voices" sub="Founders & investors on this space — podcasts, talks, blogs and essays from Eigen's first-person index, ranked to your thesis. How operators frame the market; a signal to explore, not graded evidence." />
      {vq.isLoading ? <Loading /> : null}
      {!vq.isLoading && moments.length === 0 ? (
        <p className="muted">No first-person voices matched this thesis's topic yet. As the Voices corpus grows, relevant podcasts, talks and essays will surface here.</p>
      ) : null}
      {byGroup.map((g) => (
        <div key={g.title} className="vc-group">
          <div className="kick">{g.title}</div>
          <div className="vc-grid">
            {g.items.map((m) => <VoiceCard key={m.id} m={m} />)}
          </div>
        </div>
      ))}
    </>
  );
}

function VoiceCard({ m }: { m: Voice }) {
  const meta = KIND_META[m.kind] || { label: m.kind, icon: "•" };
  const playable = m.media?.kind === "youtube" || m.media?.kind === "audio";
  const who = [m.speaker, m.show].filter(Boolean).join(" · ");
  const date = m.published || m.year || "";
  return (
    <a className="vc-card" href={m.url || "#"} target="_blank" rel="noreferrer noopener">
      <div className="vc-top">
        <span className="vc-badge">{meta.icon} {meta.label}</span>
        {playable ? <span className="vc-play">{m.media?.kind === "youtube" ? "▶ watch" : "▶ listen"}</span> : null}
      </div>
      {m.title ? <div className="vc-title">{m.title}</div> : null}
      {who ? <div className="vc-who">{who}</div> : null}
      {m.text ? <div className="vc-snip">{m.text}</div> : null}
      {date ? <div className="vc-date">{String(date).slice(0, 10)}</div> : null}
    </a>
  );
}
