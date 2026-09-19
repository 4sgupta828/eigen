// Typed API client for the thesis backend (unchanged FastAPI contract).
// Preserves the client-only owner-token capability scheme (see docs/specs/beachhead-build-plan.md §0.1).

export type Cited = { text?: string; markers?: string };
export type Analysis = { kind: string; text?: string; markers?: string };

export type TakeSection = { key: string; title: string; grounded?: Cited[]; analysis?: Analysis[] };
export type Take = { empty?: boolean; bottom_line?: Cited; sections?: TakeSection[]; findings?: number; synthesized_over?: number; truncated?: boolean; error?: string; error_detail?: string };

export type DeckSpine = { one_liner?: Cited; insight?: Cited; bottom_line?: Cited };
export type DeckSection = { key: string; title: string; headline?: Cited; points?: Cited[]; prose?: string; visual?: BsVisual };
export type SimilarThesis = { title: string; url: string; source?: string; snippet?: string };
export type Deck = { empty?: boolean; spine?: DeckSpine; sections?: DeckSection[]; references?: SimilarThesis[] };

export type CompCell = { text?: string; markers?: string; source_url?: string; source_title?: string };
export type CompPlayer = { name: string; is_subject?: boolean; cells?: Record<string, CompCell> };
export type CompCandidate = { name: string; kind?: string; note?: string };
export type CompRow = { entity: string; subject?: boolean; cells?: CompCell[] };
export type Competitive = { empty?: boolean; space?: string; reason?: string; columns?: { key: string; label: string }[]; players?: CompPlayer[]; rows?: CompRow[] };

export type Aspect = { key: string; prompt?: string; verdict?: string; critical?: boolean; settleable?: string };
export type Question = {
  id: string; text?: string; answer?: string; target_status?: string;
  aspect_key?: string; inquiry_name?: string; kind?: string; priority?: number;
};
export type Inquiry = { key: string; name?: string; framing?: string; aspects?: Aspect[]; questions?: Question[] };

export type Evidence = {
  id: string; title?: string; quote?: string; source_url?: string; register?: string;
  evidence_kind?: string; source_subject?: string; as_of?: string; side?: string; relation?: string;
  signal_only?: boolean; said_by?: string; said_role?: string; period?: string;
  source_key?: string; document_id?: string;
};
export type Claim = { rung?: string; verdict?: string; research_status?: string; evidence?: Evidence[] };

export type GenesisMemory = { open_threads?: string[]; assumptions?: string[]; shaping_prefs?: unknown };
export type Person = { name?: string; why?: string };
export type TurnPayload = {
  ready?: boolean; proposed_thesis?: string; memory?: GenesisMemory; change_rationale?: string;
  evidence?: Evidence[]; question?: string; people?: Person[]; guidance?: string; subject?: unknown;
};
export type Turn = { role: "user" | "agent"; move?: string; text?: string; payload?: TurnPayload };

export type ThesisDoc = {
  id?: string; thesis?: string; title?: string;
  subject?: Record<string, unknown>;
  claims?: Claim[]; is_owner?: boolean; board_entry?: string;
  proposed_thesis?: string; research_status?: string;
  turns?: Turn[]; versions?: Version[]; shaping_prefs?: unknown;
  pitch_deck?: Deck; collective_take?: Take; competitive?: Competitive;
  attachments?: StoredAttachment[];
};
// Intake reference material: sent as base64 (Attachment), stored text-extracted (StoredAttachment).
export type Attachment = { name: string; media_type: string; data: string };
export type StoredAttachment = { name: string; media_type?: string; chars?: number; text?: string };

export type InquiriesView = { inquiries?: Inquiry[]; deck?: Deck; take?: Take; competitive?: Competitive };

export type BoardCard = { id: string; title?: string; summary?: string; findings?: number; published_at?: string; updated_at?: string };
export type BoardEntry = {
  board_id: string; title?: string; summary?: string; findings?: number; published_at?: string; anonymous?: boolean;
  doc: ThesisDoc; inq: InquiriesView;
};
export type ThesisListItem = {
  id: string; title?: string; thesis?: string; settled?: number; claims?: number; updated_at?: string;
  // richer status for the dashboard cards (present for owned theses we could hydrate)
  draft?: boolean;
  questions?: { total: number; answered: number };
  has_brief?: boolean; has_reasoning?: boolean; has_competitive?: boolean; has_deck?: boolean;
  on_board?: boolean;
};

// ── owner-token capability store (localStorage) ────────────────────────────────
const OWNER_KEY = "eigen.thesis.owners.v1";
export function readOwners(): Record<string, string> {
  try { const v = JSON.parse(localStorage.getItem(OWNER_KEY) || "{}"); return v && typeof v === "object" ? v : {}; }
  catch { return {}; }
}
export function saveOwners(v: Record<string, string>) { try { localStorage.setItem(OWNER_KEY, JSON.stringify(v || {})); } catch { /* ignore */ } }
export function rememberOwner(id: string, token: string) { const o = readOwners(); o[id] = token; saveOwners(o); }
export function forgetOwner(id: string) { const o = readOwners(); if (o[id]) { delete o[id]; saveOwners(o); } }

function ownerHeaders(id?: string): Record<string, string> {
  const h: Record<string, string> = { "content-type": "application/json" };
  const cap = id ? readOwners()[id] : undefined;
  if (cap) h["X-Thesis-Owner"] = cap;
  const tok = readUser()?.token;             // signed-in bearer token (shared with the classic app)
  if (tok) h["x-eigen-token"] = tok;
  return h;
}

// ── identity (shared with the classic /app shell via the same localStorage key) ────────────────
export type EigenUser = { name?: string; email?: string; token?: string; verified?: boolean; disclaimer_ack?: boolean };
const USER_KEY = "eigen_user";
export function readUser(): EigenUser | null {
  try { const v = JSON.parse(localStorage.getItem(USER_KEY) || "null"); return v && typeof v === "object" ? v : null; }
  catch { return null; }
}
export function saveUser(u: EigenUser | null) {
  try { u ? localStorage.setItem(USER_KEY, JSON.stringify(u)) : localStorage.removeItem(USER_KEY); } catch { /* ignore */ }
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

// Admin-gated requests carry the admin token (never the owner cap).
async function adminReq<T>(method: string, path: string, token: string, body?: unknown): Promise<T> {
  const r = await fetch(path, { method, headers: { "content-type": "application/json", "X-Admin-Token": token },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d && (d as { detail?: string }).detail) || `request failed (${r.status})`);
  return d as T;
}
export type Disclaimer = { gate?: string; footer?: string; answer?: string };
export type AppConfig = { accounts_enabled?: boolean; console?: { heading?: string; disclaimer?: Disclaimer } };
export type AuthResp = { user?: { name?: string; email?: string; verified?: boolean; profession?: string }; token?: string };
export type SettingSpec = { value: string; default: string; override: string; options: string[]; label: string; help: string; source: string };
export type SettingsResp = { status: string; settings: Record<string, SettingSpec> };

// response shapes for the do-side
export type Version = { id: string; text?: string; parent_id?: string; source?: string; rationale?: string; at?: string; active?: boolean };
export type GenesisResp = { status: string; reply?: string; ready?: boolean; proposed_thesis?: string; versions?: Version[]; change_rationale?: string; thesis?: ThesisDoc };
// Deficiency-driven sharpening: one identified gap + one proposed rewrite at a time.
export type ThesisPillar = { key: string; label: string; addressed?: boolean; skipped?: boolean };
export type Deficiency = { done: boolean; pillar: string; pillar_label: string; deficiency: string; why: string; proposed_thesis: string; rationale: string };
export type ImproveResp = { status: string; proposal: Deficiency; skip: string[]; pillars: ThesisPillar[]; proposed_thesis?: string; versions?: Version[]; thesis?: ThesisDoc };
export type Projection = { claims?: number; projected_usd?: number; components?: Record<string, number> };
export type Run = { id: string; state: string; stage?: string; projected_usd?: number; approved_usd?: number; actual_usd?: number; metadata?: Record<string, unknown> };
export type RunResp = { status: string; projection?: Projection; run?: Run; findings?: number; selected?: number };
export type RunStatus = { status: string; run_id?: string; state?: string; stage?: string; done?: number; total?: number; actual_usd?: number; error?: Record<string, unknown> };
export type RunLevel = { level: number; label: string; total: number; answered: number; remaining: number };
export type RunPlan = { status: string; levels: RunLevel[]; answered: number; total: number; remaining: number; all_answered: boolean; next_level: number | null; next_run: number; has_take: boolean };
// ── brainstorm: a continuous, memory-bearing agent over the thesis's whole context ──
export type BrainstormMemory = { summary?: string; assumptions?: string[]; explored?: string[]; open_threads?: string[] };
export type BsSection = { kind: string; items: string[] };
export type BsDirection = { kind: string; label: string; query: string };
export type BsSourceCard = { title: string; url: string; source?: string; snippet?: string; tag?: string };
export type BsPerson = { name: string; url: string; headline?: string; org?: string };
export type BsCard = { kind: string; query?: string; cards?: BsSourceCard[]; people?: BsPerson[]; summary?: string[]; unavailable?: boolean };
export type BsBarSeries = { label: string; value: number };
export type BsTreeNode = { id: string; label: string; note?: string };
export type BsTreeEdge = { from: string; to: string; label?: string };
export type BsVisual = { kind: string; title?: string; unit?: string; series?: BsBarSeries[]; nodes?: BsTreeNode[]; edges?: BsTreeEdge[] };
export type BsContent = { text?: string; reply?: string; sections?: BsSection[]; directions?: BsDirection[]; visuals?: BsVisual[]; card?: BsCard };
export type BrainstormMsg = { id: number; role: "user" | "agent"; content: BsContent; created_at?: string };
export type BrainstormThread = { id: string; thesis_id?: string; title?: string; memory?: BrainstormMemory; messages?: BrainstormMsg[] | number; created_at?: string; updated_at?: string };

// ── voices: first-person founder/investor content (podcasts, talks, blogs, essays) ──
export type VoiceMedia = { kind?: string; id?: string; url?: string; t?: number };
export type Voice = { id: string; kind: string; text?: string; title?: string; show?: string; speaker?: string; role?: string; published?: string; year?: string; url?: string; media?: VoiceMedia; site?: string; image?: string };
export type VoiceBucket = { label: string; items: { id: string; why?: string }[] };
export type VoiceSummary = { heading?: string; points?: string[]; quotes?: string[]; sections?: { title?: string; paragraphs?: string[] }[]; note?: string; basis?: string; title?: string };

export type Candidate = { name?: string; profile_url?: string; headline?: string; org?: string; role?: string; relevance?: number; provider?: string };
export type ExpertAspect = { key: string; prompt?: string; verdict?: string; verdict_note?: string; roles?: { role: string; label: string }[]; questions?: string[]; candidates?: Candidate[]; calls?: { quote?: string; said_by?: string; said_role?: string; firm?: string; relation?: string }[]; guidance?: string };
export type Insight = { quote?: string; insight?: string; stance?: "validates" | "invalidates" | "context"; refers_to?: string };
export type TranscriptResp = { status: string; id?: string; inquiry_key?: string; insights?: Insight[]; tally?: { validates?: number; invalidates?: number; context?: number }; note?: string };

type CreateResp = { status: string; id: string; owner_token?: string | null; thesis: ThesisDoc; projection?: Projection };

export const api = {
  // ── reads ──
  theses: () => getJSON<{ theses: ThesisListItem[] }>("/theses").then((d) => d.theses || []),
  // The user's theses = server list (if signed in) + every thesis this device created (owner tokens in
  // localStorage), reconstructed by fetching each — so anonymously-created theses still show up.
  async myTheses(): Promise<ThesisListItem[]> {
    const ids = Object.keys(readOwners());
    // Hydrate each owned thesis into a rich dashboard card: doc gives claims + which artifacts exist
    // (brief/reasoning/competitive/deck); the run plan gives drafted-vs-answered question counts.
    const has = (v: unknown) => !!v && typeof v === "object" && Object.keys(v as object).length > 0;
    const hydrate = async (id: string): Promise<ThesisListItem | null> => {
      try {
        const d = (await getJSON<{ thesis: ThesisDoc }>(`/thesis/${enc(id)}`, id)).thesis;
        if (!d?.id) return null;
        const claims = d.claims || [];
        const settled = claims.filter((c) => { const s = c.research_status || c.verdict; return s && s !== "open"; }).length;
        const draft = !claims.length;
        const item: ThesisListItem = {
          id: d.id, thesis: d.thesis, title: d.title, claims: claims.length, settled, draft,
          has_brief: has(d.collective_take), has_reasoning: has(d.collective_take),
          has_competitive: !!(d.competitive?.players || []).length, has_deck: has(d.pitch_deck),
          on_board: !!d.board_entry,
        };
        if (!draft) {
          const plan = await api.runPlan(id).catch(() => null);
          if (plan) {
            item.questions = { total: plan.total || 0, answered: plan.answered || 0 };
            if (plan.has_take) { item.has_brief = true; item.has_reasoning = true; }
          }
        }
        return item;
      } catch { return null; }
    };
    const [server, owned] = await Promise.all([
      getJSON<{ theses: ThesisListItem[] }>("/theses").then((d) => d.theses || []).catch(() => [] as ThesisListItem[]),
      Promise.all(ids.map(hydrate)),
    ]);
    const list: ThesisListItem[] = [];
    const seen = new Set<string>();
    const add = (t: ThesisListItem) => { if (t.id && !seen.has(t.id)) { seen.add(t.id); list.push(t); } };
    owned.forEach((t) => { if (t) add(t); });
    server.forEach(add);
    return list;
  },
  deleteThesis: (id: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}`, undefined, id),
  // ── identity gate (shared /auth + /config contract with the classic shell) ──
  config: () => getJSON<AppConfig>("/config"),
  authRegister: (b: { email: string; password: string; name: string; country?: string }) =>
    req<AuthResp>("POST", "/auth/register", { ...b, disclaimer_ack: true }),
  authLogin: (b: { email: string; password: string }) => req<AuthResp>("POST", "/auth/login", b),
  adminAllTheses: (token: string) => adminReq<{ status: string; theses: ThesisListItem[] }>("GET", "/thesis/admin/theses", token).then((d) => d.theses || []),
  adminAdopt: (token: string, thesis_id: string) => adminReq<{ status: string; thesis_id: string; owner_token: string }>("POST", "/thesis/admin/adopt", token, { thesis_id }),
  adminDeleteThesis: (token: string, thesis_id: string) => adminReq<{ status: string }>("POST", "/thesis/admin/delete", token, { thesis_id }),
  board: (limit = 60) => getJSON<{ entries: BoardCard[] }>(`/board?limit=${limit}`).then((d) => d.entries || []),
  boardEntry: (entryId: string) => getJSON<{ entry: BoardEntry }>(`/board/${enc(entryId)}`).then((d) => d.entry),
  thesis: (id: string, share?: string) =>
    getJSON<{ thesis: ThesisDoc }>(`/thesis/${enc(id)}${share ? `?share=${enc(share)}` : ""}`, id).then((d) => d.thesis),
  inquiries: (id: string, share?: string) =>
    getJSON<{ status: string } & InquiriesView>(`/thesis/${enc(id)}/inquiries${share ? `?share=${enc(share)}` : ""}`, id),

  // ── intake / genesis ──  (create returns owner_token → persisted here)
  async create(thesis: string, draft = true, attachments?: Attachment[]): Promise<CreateResp> {
    const d = await req<CreateResp>("POST", "/thesis", { thesis, draft, ...(attachments && attachments.length ? { attachments } : {}) });
    if (d.id && d.owner_token) rememberOwner(d.id, d.owner_token);
    return d;
  },
  genesis: (id: string, text: string, attachments?: Attachment[]) =>
    req<GenesisResp>("POST", `/thesis/${enc(id)}/genesis`, { text, ...(attachments && attachments.length ? { attachments } : {}) }, id),
  confirm: (id: string, thesis: string, max_usd = 5, project_only = false) =>
    req<{ status: string; projection?: Projection; thesis?: ThesisDoc; reason?: string }>("POST", `/thesis/${enc(id)}/confirm`, { thesis, max_usd, project_only }, id),
  sample: () => req<{ thesis: string }>("POST", "/thesis/sample").then((d) => d.thesis),
  versions: (id: string) => getJSON<{ versions: Version[] }>(`/thesis/${enc(id)}/versions`, id).then((d) => d.versions || []),
  revert: (id: string, version_id: string) => req<GenesisResp>("POST", `/thesis/${enc(id)}/revert`, { version_id }, id),
  editThesis: (id: string, text: string) => req<GenesisResp>("POST", `/thesis/${enc(id)}/edit`, { text }, id),
  improve: (id: string, body?: { action?: string; pillar?: string; proposed_thesis?: string }) =>
    req<ImproveResp>("POST", `/thesis/${enc(id)}/improve`, { action: "propose", ...(body || {}) }, id),

  // ── plan ──
  generate: (id: string) => req<RunResp>("POST", `/thesis/${enc(id)}/inquiries/generate`, undefined, id),
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
  runPlan: (id: string) => getJSON<RunPlan>(`/thesis/${enc(id)}/inquiries/run_plan`, id),
  runQuestion: (id: string, qid: string, max_usd: number) =>
    req<RunResp>("POST", `/thesis/${enc(id)}/question/${enc(qid)}/run`, { max_usd, web: true, idempotency_key: max_usd > 0 ? `q-${qid}-${Date.now()}` : undefined }, id),
  inquiryStatus: (id: string, run: string) => getJSON<RunStatus>(`/thesis/${enc(id)}/inquiry/status?run=${enc(run)}`, id),
  cancelRun: (id: string, run?: string) => req<{ status: string; run_id?: string | null }>("POST", `/thesis/${enc(id)}/inquiry/cancel${run ? `?run=${enc(run)}` : ""}`, {}, id),
  activeRun: (id: string) => getJSON<{ run: Run | null; kind: string; thread_id?: string }>(`/thesis/${enc(id)}/inquiry/active`, id),
  synthesize: (id: string) => req<{ status: string; take?: Take; deck?: Deck; competitive?: Competitive; findings?: number }>("POST", `/thesis/${enc(id)}/synthesize`, undefined, id),
  buildDeck: (id: string) => req<RunResp>("POST", `/thesis/${enc(id)}/deck`, undefined, id),
  // rebuild the read (take) + deck as ONE async, stoppable background run
  regenerate: (id: string) => req<RunResp>("POST", `/thesis/${enc(id)}/regenerate`, undefined, id),

  // ── brainstorm: a continuous, memory-bearing agent over the thesis's whole context ──
  bsThreads: (id: string) => getJSON<{ status: string; threads: BrainstormThread[] }>(`/thesis/${enc(id)}/brainstorm/threads`, id).then((d) => d.threads || []),
  bsThread: (id: string, tid: string) => getJSON<{ status: string; thread: BrainstormThread }>(`/thesis/${enc(id)}/brainstorm/thread/${enc(tid)}`, id).then((d) => d.thread),
  bsNewThread: (id: string, title = "") => req<{ status: string; thread: BrainstormThread }>("POST", `/thesis/${enc(id)}/brainstorm/thread`, { title }, id).then((d) => d.thread),
  bsRenameThread: (id: string, tid: string, title: string) => req<{ status: string }>("PATCH", `/thesis/${enc(id)}/brainstorm/thread/${enc(tid)}`, { title }, id),
  bsDeleteThread: (id: string, tid: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}/brainstorm/thread/${enc(tid)}`, undefined, id),
  bsMessage: (id: string, tid: string, text: string) => req<RunResp>("POST", `/thesis/${enc(id)}/brainstorm/thread/${enc(tid)}/message`, { text }, id),
  bsExpand: (id: string, tid: string, leg: string, query: string) => req<RunResp>("POST", `/thesis/${enc(id)}/brainstorm/thread/${enc(tid)}/expand`, { leg, query }, id),

  // ── competitive research (projection via max_usd:0 → refused+projection; then run with the approved budget) ──
  competitiveResearch: (id: string, max_usd: number) =>
    req<RunResp>("POST", `/thesis/${enc(id)}/competitive/research`, { max_usd, web: true, idempotency_key: max_usd > 0 ? "comp-" + Date.now() : undefined }, id),
  // suggest MORE competitors to add (cheap, names only), then profile + append the chosen ones (gated)
  competitiveCandidates: (id: string) =>
    req<{ status: string; candidates?: CompCandidate[]; space?: string; unavailable?: boolean }>("POST", `/thesis/${enc(id)}/competitive/candidates`, {}, id),
  competitiveAdd: (id: string, names: string[], max_usd: number) =>
    req<RunResp & { selected?: number }>("POST", `/thesis/${enc(id)}/competitive/add`, { names, max_usd, idempotency_key: max_usd > 0 ? "compadd-" + Date.now() : undefined }, id),

  // ── voices: first-person founder/investor content relevant to the thesis (Voices corpus) ──
  voices: (q: string, limit = 14, kinds?: string[]) => req<{ moments: Voice[] }>("POST", "/voices/search", { q, limit, ...(kinds && kinds.length ? { kinds } : {}) }).then((d) => d.moments || []),
  voicesOrganize: (id: string, moments: { id: string; kind: string; title?: string; snippet?: string; speaker?: string; show?: string }[], refresh = false) =>
    req<{ status: string; buckets: VoiceBucket[]; cached?: boolean }>("POST", `/thesis/${enc(id)}/voices/organize`, { moments, refresh }, id).then((d) => d.buckets || []),
  voiceSummary: (momentId: string, refresh = false) => req<VoiceSummary>("POST", "/voices/summary", { id: momentId, refresh }),

  // ── experts + transcripts ──
  experts: (id: string) => getJSON<{ status: string; aspects: ExpertAspect[] }>(`/thesis/${enc(id)}/experts`, id).then((d) => d.aspects || []),
  discoverExperts: (id: string, aspect_key: string) => req<{ status: string; candidates?: Candidate[]; unavailable?: boolean }>("POST", `/thesis/${enc(id)}/experts/discover`, { aspect_key }, id),
  uploadTranscript: (id: string, inquiry_key: string, b: { expert_name?: string; expert_url?: string; firm?: string; role?: string; transcript: string; save_to_roster?: boolean }) =>
    req<TranscriptResp>("POST", `/thesis/${enc(id)}/inquiry/${enc(inquiry_key)}/transcript`, { save_to_roster: true, ...b }, id),
  transcripts: (id: string) => getJSON<{ status: string; by_line: Record<string, unknown[]> }>(`/thesis/${enc(id)}/transcripts`, id).then((d) => d.by_line || {}),

  // ── admin settings (runtime toggles, admin-token gated) ──
  adminSettings: (token: string) => adminReq<SettingsResp>("GET", "/thesis/admin/settings", token),
  adminSetSetting: (token: string, key: string, value: string) => adminReq<SettingsResp>("POST", "/thesis/admin/settings", token, { key, value }),

  // ── share / board ──
  share: (id: string) => req<{ status: string; share_token: string }>("POST", `/thesis/${enc(id)}/share`, {}, id).then((d) => d.share_token),
  unshare: (id: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}/share`, undefined, id),
  publish: (id: string) => req<{ status: string; board_id: string }>("POST", `/thesis/${enc(id)}/publish`, {}, id).then((d) => d.board_id),
  unpublish: (id: string) => req<{ status: string }>("DELETE", `/thesis/${enc(id)}/publish`, undefined, id),
};
