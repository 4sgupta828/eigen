# Voices — panel reviews (verbatim)

Two reviewers, not three: the Codex CLI was unusable on this account (every model returned
"not supported when using Codex with a ChatGPT account", and the configured default gpt-5.5 404s).
So the panel was Gemini 3 Pro on the design, a code-grounded subagent on the repo, and Gemini 3 Pro
again on the built code. Each is relayed unedited.

## 1. Design review (Gemini 3 Pro, before any code)

Here is a direct critique of the proposed design and concrete answers to your questions.

### 1. The biggest failure mode: Architectural duplication and the zero-credit reality
The biggest flaw is building `apps/api/voices/` as a detached `vo_*` feature that mirrors the `startups` module. 
`su_*` was detached because it is a structured entity database (companies, facts, metrics). A podcast transcript or blog post is fundamentally an unstructured document. Building a custom `vo_segment` table duplicates the exact work already done in the kernel's `Document → ParsedDoc → Block` pipeline (`rs_block`).
**Furthermore:** You proposed using the facet engine (which relies on LLMs to extract themes like "pivot" or "fundraising") while explicitly stating model credits are at **ZERO**. This feature will instantly crash or do nothing. 

### 2. Title/description-only vs. Passage-level retrieval
A title/description-only index is a trap. It will yield high-recall, low-precision garbage that cannot answer specific VC diligence questions. A user asking "how did they handle a pivot" does not want a link to a 2-hour podcast whose description says "Today we discuss the journey."
**Cheapest path to passage-level:** Filter ruthlessly. Only ingest sources that *natively provide* full text.
*   Blogs/Essays (Atom/RSS full text).
*   YouTube videos (fetch auto-generated `.vtt` captions which include timestamps).
*   Podcasting 2.0 (only episodes with `<podcast:transcript>`).
If a source doesn't provide text, skip it entirely. Do not fall back to descriptions.

### 3. Attribution risk and the required gate
**The Risk:** In an un-diarized podcast transcript, the host asks, "Did your product fail miserably?" The founder says, "No." If you keyword-match the transcript chunk, you might attribute "product fail miserably" to the founder.
**The Gate:** Strict Diarization Enforcement.
*   If a transcript contains explicit speaker tags (e.g., `[Host]: ...`, `[Founder]: ...`), parse and attribute claims to the specific speaker.
*   If a transcript is a continuous blob (like most YouTube auto-captions), **it is structurally impossible to attribute a quote to a specific person.** The gate must enforce that claims from un-diarized text are attributed *only* to the episode/session ("Discussed on [Show Name] featuring [Founder]"), never prefaced with "[Founder] said".

### 4. Copyright and ToS limits
Storing full text and serving it as a substitute for the original content violates copyright and ToS (especially YouTube's). 
**The design constraints:** 
1. **Store chunks, not files:** Break transcripts into `rs_block` rows.
2. **Display snippets only:** Never render the full transcript in the UI. Serve only the matched passage (fair use / search index precedent).
3. **Deep-link out:** The primary CTA must be driving traffic to the original creator (e.g., `youtube.com/watch?v=ID&t=123s`).

### 5. The Eval Trap
**The "Competitor/Hypothetical" Trap:** 
A founder is on a podcast saying, "If we had run out of money, we would have had to do what *Competitor X* did and fire half the staff." 
*   **The Trap Query:** "Did Founder A's company have a massive layoff?"
*   **The Trap Mechanism:** The passage matches the keywords ("Founder A", "money", "fire", "staff"). A naive LLM judge or retrieval engine will return it as evidence that Founder A had layoffs. 
*   **The Gate:** The provenance gate must check *Subject Congruence*. The subject of the query (Founder A's company) must match the subject of the retrieved sentence (Competitor X). If they do not match, the evidence must be rejected.

### 6. The MVP (The smallest useful version)
**Phase 1: Founder Blogs and Essays (Text-only)**
Do not touch audio, video, or timestamps yet. 
1. Ingest a curated list of founder/investor blogs (Substack, Paul Graham, First Round) directly into the **existing Kernel corpus** as a new Document type.
2. The author is unambiguous (no diarization needed).
3. The format is clean text.
4. Because credits are at zero, rely entirely on PostgreSQL `tsvector` keyword search over `rs_block`.
5. Add a new Evidence Kind (`first_person_testimony`) to the vertical.
6. Surface these hits in the standard Q&A loop with a labeled "Market Signal / From the Source" register. 

Once credits are restored and this proves useful, expand to YouTube `.vtt` captions for timed video passages.

## 2. Implementation review (Gemini 3 Pro, after Phase 1 was built)

Here is the review of the Voices feature implementation:

**1. Where can this put words in someone's mouth or misattribute a claim?**
*   **Wrong Company (Subject Congruence):** In `apps/api/voices/ingest.py:bind_guests()`, the `company_id` facet is applied to *every* chapter block in the episode via a bulk `UPDATE`. If a guest (e.g., Tony Xu of DoorDash) is interviewed and one chapter is titled "14:00 Why Uber struggled", that chapter block receives `company_id="doordash.com"`. It will incorrectly surface on DoorDash's startup card for searches about struggles or layoffs. 
*   **Wrong Person (Essay Quotes):** In `apps/api/voices/search.py:moment()`, all `founder_essay` blocks are explicitly set to `quotable: True` and `speaker` defaults to the author. If a founder's essay includes a quote from a competitor or employee, it is surfaced and attributed directly to the essay author as their own first-person claim.

**2. Is the "pointer" tier enforced?**
It is **advisory and currently unenforced** by the policy layer itself.
While `evidence_kind.py` correctly maps it to `"pointer"` and `authority.py:is_evidence()` evaluates it to `False`, `authority.py` assigns it a `rank()` of `0`. This is the exact same rank given to unstamped open-web hits. The docstring in `authority.py` explicitly states that rank *"NEVER gates the span/entailment provenance checks"*. Because it passes through with rank 0, a pointer will flow directly into the synthesis prompt as evidence unless a hard gate (e.g., `if not policy.is_evidence(kind): continue`) is explicitly enforced in the downstream pipeline (likely in `eigen_vertical_tech/answer_contract.py` or the `eigen_kernel/synthesis/` compose loop).

**3. Real-world show-note shapes that break the chapter regex:**
*   **Silently produces none:** Formats like `14m30s - The Pivot`. The regex `\d{1,2}:\d{2}` strictly requires a colon, so it will miss these entirely. It will also produce none if the publisher writes only 2 timestamps, as it silently drops lists below `MIN_CHAPTERS=3`.
*   **Produces garbage chapters:** Inline times in prose, like *"At 08:30 we wake up and start coding"*. The regex will match `08:30`, and the title will capture `"we wake up and start coding"`. Because it lacks 3 periods and is under 110 characters, it bypasses the validation checks and becomes a garbage chapter.

**4. Highest-value thing missing without models/embeddings:**
**Document-level deduplication for the startup card.** The "from the founders" strip calls `/voices/company/{company_id}` with an empty query (`q=""`) and `limit=8`, ordered by `created_at DESC`. Because the document is split into one block per chapter and every chapter inherits the `company_id`, the UI will simply render the first 8 chapters of the *single most recent episode* (e.g., "00:00 Intro", "02:00 Early days"). It will completely push out older episodes and high-value essays. 

**5. Wrong, fragile, or delete:**
*   **The "backward offset" bug (`show_notes_doc.py:chapters`):** The docstring states *"a non-increasing offset ends the list rather than corrupting it"*. However, the code uses `if secs <= last: continue`. This skips the backward timestamp but continues parsing, which actively corrupts the list rather than ending it. It must be `break`.
*   **Fragile Founder Dictionary (`ingest.py:bind_guests`):** The `founders` dictionary is keyed by `guest.lower()`. If two founders in the database share the same name (e.g., "David Smith"), the dictionary silently overwrites the first one. The overwritten founder will never bind to their episodes.
*   **Useless Test (`test_voices.py:test_a_mention_in_the_body_never_binds`):** The test explicitly passes `guest="Tony Xu"` into `bind_guest()`. In reality, the pipeline uses `guest_from_title()`, which for the test's title ("Gokul Rajaram - ...") would extract "Gokul Rajaram". The test hardcodes the bypass of the actual extraction logic it's supposed to be validating.
*   **Bad Fallback (`search.py:build_query`):** If the user passes an invalid string in the `kinds` array, `keys` evaluates to empty, and the query silently falls back to querying `list(VOICE_SOURCE_KEYS)` (everything) instead of returning 0 results.
