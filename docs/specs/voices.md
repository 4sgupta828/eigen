# Voices — first-person startup content as a mode

**Status:** Phase 1 built and deployed behind `EIGEN_VOICES`. Panel-reviewed, measured.
**Owner ask (2026-09-07):** "Another mode: podcasts / videos / posts from founders, investors, influencers,
all about startups, tech and learnings from wins, losses, evolutions, hard-won battles. Content FROM THE
SOURCE vs. search of meta information. Tech-wide or vertical/industry specific. Build a corpus, surface it
aligned to the user's query, and potentially attach items to startup cards when they are from founders."

## 0. What the measurements say (all free, run 2026-09-07, before any code)

The design turns on one question: can a 90-minute podcast be made retrievable at the level of a specific
lesson without paid transcription? Measured, not assumed.

| Probe | Result |
| --- | --- |
| `<podcast:transcript>` in founder/VC feeds | 20VC 0, Lenny's 0, Invest Like the Best 0, a16z 0, My First Million 0, Indie Hackers 0, Acquired 2 of 216 |
| Publisher transcript on the episode page | Acquired yes (~280k chars); Lenny's, Colossus, a16z, Indie Hackers no |
| YouTube auto-caption fetch | `captionTracks` present, every format returns **0 bytes** — the timedtext endpoint is token-gated |
| **Timestamped chapters in show notes** | **Lenny's 98%, Invest Like the Best 98%, My First Million 85%, 20VC 48%** of the last 60 episodes; Acquired, a16z, Indie Hackers 0% |
| Essay/newsletter feeds carrying full text | Not Boring 89k chars, Lenny's 24k, The Generalist 10.5k, AVC 7k; Paul Graham's third-party RSS carries none (fetch the essays directly) |
| Naive guest matching against our index | Useless: 100% "company named" because *inside*, *check*, *built*, *ambition* are company names |
| **Gated matching** (2-token founder name AND that founder's company name) | 20VC 4%, My First Million 4%, Invest Like the Best 2%, Lenny's 1% of episodes bind; spot-checked correct (Ryan Petersen/Flexport, Brian Chesky/Airbnb, Amjad Masad/Replit, Wade Foster/Zapier) |

Conclusions forced by the data:
1. **Podcast transcripts do not exist at scale for this genre.** Any design that assumes them is fiction.
2. **Chapters are the free lesson-level unit.** A chapter is a publisher-written title plus an offset —
   "13:00 Is Series A the hardest stage at which to invest" — and it deep-links to the exact moment.
3. **Video is metadata-only today.** YouTube's caption endpoint is closed. Do not build on it.
4. **Essays are the strongest leg**: full text, unambiguous author, no diarization problem.
5. **Attachment to startup cards is real but rare** — a few percent of episodes. Worth building, never
   worth forcing.

## 1. What already exists (verified in code, do not rebuild)

- `connectors/podcast.py` — a transcript-only podcast connector over a curated show allowlist. It ingests
  ONLY publisher-provided `<podcast:transcript>` content, never machine-transcribes, never scrapes YouTube.
  Its allowlist is engineering shows (Changelog network, Latent Space), not founder/investor shows.
- `connectors/expert_feed.py` and `connectors/eng_blog.py` — curated essay/newsletter feeds, already parsed.
- `evidence_kind.py` — `source_kind` in (`essay`, `newsletter`, `expert`, `podcast`) → **`expert_analysis`**,
  rank 3, never controlling. The tiering this feature needs is already correct.
- `use_case_lenses.py` — `wisdom` ("what expert practitioners actually argue… hard-won tradeoffs and
  DISAGREEMENTS") and `foresight`, both `suppress_authority: True`. The answer register already exists.
- The kernel corpus is LIVE in prod: 650,298 `rs_block` rows over 35,325 documents, already including 147
  podcast blocks and 212 essay blocks.

So the ingest half of this feature exists and is correctly tiered. **What is missing is the show list, the
chapter unit, the timestamp, the guest binding, and the mode UI.**

## 2. Storage: the kernel corpus, not a new `vo_*` schema

Rejected: a detached `vo_*` feature mirroring `apps/api/startups/`. `su_*` is right for startups because a
company is a structured ENTITY with typed facets. A podcast moment is an unstructured PASSAGE, which is
exactly what `rs_block` already is (text + tsvector + embedding + jsonb facets, GIN-indexed).

One constraint found in the code: `Block.char_start` / `char_end` exist in the model but are **dropped at
persistence** — `materialize_to_postgres` writes ten columns and `rs_block` has no offset column. So the
time offset rides in the per-block `facets` jsonb as `t_start` (seconds). No kernel DDL change, no new
kernel field, and the kernel stays domain-free because "an offset in seconds" names no domain noun.

## 3. Three content types, and only two of them are evidence

This is the discipline the feature lives or dies by. Evidence is typed, not text.

| Type | Source | Citable? | Register |
| --- | --- | --- | --- |
| `essay` | Full text from the author's own feed | Yes | First-person testimony, attributed to the named author |
| `transcript` | Publisher-provided transcript only | Yes | First-person testimony, attributed to the show and, if diarized, the speaker |
| `chapter` | A timestamped show-note marker | **No — pointer only** | A navigation aid. Never quoted as if someone said it |

A chapter title is written by the publisher's producer, not spoken by the founder. It tells you *where to
listen*, never *what was said*. It is indexed for retrieval and display and is structurally barred from the
research loop's evidence path. Anything else would manufacture quotes.

## 4. Attribution gates (a wrong attribution must be impossible, not unlikely)

1. **A speaker is a person.** Reuse `extract.is_person_name`. The measurement produced "founder=founders"
   from a collective row, which is exactly the failure this prevents.
2. **Guest, not mention.** Bind a person to an episode only when the name appears in the TITLE (or an
   explicit guest field). A name in the description is a MENTION and is stamped as such. The measurement
   caught this: an episode with Gokul Rajaram as guest bound to Tony Xu because DoorDash and Tony Xu appear
   in the body copy.
3. **Two-key company binding.** A company binds only when a two-token founder name AND that founder's own
   company name both appear. Single-token names and companies with names under four characters never bind.
4. **Un-diarized text is attributed to the EPISODE, never to a person.** If a transcript has no speaker
   tags, a passage is "discussed on <show> featuring <guest>", never "<guest> said". This is the host's
   question problem: the host asks "did it fail?", the founder says "no", and a naive index attributes the
   failure to the founder.
5. **Subject congruence, inherited.** A passage supports a claim only if the passage's subject is the
   claim's subject. A founder describing a *competitor's* layoffs is not evidence about their own company.

## 5. Copyright and ToS posture

Inherited from the existing podcast connector and kept: publisher-provided text only, never machine
transcription, never scraped captions. Store passages, never whole works for redistribution; display a
snippet and deep-link out to the original so the traffic goes to the creator. Chapter titles are short
factual metadata. Feeds are fetched politely under robots with per-host pacing.

## 6. The eval traps (written before the code, each designed to PASS a gate while being wrong)

1. **The hypothetical.** "If we had run out of money we'd have done what <Competitor> did and cut half the
   team." Query: "did <Founder>'s company do layoffs?" Every keyword matches. Must fail subject congruence.
2. **The host's question.** An un-diarized passage where the host names the failure and the guest denies it.
   Must never be attributed to the guest.
3. **The chapter as a quote.** "13:00 Why we nearly died" surfaced as if the founder said "we nearly died".
   Must be barred: chapters are pointers.
4. **The mention as a guest.** An episode that names a founder only in the body copy must not bind to that
   founder's company card.
5. **The stale lesson.** A 2019 episode about hiring in a zero-rate market answering a 2026 question. Must
   carry its date in the register.

## 7. Build order (Phase 1 is entirely free of model credits)

**Phase 1 — the corpus and the mode, keyword-only.** Both model accounts are empty, so nothing here may
call an LLM or an embedder. `rs_block` rows can be written without an embedding (there is precedent) and
searched by tsvector; embeddings backfill when credit returns.
1. A chapter connector over a curated founder/investor show allowlist, emitting one pointer block per
   chapter with `t_start`, plus the show, episode, date and deep link.
2. Extend the essay feed allowlist with founder/investor writing.
3. The gated guest binder, stamping `person` and `company_id` facets.
4. A `/voices/search` endpoint: tsvector over testimony blocks, filtered by type, show, person, company,
   date; returns moment cards.
5. The mode in the web shell next to Q&A, Startups and Guided, with cards that deep-link to the moment,
   and a "from the founders" strip on startup cards driven by the `company_id` facet.

**Phase 2 — when credits return.** Embeddings for semantic ranking, the same recipe/RRF/judge machinery
the startup contract search uses, and theme facets (pivot, fundraising, layoffs, pricing, hiring) extracted
by a model from chapter titles and essay passages rather than guessed by keyword.

**Explicitly not built:** machine transcription (cost and ToS), YouTube caption scraping (closed), and any
title-only podcast index (the panel's "shallow and useless" trap).


## 8. Build status (2026-09-07)

Phase 1 is built, tested and deployed. Nothing in it spends a model credit.

**Vertical (vocabulary).**
- `connectors/show_notes.py` + `show_notes_doc.py` — 15 curated shows, each kept only after measuring
  its chapter yield. One block per chapter, carrying an offset and a deep link. The chapter-only
  contract is enforced in `discover_entities` on every path, fixtures included, so an episode with no
  chapter list never becomes an entity.
- `connectors/founder_essay.py` — 15 full-text feeds, each stamped with the writer and a `voice_role`
  of founder, investor, operator or analyst.
- `evidence_kind.py` + `authority.py` — a new `pointer` tier at rank 0 with `is_evidence()` False.
  This is the structural bar that stops a producer's chapter title from ever supporting a claim.

**Kernel (mechanics, still domain-free).**
- `ingest_connector_to_postgres(embedder=None)` — ingest without vectors. `rs_block.tsv` is a
  generated column, so the rows are searchable the moment they land and embeddings backfill later.

**App.**
- `apps/api/voices/` — `search.py` (moments, `is_quotable`, `ts_headline` snippets), `bind.py` (the
  attribution gates), `ingest.py` (chapter-safe splitting: `target_chars=0`, `min_chars=1`),
  `routes.py` (search, per-company, sources, admin jobs), all behind `EIGEN_VOICES`.
- `apps/web/index.html` — the Voices mode and the "from the founders" strip on startup cards.

**Verified against the live feeds locally:** 30 episodes produced 531 chapter blocks, 30 essays
produced 104 blocks, zero embeddings were written, and keyword search returned timestamped moments
for "pivot", "layoffs" and "hiring first sales".

**Tests:** 12 in `apps/api/voices/` (3 against a real Postgres), 12 in the vertical. The eval traps
from §6 that are testable without a corpus are pinned: the body-mention that must not bind, the
collective that is not a person, the common-word company that must not attach, and the chapter that
must never be quotable.

**Known gaps, honestly.** Semantic ranking is absent until credits return. Theme facets (pivot,
layoffs, pricing) are not extracted yet, so a query relies on the publisher's own words. Some essay
feeds put navigation chrome in the item body, which occasionally surfaces a block of post titles.
Video remains metadata-only.

## 9. Panel findings and what changed (2026-09-07)

The implementation review (`docs/specs/voices-panel.md`) landed six findings worth acting on. All six
are fixed; the reasoning is recorded because each one is a way the feature could have lied.

1. **A chapter about a competitor inherited the guest's company.** Every block of an episode got
   `company_id`, so "14:00 Why Uber struggled" would surface on the guest's own company card. The
   company strip now returns ONE row per episode (`DISTINCT ON (document_id)`) and shows the episode,
   not a chapter, so a company is never represented by a marker about someone else.
2. **The pointer tier was advisory.** `is_evidence()` returned False but nothing consulted it, and
   the blocks sit in the same `rs_block` table the research loop searches — so an answer could have
   cited a producer's chapter title. The manifest now declares `non_evidence_facets`, and
   `PostgresRetrievalSource(never_return=…)` merges that into every request's exclusions. The bar is
   now structural: a caller cannot forget it.
3. **A backward timestamp corrupted the chapter list.** The docstring said such an offset ends the
   list; the code skipped it and kept parsing. It now breaks, as documented.
4. **Prose times became chapters.** "At 08:30 we wake up and start coding" matched. A timestamp must
   now open its line.
5. **A shared founder name bound silently to whichever company came back first.** Two founders called
   "David Smith" made the binding arbitrary. An ambiguous name now binds to nobody.
6. **An unrecognised filter widened the search to everything.** A typo'd kind fell back to the whole
   corpus. It now narrows to nothing, which is what the user asked for.

Also fixed while acting on the review: the guest extractor. Against 16 real prod titles it scored
9/16 and produced "Netic Founder Me", "Chasing Trillion" and "Arm CEO Rene" — a company, a sentence
and a role, each of which would have been printed as a person. It now scores 16/16 and those titles
are pinned as a regression test.

**Accepted, not fixed.** An essay that quotes a third party is still attributed to the essay's author,
because the passage index cannot tell whose words are inside the quotation marks. The register line
says "first-person account, attributed to its author" rather than asserting the author said it, and a
real fix needs quote attribution, which is Phase 2 work.


## 10. In production (2026-09-07)

Live at `EIGEN_VOICES=1`. The corpus, all ingested free of model spend:

| | |
| --- | --- |
| Sources with content | 37 |
| Podcast episodes | 85 |
| Chapter blocks | ~1,200 |
| Essay items | ~90 |
| Embeddings written | 0 |

Four quality problems only production traffic exposed, each now fixed:
1. **Every question returned one result.** `plainto_tsquery` requires every word, so a question
   phrased as a sentence matched almost nothing. Terms are OR-ed and ranked, stopwords dropped.
2. **The same block five times.** Newsletters paste a sidebar of post titles into every item, and
   that text ranks like prose. `mark_boilerplate` stamps text repeated across three or more items of
   one source, and results are deduped with a two-per-document cap.
3. **Podcast moments never appeared.** Without length normalisation a long essay mentioning a word
   twice outranks a chapter titled exactly that word. `ts_rank(..., 1)` fixed it, and searches now
   return moments like "The first recruiting hire most founders get wrong" at 1:11:18.
4. **Stale guest names.** Blocks key on a hash of their text, so a re-ingest never revisits an
   episode the feed has dropped, and names the first extractor got wrong ("Arm CEO Rene") persisted.
   `refresh_guests` re-derives them and clears any binding that rested on a wrong name.

**Binding is as rare as measured.** Of 44 episodes with a parsed guest, 7 guests are founders in our
index and 1 bound fully to a company. That is the gate working, not a bug: the guests on these shows
are mostly investors and large-company executives, and our index is YC, Form D issuers and fund
portfolios. The strip appears where it is earned.

**Operations.** `POST /admin/voices/jobs` with `{"kind": …}` — `ingest` (fetch feeds),
`refresh_guests` (re-derive names), `bind` (attach guests to companies), `mark_boilerplate`. All are
free. Run them in that order after any change to the extractor.
