"""Server-side NPPES fetch+load (Frontier People) — runs INSIDE the US-region prod container
because CMS's Akamai edge denies non-US/automated clients (both the operator's browser and
local curl were blocked). Downloads the monthly zip (~1GB, fits ephemeral disk), then
STREAMS the npidata CSV member straight out of the zip through the pilot-taxonomy filter
into Postgres — the 9GB CSV never touches disk, memory stays flat.

Mirrors scripts/load_nppes.py (the offline path for US-located operators)."""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import zipfile

# Coverage = ALL physician taxonomies (NUCC Allopathic & Osteopathic grouping, 238 codes;
# was a 23-code pilot until 2026-08-12). PILOT_TAXONOMIES kept as the working alias — the
# loader and scripts/load_nppes.py both key off it.
from api.people_taxonomies import TAXONOMY_LABELS

PILOT_TAXONOMIES: dict[str, str] = TAXONOMY_LABELS
COLS = {
    "npi": "NPI", "type": "Entity Type Code",
    "last": "Provider Last Name (Legal Name)", "first": "Provider First Name",
    "cred": "Provider Credential Text",
    "org_city": "Provider Business Practice Location Address City Name",
    "org_state": "Provider Business Practice Location Address State Name",
    "phone": "Provider Business Practice Location Address Telephone Number",
    "deact": "NPI Deactivation Date",
}
TAX_COLS = [f"Healthcare Provider Taxonomy Code_{i}" for i in range(1, 16)]
PRIMARY_COLS = [f"Healthcare Provider Primary Taxonomy Switch_{i}" for i in range(1, 16)]

LISTING = "https://download.cms.gov/nppes/NPI_Files.html"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


async def find_zip_url() -> str:
    """Find the monthly dissemination zip. Format-agnostic: ANY .zip href on the listing,
    excluding weekly/deactivated files; falls back to probing guessed month-name URLs
    (the page markup has changed before — the 'no monthly zip link' failure)."""
    import httpx
    async with httpx.AsyncClient(timeout=60, headers=_UA, follow_redirects=True) as c:
        r = await c.get(LISTING)
        r.raise_for_status()
        m = re.findall(r"""href=["']([^"']+\.zip)["']""", r.text, flags=re.I)
        full = [u for u in m if "weekly" not in u.lower() and "deactiv" not in u.lower()
                and "dissemination" in u.lower()]
        if full:
            u = full[0]
            if u.startswith("http"):
                return u
            return f"https://download.cms.gov/nppes/{u.lstrip('./')}"
        # fallback: probe guessed filenames for this + last month, V2/V1/plain
        today = dt.date.today()
        months = [today.replace(day=1)]
        months.append((months[0] - dt.timedelta(days=1)).replace(day=1))
        for mo in months:
            base = f"NPPES_Data_Dissemination_{mo.strftime('%B')}_{mo.year}"
            for suffix in ("", "_V2", "_V.2"):
                url = f"https://download.cms.gov/nppes/{base}{suffix}.zip"
                try:
                    h = await c.head(url)
                    if h.status_code == 200:
                        return url
                except Exception:   # noqa: BLE001
                    continue
        snippet = re.sub(r"\s+", " ", r.text)[:300]
        raise RuntimeError(f"no monthly zip link found; page starts: {snippet!r}")


async def download_zip(url: str, dest: str, progress=None) -> None:
    import httpx
    async with httpx.AsyncClient(timeout=None, headers=_UA, follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            done = 0
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if progress and done % (100 << 20) < (1 << 20):
                        await progress(f"downloaded {done >> 20} MB")


async def load_from_zip(zip_path: str, dsn: str, vintage: str, progress=None) -> dict:
    import asyncpg
    from eigen_kernel.people.store import PeopleStore
    store = PeopleStore(dsn)
    await store._get_pool()
    await store.close()
    conn = await asyncpg.connect(dsn)
    seen = kept = 0
    ent_rows, contact_rows = [], []
    vintage_d = dt.date.fromisoformat(vintage)

    async def flush():
        nonlocal ent_rows, contact_rows
        if ent_rows:
            await conn.executemany(
                """INSERT INTO noesis_entity (entity_id, vertical, kind, name, taxonomy,
                     specialty, credential, city, state, country, status, source, valid_as_of)
                   VALUES ($1,'medical','physician',$2,$3,$4,$5,$6,$7,'US',$8,'nppes',$9)
                   ON CONFLICT (entity_id) DO UPDATE SET
                     name=EXCLUDED.name, taxonomy=EXCLUDED.taxonomy, specialty=EXCLUDED.specialty,
                     credential=EXCLUDED.credential, city=EXCLUDED.city, state=EXCLUDED.state,
                     status=CASE WHEN noesis_entity.status='suppressed'
                                 THEN 'suppressed' ELSE EXCLUDED.status END,
                     valid_as_of=EXCLUDED.valid_as_of, updated_at=now()""", ent_rows)
        if contact_rows:
            await conn.executemany(
                """INSERT INTO noesis_entity_contact (entity_id, kind, value, source)
                   VALUES ($1,'phone',$2,'nppes') ON CONFLICT DO NOTHING""", contact_rows)
        ent_rows, contact_rows = [], []

    zf = zipfile.ZipFile(zip_path)
    member = next(n for n in zf.namelist()
                  if n.lower().startswith("npidata_pfile") and n.endswith(".csv")
                  and "fileheader" not in n.lower())
    with zf.open(member) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
        for row in reader:
            seen += 1
            if row.get(COLS["type"]) != "1":
                continue
            taxes = [(row.get(t) or "").strip() for t in TAX_COLS]
            prim = [(row.get(p) or "").strip() for p in PRIMARY_COLS]
            code = next((c for c, p in zip(taxes, prim)
                         if c in PILOT_TAXONOMIES and p == "Y"), "") or \
                next((c for c in taxes if c in PILOT_TAXONOMIES), "")
            if not code:
                continue
            npi = (row.get(COLS["npi"]) or "").strip()
            if not (npi.isdigit() and len(npi) == 10):
                continue
            name = (f"{(row.get(COLS['first']) or '').strip()} "
                    f"{(row.get(COLS['last']) or '').strip()}").strip()
            if not name:
                continue
            status = "retired" if (row.get(COLS["deact"]) or "").strip() else "active"
            eid = f"npi:{npi}"
            ent_rows.append([eid, name, code, PILOT_TAXONOMIES[code],
                             (row.get(COLS["cred"]) or "").strip()[:40],
                             (row.get(COLS["org_city"]) or "").strip()[:80],
                             (row.get(COLS["org_state"]) or "").strip()[:2],
                             status, vintage_d])
            phone = (row.get(COLS["phone"]) or "").strip()
            if phone:
                contact_rows.append([eid, phone[:24]])
            kept += 1
            if len(ent_rows) >= 5000:
                await flush()
                if progress:
                    await progress(f"loaded {kept:,} of {seen:,} scanned")
    await flush()
    n = await conn.fetchval("SELECT count(*) FROM noesis_entity WHERE source='nppes'")
    await conn.close()
    return {"scanned": seen, "kept": kept, "total_nppes_entities": n}
