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


def _scrub(text: str, ids: list[str]) -> str:
    """Strip any RAW evidence id the model wrote into the text (bare, or wrapped in ()/[]), then collapse
    any empty wrapper left behind (the "[]" bug) and tidy spacing. The only citation the reader sees is
    the clean [[e:id]] marker we append separately."""
    text = re.sub(r"[(\[]\s*[A-Za-z0-9_-]{12,}\s*[)\]]", "", text)   # (id) or [id]
    for i in ids:
        if len(i) >= 8:              # only strip a real id string, never a short token that is a real word
            text = text.replace(i, "")
    text = re.sub(r"[(\[]\s*[,;\s]*[)\]]", "", text)                 # empty () or [] left behind
    text = re.sub(r"\s+([.,;])", r"\1", text)                        # tidy space before punctuation
    return re.sub(r"\s{2,}", " ", text).strip()


def _cited(item: dict, allowed: set) -> tuple[str, str] | None:
    """(clean_text, markers) for a gated unit, or None if it is uncited / cites a disallowed id."""
    text = str((item or {}).get("text") or "").strip()
    ids = [str(x) for x in (item.get("evidence_ids") or []) if _ID.match(str(x))]
    if not text or not ids or any(i not in allowed for i in ids):
        return None
    text = _scrub(text, ids)
    if not text:
        return None
    return text, "".join(f"[[e:{i}]]" for i in dict.fromkeys(ids))   # de-duped, order-stable


def sanitize_answer(items: list[dict], allowed_ids, *, bullets: bool = False) -> str:
    """Keep a sentence only if it cites at least one evidence id AND every id it cites is allowed. An
    uncited factual sentence is dropped (no unbacked prose); a sentence citing an invented or wrong id
    is dropped whole. If nothing survives, the answer is the explicit fail-safe — never a guess.

    `bullets`: render each point as a markdown "- " list item (one line each) instead of a standalone
    paragraph — for an enumeration of distinct facts. The client renders the list; grounding is
    unchanged (every bullet still carries its [[e:id]] marker)."""
    allowed = {str(x) for x in (allowed_ids or ()) if str(x)}
    kept: list[str] = []
    for item in items or []:
        got = _cited(item, allowed)
        if got:
            kept.append(f"- {got[0]} {got[1]}".strip() if bullets else f"{got[0]} {got[1]}".strip())
    if bullets:
        return "\n".join(kept) if kept else NOT_ESTABLISHED
    # Each grounded point on its own line (blank-line separated) so the reader gets distinct,
    # readable points rather than one wall of prose. The client renders each as its own paragraph.
    return "\n\n".join(kept) if kept else NOT_ESTABLISHED

def sanitize_table(table: dict, allowed_ids) -> str:
    """A comparison table, gated row-by-row, rendered as markdown with a trailing Source column carrying
    each row's [[e:id]] markers. A row is kept only if it cites at least one allowed id and fills every
    column — same grounding contract as a sentence, so a table can never smuggle in unbacked cells.
    Returns "" when there is no usable table (the caller falls back to prose/bullets)."""
    allowed = {str(x) for x in (allowed_ids or ()) if str(x)}
    if not isinstance(table, dict):
        return ""
    cols = [str(c).strip() for c in (table.get("columns") or []) if str(c).strip()]
    if len(cols) < 2:
        return ""                         # a one-column "table" is just a list — use bullets
    kept: list[list[str]] = []
    for row in (table.get("rows") or []):
        cells = [str(c).strip() for c in ((row or {}).get("cells") or [])]
        ids = [str(x) for x in ((row or {}).get("evidence_ids") or []) if _ID.match(str(x))]
        if len(cells) != len(cols) or not ids or any(i not in allowed for i in ids):
            continue
        cells = [_scrub(c, ids).replace("|", r"\|") or "—" for c in cells]
        markers = "".join(f"[[e:{i}]]" for i in dict.fromkeys(ids))
        kept.append(cells + [markers])
    if not kept:
        return ""
    head = "| " + " | ".join(cols + ["Source"]) + " |"
    sep = "| " + " | ".join(["---"] * (len(cols) + 1)) + " |"
    body = "\n".join("| " + " | ".join(row) + " |" for row in kept)
    return f"{head}\n{sep}\n{body}"
