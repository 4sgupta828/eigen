"""`vehicle_bound` — turning fund filings into managers, without inventing firms (docs/specs/investors.md §5).

A Form D fund filing names a vehicle, not a manager. "Layer Global Fund I, L.P.", "Layer Global Fund I-A, L.P."
and "Layer China Fund I, L.P." are three filings and one firm; "Anthropic SPV I, LLC" is a filing and no firm
at all. Getting from one to the other is the whole of Step 0, and the naive version fails loudly.

Measured on the 2026Q2 quarter (2,983 filings the filer typed "Venture Capital Fund"):

* Attaching by name alone — the fund's legal name starting with a known firm's name — reaches only **28%**.
* Clustering by shared related persons, ungated, produces **two blobs of 733 and 674 filings**. The cause is
  precise: the top signatories are SPV administration platforms — `fund gp, llc` (733 filings), `belltower fund
  group, ltd.` (715), `llc sydecar` (673) and one platform employee (669) — who sign hundreds of unrelated
  vehicles a quarter. **29 signatories out of 2,224 carry all of the damage.**
* Dropping SPV-shaped names first (59% of the quarter) and capping signatory degree at 8 gives **1,220 real
  vehicles → 924 manager clusters, largest cluster 8** — Tamarack Global's four vehicles, WH Capital's four.

So: drop SPVs, cap the degree, cluster, then attach the CLUSTER to a named firm. Never the reverse.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

# A signatory on more than this many fund filings IN ONE YEAR is a service provider, not a GP. Measured on a
# single quarter the real GPs sat at 1-8 and the administrators at 68-733 — nothing in between. Per year rather
# than in total, because over thirty quarters a working GP legitimately signs dozens.
MAX_SIGNATORY_DEGREE = 8

# Words that may legally follow a firm's name inside its own fund's name. Anything else is a different firm.
FUND_FORM_WORDS = {
    "fund", "funds", "capital", "partners", "partnership", "ventures", "venture", "lp", "llc", "l", "p", "ltd",
    "limited", "inc", "co", "company", "gp", "management", "growth", "opportunities", "opportunity", "select",
    "annex", "parallel", "associates", "investors", "investments", "investment", "holdings", "trust", "the",
    "a", "of", "and", "series", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii",
    "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "one", "two", "three", "four", "five",
}
_ROMAN_OR_NUM = re.compile(r"^(?:[ivxl]+|\d+[a-z]?)$")


def words(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (s or "").lower()) if w]


def name_opens_with(firm_name: str, fund_name: str) -> bool:
    """Does `fund_name` open with `firm_name`, with only fund-form words after it?

    The existing `api/startups/sources/investors.py:name_matches` is a plain prefix test on word lists. It
    correctly refuses "accel" → "Accela", but it ACCEPTS "accel" → "Accel KKR Capital Partners", because
    ["accel"] is a prefix of ["accel","kkr",...]. That is this spec's own §5 trap passing its own gate, found
    by the code-grounded reviewer. The fix is the tail test: after the firm's name is consumed, every remaining
    word must be a fund-form word or a numeral. "kkr", "india", "china" are content words, and they refuse.
    """
    a, b = words(firm_name), words(fund_name)
    if not a or not b or len(a) > len(b):
        return False
    if any(x != y for x, y in zip(a, b)):
        return False
    return all(w in FUND_FORM_WORDS or _ROMAN_OR_NUM.match(w) for w in b[len(a):])


# Words a management company appends to the brand it actually goes by. Form ADV records the legal manager
# ("UP PARTNERS MANAGEMENT COMPANY, LLC") while the fund is filed under the brand ("UP Partners Fund II, LP"),
# so matching only on the full legal name found 50 of 2,113 clusters in the measured run. Stripping this tail
# is what closes that gap.
_MANAGER_TAIL = {"management", "managers", "manager", "advisors", "advisers", "company", "co", "llc", "lp",
                 "l", "p", "ltd", "limited", "inc", "gp", "group", "holdings", "partners", "capital",
                 "ventures", "venture", "associates", "corp", "corporation", "llp", "plc"}


def brand_variants(firm: dict) -> list[tuple[str, bool]]:
    """[(name to match on, needs_state_confirmation)] for a firm — the legal name, then the brand inside it.

    The stripped brand is the recall fix, and it carries a cost: stripping "Bond Capital" to "bond" makes a
    one-token name that a stranger's "Bond Fund I LP" would also satisfy. So a SINGLE-token stripped brand only
    attaches when the fund's state also matches the firm's — an evidenced conjunction, not a looser string test.
    """
    out: list[tuple[str, bool]] = []
    for raw in (firm.get("name") or "", firm.get("legal_name") or ""):
        if not raw:
            continue
        if (raw, False) not in out:
            out.append((raw, False))
        w = words(raw)
        while w and w[-1] in _MANAGER_TAIL:
            w.pop()
        if w and len(w) < len(words(raw)):
            cand = (" ".join(w), len(w) < 2)
            if cand not in out:
                out.append(cand)
    return out


def signatory_degree(funds: list[dict]) -> Counter:
    """How many distinct filings each related person signs — the statistic that separates GPs from admins."""
    deg: Counter = Counter()
    for f in funds:
        for p in {(p.get("name") or "").strip().lower() for p in (f.get("persons") or [])}:
            if p:
                deg[p] += 1
    return deg


def _eligible_signers(funds: list[dict], max_per_year: int) -> set:
    """Signers who look like GPs rather than fund administrators.

    Degree is measured PER YEAR, not in total. The first version of this capped total degree at 8, which was
    calibrated on a single quarter — over thirty quarters a real GP signs far more than 8 filings and was
    being discarded, while administrators still slipped through. A general partner signs a handful of vehicles
    a year for years; a Luxembourg or Cayman fund administrator signs hundreds a year.
    """
    per_year: dict = {}
    for f in funds:
        yr = str(f.get("first_sale") or "")[:4] or "?"
        for p in {(p.get("name") or "").strip().lower() for p in (f.get("persons") or [])}:
            if p:
                per_year.setdefault(p, Counter())[yr] += 1
    out = set()
    for name, years in per_year.items():
        if max(years.values()) <= max_per_year:
            out.add(name)
    return out


def cluster_funds(funds: list[dict], *, max_degree: int = MAX_SIGNATORY_DEGREE) -> dict[str, str]:
    """{fund id → cluster id}. SPVs excluded; administrators excluded; and a single shared name is not enough.

    **Why one shared signer cannot join two funds.** The first version unioned any two filings that shared one
    low-degree signer. Run over one quarter that looked fine. Run over thirty quarters of real data it produced
    a 142-vehicle cluster containing Access Capital, ARDIAN and Arrow — three unrelated European managers —
    because union-find is TRANSITIVE: A signs with B, B signs with C, and a chain of individually-plausible
    links merges managers that share nobody. Requiring **two** shared signers (or one plus a shared brand word
    in the fund names) breaks the chains, because two unrelated managers sharing two people is rare in a way
    that sharing one administrator is not.
    """
    real = [f for f in funds if not f.get("is_spv")]
    eligible = _eligible_signers(real, max_degree)
    by_signer: dict = {}
    for f in real:
        st = (f.get("state") or "").upper()
        for p in {(p.get("name") or "").strip().lower() for p in (f.get("persons") or [])}:
            if p in eligible:
                by_signer.setdefault((p, st), []).append(f["id"])

    first_word = {f["id"]: (words(f.get("name") or "") or [""])[0] for f in real}
    shared: Counter = Counter()
    for ids in by_signer.values():
        if len(ids) < 2 or len(ids) > 60:      # a list this long is an administrator the year filter missed
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = sorted((ids[i], ids[j]))
                shared[(a, b)] += 1

    parent: dict = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for f in real:
        find(f["id"])
    for (a, b), n in shared.items():
        # two signers in common, or one plus the same leading word in both fund names (a shared brand)
        fw = first_word.get(a)
        brandish = bool(fw) and fw == first_word.get(b) and fw not in FUND_FORM_WORDS and not _ROMAN_OR_NUM.match(fw)
        if n >= 2 or (n == 1 and brandish):
            union(a, b)

    members: dict = defaultdict(list)
    for f in real:
        members[find(f["id"])].append(f)
    out: dict[str, str] = {}
    for root, fs in members.items():
        anchor = min(fs, key=lambda x: (x.get("first_sale") or "9999", x["id"]))
        cid = f"cl_{anchor['id']}"
        for f in fs:
            out[f["id"]] = cid
    return out


def build_firm_index(firms: list[dict]) -> dict:
    """A first-word index over every firm's name variants, so attaching is linear in the funds, not quadratic.

    Attaching thousands of clusters against thousands of firms by scanning every pair is tens of millions of
    string comparisons. A fund name can only ever match a variant that shares its FIRST word, so that word is
    the index.
    """
    by_word: dict = {}
    by_cik: dict = {}
    one_token: Counter = Counter()
    for fm in firms:
        if fm.get("cik"):
            by_cik.setdefault(str(fm["cik"]).strip(), fm)
        for cand, needs_state in brand_variants(fm):
            w = words(cand)
            if not w:
                continue
            if len(w) == 1:
                one_token[w[0]] += 1
            by_word.setdefault(w[0], []).append((cand, w, needs_state, fm))
    # Namesake rejection for brands. A one-word brand two different firms share ("Eclipse", "Reach",
    # "Ascend") cannot identify either of them, so it identifies neither — the same rule the startup module
    # applies to company names, and the only class the hand-check of 40 attachments found doubtful.
    ambiguous = {t for t, n in one_token.items() if n > 1}
    return {"by_word": by_word, "by_cik": by_cik, "ambiguous_one_token": ambiguous}


def assign_cluster(cluster: list[dict], index: dict) -> dict:
    """{fund id → (firm_id|None, method, note)} — attach PER FUND when a cluster spans more than one firm.

    Attaching a whole cluster to one firm is right when the cluster is one manager's vehicles: the shared GPs
    are evidence that the unmatched vehicles belong there too. It is wrong when the cluster is a platform.
    Measured in prod: all 122 Blackstone vehicles attached to "Blackstone Tactical Opportunities Advisors",
    because one fund in the cluster opened with that arm's name — so a single Blackstone arm claimed the
    firm's entire fund history, which is the same wrong-subject error as reading a16z off a16z Perennial.

    So: if every name match in the cluster points at ONE firm, the cluster attaches to it. If the matches
    disagree, each matched fund goes to its own firm and the unmatched ones stay unattached — because a
    cluster that spans several firms is no longer evidence about any of them.
    """
    per: dict = {}
    for f in cluster:
        fid, method, note = attach_cluster([f], index=index)
        per[f["id"]] = (fid, method, note)
    firms = {v[0] for v in per.values() if v[0]}
    if not firms:
        return {f["id"]: (None, "", "no evidenced path from this cluster to a named firm") for f in cluster}
    if len(firms) == 1:
        only = next(iter(firms))
        note = next(v[2] for v in per.values() if v[0] == only)
        return {f["id"]: (only, per[f["id"]][1] or "cluster", note) for f in cluster}
    return {f["id"]: (per[f["id"]][0], per[f["id"]][1], per[f["id"]][2] if per[f["id"]][0]
                      else f"this cluster spans {len(firms)} firms, so it evidences none of them")
            for f in cluster}


def attach_cluster(cluster: list[dict], firms: list[dict] | None = None, index: dict | None = None) -> tuple[str | None, str, str]:
    """(firm_id, method, note) for a cluster of fund filings against candidate firms.

    Three evidenced paths, in order of strength. Anything else leaves the cluster unattached — a searchable row
    with no firm card, which is the honest outcome and not a failure.
    """
    idx = index or build_firm_index(firms or [])
    for f in cluster:
        cik = (f.get("cik") or "").strip()
        fm = idx["by_cik"].get(cik) if cik else None
        if fm:
            return fm["id"], "cik", f"manager CIK {cik} on the filing"
    names = [f.get("name") or "" for f in cluster]
    states = {(f.get("state") or "").upper() for f in cluster if f.get("state")}
    best: tuple[int, dict, str, str] | None = None
    for fund_name in names:
        fw = words(fund_name)
        if not fw:
            continue
        for cand, cw, needs_state, fm in idx["by_word"].get(fw[0], ()):
            if len(cw) == 1 and cw[0] in idx.get("ambiguous_one_token", ()):
                continue                                  # a brand two firms share names neither
            if needs_state and (fm.get("hq_state") or "").upper() not in states:
                continue
            if name_opens_with(cand, fund_name):
                n = len(cw)
                if best is None or n > best[0]:          # the longest matching firm name wins
                    best = (n, fm, fund_name, cand)
    if best:
        _, fm, fund_name, cand = best
        return fm["id"], "name_sequence", f"fund {fund_name!r} opens with {cand!r}"
    return None, "", "no evidenced path from this cluster to a named firm"
