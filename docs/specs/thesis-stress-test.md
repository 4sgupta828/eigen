# Spec: Thesis Stress Test — a conversational stress-tester

Status: DRAFT for review. Date: 2026-09-11.

## The problem

> "We need a mode to stress test a startup thesis (potential new idea) with experts in industry. Will
> product X sell? What happens in absence of it? Is there willingness to pay? What people really
> need? These are potentially advisor, customer, industry expert for product calls. To gather data
> about a thesis, proving or disproving it."
>
> "I think we can write a stress-tester agent for it — conversational with the user, brainstorms
> proactively to stress this, brings out potential people who can prove or disprove the thesis."

## The shape

**An agent that argues with you about your idea, and ends every exchange with either evidence or a
name.**

Not a form that returns a report. A conversation whose job is to attack the thesis, and whose two
outputs are the only two things that can move it: **what the record already says**, and **who could
settle what the record cannot**.

Behind the conversation is a ledger. A thesis is a set of claims that could be false; evidence accrues
to each claim from two places — the corpus, which is free and instant, and calls, which are slow and
expensive and the only thing that can settle the questions that matter most. The agent's job each turn
is to advance that ledger: fill a claim, kill a claim, or name who could.

## What already exists

The adversarial engine is built. This is the finding that makes the mode small.

- **`packages/kernel/eigen_kernel/research/refuter.py`** — a red-team refuter: a **different-family**
  model whose only job is to author disconfirming queries. *"You are a skeptic. Given a CLAIM, produce
  up to N search queries that would surface the STRONGEST DISCONFIRMING evidence against it —
  counterexamples, failures, contrary findings, negative results."* It exists because the drafting
  model authoring its own disconfirmation is *"grading its own homework"*. Fail-closed: no judge, no
  claim, or any error returns `[]`.
- **The UNDER-TESTED flag** (`react.py:1714`) — when a hypothesis's disconfirming search surfaces
  nothing, the hypothesis is marked under-tested and the composer warns about it. *Disconfirmation
  attempted ≠ disconfirmation found.* This is exactly the verdict a thesis stress test needs and
  nobody else ships it.
- **Competing hypotheses** (`react.py:693`), the `subject_bound` and `metric_defined` congruence
  gates, the three registers, and the Manifest of Absence.

So the build is not an adversarial engine. It is a conversation over one, plus the people layer.

## The agent

**Proactive, not interrogative.** It does not ask the user to enumerate their assumptions — that is
the user's job made harder. It *proposes* the attack: "Here is what has to be true for this to work.
Here is the one I think is weakest, and here is why." The user pushes back, and the argument is the
product.

**The rule for asking a question** — inherited from the guided analyst, and it is what stops this
becoming a chatbot that asks twenty things: a question is put to the user only when it is
**missing, critical, and answerable by them**. Anything the corpus can settle is not asked, it is
looked up. Anything only a customer can answer is not asked either — it becomes a call.

**Every turn ends in one of three moves**, and the agent says which:

1. **Settled** — the record answers this. Here it is, with its register and source.
2. **Attacked** — here is the strongest disconfirming evidence the refuter found. Your claim has to
   survive this.
3. **Only a person can answer this** — here is who, here is why them, here is the question.

A turn that does none of the three is a turn that wasted the user's time, and the mode should notice.

**It brainstorms sideways.** The request says *brainstorms proactively*, and the useful form of that is
not idea generation, it is **adjacent-case retrieval**: who already tried this and what happened, what
the closest analog was, which segment the evidence actually points at rather than the one the user
named. The corpus is good at this and a founder usually is not, because they have been staring at one
version of the idea.

## The claims, and who can settle them

Decomposition matters because claims are not equally knowable.

| Claim | Corpus | A call |
|---|---|---|
| the problem occurs in the wild | **settles it** — workarounds, postmortems, filed risk factors | confirms scale |
| the status quo costs real money or time | **settles it**, in orders of magnitude | gives the real number |
| someone already allocates budget or people | **settles it** — grants, spend categories, hiring | names the line item |
| a function owns the problem | usually settles it | names the person |
| a budget category exists | partly — category, not line item | **only a call** |
| an economic buyer can be named | partly, by title | **only a call** |
| switching cost is surmountable | **never** — we see obstacles, never latent ease | **only a call** |
| something forces a revisit now | partly — regulation, discontinuity, failure | confirms urgency |
| **willingness to pay exceeds cost to serve** | **never — structurally** | **only a call** |
| enough such buyers exist | settles it, in bands | — |

Two rows are marked *never*, and they stay that way however much we ingest. No document records a
budget that was never allocated for a SKU that was never offered. Under Eigen's own congruence rule
the claim *"this will sell"* cannot bind congruent evidence and therefore does not exist — we never
produce it, score it, or imply it. **Those two rows are why the calls exist**, and they are hardcoded
unsettleable so a model that found encouraging text cannot promote them.

The corpus rows are not a consolation prize. They are how the user walks into a call already knowing
half the answer, so the 45 minutes goes on the half nobody can look up.

### Reading the present

*"What happens in absence of it"* is the most tractable of the four questions, because a thesis
proposes to replace something that exists now and is written down: the workaround described in a forum
thread, the glue repo whose README says *"we wrote this because nothing does X"*, the engineering post
about the bespoke system and what it cost, the risk factor in the filing.

One trap, and the instinct runs the other way: **"they built it internally" is as often evidence
against a market as for it.** If the thing is welded to proprietary data or defended as core IP, no
vendor can be allowed to run it — those firms are not future customers, they are hostile terrain. An
internal build counts as demand only when it is *general* (would transfer) and *non-strategic*
(plumbing they resent maintaining). Other cases are shown, labelled, and not counted.

## Bringing out the people

The agent surfaces candidates as it goes, attached to the claim they could settle — never a list of
names for their own sake.

- **Customer / economic buyer** — the only one who can speak to price. Hardest to find from public
  record: named in an incumbent's case study, a filed officer role in the owning function, a public
  procurement record. **Users complain; buyers allocate** — a loud practitioner with no purchasing
  authority is not a customer contact and is never presented as one.
- **Operator / practitioner** — lives the status quo, so answers what it costs and whether switching
  is feasible. Easiest to find: they authored the workaround, wrote the glue, published the migration
  post. Identity is carried by the artifact.
- **Category advisor** — structure and timing, evidenced by repeated public analysis over years.

Every candidate carries **why them, for which claim**, with the artifact that says so. We do not
broker, schedule or contact anyone; the user runs the call through their own network or an expert
network. We decide who is worth the slot and what to do with it.

Identity discipline: **strong keys only, never a name merge** — the repo has already paid for this
failure three times (`voices/bind.py` measured naive name matching binding 100% of episodes wrongly
versus 1–4% correctly when gated; `voices/people.py` resolves a name shared by two rows to *nobody*;
`deepdive/assemble.py` keeps *"two Roberts as two Roberts"*).

## The call comes back

**What to ask** is generated only from unsettled claims, and every question carries the evidence that
motivates it — the specific contradiction, the named workaround, the incumbent they currently pay. A
question with no evidence behind it is not generated. That is what separates this from a generic
customer-discovery checklist.

**What they said** returns as evidence on the claim, in the register it deserves: a named person's
first-hand account is `stated`, with a basis recording who, in what role, and when. It is strong
evidence for exactly the claims documents cannot reach, and it is never laundered into `filed`. Two
people saying the same thing is corroboration only if they are independent — two employees of one
company are one source.

**Cross-check.** When an interviewee asserts something the record can check — *"everyone in this
segment runs Y"*, *"nobody has solved Z"* — the agent checks it and shows the agreement or the
conflict. Cheapest high-value thing here, and it falls straight out of machinery that already exists.

## Where the thesis stands

One view, always: each claim with its verdict — **supported / contradicted / under-tested / open /
unsettleable** — its evidence, and what would change it. `under-tested` comes free from the existing
flag and is the most honest state in the set: *we went looking for evidence against this and found
nothing either way.*

No thesis score, no probability, no verdict on the idea as a whole. The rollup reads the claims; it
does not replace them.

A negative result is the product working. *"No observed evidence that anyone currently allocates money
to this problem"* and *"if you build this you are not capturing an existing budget, you must create
one"* are the same fact — the second tells a category creator what they have to do. Absence renders as
a constraint, never a dismissal, and a thesis cannot be shared without the list of what we could not
find attached.

## Build

**Phase 0 — measure (free, half a day).** The corpus is ~650k blocks, but the known composition is
464k filings, 92k preprints, 33k code documents, 19k papers. The sources this leans on —
`stackexchange`, `hackernews`, `reddit`, `eng_blog` — are not in that breakdown and may be thin. Count
blocks per demand-side source; take five real theses and count congruent blocks per claim. **If a
median thesis binds fewer than ~10, Phase 1 is an ingest campaign, not a feature.** Same discipline
that found `observed_sector` at 0.8% before the investor matcher was built.

**Phase 1 — thesis → claims (~3 days).** One model call. The ladder is a fixed schema; the model
instantiates it and never judges it. `settleable` comes from the table, not the model.

**Phase 2 — the attack (~1 week).** Point the existing refuter at each claim; retrieve through the
existing congruence gates; carry the under-tested flag through to the claim verdict. This is wiring,
not new machinery.

**Phase 3 — the conversation (~1 week).** The agent loop: propose the weakest claim, argue, and close
each turn with settled / attacked / needs-a-person. Candidates surfaced per claim.

**Phase 4 — the call loop (~3 days).** Question set per open claim; somewhere to paste what came back;
the cross-check; the updated standing.

**Later:** a saved, shareable thesis. Copy `su_map`'s implementation — of the three saved-artifact
implementations in the repo it is the only one that writes revisions, does not leak its share token to
non-owners, and uses a resolved user id.

## Refusals

- No thesis score, no probability of success, no "will it sell" verdict — any scalar there is a
  fabricated claim about a product that does not exist.
- No TAM/SAM/SOM, no willingness-to-pay estimate inferred from adjacent categories. Analogy is not
  evidence and never renders as a number.
- No contacting, scheduling or outreach to named individuals.
- No LinkedIn scraping — a link, never a source. `person_reader.py` already states this position, and
  `investors/sources/people.py` measured that LinkedIn-anchored parsing reads almost nobody: of four
  real VC team pages, two printed zero LinkedIn links.
- Forum sentiment never becomes a conclusion. It is the most seductive false positive in this mode.
- The agent never asks a question the corpus can answer.

## Eval cases

Each designed to pass a gate while being wrong.

1. **The enthusiastic forum** — lively thread, zero filed or observed spend. Market signal only.
2. **The unvendorable internal build** — five firms describe building it as core IP. Hostile terrain,
   not demand.
3. **The solved pain** — real problem, mature good-enough substitute already running.
4. **The adjacent category** — evidence one hop away. Must fail `subject_bound`, not pad the report.
5. **The complainer with no budget** — never presented as a customer contact.
6. **The dead predecessor** — someone already tried this and failed. Must be found by the refuter;
   missing it is the most expensive failure this mode can have.
7. **The confident interviewee** — a call assertion the record contradicts. The conflict must surface
   and neither side may silently win.
8. **The agreeable agent** — a thesis with no disconfirming evidence available. Must return
   *under-tested*, never *supported*. This is the case that decides whether the mode is honest.
9. **The genuine category creation** — no spend evidence anywhere and the thesis is still good. Must
   produce the constraint framing, not a dismissal. This decides whether the mode is opened twice.

## Open questions

1. **Founder or investor?** An investor wants the fastest defensible "no"; a founder wants to know
   where to look next. The claim ledger serves both; the default view and the copy do not. The review
   panel was unanimous that serving both audiences equally fails. Owner's call; nothing else depends
   on it.
2. **Does Phase 0 clear its gate?** Everything is contingent on it.
3. **Does the refuter work on a demand claim?** It was built for research hypotheses over a technical
   corpus. Whether *"mid-market banks already pay for this"* produces useful disconfirming queries is
   an open empirical question, and the cheapest thing to test first — a one-afternoon check before
   Phase 1.
4. **How much of a call actually gets captured?** Pasting notes is the cheap version. Whether people
   do it at all is the risk that decides whether the ledger is real or decorative.
