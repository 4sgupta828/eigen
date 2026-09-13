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
        # Strip any RAW evidence id the model wrote into the prose (e.g. "(9af40…)", "[9af40…]", or a
        # bare id) — the only citation the reader should see is the clean [[e:id]] marker we append. The
        # model often wraps its inline cite in () OR [], so handle both, then collapse any empty wrapper
        # it leaves behind (the "[]" bug): a bracket/paren with nothing but separators inside.
        text = re.sub(r"[(\[]\s*[A-Za-z0-9_-]{12,}\s*[)\]]", "", text)   # (id) or [id]
        for i in ids:
            text = text.replace(i, "")
        text = re.sub(r"[(\[]\s*[,;\s]*[)\]]", "", text)                 # empty () or [] left behind
        text = re.sub(r"\s+([.,;])", r"\1", text)                        # tidy space before punctuation
        text = re.sub(r"\s{2,}", " ", text).strip()
        if not text:
            continue
        markers = "".join(f"[[e:{i}]]" for i in dict.fromkeys(ids))   # de-duped, order-stable
        kept.append(f"{text} {markers}".strip())
    # Each grounded point on its own line (blank-line separated) so the reader gets distinct,
    # readable points rather than one wall of prose. The client renders each as its own paragraph.
    return "\n\n".join(kept) if kept else NOT_ESTABLISHED
