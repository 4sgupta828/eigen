"""GUIDED search for startups — roster's guided intake adapted: the shortest path from a vague thesis to a contract
the rail can run. No artifact here (no résumé, no JD); the "artifact" is the thesis in the investor's words.

Flow (one turn at a time, stateless — the state rides the request):
  opening words → compile (the existing brief compiler) → questions, in order:
    REQUIRED  what they build (tech_area) · stage (centre, never a must — the record states rounds for few)
    OPTIONAL  asked only when the answer would change the results: the counts over the current slice are spread on
              the key, the key is not already constrained, and the ask budget remains
  → READY: "what I understood" in plain words, the contract as chips, the pool size, advice — nothing runs until
    the user taps Search. "Search now" ends it from any turn.
Code decides WHETHER to ask (`eigen_kernel.facets.intake`); the words, keys and how an answer lands are here; a
model maps a TYPED reply onto the pending question (one small JSON call; a chip tap costs nothing)."""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from eigen_kernel.facets import Contract, edit, validate_contract
from eigen_kernel.facets.intake import IntakeState, Question, apply_answer, next_question, search_now, spread

from .schema import KIND, SCHEMA, VALUE_LABELS

TRANSCRIPT_CAP, MSG_CAP = 40, 1500

# the keys the intake must know before a search runs, and the keys it may ask about when the pool splits on them
REQUIRED_KEYS = ["tech_area", "stage"]
OPTIONAL_KEYS = ["total_disclosed_funding", "country", "last_round_months", "founder_count", "program", "customer", "business_model", "hiring", "metro"]
# how an answer lands: a must (a promise the index keeps), a prefer, or the centre; numeric bands become a range
LANDING = {"tech_area": "must", "stage": "center", "country": "must", "metro": "must", "program": "must", "customer": "prefer",
           "business_model": "prefer", "total_disclosed_funding": "must", "last_round_months": "must", "founder_count": "must", "hiring": "must"}
QUESTION_WORDS = {
    "tech_area": ("What do they build?", "one or more areas — the index counts are shown"),
    "stage": ("What stage are you looking at?", "results centre on it; nearby stages still show, further ones rank lower"),
    "country": ("Where should they be based?", "a country, or skip for anywhere"),
    "metro": ("Any particular metro?", ""),
    "total_disclosed_funding": ("Any floor on disclosed funding?", "from SEC filings and stated rounds; startups with no disclosed funding would drop out"),
    "last_round_months": ("How recent should the last round be?", "a window on the latest filing or stated round"),
    "founder_count": ("How many founders?", "named founders on record"),
    "program": ("Only companies from a particular program?", "Y Combinator is the only program indexed so far"),
    "customer": ("Who should they sell to?", "as their own site states it"),
    "business_model": ("A particular business model?", "as their own site states it"),
    "hiring": ("Only companies that are hiring right now?", "open roles on their job board"),
}
SKIP_WORDS = {"tech_area": "Any area", "stage": "Any stage", "country": "Anywhere", "metro": "Any metro", "total_disclosed_funding": "No floor",
              "last_round_months": "Any time", "founder_count": "Any number", "program": "Any program", "customer": "Any customer",
              "business_model": "Any model", "hiring": "Hiring or not"}
BAND_MIN = {"total_disclosed_funding": {"under_1m": None, "1m_5m": 1e6, "5m_20m": 5e6, "20m_50m": 20e6, "50m_100m": 50e6, "100m_plus": 100e6},
            "founder_count": {"1": (1, 1), "2": (2, 2), "3": (3, 3), "4_plus": (4, None)},
            "last_round_months": {"0_6": (0, 6), "6_12": (0, 12), "12_24": (0, 24), "24_plus": (24, None)}}


def option_label(key: str, value: str) -> str:
    return VALUE_LABELS.get(value) or str(value).replace("_", " ")


def option_hint(key: str, value: str) -> str:
    if key == "total_disclosed_funding":
        return "at least " + option_label(key, value).replace("< ", "under ")
    if key == "last_round_months":
        return "within " + option_label(key, value)
    return ""


def turn_prompt(pending: dict | None) -> str:
    keys = REQUIRED_KEYS + OPTIONAL_KEYS
    vocab = "; ".join(f"{k.key}: {', '.join(k.values) if k.values else 'bands ' + ', '.join(b[0] for b in k.bands) if k.bands else 'free lowercase token'}"
                      for k in SCHEMA.for_kind(KIND) if k.key in keys)
    asked = f'The user was asked: "{pending["words"]}" (key {pending["key"]}).' if pending else "No question is pending."
    return (f"You are the intake for a STARTUP search (an investor describing a thesis). {asked} The user replied. Map the reply onto that "
            "question and onto any other key it CLEARLY states. Return ONLY JSON: {\"answers\": {key: value | [values] | null}, \"free_text\": "
            "\"the reply's own words for anything that fits no key\", \"search_now\": true|false}. A value must be one of the key's vocabulary "
            f"tokens or bands ({vocab}); null means the user declined or skipped ('any', 'doesn't matter', 'skip'). search_now is true when the "
            "user says to just run it. Never guess; never add an answer the reply does not state.")


def understood_words(contract: dict, answers: dict | None = None) -> str:
    c = contract or {}
    parts = []
    musts = []
    for k, vs in (c.get("must") or {}).items():
        if isinstance(vs, dict):
            lab = SCHEMA.key(k).label.lower() if SCHEMA.key(k) else k
            rng = " to ".join(x for x in ((f"≥ {_usd(vs['min'])}" if vs.get("min") is not None and SCHEMA.key(k).unit == "usd" else f"≥ {vs['min']:g}" if vs.get("min") is not None else ""),
                                          (f"≤ {_usd(vs['max'])}" if vs.get("max") is not None and SCHEMA.key(k).unit == "usd" else f"≤ {vs['max']:g}" if vs.get("max") is not None else "")) if x)
            musts.append(f"{lab} {rng}")
        else:
            musts.append(", ".join(option_label(k, v) for v in vs))
    base = "Startups" + (f" matching “{c.get('text')}”" if c.get("text") else "")
    parts.append(base + (" that must be " + "; ".join(musts) if musts else ""))
    ex = (c.get("scope") or {}).get("exclude") or {}
    if ex:
        parts.append("excluding " + ", ".join(option_label(k, v) for k, vs in ex.items() for v in vs))
    prefers = [option_label(k, v) for k, vs in (c.get("prefer") or {}).items() if isinstance(vs, list) for v in vs]
    if prefers:
        parts.append("preferring " + ", ".join(prefers))
    ctr = c.get("center") or {}
    if ctr.get("key"):
        parts.append(f"centred on {option_label('stage', str(ctr.get('value')))}")
    return "; ".join(parts) + "."


def _centre_from_stage(c: Contract) -> Contract:
    """A stage the brief names (the compiler files it as a prefer, since few startups state a round) becomes the centre."""
    if not c.center:
        stages = (c.prefer or {}).get("stage") or (c.must or {}).get("stage") or []
        if isinstance(stages, list) and stages:
            c.center = {"key": "stage", "value": stages[0], "span": 1}
            if "stage" in (c.must or {}):
                c.prefer["stage"] = sorted(set(c.prefer.get("stage", [])) | set(c.must.pop("stage")))
    return c


def _merge(base: Contract, new: Contract) -> Contract:
    """The refinement's filters land ON TOP of the established contract: a new must replaces the same key, prefers
    and exclusions union, the centre and the text follow the refinement when it states them."""
    out = Contract.from_dict(base.to_dict())
    for k, v in (new.must or {}).items():
        out.must[k] = v
    for k, v in (new.prefer or {}).items():
        out.prefer[k] = sorted(set(out.prefer.get(k, [])) | set(v)) if isinstance(v, list) else v
    ex = dict((out.scope or {}).get("exclude") or {})
    for k, v in ((new.scope or {}).get("exclude") or {}).items():
        ex[k] = sorted(set(ex.get(k, [])) | set(v))
    if ex:
        out.scope = {**(out.scope or {}), "exclude": ex}
    if new.center:
        out.center = new.center
    if new.text:
        out.text = (out.text + " " + new.text).strip()[:200]
    return out


def _usd(x) -> str:
    x = float(x or 0)
    return f"${x / 1e9:.1f}B" if x >= 1e9 else f"${x / 1e6:.0f}M" if x >= 1e6 else f"${x / 1e3:.0f}k" if x >= 1e3 else f"${x:.0f}"


# A question is a choice, not a catalogue: past twenty options people stop reading and start scrolling.
_MAX_OPTIONS = 20


class StartupIntake:
    def __init__(self, *, llm_json: Callable[[str, str], Awaitable[dict]] | None, counts_fn: Callable[[dict, dict], Awaitable[dict]], compile_fn,
                 slice_fn=None, coverage_fn=None):
        self.llm_json = llm_json
        self.counts_fn = counts_fn          # async (must, exclude) → counts per key (with "_total")
        self.compile_fn = compile_fn        # async (text) → (Contract, notes)
        self.slice_fn = slice_fn            # async (must, exclude) → bounded pool size (the structural probe); None = no probes
        self.coverage_fn = coverage_fn      # async () → {"known_rate": {...}}

    def user_keys(self, st: IntakeState) -> set:
        """The user's OWN constraints: keys they answered in the intake (never relaxed by any index-aware rule)."""
        return {k for k in st.asked if k in ((st.contract or {}).get("must") or {})}

    # ---------------- pieces ----------------
    async def _counts(self, st: IntakeState) -> dict:
        c = st.contract or {}
        try:
            return await self.counts_fn(c.get("must") or {}, (c.get("scope") or {}).get("exclude") or {}) or {}
        except Exception:   # noqa: BLE001 — counts are an aid; the intake proceeds without options
            return {}

    def _question_payload(self, q: Question, counts: dict) -> dict:
        words, hint = QUESTION_WORDS.get(q.name, (f"{q.name.replace('_', ' ')}?", ""))
        k = SCHEMA.key(q.name)
        opts = q.options
        if k is not None and k.type.value in ("ordinal", "numeric"):
            # ordered vocabularies show every step in order, with the slice's count (0 where the index knows none —
            # stage is stated for few, and the user still needs to choose it)
            order = list(k.values) if k.values else [b[0] for b in k.bands]
            have = {v: n for v, n in opts}
            opts = [(v, int(have.get(v, (counts.get(q.name) or {}).get(v, 0)))) for v in order]
        elif k is not None and k.type.value == "categorical":
            # Most common first (the kernel's top-6 is too few for a key like tech area). Offering the
            # WHOLE vocabulary stopped scaling at thirty areas: a value the index has nothing under is
            # a filter that returns nothing, so it is not offered — except the catch-alls, which are
            # how someone says "none of these".
            have = {v: n for v, n in opts}
            allc = {v: int(have.get(v, (counts.get(q.name) or {}).get(v, 0))) for v in k.values}
            keep = [kv for kv in allc.items() if kv[1] > 0 or kv[0] in ("other", "unknown")]
            opts = sorted(keep or list(allc.items()), key=lambda kv: (-kv[1], k.values.index(kv[0])))[:_MAX_OPTIONS]
        return {"kind": "key", "name": q.name, "key": q.name, "words": words, "hint": hint, "klass": q.klass,
                "options": [[v, option_label(q.name, v), int(n), option_hint(q.name, v)] for v, n in opts],
                "skip": SKIP_WORDS.get(q.name, "Skip"), "free_text": True,
                "multi": bool(k is not None and k.type.value == "categorical" and q.name not in ("program",)) or q.name in ("country", "metro")}

    def _next(self, st: IntakeState, counts: dict) -> Question | None:
        return next_question(st, required_items=[], required_keys=REQUIRED_KEYS, optional_keys=OPTIONAL_KEYS, counts=counts)

    def _apply(self, st: IntakeState, q: Question, value) -> IntakeState:
        """An answer lands per LANDING: stage → centre (+ prefer); numeric bands → a must range; the rest → must / prefer."""
        if value is None or value == [] or value == "":
            return apply_answer(st, q, None)
        vals = [str(v) for v in (value if isinstance(value, (list, tuple)) else [value])]
        landing = LANDING.get(q.name, "prefer")
        k = SCHEMA.key(q.name)
        if q.name == "stage":
            v = next((x for x in vals if SCHEMA.validate_value("stage", x)), None)
            if not v:
                return apply_answer(st, q, None)
            n = apply_answer(st, q, v)
            c = Contract.from_dict(n.contract)
            c.center = {"key": "stage", "value": SCHEMA.validate_value("stage", v), "span": 1}
            c = edit(c, "stage", SCHEMA.validate_value("stage", v), "prefer")
            n.contract = c.to_dict()
            return n
        if k is not None and k.type.value == "numeric":
            n = apply_answer(st, q, vals[0])
            c = Contract.from_dict(n.contract)
            band = BAND_MIN.get(q.name, {}).get(vals[0])
            rng = None
            if q.name == "total_disclosed_funding":
                rng = {"min": float(band)} if band else None
            elif isinstance(band, tuple):
                lo, hi = band
                rng = {**({"min": float(lo)} if lo is not None else {}), **({"max": float(hi)} if hi is not None else {})}
            if q.name == "hiring":
                rng = {"min": 1.0} if vals[0] in ("yes", "1_5", "6_20", "20_plus") else None
            if rng:
                c.must[q.name] = rng
            n.contract = c.to_dict()
            return n
        legal = [SCHEMA.validate_value(q.name, v) for v in vals]
        legal = [v for v in legal if v]
        if not legal:
            return apply_answer(st, q, None)
        return apply_answer(st, q, legal if len(legal) > 1 else legal[0], mode=("must" if landing == "must" else "prefer"))

    def _pool(self, counts: dict) -> int:
        return int(counts.get("_total") or 0)

    def _advice(self, counts: dict) -> list[str]:
        nav = [k for k in SCHEMA.for_kind(KIND) if k.navigable and k.type.value != "set"]
        scored = sorted(((spread(counts.get(k.key))[0], k.label.lower()) for k in nav if spread(counts.get(k.key))[1] >= 0.5 and spread(counts.get(k.key))[0] >= 0.3), reverse=True)
        out = []
        if scored:
            out.append("This pool splits most on " + " and ".join(n for _, n in scored[:2]) + " — those chips narrow it fastest.")
        unknowns = [k.label.lower() for k in nav if counts.get(k.key) and spread(counts.get(k.key))[1] < 0.5]
        if unknowns:
            out.append("Mostly unknown here: " + ", ".join(unknowns[:3]) + " — a must on those would filter by absence.")
        out.append("Open a card's evidence for every quote and source; ☆ Save as map keeps the search with revisions.")
        return out

    async def _ready(self, st: IntakeState, counts: dict, transcript: list, notes: list) -> dict:
        from . import contract_search as cs
        c = Contract.from_dict(st.contract)
        if validate_contract(c, SCHEMA):
            c = Contract(kind=KIND, text=c.text, limit=c.limit); st.contract = c.to_dict()
        uk = self.user_keys(st)
        aware_notes: list = []
        recipes_out: list = []
        diagnostics: list = []
        if self.slice_fn is not None:
            # INDEX-AWARE (spec §12 step 1): a compiled must that collapses the pool ranks instead — never the user's own
            cov = {}
            if self.coverage_fn is not None:
                try:
                    cov = (await self.coverage_fn()).get("known_rate") or {}
                except Exception:   # noqa: BLE001
                    cov = {}
            c, aware_notes = await cs.index_aware(c, user_keys=uk, slice_fn=self.slice_fn, coverage=cov)
            if aware_notes:
                st.contract = c.to_dict()
                counts = await self._counts(st)
            # the READINGS the merged search will run, each with its measured pool (the card shows them as toggles)
            from eigen_kernel.facets.contract_search import recipes as _recipes
            ladder = _recipes(c, user_keys=uk, relaxable_keys=set(cs.RELAXABLE_KEYS), readings=[], default_keys=set(cs.LADDER_DEFAULT_KEYS))
            exclude = (c.scope or {}).get("exclude") or {}
            for r in ladder:
                try:
                    n = await self.slice_fn(dict(r.contract.must), exclude)
                except Exception:   # noqa: BLE001
                    n = None
                recipes_out.append({"name": r.name, "why": r.why, "pool": n, "must": r.contract.must, "prefer": r.contract.prefer})
            diagnostics = await cs.u_diagnostics(c, user_keys=uk, slice_fn=self.slice_fn)
        handoff = {**st.contract, "merge": {"mode": "merged", "user_keys": sorted(uk)}}
        note_lines = [f"{n.get('key', '').replace('_', ' ')}: {n.get('why')} — it ranks instead of filtering" for n in aware_notes]
        return {"understood": understood_words(st.contract, st.answers), "contract": handoff, "pool": self._pool(counts), "counts": counts,
                "advice": self._advice(counts), "notes": list(notes) + note_lines, "answers": dict(st.answers), "user_keys": sorted(uk),
                "recipes": recipes_out, "diagnostics": diagnostics, "transcript_audit": transcript[-TRANSCRIPT_CAP:]}

    # ---------------- the turn ----------------
    async def step(self, *, state: dict | None = None, message: str = "", answer: dict | None = None, search_now_flag: bool = False) -> dict:
        state = dict(state or {})
        st = IntakeState.from_dict(state.get("kernel") or {})
        transcript = [m for m in (state.get("transcript") or []) if isinstance(m, dict)][-TRANSCRIPT_CAP:]
        pending = state.get("pending") or None
        notes = list(state.get("notes") or [])
        message = (message or "").strip()
        opening = str(state.get("opening") or "")
        if answer is not None and not message:
            av = answer.get("value")
            label = (SKIP_WORDS.get(str(answer.get("name") or ""), "Skip") if av in (None, "", "__skip__", []) else
                     ", ".join(option_label(str(answer.get("name") or ""), str(x)) for x in av) if isinstance(av, (list, tuple)) else option_label(str(answer.get("name") or ""), str(av)))
            transcript.append({"role": "user", "text": label[:MSG_CAP]})
        if message:
            transcript.append({"role": "user", "text": message[:MSG_CAP]})

        def pack(stage: str, question: dict | None = None, ready: dict | None = None) -> dict:
            if question:
                transcript.append({"role": "assistant", "text": question["words"][:MSG_CAP]})
            if ready:
                transcript.append({"role": "assistant", "text": ready["understood"][:MSG_CAP]})
                ready["transcript_audit"] = transcript[-TRANSCRIPT_CAP:]
            return {"stage": stage, "question": question, "ready": ready,
                    "state": {"kernel": st.to_dict(), "transcript": transcript[-TRANSCRIPT_CAP:], "pending": question, "opening": opening[:400], "notes": notes[:8]}}

        # 0) OPENING: the thesis in the user's words → the compiled contract (musts the words state, the semantic text)
        if not st.contract and not (answer is not None):
            if not message:
                q = {"kind": "opening", "name": "opening", "key": "", "words": "What are you looking for? Describe the thesis in your own words.",
                     "hint": "e.g. seed AI-infra startups selling to banks, founders ex-Stripe, hiring sales", "options": [], "skip": "", "free_text": True, "klass": ""}
                return pack("opening", question=q)
            opening = message
            c, n = await self.compile_fn(message)
            notes = list(n)
            st.contract = _centre_from_stage(c).to_dict()
            st.stage = "questions"
            counts = await self._counts(st)
            if search_now_flag:
                st = search_now(st)
                return pack("ready", ready=await self._ready(st, counts, transcript, notes))
            q = self._next(st, counts)
            return pack("questions", question=self._question_payload(q, counts)) if q else pack("ready", ready=await self._ready(st, counts, transcript, notes))

        # SEARCH NOW: ready with what is known, from any stage
        if search_now_flag:
            st = search_now(st)
            counts = await self._counts(st)
            return pack("ready", ready=await self._ready(st, counts, transcript, notes))

        # 1) an ANSWER to the pending question: a chip (no model) or typed words (one small model read)
        if pending and pending.get("kind") == "key":
            q = Question(kind="key", name=pending["name"], options=[(o[0], o[2]) for o in (pending.get("options") or [])], klass=pending.get("klass") or "optional")
            if answer is not None:
                av = answer.get("value")
                st = self._apply(st, q, None if av in (None, "", "__skip__") else av)
            elif message and self.llm_json:
                try:
                    read = await self.llm_json(turn_prompt(pending), json.dumps({"reply": message[:600]}))
                except Exception:   # noqa: BLE001
                    read = {}
                if not isinstance(read, dict):
                    read = {}
                answers = read.get("answers") or {}
                got = answers.pop(pending["name"], None) if isinstance(answers, dict) else None
                st = self._apply(st, q, got)
                for k, v in (answers.items() if isinstance(answers, dict) else []):
                    if k in REQUIRED_KEYS + OPTIONAL_KEYS and v not in (None, "", []) and k not in st.asked:
                        st = self._apply(st, Question(kind="key", name=k, klass="optional"), v)
                if read.get("search_now"):
                    st = search_now(st)
                ft = str(read.get("free_text") or "").strip()
                if ft and len(ft) > 3:
                    c = Contract.from_dict(st.contract); c.text = (c.text + " " + ft).strip()[:200]; st.contract = c.to_dict()
            counts = await self._counts(st)
            q2 = self._next(st, counts)
            return pack("questions", question=self._question_payload(q2, counts)) if q2 else pack("ready", ready=await self._ready(st, counts, transcript, notes))

        # a message with no pending question and a contract already: a refinement — compiled on its own and MERGED
        # into what the conversation already established (never a replacement: earlier answers stay)
        if message and st.contract:
            c, n = await self.compile_fn(message)
            st.contract = _merge(Contract.from_dict(st.contract), _centre_from_stage(c)).to_dict(); notes = list(n); opening = (opening + " " + message).strip()
            counts = await self._counts(st)
            q = self._next(st, counts)
            return pack("questions", question=self._question_payload(q, counts)) if q else pack("ready", ready=await self._ready(st, counts, transcript, notes))
        counts = await self._counts(st)
        q = self._next(st, counts)
        return pack("questions", question=self._question_payload(q, counts)) if q else pack("ready", ready=await self._ready(st, counts, transcript, notes))
