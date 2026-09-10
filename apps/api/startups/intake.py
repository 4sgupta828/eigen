"""GUIDED search for startups — an ANALYST, not a form: it extracts the investor's intent through a few
clarifying questions and lands them on a search whose results are actually about what they meant.

Flow (one turn at a time, stateless — the state rides the request):
  opening words → compile (the existing brief compiler) → an analyst turn per reply → READY → Startups mode.

Each analyst turn (ONE small JSON call, and only while the analyst budget holds) reads the whole conversation
so far — the thesis, every question and answer, what the investor has ruled out, the contract as it stands —
together with a MEASURED shortlist of what this index can still be filtered on (`intake.askable`), and returns
three things: a running read-back in plain words, a sharpened retrieval query, and the ONE next question.

Two kinds of question, because a thesis has two kinds of ambiguity:
  key   — a facet the index holds and the search can filter on. Only ever chosen from the measured shortlist,
          so a question is asked only when the answer is MISSING, CRITICAL and ANSWERABLE. A key the index
          knows for almost nobody never reaches the shortlist, so it is never asked (this is why stage — 0%
          coverage — stopped being a required question: measurement retired it, not a hardcoded ban).
  open  — a distinction the schema cannot express and only the words can carry ("training-time infrastructure
          or inference and serving?"). Its answer sharpens `contract.text`, which is the leg that actually
          separates such companies, since one tech_area covers models, training, inference and eval alike.

The model may CHOOSE and PHRASE; it may never invent. Every key it names must be on the shortlist and every
value it offers comes from the counts (`intake.accept_question`), so no question can promise a filter the
index cannot honour. With no model, a bad answer, or the budget spent, the deterministic gate takes over and
nothing is lost. "Search now" ends it from any turn."""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from eigen_kernel.facets import Contract, edit, validate_contract
from eigen_kernel.facets.intake import (IntakeState, Question, accept_question, apply_answer, askable, next_question, remember,
                                         search_now, spread)

from .schema import KIND, SCHEMA, VALUE_LABELS

TRANSCRIPT_CAP, MSG_CAP = 40, 1500

# The one key the search is shapeless without, and the keys the analyst may ask about — in INVESTOR importance
# order, which is only the tie-break: `askable` measures each against the live slice first, so a key the index
# cannot answer never appears however high it sits here. `stage` sits last and, at today's coverage, never
# surfaces; it will return by itself if stage extraction ever lands.
REQUIRED_KEYS = ["tech_area"]
OPTIONAL_KEYS = ["tech_area", "customer", "business_model", "country", "metro", "total_disclosed_funding",
                 "last_round_months", "program", "hiring", "founder_count", "stage"]
# Questions a model may choose; the deterministic fallback uses the same list minus the thesis key.
ASKABLE_KEYS = list(OPTIONAL_KEYS)
ANALYST_BUDGET = 3          # a hard ceiling on MODEL-chosen questions; the prompt aims for two
# …and a ceiling on the intake as a whole, whoever picked the question. The analyst budget alone caps
# nothing: when the model proposes a question that cannot be accepted, the deterministic gate takes the
# turn on its own budget, and the two can stack into an interrogation. An investor who wanted to fill in
# a form would not have described a thesis.
MAX_QUESTIONS = 3
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
    lab = VALUE_LABELS.get(value)
    if lab:
        return lab
    v = str(value)
    # ISO country codes have no label of their own; "fr" reads as a typo next to "US" and "UK".
    if key in ("country",) and len(v) == 2 and v.isalpha():
        return v.upper()
    return v.replace("_", " ")


def option_hint(key: str, value: str) -> str:
    if key == "total_disclosed_funding":
        return "at least " + option_label(key, value).replace("< ", "under ")
    if key == "last_round_months":
        return "within " + option_label(key, value)
    return ""


def analyst_prompt(budget_left: int, first: bool = False) -> str:
    """The analyst's brief. It is told what it may ask about and, just as importantly, what it may not promise."""
    return (
        "You are a startup analyst sitting with an investor who has described a thesis in their own words. Your job is to "
        "understand what they actually mean and turn it into a search over an index of companies — NOT to interview them. "
        "Ask the FEWEST questions that change which companies come back.\n"
        "You get the whole conversation so far, the search as it currently stands, and CAN_FILTER_ON: the facets this index "
        "can still filter on right now, each with the values it actually holds and how many companies carry each. That list is "
        "the truth about this index. A facet not on it either is already set, or the index does not know it for enough "
        "companies to act on — never ask about one, and never promise a filter that is not there.\n"
        "ONE question per turn, of one of two kinds:\n"
        "  \"key\"  — a facet from CAN_FILTER_ON. Ask only when the answer is MISSING from what they have said, CRITICAL to "
        "which companies come back, and the facet genuinely divides this pool. Never ask a question whose answer you can "
        "already infer from their words.\n"
        "  \"open\" — a distinction the facets cannot express, which only the wording can carry: which LAYER of a stack, "
        "which workload, which buyer, which way an ambiguous term was meant. Offer 2-5 short answer chips in the investor's "
        "language, not schema tokens.\n"
        + ("THIS IS YOUR FIRST QUESTION AND IT MUST BE kind=\"open\". CAN_FILTER_ON is deliberately empty: on this turn "
           "there is nothing to filter on, only the thesis to sharpen. Ask the ONE thing about WHAT THESE COMPANIES BUILD "
           "OR DO that you would have to know to tell two of them apart — which layer of the stack, which workload, which "
           "of two readings of an ambiguous word. Do NOT ask about business model, revenue, geography, funding, stage, "
           "team or hiring: those are filters the investor can add in one tap afterwards, and they are not what you are "
           "for.\n" if first else "") +
        "START WITH THE OPEN QUESTION whenever the thesis names a technical area broad enough that one index category "
        "covers several different businesses — that is where the misunderstanding lives, and it is the only ambiguity the "
        "investor cannot fix later. A filter is one tap in the rail after the search; the WORDING is not, because it decides "
        "what is retrieved at all. Spending your first question narrowing geography when you have not established WHAT they "
        "build is the mistake to avoid.\n"
        "Never ask two questions that narrow the same dimension (a country and then a city). Never ask a question whose "
        "honest answer is 'no preference' for most investors with this thesis.\n"
        "Also maintain TEXT: the thesis rewritten as the sharpest description of the companies they want, in the words those "
        "companies would use about themselves — this is what the semantic leg of the search matches on, so it matters more "
        "than any filter. Fold every answer into it. Keep it under 200 characters, concrete, no filler.\n"
        "Return ONLY JSON: {\"understanding\": \"one or two plain sentences: what you now believe they are looking for, "
        "in their language, no schema tokens\", \"text\": \"the sharpened description\", \"answers\": {facet_key: value | "
        "[values] | null}, \"ruled_out\": [\"short phrases for what they have said they do NOT want\"], "
        "\"question\": {\"kind\": \"key\"|\"open\", \"key\": \"facet key, or a short slug for an open question\", "
        "\"words\": \"the question, one sentence, plain and specific\", \"why\": \"under 10 words: what this changes\", "
        "\"options\": [\"...\"]} | null, \"ready\": true|false, \"search_now\": true|false}.\n"
        "`answers` maps anything the LATEST reply clearly states onto facet keys — vocabulary tokens only, never invented "
        "values, null when they declined or said it does not matter. For an \"open\" question, `options` are plain phrases; "
        "for a \"key\" question they must be values from CAN_FILTER_ON for that facet.\n"
        f"You have at most {budget_left} more question(s), and TWO is usually the right total for a whole intake. Set "
        "ready=true — with question=null — as soon as another question would not change which companies come back, or when "
        "the investor sounds finished. An investor who wanted to fill in a form would not have described a thesis; ending "
        "early is better than asking one question too many. search_now=true only if they say to just run it.")


def analyst_payload(*, thesis: str, transcript: list, st: IntakeState, pending: dict | None, reply: str, shortlist: list, counts: dict) -> dict:
    """Everything the analyst remembers, plus what this index can still be filtered on — measured, not assumed."""
    c = st.contract or {}
    can = []
    # The kernel ranks by what it MEASURED (how much a key divides this pool); the vertical presents them in
    # the order an investor would care about, and lets the measurement speak for itself in the numbers. Founder
    # count divides this pool cleanly and is still almost never the question worth spending a turn on.
    rank = {k: i for i, k in enumerate(OPTIONAL_KEYS)}
    for a in sorted(shortlist, key=lambda a: (rank.get(a.key, 99), -a.reach)):
        k = SCHEMA.key(a.key)
        can.append({"key": a.key, "label": (k.label if k else a.key), "means": (k.guidance[:200] if k and k.guidance else ""),
                    "known_share": round(a.known, 2), "divides_pool": round(a.decisive, 2),
                    "values": [[v, option_label(a.key, v), int(n)] for v, n in a.options[:12]]})
    return {"thesis": thesis[:600],
            "conversation": [{"who": m.get("role"), "said": m.get("text")} for m in transcript[-12:]],
            "understanding_so_far": st.understanding,
            "ruled_out": list(st.ruled_out),
            "search_so_far": {"words": c.get("text") or "", "must": c.get("must") or {}, "prefer": c.get("prefer") or {},
                              "exclude": (c.get("scope") or {}).get("exclude") or {}},
            "already_asked": list(st.asked),
            "pool_now": int(counts.get("_total") or 0),
            "pending_question": (pending or {}).get("words") or "",
            "latest_reply": reply[:600],
            "can_filter_on": can}


def _phrase_range(key: str, rng: dict) -> str:
    """A numeric must in the words a person would use, not the bounds a machine stores."""
    k = SCHEMA.key(key)
    lab = (k.label.lower() if k else key.replace("_", " "))
    lo, hi = rng.get("min"), rng.get("max")
    money = bool(k and k.unit == "usd")
    fmt = (lambda x: _usd(x)) if money else (lambda x: f"{float(x):g}")
    if lo is not None and hi is not None and float(lo) == float(hi):
        return (f"{fmt(lo)} {lab}" if not money else f"{fmt(lo)} in {lab}") if key != "founder_count" else f"{float(lo):g} founders"
    if key == "last_round_months":
        return f"a round in the last {fmt(hi)} months" if hi is not None else f"nothing newer than {fmt(lo)} months"
    if lo is not None and hi is not None:
        return f"{lab} between {fmt(lo)} and {fmt(hi)}"
    if lo is not None:
        return f"at least {fmt(lo)}" + (f" in {lab}" if money else f" {lab}")
    return f"at most {fmt(hi)}" + (f" in {lab}" if money else f" {lab}")


def _phrase_values(key: str, vals) -> str:
    k = SCHEMA.key(key)
    lab = (k.label.lower() if k else key.replace("_", " "))
    named = [option_label(key, v) for v in (vals if isinstance(vals, (list, tuple)) else [vals])]
    joined = named[0] if len(named) == 1 else " or ".join((", ".join(named[:-1]), named[-1]))
    if key in ("country", "metro"):
        return f"based in {joined}"
    if key == "tech_area":
        return f"building in {joined}"
    if key == "customer":
        return f"selling to {joined}"
    if key == "program":
        return f"out of {joined}"
    if key == "business_model":
        return f"on a {joined} model"
    return f"{lab}: {joined}"


def understood_words(contract: dict, answers: dict | None = None, understanding: str = "") -> str:
    """What will be searched, in a sentence a person would say — never the contract read aloud.

    The analyst's own read-back leads when there is one: it is the only part that knows WHY, and it is in the
    investor's language. The derived clauses follow it, because a filter that is not said is a filter the
    investor cannot catch us getting wrong."""
    c = contract or {}
    clauses = [(_phrase_range(k, vs) if isinstance(vs, dict) else _phrase_values(k, vs)) for k, vs in (c.get("must") or {}).items()]
    ex = (c.get("scope") or {}).get("exclude") or {}
    if ex:
        clauses.append("not " + ", ".join(option_label(k, v) for k, vs in ex.items() for v in vs))
    prefers = [_phrase_values(k, vs) for k, vs in (c.get("prefer") or {}).items() if isinstance(vs, list) and vs]
    ctr = c.get("center") or {}
    words = (c.get("text") or "").strip()
    lead = (understanding or "").strip()

    if not lead:
        head = ("Startups matching “" + words + "”") if words else "Startups"
        parts = list(clauses)
        if prefers:
            parts.append("ranking up " + ", ".join(prefers))
        if ctr.get("key"):
            parts.append("centred on " + option_label(str(ctr.get("key")), str(ctr.get("value"))))
        return head + (" — " + "; ".join(parts) if parts else "") + "."

    out = [lead if lead.endswith((".", "!", "?")) else lead + "."]
    if clauses:
        out.append("Filtering to companies " + "; ".join(clauses) + ".")
    if prefers:
        out.append("Ranking up " + ", ".join(prefers) + ".")
    if ctr.get("key"):
        out.append("Centred on " + option_label(str(ctr.get("key")), str(ctr.get("value"))) + ".")
    if words:
        out.append("The words the search matches on: “" + words + "”.")
    return " ".join(out)


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
        if q.kind == "open":
            # A distinction the schema cannot hold: plain-language chips, and the answer sharpens the words.
            return {"kind": "open", "name": q.name, "key": "", "words": q.words, "hint": q.why or "in your own words — this sharpens what the search matches on",
                    "klass": q.klass, "options": [[v, v, 0, ""] for v, _ in q.options], "skip": "Doesn't matter", "free_text": True, "multi": True}
        words, hint = QUESTION_WORDS.get(q.name, (f"{q.name.replace('_', ' ')}?", ""))
        words, hint = (q.words or words), (q.why or hint)
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
        """The deterministic floor — used when there is no model, when it answers badly, or when its budget is spent."""
        return next_question(st, required_items=[], required_keys=REQUIRED_KEYS, optional_keys=OPTIONAL_KEYS, counts=counts)

    def _shortlist(self, st: IntakeState, counts: dict) -> list:
        return askable(st, keys=ASKABLE_KEYS, counts=counts)

    def _retire(self, st: IntakeState, pending: dict | None, reply: str) -> IntakeState:
        """A question that has been answered — or answered around — is spent, so it is never asked twice. This
        runs whatever happened to the analyst: a spent budget and a missing model must not resurrect a question
        the investor has already seen. An open question's own words still reach the query."""
        name, kind = str((pending or {}).get("name") or ""), str((pending or {}).get("kind") or "")
        if not name or name in st.asked or kind not in ("key", "open"):
            return st
        q = Question(kind=kind, name=name, klass=(pending or {}).get("klass") or "analyst")
        return self._apply(st, q, (reply or None) if kind == "open" else None)

    async def _analyst(self, st: IntakeState, counts: dict, *, transcript: list, thesis: str, pending: dict | None, reply: str) -> tuple[IntakeState, Question | None, bool]:  # noqa: C901
        """ONE analyst turn: read everything said so far plus what the index can still be filtered on, then
        return the updated state, the next question (validated — never invented), and whether it is ready.

        Every failure mode lands on the deterministic gate: no model, a raised call, a non-dict answer, a
        question naming a key that is not on the measured shortlist, or a spent budget."""
        if self.llm_json is None:
            return st, None, False                      # unavailable → the deterministic gate takes over
        if st.counts_asked.get("analyst", 0) >= st.budgets.get("analyst", ANALYST_BUDGET):
            return st, None, True                       # spent → READY. A budget that only caps the MODEL's
            #   questions caps nothing: the first prod run asked its three, then the gate quietly added a
            #   fourth (a metro, right after a country). An analyst that has decided it has enough stops.
        shortlist = self._shortlist(st, counts)
        left = max(0, st.budgets.get("analyst", ANALYST_BUDGET) - st.counts_asked.get("analyst", 0))
        # WHICH SHAPE the opening question takes is a judgment, so the vertical makes it rather than asking
        # the model nicely: told merely to "prefer" an open question, the first prod run asked for a business
        # model and labelled it "open". On the first turn the facets are withheld entirely — there is nothing
        # to filter on and only the thesis to sharpen — so the question can only be about what they build.
        first = st.counts_asked.get("analyst", 0) == 0 and not st.asked
        payload = analyst_payload(thesis=thesis, transcript=transcript, st=st, pending=pending, reply=reply,
                                  shortlist=([] if first else shortlist), counts=counts)
        try:
            read = await self.llm_json(analyst_prompt(left, first=first), json.dumps(payload))
        except Exception:   # noqa: BLE001 — the analyst is an aid; the intake proceeds on the deterministic gate
            return st, None, False
        if not isinstance(read, dict):
            return st, None, False
        # 1) anything the reply plainly stated lands on its key, before the next question is chosen
        answers = read.get("answers") if isinstance(read.get("answers"), dict) else {}
        for key, v in list(answers.items()):
            if key in ASKABLE_KEYS and key not in st.asked and v not in (None, "", []):
                st = self._apply(st, Question(kind="key", name=key, klass="analyst"), v)
        # 2) the memory: the running read-back, what they have ruled out, and the sharpened words
        st = remember(st, understanding=str(read.get("understanding") or "") or None,
                      ruled_out=[str(x) for x in (read.get("ruled_out") or []) if str(x).strip()])
        text = str(read.get("text") or "").strip()
        if len(text) > 8:
            c = Contract.from_dict(st.contract); c.text = text[:200]; st.contract = c.to_dict()
        if read.get("search_now"):
            return search_now(st), None, True
        if read.get("ready"):
            return st, None, True
        # On the first turn only an open question is admissible; `allowed=[]` makes a facet proposal
        # unacceptable structurally, so mislabelling one cannot smuggle it through.
        q = accept_question(st, read.get("question"), allowed=([] if first else shortlist), klass="analyst")
        if q is not None and first and q.kind != "open":
            q = None
        return st, q, False

    def _apply(self, st: IntakeState, q: Question, value) -> IntakeState:
        """An answer lands per LANDING: stage → centre (+ prefer); numeric bands → a must range; the rest → must /
        prefer. An OPEN answer names no key — it joins the words the semantic leg matches on, which is the whole
        point of asking it."""
        if value is None or value == [] or value == "":
            return apply_answer(st, q, None)
        vals = [str(v) for v in (value if isinstance(value, (list, tuple)) else [value])]
        if q.kind == "open":
            n = apply_answer(st, q, ", ".join(vals))
            c = Contract.from_dict(n.contract)
            c.text = (c.text + " " + " ".join(vals)).strip()[:200]
            n.contract = c.to_dict()
            return n
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
        return {"understood": understood_words(st.contract, st.answers, understanding=st.understanding), "contract": handoff,
                "pool": self._pool(counts), "counts": counts, "brief": (st.contract or {}).get("text") or "",
                "advice": self._advice(counts), "notes": list(notes) + note_lines, "answers": dict(st.answers), "user_keys": sorted(uk),
                "ruled_out": list(st.ruled_out), "recipes": recipes_out, "diagnostics": diagnostics,
                "transcript_audit": transcript[-TRANSCRIPT_CAP:]}

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

        async def advance(reply: str = "") -> dict:
            """Whatever just happened, this decides the next turn: one analyst read, and the deterministic
            gate underneath it, so a missing or misbehaving model degrades to the old behaviour rather than
            to a dead end."""
            nonlocal st
            counts = await self._counts(st)
            st, q, ready = await self._analyst(st, counts, transcript=transcript, thesis=opening, pending=pending, reply=reply)
            st = self._retire(st, pending, reply)
            if not ready and q is None and len(st.asked) < MAX_QUESTIONS:
                q = self._next(st, counts)
            if q is not None and len(st.asked) >= MAX_QUESTIONS:
                q = None
            if q is not None:
                return pack("questions", question=self._question_payload(q, counts))
            st.stage = "ready"
            return pack("ready", ready=await self._ready(st, counts, transcript, notes))

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
            if search_now_flag:
                st = search_now(st)
                return pack("ready", ready=await self._ready(st, await self._counts(st), transcript, notes))
            return await advance(reply=message)

        # SEARCH NOW: ready with what is known, from any stage
        if search_now_flag:
            st = search_now(st)
            counts = await self._counts(st)
            return pack("ready", ready=await self._ready(st, counts, transcript, notes))

        # 1) an ANSWER to the pending question. A chip lands deterministically and costs nothing; typed words are
        #    read by the analyst turn itself, so a turn is ONE model call, never two.
        if pending and pending.get("kind") in ("key", "open"):
            if answer is not None:
                av = answer.get("value")
                q = Question(kind=str(pending.get("kind")), name=pending["name"], options=[(o[0], o[2]) for o in (pending.get("options") or [])],
                             klass=pending.get("klass") or "optional")
                st = self._apply(st, q, None if av in (None, "", "__skip__") else av)
            return await advance(reply=message)

        # a message with no pending question and a contract already: a refinement — compiled on its own and MERGED
        # into what the conversation already established (never a replacement: earlier answers stay)
        if message and st.contract:
            c, n = await self.compile_fn(message)
            st.contract = _merge(Contract.from_dict(st.contract), _centre_from_stage(c)).to_dict()
            notes = list(n); opening = (opening + " " + message).strip()
        return await advance(reply=message)
