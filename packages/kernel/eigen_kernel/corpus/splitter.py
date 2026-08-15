"""Deterministic block splitter — domain-free.

Splits parsed text into Blocks on blank-line paragraph boundaries, tracking char
offsets and a heading-derived section_path (markdown `#` headings). Deterministic
and versioned so re-splitting the same text yields identical blocks (stable
content_key → cross-document dedup of identical passages).
"""
from __future__ import annotations

from eigen_kernel.corpus.models import Block
from eigen_kernel.ingestion.storage import content_key

SPLITTER_VERSION = "para.v1"


def _heading_level(line: str) -> int | None:
    s = line.lstrip()
    if s.startswith("#"):
        n = len(s) - len(s.lstrip("#"))
        if 1 <= n <= 6 and (len(s) == n or s[n] == " "):
            return n
    return None


def split(document_id: str, text: str, *, min_chars: int = 1) -> list[Block]:
    blocks: list[Block] = []
    section: list[str] = []          # current heading stack (titles)
    index = 0
    pos = 0
    n = len(text)

    # Walk paragraph chunks separated by blank lines, preserving offsets.
    while pos < n:
        # skip leading blank lines
        while pos < n and text[pos] == "\n":
            pos += 1
        if pos >= n:
            break
        start = pos
        # extend to the next blank line (\n\n) or EOF
        nl = text.find("\n\n", pos)
        end = n if nl == -1 else nl
        chunk = text[start:end]
        pos = end

        stripped = chunk.strip()
        if not stripped:
            continue

        # A chunk may be a heading, OR a heading immediately followed by body text
        # on the next line (well-formed markdown without a blank line between). Peel
        # any leading heading line off as a section marker; keep the body as a block.
        first_nl = stripped.find("\n")
        first_line = stripped if first_nl == -1 else stripped[:first_nl]
        lvl = _heading_level(first_line)
        if lvl is not None:
            title = first_line.lstrip("#").strip()
            section = section[: lvl - 1] + [title]   # update heading stack
            if first_nl == -1:
                continue                              # heading only, no body
            stripped = stripped[first_nl + 1:].strip()
            if not stripped:
                continue

        if len(stripped) < min_chars:
            continue

        # locate the (post-heading) block text within the original document
        char_start = text.find(stripped, start)
        char_end = char_start + len(stripped)
        blocks.append(Block(
            document_id=document_id,
            index=index,
            content_key=content_key(stripped.encode("utf-8")),
            text=stripped,
            char_start=char_start,
            char_end=char_end,
            section_path=tuple(section),
        ))
        index += 1
    return blocks
