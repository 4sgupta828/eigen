// Typed API client for the thesis backend (unchanged FastAPI contract).
// Preserves the client-only owner-token capability scheme (see docs/specs/beachhead-build-plan.md §0.1).

export type Cited = { text?: string; markers?: string };
export type Analysis = { kind: string; text?: string; markers?: string };

export type TakeSection = { key: string; title: string; grounded?: Cited[]; analysis?: Analysis[] };
export type Take = { empty?: boolean; bottom_line?: Cited; sections?: TakeSection[] };

export type DeckSpine = { one_liner?: Cited; insight?: Cited; bottom_line?: Cited };
export type DeckSection = { key: string; title: string; headline?: Cited; points?: Cited[]; prose?: string };
export type Deck = { empty?: boolean; spine?: DeckSpine; sections?: DeckSection[] };

export type CompCell = { text?: string; markers?: string; source_url?: string; source_title?: string };
export type CompPlayer = { name: string; is_subject?: boolean; cells?: Record<string, CompCell> };
export type CompRow = { entity: string; subject?: boolean; cells?: CompCell[] };
export type Competitive = { empty?: boolean; columns?: { key: string; label: string }[]; players?: CompPlayer[]; rows?: CompRow[] };

export type Aspect = { key: string; prompt?: string; verdict?: string; critical?: boolean; settleable?: string };
export type Question = {
  id: string; text?: string; answer?: string; target_status?: string;
  aspect_key?: string; inquiry_name?: string;
};
export type Inquiry = { key: string; name?: string; framing?: string; aspects?: Aspect[]; questions?: Question[] };

export type Evidence = {
  id: string; title?: string; quote?: string; source_url?: string; register?: string;
  evidence_kind?: string; source_subject?: string; as_of?: string; side?: string; relation?: string;
};
export type Claim = { rung?: string; evidence?: Evidence[] };

export type ThesisDoc = {
  id?: string; thesis?: string; title?: string;
  subject?: Record<string, unknown>;
  claims?: Claim[]; is_owner?: boolean; board_entry?: string;
  proposed_thesis?: string; research_status?: string;
  pitch_deck?: Deck; collective_take?: Take; competitive?: Competitive;
};

export type InquiriesView = { inquiries?: Inquiry[]; deck?: Deck; take?: Take; competitive?: Competitive };

export type BoardCard = { id: string; title?: string; summary?: string; findings?: number; published_at?: string; updated_at?: string };
export type BoardEntry = {
  board_id: string; title?: string; summary?: string; findings?: number; published_at?: string; anonymous?: boolean;
  doc: ThesisDoc; inq: InquiriesView;
};
export type ThesisListItem = { id: string; title?: string; thesis?: string; settled?: number; claims?: number; updated_at?: string };

// ── owner-token capability store (localStorage) ────────────────────────────────
const OWNER_KEY = "eigen.thesis.owners.v1";
export function readOwners(): Record<string, string> {
  try { const v = JSON.parse(localStorage.getItem(OWNER_KEY) || "{}"); return v && typeof v === "object" ? v : {}; }
  catch { return {}; }
}
export function saveOwners(v: Record<string, string>) { try { localStorage.setItem(OWNER_KEY, JSON.stringify(v || {})); } catch { /* ignore */ } }
export function rememberOwner(id: string, token: string) { const o = readOwners(); o[id] = token; saveOwners(o); }

function ownerHeaders(id?: string): Record<string, string> {
  const h: Record<string, string> = { "content-type": "application/json" };
  const cap = id ? readOwners()[id] : undefined;
  if (cap) h["X-Thesis-Owner"] = cap;
  // (a signed-in bearer token would be attached here too, once the account model is ported)
  return h;
}

async function req<T>(method: string, path: string, body?: unknown, id?: string): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: ownerHeaders(id),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d && (d as { detail?: string }).detail) || `request failed (${r.status})`);
  return d as T;
}
const getJSON = <T,>(p: string, id?: string) => req<T>("GET", p, undefined, id);
const enc = encodeURIComponent;

// response shapes for the do-side
export type Version = { id: string; text?: string; parent_id?: string; source?: string; rationale?: string; at?: string; active?: boolean };
export type GenesisResp = { status: string; reply?: string; ready?: boolean; proposed_thesis?: string; versions?: Version[]; change_rationale?: string; thesis?: ThesisDoc };
export type Projection = { claims?: number; projected_usd?: number; components?: Record<string, number> };
export type Run = { id: string; state: string; stage?: string; projected_usd?: number; approved_usd?: number; actual_usd?: number; metadata?: Record<string, unknown> };
export type RunResp = { status: string; projection?: Projection; run?: Run; findings?: number; selected?: number };
export type RunStatus = { status: string; run_id?: string; state?: string; stage?: string; done?: number; total?: number; actual_usd?: number; error?: Record<string, unknown> };
export type Candidate = { name?: string; profile_url?: string; headline?: string; org?: string; role?: string; relevance?: number; provider?: string };
export type ExpertAspect = { key: string; prompt?: string; verdict?: string; verdict_note?: string; roles?: { role: string; label: string }[]; questions?: string[]; candidates?: Candidate[]; calls?: { quote?: string; said_by?: string; said_role?: string; firm?: string; relation?: string }[]; guidance?: string };
export type Insight = { quote?: string; insight?: string; stance?: "validates" | "invalidates" | "context"; refers_to?: string };
export type TranscriptResp = { status: string; id?: string; inquiry_key?: string; insights?: Insight[]; tally?: { validates?: number; invalidates?: number; context?: number }; note?: string };

type CreateResp = { status: string; id: string; owner_token?: string | null; thesis: ThesisDoc; projection?: Projection };

export const api = {
  // ── reads ──
  theses: () => getJSON<{ theses: ThesisListItem[] }>("/theses").then((d) => d.theses || []),
  board: (limit = 60) => getJSON<{ entries: BoardCard[] }>(`/board?limit=${limit}`).then((d) => d.entries || []),
  boardEntry: (entryId: string) => getJSON<{ entry: BoardEntry }>(`/board/${enc(entryId)}`).then((d) => d.entry),
  thesis: (id: string, share?: string) =>
    getJSON<{ thesis: ThesisDoc }>(`/thesis/${enc(id)}${share ? `?share=${enc(share)}` : ""}`, id).then((d) => d.thesis),
  inquiries: (id: string, share?: string) =>
    getJSON<{ status: string } & InquiriesView>(`/thesis/${enc(id)}/inquiries${share ? `?share=${enc(share)}` : ""}`, id),

  // ── intake / genesis ──  (create returns owner_token → persisted here)
  async create(thesis: string, draft = true): Promise<CreateResp> {
    const d = await req<CreateResp>("POST", "/thesis", { thesis, draft });
    if (d.id && d.owner_token) rememberOwner(d.id, d.owner_token);
    return d;
  },
  genesis: (id: string, text: string) => req<GenesisResp>("POST", `/thesis/${enc(id)}/genesis`, { text }, id),
  confirm: (id: string, thesis: string, max_usd = 5, project_only = false) =>
    req<{ status: string; projection?: Projection; thesis?: ThesisDoc; reason?: string }>("POST", `/thesis/${enc(id)}/confirm`, { thesis, max_usd, project_only }, id),
  sample: () => req<{ thesis: string }>("POST", "/thesis/sample").then((d) => d.thesis),
  versions: (id: string) => getJSON<{ versions: Version[] }>(`/thesis/${enc(id)}/versions`, id).then((d) => d.versions || []),
  revert: (id: string, version_id: string) => req<GenesisResp>("POST", `/thesis/${enc(id)}/revert`, { version_id }, id),

  // ── plan ──
  generate: (id: string) => req<{ status: string } & InquiriesView>("POST", `/thesis/${enc(id)}/inquiries/generate`, undefined, id),
  prioritize: (id: string) => req<{ status: string } & InquiriesView>("POST", `/thesis/${enc(id)}/inquiries/prioritize`, undefined, id),
  addQuestion: (id: string, b: { inquiry_key: string; aspect_key: string; text: string; target: string; kind?: string; polarity?: number }) =>
    req<{ status: string; id: string }>("POST", `/thesis/${enc(id)}/question`, { kind: "seek_support", polarity: 1, ...b }, id),
  editQuestion: (id: string, qid: string, b: { text: string; target: string }) =>
    req<{ status: string; id: string }>("PATCH", `/thesis/${enc(id)}/question/${enc(qid)}`, b, id),
  deleteQuestion: (id: string, qid: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}/question/${enc(qid)}`, undefined, id),

  // ── run (project via max_usd:0 → refused+projection; then run with the approved budget) ──
  projectRun: (id: string) => req<RunResp>("POST", `/thesis/${enc(id)}/inquiries/run`, { max_usd: 0, web: true }, id),
  runAll: (id: string, max_usd: number) => req<RunResp>("POST", `/thesis/${enc(id)}/inquiries/run`, { max_usd, web: true }, id),
  runCritical: (id: string, max_usd: number, level = 0) => req<RunResp>("POST", `/thesis/${enc(id)}/inquiries/run_critical`, { max_usd, level, web: true }, id),
  inquiryStatus: (id: string, run: string) => getJSON<RunStatus>(`/thesis/${enc(id)}/inquiry/status?run=${enc(run)}`, id),
  synthesize: (id: string) => req<{ status: string; take?: Take; deck?: Deck; competitive?: Competitive; findings?: number }>("POST", `/thesis/${enc(id)}/synthesize`, undefined, id),
  buildDeck: (id: string) => req<{ status: string; deck?: Deck; findings?: number }>("POST", `/thesis/${enc(id)}/deck`, undefined, id),

  // ── experts + transcripts ──
  experts: (id: string) => getJSON<{ status: string; aspects: ExpertAspect[] }>(`/thesis/${enc(id)}/experts`, id).then((d) => d.aspects || []),
  discoverExperts: (id: string, aspect_key: string) => req<{ status: string; candidates?: Candidate[]; unavailable?: boolean }>("POST", `/thesis/${enc(id)}/experts/discover`, { aspect_key }, id),
  uploadTranscript: (id: string, inquiry_key: string, b: { expert_name?: string; expert_url?: string; firm?: string; role?: string; transcript: string; save_to_roster?: boolean }) =>
    req<TranscriptResp>("POST", `/thesis/${enc(id)}/inquiry/${enc(inquiry_key)}/transcript`, { save_to_roster: true, ...b }, id),
  transcripts: (id: string) => getJSON<{ status: string; by_line: Record<string, unknown[]> }>(`/thesis/${enc(id)}/transcripts`, id).then((d) => d.by_line || {}),

  // ── share / board ──
  share: (id: string) => req<{ status: string; share_token: string }>("POST", `/thesis/${enc(id)}/share`, {}, id).then((d) => d.share_token),
  unshare: (id: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}/share`, undefined, id),
  publish: (id: string) => req<{ status: string; board_id: string }>("POST", `/thesis/${enc(id)}/publish`, {}, id).then((d) => d.board_id),
  unpublish: (id: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}/publish`, undefined, id),
};
