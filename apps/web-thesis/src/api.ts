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

async function getJSON<T>(path: string, id?: string): Promise<T> {
  const r = await fetch(path, { headers: ownerHeaders(id) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d && (d as { detail?: string }).detail) || `request failed (${r.status})`);
  return d as T;
}

const enc = encodeURIComponent;

export const api = {
  theses: () => getJSON<{ theses: ThesisListItem[] }>("/theses").then((d) => d.theses || []),
  board: (limit = 60) => getJSON<{ entries: BoardCard[] }>(`/board?limit=${limit}`).then((d) => d.entries || []),
  boardEntry: (entryId: string) => getJSON<{ entry: BoardEntry }>(`/board/${enc(entryId)}`).then((d) => d.entry),
  thesis: (id: string, share?: string) =>
    getJSON<{ thesis: ThesisDoc }>(`/thesis/${enc(id)}${share ? `?share=${enc(share)}` : ""}`, id).then((d) => d.thesis),
  inquiries: (id: string, share?: string) =>
    getJSON<{ status: string } & InquiriesView>(`/thesis/${enc(id)}/inquiries${share ? `?share=${enc(share)}` : ""}`, id),
};
