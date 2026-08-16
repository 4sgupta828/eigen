"""Deterministic block splitter — domain-free.

Splits parsed text into Blocks on blank-line paragraph boundaries, tracking char
offsets and a heading-derived section_path (markdown `#` headings). Deterministic
and versioned so re-splitting the same text yields identical blocks (stable
content_key → cross-document dedup of identical passages).
"""
from __future__ import annotations

from eigen_kernel.corpus.models import Block
from eigen_kernel.ingestion.storage import content_key

SPLITTER_VERSION = "para.v2"

# Hard cap on a single block's characters. A paragraph longer than this is sub-split at whitespace
# boundaries so no block can exceed an embedder's input-token limit (OpenAI text-embedding-3 = 8192
# tokens ≈ ~32k chars; we cap well under that, which also keeps blocks retrieval-sized). Deterministic.
MAX_BLOCK_CHARS = 8000


def _slice_long(s: str, max_chars: int) -> list[str]:
    """Split an over-long paragraph into <=max_chars pieces at whitespace boundaries (deterministic)."""
    if len(s) <= max_chars:
        return [s]
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if n - i <= max_chars:
            out.append(s[i:]); break
        cut = s.rfind(" ", i + 1, i + max_chars)
        if cut <= i:
            cut = i + max_chars            # no whitespace in range → hard cut
        out.append(s[i:cut])
        i = cut
        while i < n and s[i] == " ":
            i += 1
    return [c for c in out if c.strip()]


def _heading_level(line: str) -> int | None:
    s = line.lstrip()
    if s.startswith("#"):
        n = len(s) - len(s.lstrip("#"))
        if 1 <= n <= 6 and (len(s) == n or s[n] == " "):
            return n
    return None


def split(document_id: str, text: str, *, min_chars: int = 1,
          max_chars: int = MAX_BLOCK_CHARS) -> list[Block]:
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
        base = text.find(stripped, start)
        # An over-long paragraph is sub-split so no block exceeds the embedder's input limit.
        offset = 0
        for piece in _slice_long(stripped, max_chars):
            piece = piece.strip()
            if len(piece) < min_chars:
                offset += len(piece)
                continue
            char_start = base + offset
            blocks.append(Block(
                document_id=document_id,
                index=index,
                content_key=content_key(piece.encode("utf-8")),
                text=piece,
                char_start=char_start,
                char_end=char_start + len(piece),
                section_path=tuple(section),
            ))
            index += 1
            offset += len(piece)
    return blocks
