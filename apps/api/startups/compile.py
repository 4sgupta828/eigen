"""Brief → contract (the only model call at search time; cached by text hash by the route).

The prompt is rendered from the schema. Code then validates the contract against the schema and applies the
honesty rules: a must on a key with low index coverage or on `arr` becomes a prefer with a note; a must-not
("not YC") is an `exclude` the store applies in SQL; a centre on stage only when the brief names a stage;
numeric musts carry min / max in USD, months, or years. Explicit rail edits never pass through here."""
from __future__ import annotations

import json
import re

from eigen_kernel.facets import Contract, validate_contract

from .schema import KIND, LOW_COVERAGE_DEFAULT_PREFER, SCHEMA, STAGES

COVERAGE_FLOOR = 0.5
MIN_MUST_SUPPORT = 25       # a categorical must stays a must when at least this many startups carry the requested values
MIN_RANGE_SUPPORT = 200     # a numeric must stays a must when at least this many startups have any value for the key


def system_prompt() -> str:
    keys = SCHEMA.to_prompt_block(KIND)
    return f"""You compile a venture investor's search brief about STARTUPS into a filter contract, as strict JSON:
{{"text": "<the semantic gist of the brief for similarity search, 3-12 words, no filters restated>",
 "must": {{"<key>": ["<value>", ...] | {{"min": <number>, "max": <number>}}}},
 "must_not": {{"<key>": ["<value>"]}},
 "prefer": {{"<key>": ["<value>", ...]}},
 "avoid": {{"<key>": ["<value>", ...]}},
 "center": {{"key": "stage", "value": "<stage>", "span": 1}} | null,
 "rank_by": "match" | "<numeric or ordinal key>",
 "notes": ["<ONLY a requirement in the brief that these keys cannot express, in the user's words; never an explanation of your choices; usually empty>"]}}
Rules: only the keys and values listed below. A must is only what the brief states as a hard requirement ("only", "must",
"at least", "> $5M", a named program or investor); what it merely describes is a prefer. "not X" / "no X" / "excluding X" go in
must_not. Numeric keys take a range in their unit: money keys in USD (so "$5M" is 5000000), last_round_months in months
("12–24 months ago" → min 12, max 24), founded in years, founder_count / headcount / hiring in counts. "seed to series A" →
must stage [seed, series_a] and center seed span 1. Stage words: pre_seed seed series_a series_b series_c series_d_plus growth.
A stage (or a center) ONLY when the brief names one (seed, series A, …) — "startups" alone is not a stage. EVERY area, place, program,
investor, founder count, funding figure or hiring condition the brief names MUST appear under a key (never only in `text`).
Money is "raised" / "funding" → total_disclosed_funding unless the brief says "last round". Do not invent values the brief does not imply.
Examples:
  brief: "robotics startups in Boston that raised over $5M"
  → {{"text": "robotics startups", "must": {{"tech_area": ["robotics"], "metro": ["boston"], "total_disclosed_funding": {{"min": 5000000}}}}, "must_not": {{}}, "prefer": {{}}, "avoid": {{}}, "center": null, "rank_by": "match", "notes": []}}
  brief: "seed to series A fintech startups from YC with 2 founders, not in the US"
  → {{"text": "fintech startups", "must": {{"tech_area": ["fintech"], "program": ["yc"], "founder_count": ["2"], "stage": ["seed", "series_a"]}}, "must_not": {{"country": ["us"]}}, "prefer": {{}}, "avoid": {{}}, "center": {{"key": "stage", "value": "seed", "span": 1}}, "rank_by": "match", "notes": []}}
Keys:
{keys}"""


def _clean_map(m, *, numeric_ok: bool) -> dict:
    out = {}
    for key, vals in (m or {}).items():
        k = SCHEMA.key(str(key))
        if k is None:
            continue
        if isinstance(vals, dict):
            if not numeric_ok or k.type.value != "numeric":
                continue
            rng = {}
            for b in ("min", "max"):
                if vals.get(b) is not None:
                    try:
                        rng[b] = float(vals[b])
                    except (TypeError, ValueError):
                        pass
            if rng:
                out[k.key] = rng
            continue
        if isinstance(vals, (int, float)) and not isinstance(vals, bool) and k.type.value == "numeric":
            # a bare number on a numeric key: a band when it names one (founder_count 2 → "2"), else a floor ("over 5M")
            band = str(int(vals)) if float(vals).is_integer() else ""
            if band and band in {b[0] for b in k.bands}:
                out[k.key] = [band]
            elif numeric_ok:
                out[k.key] = {"min": float(vals)}
            continue
        if isinstance(vals, str) and k.type.value == "numeric" and numeric_ok:
            from .extract import parse_money
            n = parse_money(vals)
            if n is not None:
                out[k.key] = {"min": float(n)}
                continue
        vs = vals if isinstance(vals, list) else [vals]
        keep = []
        for v in vs:
            nv = SCHEMA.validate_value(k.key, v)
            if nv is None and k.type.value == "numeric":
                nv = v if str(v) in {b[0] for b in k.bands} else None
            if nv is not None and nv not in keep:
                keep.append(nv)
        if keep:
            out[k.key] = keep
    return out


_STAGE_WORDS = re.compile(r"\b(pre[- ]?seed|seed|series [a-f]\b|growth[- ]stage|late[- ]stage|early[- ]stage)", re.I)


def brief_names_a_stage(text: str) -> bool:
    return bool(_STAGE_WORDS.search(text or ""))


# What each coarse area is actually called, so we can tell "the brief said this" from "we picked the
# nearest one". Only the words a person would write; the point is recognition, not a thesaurus.
AREA_WORDS = {
    "ai_infra": ("ai infra", "inference", "gpu", "model serving", "ml infra"),
    "llm_apps": ("llm", "genai", "generative ai", "chatbot", "copilot"),
    "agents": ("agent", "agents", "agentic"),
    "devtools": ("devtool", "developer tool", "developer tools", "ide", "ci/cd"),
    "data": ("data", "analytics", "warehouse", "etl", "database"),
    "security": ("security", "cyber", "infosec", "appsec"),
    "robotics": ("robot", "robotics", "autonomy", "drone"),
    "hardware_semis": ("hardware", "semiconductor", "chip", "chips", "silicon"),
    "bio_health": ("bio", "biotech", "health", "healthcare", "medical", "clinical"),
    "climate_energy": ("climate", "energy", "solar", "battery", "carbon"),
    "fintech": ("fintech", "payments", "banking", "lending", "insurance"),
    "consumer": ("consumer", "d2c", "social app", "mobile app"),
    "enterprise_saas": ("enterprise", "saas", "b2b software"),
    "space_defense": ("space", "defense", "defence", "satellite", "aerospace"),
    "other": (),
}


def area_named_in(brief: str, area: str) -> bool:
    """Did the brief actually SAY this area, rather than us choosing it as the nearest one?"""
    b = " " + re.sub(r"[^a-z0-9]+", " ", (brief or "").lower()) + " "
    words = AREA_WORDS.get(area, ())
    if any(" " + w + " " in b for w in words):
        return True
    return " " + area.replace("_", " ") + " " in b


def build_contract(out: dict, *, coverage: dict | None = None, value_counts: dict | None = None, limit: int = 60, brief: str = "") -> tuple[Contract, list[str]]:
    """Model JSON → validated Contract + notes. `coverage` = known-rate per key (0..1) from the index (a key
    absent from it is known for nobody); `value_counts` = index-wide count per key per value, so a must on a
    value no startup carries yet is downgraded instead of silently returning nothing."""
    notes = [str(n)[:200] for n in (out.get("notes") or []) if n and not re.search(r"\b(schema|I'll|I will|I use|so I)\b", str(n))][:4]   # the model's own reasoning is not a note
    must = _clean_map(out.get("must"), numeric_ok=True)
    prefer = _clean_map(out.get("prefer"), numeric_ok=False)
    avoid = _clean_map(out.get("avoid"), numeric_ok=False)
    exclude = _clean_map(out.get("must_not"), numeric_ok=False)
    # An AREA the brief did not name is an approximation, and an approximation must not filter.
    # "Ecommerce Startups" compiled to a hard tech_area=consumer, which is not what ecommerce means:
    # it excluded every ecommerce company filed under enterprise software and admitted every consumer
    # company that sells nothing online. The vocabulary is coarse on purpose; when the brief's own
    # word is not in it, the nearest area ranks instead of filtering and the words do the work.
    if brief and must.get("tech_area"):
        named = [v for v in must["tech_area"] if area_named_in(brief, v)]
        approximated = [v for v in must["tech_area"] if v not in named]
        if approximated:
            if named:
                must["tech_area"] = named
            else:
                must.pop("tech_area")
            for v in approximated:
                prefer.setdefault("tech_area", [])
                if v not in prefer["tech_area"]:
                    prefer["tech_area"].append(v)
            notes.append("\u201c" + brief.strip()[:40] + "\u201d has no exact area in our vocabulary, so "
                         + ", ".join(v.replace("_", " ") for v in approximated)
                         + " ranks results instead of filtering them out")

    # a STAGE only when the brief names one — the model tends to assume "startups" means seed / series A
    if brief and not brief_names_a_stage(brief):
        must.pop("stage", None); prefer.pop("stage", None); avoid.pop("stage", None)
        if isinstance(out.get("center"), dict) and out["center"].get("key") == "stage":
            out = {**out, "center": None}
    cov = coverage or {}
    vc = value_counts or {}
    for key in list(must):
        rate = cov.get(key, 0.0) if cov else None
        low = key in LOW_COVERAGE_DEFAULT_PREFER or (rate is not None and rate < COVERAGE_FLOOR)
        label = SCHEMA.key(key).label
        vals0 = must[key]
        # a low known-rate only matters when the REQUESTED values are rare: a must on a category hundreds of startups
        # carry keeps its promise even when most of the index says nothing about the key
        if low and key not in LOW_COVERAGE_DEFAULT_PREFER and vc.get(key):
            if isinstance(vals0, list) and sum(int(vc[key].get(v, 0)) for v in vals0) >= MIN_MUST_SUPPORT:
                low = False
            elif isinstance(vals0, dict) and sum(int(n) for v, n in vc[key].items() if v != "unknown") >= MIN_RANGE_SUPPORT:
                low = False
        if low:
            vals = must[key]
            if isinstance(vals, dict) and key not in LOW_COVERAGE_DEFAULT_PREFER:
                # an explicit numeric requirement ("over $100M", "last round within 12 months") stays a must — it is
                # exactly what was asked; the note says how much of the index the filter can see
                notes.append(f"{label}: known for {int((rate or 0) * 100)}% of startups — this must can only see those")
                continue
            must.pop(key)
            if isinstance(vals, dict):
                notes.append(f"{label}: known for {int((rate or 0) * 100)}% of startups and self-reported — kept as a note (tap the chip to make it a must)")
            else:
                prefer[key] = sorted(set(prefer.get(key, [])) | set(vals))
                notes.append(f"{label}: known for {int((rate or 0) * 100)}% of startups — kept as a preference (tap the chip to make it a must)")
            continue
        vals = must[key]
        if isinstance(vals, list) and key in vc:
            missing = [v for v in vals if not vc[key].get(v)]
            if missing and len(missing) == len(vals):
                must.pop(key)
                prefer[key] = sorted(set(prefer.get(key, [])) | set(vals))
                notes.append(f"{label}: no indexed startup carries {', '.join(missing)} yet — kept as a preference; the words still rank")
            elif missing:
                must[key] = [v for v in vals if v not in missing]
                notes.append(f"{label}: dropped {', '.join(missing)} from the must (no indexed startup carries it yet)")
    center = out.get("center") if isinstance(out.get("center"), dict) else None
    if center and (center.get("key") != "stage" or SCHEMA.validate_value("stage", center.get("value")) is None):
        center = None
    if center:
        center = {"key": "stage", "value": SCHEMA.validate_value("stage", center["value"]), "span": int(center.get("span", 1) or 1)}
    rank_by = str(out.get("rank_by") or "match")
    k = SCHEMA.key(rank_by)
    if rank_by != "match" and (k is None or k.type.value not in ("numeric", "ordinal")):
        rank_by = "match"
    c = Contract(kind=KIND, text=str(out.get("text") or "")[:200], must=must, prefer=prefer, avoid=avoid, center=center, rank_by=rank_by,
                 scope={"exclude": exclude} if exclude else {}, limit=limit)
    errs = validate_contract(c, SCHEMA)
    if errs:
        for section in ("must", "prefer", "avoid"):
            setattr(c, section, {kk: vv for kk, vv in getattr(c, section).items() if not any(f"{section}: " in e and repr(kk) in e for e in errs)})
        errs = validate_contract(c, SCHEMA)
        if errs:
            c = Contract(kind=KIND, text=c.text, limit=limit)
            notes.append("the brief could not be compiled into filters; ranking by the words alone")
    return c, notes


async def compile_brief(llm_json, text: str, *, coverage: dict | None = None, value_counts: dict | None = None, limit: int = 60) -> tuple[Contract, list[str]]:
    try:
        out = await llm_json(system_prompt(), json.dumps({"brief": text[:1500]}))
    except Exception:   # noqa: BLE001
        out = {}
    if not isinstance(out, dict):
        out = {}
    if not out.get("text"):
        out["text"] = re.sub(r"\s+", " ", text)[:200]
    return build_contract(out, coverage=coverage, value_counts=value_counts, limit=limit, brief=text)
