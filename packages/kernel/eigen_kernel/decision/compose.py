"""Cross-finding synthesis — compose grounded, cited prose over a set of already-answered findings.

Per-question synthesis (`make_synthesize`) answers ONE question from its own evidence. This is the next
altitude up: given every finding a decision has produced, write a comprehensive, connected document
that reads ACROSS them. The unit of citation here is the FINDING, not the raw evidence row — each
finding is itself an already-grounded answer, so the synthesis layer reasons over findings and cites
them, and the reader drills from a finding to its own sources. This is what lets the synthesis be
comprehensive (cover every line of inquiry), connective (draw a conclusion from several findings at
once), and honest about coverage (name what was tested and found nothing, citing that finding).

Findings are shown to the model with SHORT stable tokens (F1, F2, …) — an opaque 16-hex id is echoed
unreliably and the strict gate then drops every claim, which is exactly the "empty artifact" failure
this replaces. The model cites F-numbers; `_resolver` maps them (tolerating `F1`, `f1`, `[F1]`) back to
the real finding ids, which are what the emitted `[[e:<id>]]` markers carry so the client resolves them.

The mechanic is domain-free. Same fail-safe as the rest of the grounding path: a point that cites no
finding, or a token outside the set, is dropped whole; a section with nothing behind it renders
NOT_ESTABLISHED.
"""
from __future__ import annotations

import json
import re

from .synthesis import sanitize_answer, NOT_ESTABLISHED

_MARK = re.compile(r"\[\[e:[A-Za-z0-9_-]{1,80}\]\]")
# An F-token not embedded in a larger alphanumeric run (so it never matches the "f2" inside a hex id).
_FTOK = re.compile(r"(?<![A-Za-z0-9])[Ff]0*(\d+)")

_STATUS_WORD = {
    "target_supported": "the record SUPPORTS this",
    "target_contradicted": "the record CONTRADICTS this",
    "target_untested": "tested, the record is SILENT/insufficient",
}

# The reasoning-block kinds (factra's analysis-item model): a section separates GROUNDED FACT from
# INTERPRETATION, and every interpretation is tagged with what KIND of reasoning it is. Generic — a
# legal or biotech vertical reuses the same kinds; the kernel names no domain noun.
ANALYSIS_KINDS = ("tension", "gap", "assumption", "implication", "what_would_change_this")


def _resolver(findings: list[dict]):
    """-> (resolve, reals, token_of). `resolve(raw_ids)` maps whatever the model wrote (F-numbers in any
    of `F1`/`f1`/`[F1]` form, or a real id echoed verbatim) to the real finding ids it means. `reals` is
    the allowed set; `token_of` maps a real id to its short display token for the prompt."""
    real_of: dict[str, str] = {}       # "F3" -> real id
    token_of: dict[str, str] = {}      # real id -> "F3"
    reals: list[str] = []
    for i, f in enumerate(findings or []):
        rid = str(f.get("id") or "")
        if not rid or rid in token_of:
            continue
        tok = f"F{len(reals) + 1}"
        real_of[tok] = rid
        token_of[rid] = tok
        reals.append(rid)
    reals_set = set(reals)

    def resolve(raw_ids) -> list[str]:
        out: list[str] = []
        for x in (raw_ids or []):
            s = str(x).strip()
            if s in reals_set:                     # a real id echoed verbatim
                out.append(s)
                continue
            for num in _FTOK.findall(s):           # one or more F-numbers
                tok = "F" + str(int(num))
                if tok in real_of:
                    out.append(real_of[tok])
        return out

    return resolve, reals_set, token_of


def _clean_answer(answer: str, *, chars: int) -> str:
    """The finding's answer, with its OWN inner [[e:..]] markers stripped — the synthesis model cites the
    FINDING (its F-token), not a lower-level id it cannot see the source for."""
    return _MARK.sub("", str(answer or "")).replace("  ", " ").strip()[:chars]


def _findings_block(findings: list[dict], token_of: dict, *, chars: int) -> str:
    """Findings grouped by line of inquiry, each headed by its short [F#] token (to cite), the aspect it
    settled and its status, then the question and its answer."""
    by_line: dict[str, list[dict]] = {}
    order: list[str] = []
    for f in findings or []:
        line = str(f.get("line") or "Findings")
        if line not in by_line:
            by_line[line] = []
            order.append(line)
        by_line[line].append(f)
    out = []
    for line in order:
        out.append(f"### LINE OF INQUIRY: {line}")
        for f in by_line[line]:
            tok = token_of.get(str(f.get("id") or ""), "?")
            aspect = str(f.get("aspect") or "").strip()
            status = _STATUS_WORD.get(str(f.get("status") or ""), "")
            head = f"[{tok}]" + (f" — {aspect}" if aspect else "") + (f" — {status}" if status else "")
            q = str(f.get("question") or "").strip()
            a = _clean_answer(f.get("answer"), chars=chars)
            out.append(f"{head}\nQ: {q}\nWhat we found: {a}")
    return "\n\n".join(out)


_CITE_HINT = ('cite the finding(s) it rests on by their SHORT F-number(s) in `finding_ids` — e.g. '
              '["F1"] or ["F2","F5"]. Use ONLY the F-numbers shown above; a point whose finding_ids is '
              "empty or references an F-number not shown is DROPPED.")


async def compose_over_findings(llm_json, *, directive: str, sections: list[dict], findings: list[dict],
                                decision: str = "", layout: str = "bullets", answer_chars: int = 1400,
                                recover=None) -> list[dict]:
    """Compose the given SECTIONS as grounded prose over the findings, citing findings by F-token. One
    model call writes every section. Returns `[{key, title, prose}]` in order; `prose` carries
    `[[e:<real finding id>]]` markers, or `NOT_ESTABLISHED`. Never raises."""
    resolve, reals, token_of = _resolver(findings)
    blank = [{"key": s["key"], "title": s["title"], "prose": NOT_ESTABLISHED} for s in (sections or [])]
    if llm_json is None or not reals or not sections:
        return blank
    spec = "\n".join(f'- {s["key"]}: {s["title"]} — {s.get("intent", "")}' for s in sections)
    shape = ("each point ONE crisp, self-contained line" if layout == "bullets"
             else "each point a connected 2–4 sentence paragraph that reasons across findings")
    user = (
        (f"DECISION UNDER TEST: {decision}\n\n" if decision else "")
        + "You are writing ACROSS all of the findings below — the complete diligence record, grouped by "
          f"line of inquiry, each headed by a short [F#] tag. Cite by the F-number.\n\n"
        + f"{_findings_block(findings, token_of, chars=answer_chars)}\n\n"
        + f"SECTIONS to write, in this order:\n{spec}\n\n"
        + "WRITE FOR SUBSTANCE AND COVERAGE:\n"
        + f"- {shape.capitalize()}. Be comprehensive — a thin section is a failure. Pull the concrete "
          "facts the findings hold: the numbers, named parties, mechanisms, dates.\n"
        + "- CONNECT THE DOTS: the value is in what several findings, taken together, IMPLY — say what "
          "follows and cite every finding the inference rests on (a point may cite two or three).\n"
        + "- COVER EVERY LINE OF INQUIRY where a section calls for it; do not silently drop one.\n"
        + "- Where a finding tested something and the record was silent, you MAY say so and cite that "
          "finding — a named gap is a real result, not an empty section.\n"
        + "- NEVER invent a number, market size, or party not in the findings; where a figure a section "
          "wants is absent, say what IS known and that the figure is unestablished — never fabricate.\n\n"
        + 'Return ONE JSON object: {"sections": [{"key": "<section key>", "points": '
          '[{"text": "...", "finding_ids": ["F1", ...]}]}]}. Every point must ' + _CITE_HINT
        + " A section with nothing behind it gets an empty `points` list. Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        by_key: dict[str, list] = {}
        for s in (d.get("sections") or []):
            pts = (s or {}).get("points") or (s or {}).get("sentences") or []
            by_key[str((s or {}).get("key") or "")] = [
                {"text": (p or {}).get("text"),
                 "evidence_ids": resolve((p or {}).get("finding_ids") or (p or {}).get("evidence_ids"))}
                for p in pts]
    except Exception:      # noqa: BLE001 — never blocks; a failed call yields NOT_ESTABLISHED sections
        by_key = {}
    out = []
    for s in sections:
        items = by_key.get(s["key"], [])
        out.append({"key": s["key"], "title": s["title"],
                    "prose": sanitize_answer(items, reals, bullets=(layout == "bullets"))})
    return out


async def compose_deck(llm_json, *, directive: str, sections: list[dict], findings: list[dict],
                       spine_intent: dict | None = None, context: str = "", decision: str = "",
                       answer_chars: int = 1600) -> dict:
    """Compose a HEADLINE-DRIVEN brief over the findings — the presentation-grade cousin of
    `compose_over_findings`. Instead of a flat prose blob per section, each section gets a single
    assertive HEADLINE (the takeaway the section proves) plus structured, individually-cited POINTS, and
    the whole document carries a SPINE — a short set of throughline statements (`spine_intent` names and
    describes them) that tie the sections into one argument. One model call writes everything.

    `context` is optional prose shown to the model to inform the narrative (e.g. a synthesis produced
    elsewhere); it is explicitly NOT a citation source — every emitted unit must still cite findings by
    F-number or it is dropped. Same fail-safe as the rest of the path: a unit citing no finding is
    dropped whole; a section with nothing behind it renders empty. Domain-free. Never raises.

    Returns `{"spine": {<key>: {text, markers}}, "sections": [{key, title, headline: {text, markers},
    points: [{text, markers}]}]}`."""
    spine_intent = spine_intent or {}
    resolve, reals, token_of = _resolver(findings)
    blank = {"spine": {}, "sections": [{"key": s["key"], "title": s["title"],
             "headline": {"text": "", "markers": ""}, "points": []} for s in (sections or [])]}
    if llm_json is None or not reals or not sections:
        return blank
    spec = "\n".join(f'- {s["key"]}: {s["title"]} — {s.get("intent", "")}' for s in sections)
    spine_keys = [str(k) for k in spine_intent]
    spine_spec = "\n".join(f"- {k}: {spine_intent[k]}" for k in spine_keys)
    spine_json = ", ".join(f'"{k}": {{"text": "...", "finding_ids": ["F1"]}}' for k in spine_keys)
    user = (
        (f"DECISION UNDER TEST: {decision}\n\n" if decision else "")
        + "You are writing ACROSS all of the findings below — the complete diligence record, grouped by "
          f"line of inquiry, each headed by a short [F#] tag. Cite by the F-number.\n\n"
        + f"{_findings_block(findings, token_of, chars=answer_chars)}\n\n"
        + (f"SYNTHESIS SO FAR (context to inform your narrative — NOT a citation source; you still cite "
           f"findings by F-number, never this text):\n{context.strip()}\n\n" if context.strip() else "")
        + (f"SPINE — the throughline; write each element as ONE line, cited:\n{spine_spec}\n\n"
           if spine_spec else "")
        + f"SECTIONS to write, in this order:\n{spec}\n\n"
        + "WRITE IT HEADLINE-FIRST, CONNECTED, CONCRETE:\n"
        + "- Each section gets ONE headline: a single assertive sentence stating the takeaway the "
          "section proves (not a label), then 2–5 crisp points that earn it.\n"
        + "- CONNECT THE DOTS: the value is what several findings together IMPLY — say what follows and "
          "cite every finding the inference rests on (a point may cite two or three).\n"
        + "- Pull the concrete facts the findings hold: the numbers, named parties, mechanisms, dates. A "
          "vague headline or point is a failure.\n"
        + "- Where a finding tested something and the record was silent, you MAY say so and cite that "
          "finding — a named gap is a real result, not an empty section.\n"
        + "- NEVER invent a number, market size, or party not in the findings; where a figure a section "
          "wants is absent, say what IS known and that the figure is unestablished — never fabricate.\n\n"
        + 'Return ONE JSON object: {"spine": {' + spine_json + '}, "sections": [{"key": "<section key>", '
          '"headline": {"text": "...", "finding_ids": ["F1", ...]}, "points": [{"text": "...", '
          '"finding_ids": ["F1", ...]}]}]}. Every headline and point must ' + _CITE_HINT
        + " A section with nothing behind it gets an empty `points` list and may omit its headline. "
          "Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001 — never blocks; a failed call yields a blank deck
        return blank

    def _one(unit) -> dict:
        g = _gate_units([{"text": (unit or {}).get("text"),
                          "finding_ids": (unit or {}).get("finding_ids") or (unit or {}).get("evidence_ids")}],
                        resolve, reals)
        return {"text": g[0]["text"], "markers": g[0]["markers"]} if g else {"text": "", "markers": ""}

    raw_spine = d.get("spine") or {}
    spine_out = {}
    for k in spine_keys:
        cell = _one(raw_spine.get(k) if isinstance(raw_spine, dict) else None)
        if cell["text"]:
            spine_out[k] = cell
    by_key = {str((s or {}).get("key") or ""): (s or {}) for s in (d.get("sections") or [])}
    out_secs = []
    for s in sections:
        raw_s = by_key.get(s["key"], {})
        headline = _one(raw_s.get("headline"))
        points = [{"text": g["text"], "markers": g["markers"]}
                  for g in _gate_units(raw_s.get("points") or raw_s.get("sentences") or [], resolve, reals)]
        out_secs.append({"key": s["key"], "title": s["title"], "headline": headline, "points": points})
    return {"spine": spine_out, "sections": out_secs}


def _gate_units(items, resolve, reals: set) -> list[dict]:
    """Keep only points that cite ≥1 finding (after resolving F-tokens); strip inner markers, append the
    clean [[e:<real id>]] run. Returns [{text, markers, ids}]."""
    out = []
    for it in items or []:
        text = str((it or {}).get("text") or "").strip()
        ids = [i for i in dict.fromkeys(resolve((it or {}).get("finding_ids")
                                                or (it or {}).get("evidence_ids"))) if i in reals]
        if not text or not ids:
            continue
        text = _MARK.sub("", text).strip()
        if not text:
            continue
        out.append({"text": text, "markers": "".join(f"[[e:{i}]]" for i in ids), "ids": ids})
    return out


async def compose_memo(llm_json, *, directive: str, sections: list[dict], findings: list[dict],
                       decision: str = "", kinds: tuple = ANALYSIS_KINDS, answer_chars: int = 1400) -> dict:
    """A two-layer executive memo over the findings (factra's Decision-Memo model): a BLUF bottom line,
    then per section a GROUNDED layer (cited facts) and a REASONING layer (interpretation tagged by kind
    — tension / gap / assumption / implication / what_would_change_this — each citing the findings it
    builds on).

    Returns `{"bottom_line": {text, markers}, "sections": [{key, title, grounded, analysis}]}`. Never raises."""
    resolve, reals, token_of = _resolver(findings)
    empty = {"bottom_line": {"text": "", "markers": ""},
             "sections": [{"key": s["key"], "title": s["title"], "grounded": [], "analysis": []}
                          for s in (sections or [])]}
    if llm_json is None or not reals or not sections:
        return empty
    spec = "\n".join(f'- {s["key"]}: {s["title"]} — {s.get("intent", "")}' for s in sections)
    user = (
        (f"DECISION UNDER TEST: {decision}\n\n" if decision else "")
        + "This is the COMPLETE diligence record — every finding, grouped by line of inquiry, each headed "
          f"by a short [F#] tag. Cite by the F-number.\n\n{_findings_block(findings, token_of, chars=answer_chars)}\n\n"
        + f"Write a comprehensive executive read with these SECTIONS, in order:\n{spec}\n\n"
        + "EMIT a JSON object:\n"
          '{"bottom_line": {"text": "...", "finding_ids": ["F1", ...]},\n'
          ' "sections": [{"key": "<key>",\n'
          '   "grounded": [{"text": "<a fact, restating the findings>", "finding_ids": ["F1", ...]}],\n'
          '   "analysis": [{"kind": "<one of ' + "|".join(kinds) + '>", "text": "<your interpretation>", '
          '"finding_ids": ["F1", ...]}]}]}\n\n'
        + "RULES:\n"
        + "- bottom_line: a TIGHT 1–3 sentence lead — the way the record leans (fund / pass / more "
          "diligence) and the crux. Not the whole memo.\n"
        + "- grounded: the cited FACTS a section rests on — each a DIRECT claim about the world (party, "
          "number, date) with its F-number, e.g. 'The incumbent ships the same capability in-product "
          "[F3]'. Do NOT narrate your own research ('the record found that…', 'the X record found…') — "
          "state what is true, or what is UNSETTLED, in the world: e.g. 'No source establishes "
          "willingness-to-pay; it remains open [F3, F7]'. Keep an 'open / under-tested / left open' status "
          "AS a fact when that is what the record shows — never turn a gap into a definitive negative.\n"
        + "- SAY EACH FACT ONCE. Put each fact's grounded claim in the ONE section where it is most "
          "load-bearing. In a later section do NOT re-list the same claim and numbers — refer back briefly "
          "through reasoning (e.g. 'given the incumbent traction above [F3, F7]…'). The memo as a WHOLE is "
          "comprehensive; a later section that introduces no NEW fact is mostly reasoning with an empty "
          "grounded array.\n"
        + "- analysis is the PRODUCT: what several findings together IMPLY, where they are in TENSION, "
          "what GAP remains, what ASSUMPTION the thesis rests on, and (kind=what_would_change_this) the "
          "evidence that would move the call. Each item cites the findings it builds on BY F-NUMBER — and "
          "any number it uses must come from a finding it cites, never invented. Prefer one sharp reasoning "
          "block over re-listing facts.\n"
        + "- Write PLAINLY: short, direct sentences a partner would actually say; no filler, no hedging "
          "scaffolding, no jargon for its own sake.\n"
        + "- Every text " + _CITE_HINT + " Never invent a finding, number, or fact. A section with no NEW "
          "material gets empty arrays. Output ONLY the JSON.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
    except Exception:      # noqa: BLE001
        return empty
    bl = _gate_units([{"text": (d.get("bottom_line") or {}).get("text"),
                       "finding_ids": (d.get("bottom_line") or {}).get("finding_ids")}], resolve, reals)
    by_key = {str((s or {}).get("key") or ""): (s or {}) for s in (d.get("sections") or [])}
    out_secs = []
    kinds_set = set(kinds)
    for s in sections:
        raw_s = by_key.get(s["key"], {})
        grounded = _gate_units(raw_s.get("grounded") or [], resolve, reals)
        analysis = []
        for a in (raw_s.get("analysis") or []):
            kind = str((a or {}).get("kind") or "").strip()
            if kind not in kinds_set:
                continue
            g = _gate_units([a], resolve, reals)
            if g:
                analysis.append({"kind": kind, "text": g[0]["text"], "markers": g[0]["markers"]})
        out_secs.append({"key": s["key"], "title": s["title"],
                         "grounded": [{"text": g["text"], "markers": g["markers"]} for g in grounded],
                         "analysis": analysis})
    bottom_line = {"text": bl[0]["text"], "markers": bl[0]["markers"]} if bl else {"text": "", "markers": ""}
    return {"bottom_line": bottom_line, "sections": out_secs}


def _cell(text: str, raw_ids, resolve, reals: set) -> dict:
    """A gated matrix cell: keep the text only if it cites ≥1 finding (after resolving F-tokens);
    otherwise the cell is BLANK. Returns {text, markers}."""
    text = str(text or "").strip()
    ids = [i for i in dict.fromkeys(resolve(raw_ids)) if i in reals]
    if not text or not ids:
        return {"text": "", "markers": ""}
    text = _MARK.sub("", text).strip()
    return {"text": text, "markers": "".join(f"[[e:{i}]]" for i in ids)}


async def compose_matrix(llm_json, *, directive: str, columns: list[dict], findings: list[dict],
                         subject_label: str = "", decision: str = "", answer_chars: int = 1400) -> dict:
    """A comparison MATRIX over the findings: rows are entities (the subject of the decision first, then
    each peer NAMED in the findings), columns the given dimensions, every non-empty cell citing the
    finding(s) it rests on by F-number.

    Returns `{columns: [{key,label}], rows: [{entity, subject, cells: [{text, markers}]}]}`. A cell the
    record cannot fill is left blank; a non-subject row with no grounded cell is dropped. Never raises."""
    cols = [{"key": str(c["key"]), "label": str(c.get("label") or c["key"])} for c in (columns or [])]
    resolve, reals, token_of = _resolver(findings)
    empty = {"columns": cols, "rows": []}
    if llm_json is None or not reals or not cols:
        return empty
    col_spec = "\n".join(f'- {c["key"]}: {c["label"]}' for c in cols)
    user = (
        (f"DECISION UNDER TEST: {decision}\n\n" if decision else "")
        + "Build the comparison from the findings below (grouped by line of inquiry, each headed by a "
          f"short [F#] tag; cite by F-number).\n\n{_findings_block(findings, token_of, chars=answer_chars)}\n\n"
        + f"COLUMNS (dimensions to compare on):\n{col_spec}\n\n"
        + (f'The FIRST row is the subject of the decision itself: entity "{subject_label}", "subject": true.\n'
           if subject_label else "")
        + "Add one row per DISTINCT peer entity that the findings NAME — never invent an entity, and "
          "never invent a cell value. Fill each cell ONLY from the findings, citing the finding "
          "F-number(s); LEAVE A CELL EMPTY when the record does not cover it (an empty cell is correct, "
          "not a failure). A peer you cannot ground in any finding does not belong in the table.\n\n"
        + 'Return ONE JSON object: {"rows": [{"entity": "<name>", "subject": <bool>, "cells": '
          '[{"col": "<column key>", "text": "...", "finding_ids": ["F1", ...]}]}]}. Only include a cell '
          "object when you have grounded content for it. Output ONLY the JSON object.")
    try:
        raw = await llm_json(directive, user)
        d = raw if isinstance(raw, dict) else json.loads(raw)
        rows_in = d.get("rows") or []
    except Exception:      # noqa: BLE001
        return empty
    rows_out = []
    for r in rows_in:
        entity = str((r or {}).get("entity") or "").strip()
        if not entity:
            continue
        is_subject = bool((r or {}).get("subject"))
        by_col = {str((c or {}).get("col") or ""): c for c in ((r or {}).get("cells") or [])}
        cells, grounded = [], False
        for c in cols:
            cell = by_col.get(c["key"]) or {}
            gated = _cell(cell.get("text"), cell.get("finding_ids") or cell.get("evidence_ids"), resolve, reals)
            if gated["text"]:
                grounded = True
            cells.append(gated)
        if is_subject or grounded:      # the subject always shows; a peer must ground ≥1 cell
            rows_out.append({"entity": entity, "subject": is_subject, "cells": cells})
    return {"columns": cols, "rows": rows_out}
