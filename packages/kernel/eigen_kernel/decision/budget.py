"""Question budgeting — a frame-weighted, global-target allocation (not a flat ceiling). Domain-free.

The failure the flat `critical→N / else→M` ceiling caused: it bounds how MANY questions a dimension gets
but not WHICH dimensions deserve depth on THIS decision, so rabbit-holing just moves inside a dimension
and a thin dimension gets padded with filler. Fix (panel 2026-09-16): distribute a GLOBAL target across
the aspects by weight = f(criticality, how many of the frame's load-bearing assumptions/risks land on
that aspect). Depth follows the decision's own risk density. Every aspect keeps a floor of 1 (coverage
cannot regress); no aspect exceeds a cap (no rabbit-hole); an aspect that cannot use its share hands it
back (reallocation), never manufactures filler.

The kernel owns the mechanics; the vertical owns nothing here except the `critical` flags it already
sets and the `total`/`floor`/`cap` it may tune. No domain noun appears.
"""
from __future__ import annotations

from .types import Aspect

DEFAULT_TOTAL = 24     # a full, systematic sweep; the profile/app may pass a smaller total for a shallow pass
FLOOR = 1              # every aspect is asked at least once — the coverage guarantee
CAP = 4               # no single aspect may run away with the budget


def frame_dim_counts(frame: dict | None) -> dict[str, int]:
    """How many of the frame's assumptions + risks are tagged to each dimension — the per-decision signal
    of where the load-bearing questions actually live (frame.py tags each with a dimension when it maps
    to one). Untagged items contribute to no dimension."""
    counts: dict[str, int] = {}
    for section in ("assumptions", "risks"):
        for item in (frame or {}).get(section, []) or []:
            dim = str((item or {}).get("dimension") or "").strip() if isinstance(item, dict) else ""
            if dim:
                counts[dim] = counts.get(dim, 0) + 1
    return counts


def aspect_weight(aspect: Aspect, frame_counts: dict[str, int]) -> float:
    """A dimension's share weight: a base from criticality, plus one per frame assumption/risk that
    landed on it. A critical dimension the frame also flags repeatedly rises to the top; a non-critical
    dimension the frame never mentions stays at the floor."""
    base = 2.0 if aspect.critical else 1.0
    return base + float(frame_counts.get(aspect.key, 0))


def allocate_budget(aspects: tuple[Aspect, ...], frame: dict | None = None, *,
                    total: int = DEFAULT_TOTAL, floor: int = FLOOR, cap: int = CAP) -> dict[str, int]:
    """-> {aspect_key: soft budget}. Deterministic. Every aspect gets `floor`; the remainder of `total`
    is distributed by weight, clamped to `cap`, with any weight-share a capped aspect cannot take handed
    back to the others (reallocation). If `total` cannot even cover the floors, the floor still holds
    (coverage wins over the numeric target — a smaller `total` is a request, not a hard ceiling)."""
    keys = [a.key for a in aspects]
    if not keys:
        return {}
    floor = max(0, floor)
    cap = max(floor, cap)
    alloc = {k: floor for k in keys}
    remaining = total - floor * len(keys)
    if remaining <= 0:
        return alloc     # floor already meets/exceeds the target; coverage floor stands

    counts = frame_dim_counts(frame)
    weights = {a.key: aspect_weight(a, counts) for a in aspects}
    headroom = {k: cap - floor for k in keys}

    # Largest-remainder distribution, re-normalizing over only the aspects that still have headroom, so a
    # capped aspect's share flows to the rest rather than being lost or turned into filler.
    while remaining > 0:
        eligible = [k for k in keys if headroom[k] > 0]
        if not eligible:
            break
        wsum = sum(weights[k] for k in eligible) or float(len(eligible))
        # ideal (fractional) extra for each eligible aspect this round
        ideal = {k: remaining * (weights[k] / wsum) for k in eligible}
        # give each its floor of the ideal, capped by headroom; track the largest remainders for the rest
        given = 0
        rema: list[tuple[float, str]] = []
        for k in eligible:
            take = min(headroom[k], int(ideal[k]))
            alloc[k] += take
            headroom[k] -= take
            given += take
            rema.append((ideal[k] - int(ideal[k]), k))
        remaining -= given
        if given == 0:
            # fractional round: hand out one at a time by largest remainder (then by weight, then key —
            # deterministic) until the remainder is spent or headroom is gone.
            rema.sort(key=lambda t: (-t[0], -weights[t[1]], t[1]))
            for _frac, k in rema:
                if remaining <= 0:
                    break
                if headroom[k] > 0:
                    alloc[k] += 1
                    headroom[k] -= 1
                    remaining -= 1
            # if nothing could be given (all eligible out of headroom), loop's eligible check ends it
            if all(headroom[k] <= 0 for k in eligible):
                break
    return alloc
