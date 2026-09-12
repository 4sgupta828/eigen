"""The answer grounding gate — generic, string-level, fail-safe.

A question's answer is generated as a JSON ARRAY of discrete sentences, each carrying its own citations:
`[{"text": "...", "evidence_ids": ["e1", ...]}]`. Gating the model's OWN sentence units — rather than
re-splitting a prose blob with a regex — is the panel's fix: it can't be defeated by "Inc."/"Ltd."
abbreviations, and a false clause cannot ride into the answer on a single valid citation at the end,
because the WHOLE sentence is dropped if ANY id it cites is not in the allowed set.

Domain-free: the kernel checks that citations resolve; WHAT the sentence should say is the vertical's
prompt. Emits prose with immutable `[[e:<id>]]` markers for the client's citation renderer.
"""
from __future__ import annotations

import re

_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
NOT_ESTABLISHED = "Not established in the record."


def sanitize_answer(items: list[dict], allowed_ids) -> str:
    """Keep a sentence only if it cites at least one evidence id AND every id it cites is allowed. An
    uncited factual sentence is dropped (no unbacked prose); a sentence citing an invented or wrong id
    is dropped whole. If nothing survives, the answer is the explicit fail-safe — never a guess."""
    allowed = {str(x) for x in (allowed_ids or ()) if str(x)}
    kept: list[str] = []
    for item in items or []:
        text = str((item or {}).get("text") or "").strip()
        ids = [str(x) for x in (item.get("evidence_ids") or []) if _ID.match(str(x))]
        if not text or not ids:
            continue                      # uncited prose never enters a grounded answer
        if any(i not in allowed for i in ids):
            continue                      # one bad citation drops the whole sentence
        markers = "".join(f"[[e:{i}]]" for i in dict.fromkeys(ids))   # de-duped, order-stable
        kept.append(f"{text} {markers}".strip())
    return " ".join(kept) if kept else NOT_ESTABLISHED
