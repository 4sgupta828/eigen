"""Server-side CMS loaders (Frontier People) — run INSIDE the US-region prod container
because CMS's edge denies non-US/automated clients (both the operator's browser and local
curl 403). Three parts, each stream-downloaded then filtered to NPIs already in the
inventory:

- dac        Doctors & Clinicians national file → GROUP-PRACTICE affiliations
             (org PAC id + legal name), telehealth contact rows, entity.org backfill.
- facility   Facility Affiliation file → HOSPITAL (etc.) affiliations by CCN, display
             names joined from the Care Compare hospital file.
- utilization Medicare Physician & Other Practitioners "by Provider" → volume metrics
             (services + beneficiaries, honest E-4 labels with the year).

Affiliations power connections() live (shared registry key at read time — pairwise edges
are never materialized at 1.27M entities). Office hours do NOT exist in any CMS/NPPES
dataset; telehealth indicator is the closest recorded signal."""
from __future__ import annotations

import csv
import datetime as dt
import json

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
PDC_META = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{id}"
PDC_DATASETS = {"dac": "mj5m-pzi6", "facility": "27ea-46a8", "hospitals": "xubh-q36u"}
CATALOG = "https://data.cms.gov/data.json"
UTIL_TITLE = "Medicare Physician & Other Practitioners - by Provider"


async def pdc_csv_url(dataset_key: str) -> str:
    """Provider Data Catalog metastore → the dataset's CSV downloadURL."""
    import httpx
    async with httpx.AsyncClient(timeout=60, headers=_UA, follow_redirects=True) as c:
        r = await c.get(PDC_META.format(id=PDC_DATASETS[dataset_key]),
                        params={"show-reference-ids": ""})
        r.raise_for_status()
        d = r.json()
        for dist in d.get("distribution") or []:
            dd = dist.get("data") or dist
            url = dd.get("downloadURL") or ""
            if url.lower().endswith(".csv") or "csv" in (dd.get("mediaType") or ""):
                return url
    raise RuntimeError(f"no CSV distribution for {dataset_key}")


async def catalog_csv_url(title: str) -> tuple[str, str]:
    """data.cms.gov data.json catalog → (latest CSV downloadURL, year) for a dataset
    title. Distributions carry per-year titles like '... : 2023-12-31'."""
    import httpx
    async with httpx.AsyncClient(timeout=120, headers=_UA, follow_redirects=True) as c:
        r = await c.get(CATALOG)
        r.raise_for_status()
        best: tuple[str, str] | None = None
        for ds in r.json().get("dataset", []):
            if ds.get("title", "").strip() != title:
                continue
            for dist in ds.get("distribution") or []:
                url = dist.get("downloadURL") or ""
                if not url.lower().endswith(".csv"):
                    continue
                when = (dist.get("title") or "") + (ds.get("modified") or "")
                if best is None or when > best[1]:
                    best = (url, when)
        if best:
            year = "".join(ch for ch in best[1] if ch.isdigit())[:4] or "unknown"
            return best[0], year
    raise RuntimeError(f"dataset not found in catalog: {title}")


async def download(url: str, dest: str, progress=None) -> None:
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
                        await progress(f"downloaded {done >> 20} MB of {url.rsplit('/', 1)[-1]}")


def _reader(path: str):
    """DictReader with lowercased, stripped headers (CMS header casing drifts across
    releases)."""
    f = open(path, encoding="utf-8-sig", newline="")
    rd = csv.DictReader(f)
    rd.fieldnames = [h.strip().lower() for h in rd.fieldnames]
    return f, rd


async def _known_npis(conn) -> set[str]:
    rows = await conn.fetch("SELECT entity_id FROM noesis_entity WHERE entity_id LIKE 'npi:%'")
    return {r["entity_id"][4:] for r in rows}


async def load_dac(dsn: str, progress=None) -> dict:
    """Group-practice affiliations + telehealth + org backfill from the DAC national file."""
    import asyncpg
    from eigen_kernel.people.store import PeopleStore
    store = PeopleStore(dsn)
    await store._get_pool()   # ensure DDL (noesis_entity_affiliation)
    await store.close()
    url = await pdc_csv_url("dac")
    await download(url, "/tmp/cms_dac.csv", progress)
    conn = await asyncpg.connect(dsn)
    known = await _known_npis(conn)
    seen = kept = 0
    affs, tele, orgs = [], [], {}

    async def flush():
        nonlocal affs, tele
        if affs:
            await conn.executemany(
                """INSERT INTO noesis_entity_affiliation (entity_id, kind, affil_key, name, source)
                   VALUES ($1,'group_practice',$2,$3,'cms_dac')
                   ON CONFLICT (entity_id, kind, affil_key) DO UPDATE SET
                     name = CASE WHEN EXCLUDED.name != '' THEN EXCLUDED.name
                                 ELSE noesis_entity_affiliation.name END,
                     retrieved_at = now()""", affs)
        if tele:
            await conn.executemany(
                """INSERT INTO noesis_entity_contact (entity_id, kind, value, source)
                   VALUES ($1,'telehealth','offers telehealth','cms_dac')
                   ON CONFLICT DO NOTHING""", tele)
        affs, tele = [], []

    f, rd = _reader("/tmp/cms_dac.csv")
    with f:
        for row in rd:
            seen += 1
            npi = (row.get("npi") or "").strip()
            if npi not in known:
                continue
            eid = f"npi:{npi}"
            pac = (row.get("org_pac_id") or "").strip()
            # org legal name: "org_nm" in older DAC releases, "facility name" in current
            org = (row.get("org_nm") or row.get("facility name") or "").strip()[:120]
            if pac:
                affs.append([eid, pac, org])
                if org and eid not in orgs:
                    orgs[eid] = org
            if (row.get("telehlth") or "").strip().upper() == "Y":
                tele.append([eid])
            kept += 1
            if len(affs) >= 5000:
                await flush()
                if progress and kept % 100000 < 5000:
                    await progress(f"dac: {kept:,} kept of {seen:,} scanned")
    await flush()
    org_rows = list(orgs.items())
    for i in range(0, len(org_rows), 5000):
        await conn.executemany(
            "UPDATE noesis_entity SET org=$2, updated_at=now() WHERE entity_id=$1 AND org=''",
            org_rows[i:i + 5000])
    n = await conn.fetchval(
        "SELECT count(*) FROM noesis_entity_affiliation WHERE kind='group_practice'")
    await conn.close()
    return {"scanned": seen, "kept_rows": kept, "group_affiliations": n,
            "orgs_backfilled": len(org_rows)}


async def load_facility(dsn: str, progress=None) -> dict:
    """Hospital (and other facility) affiliations by CCN, names from Care Compare."""
    import asyncpg
    from eigen_kernel.people.store import PeopleStore
    store = PeopleStore(dsn)
    await store._get_pool()
    await store.close()
    hosp_url = await pdc_csv_url("hospitals")
    await download(hosp_url, "/tmp/cms_hosp.csv", progress)
    names: dict[str, str] = {}
    f, rd = _reader("/tmp/cms_hosp.csv")
    with f:
        for row in rd:
            ccn = (row.get("facility id") or row.get("facility_id") or "").strip()
            nm = (row.get("facility name") or row.get("facility_name") or "").strip()
            if ccn and nm:
                names[ccn] = nm[:120]
    if progress:
        await progress(f"hospital name lookup: {len(names):,} facilities")
    url = await pdc_csv_url("facility")
    await download(url, "/tmp/cms_fac.csv", progress)
    conn = await asyncpg.connect(dsn)
    known = await _known_npis(conn)
    seen = kept = 0
    affs = []

    async def flush():
        nonlocal affs
        if affs:
            await conn.executemany(
                """INSERT INTO noesis_entity_affiliation (entity_id, kind, affil_key, name, source)
                   VALUES ($1,$2,$3,$4,'cms_facility')
                   ON CONFLICT (entity_id, kind, affil_key) DO UPDATE SET
                     name = CASE WHEN EXCLUDED.name != '' THEN EXCLUDED.name
                                 ELSE noesis_entity_affiliation.name END,
                     retrieved_at = now()""", affs)
        affs = []

    f, rd = _reader("/tmp/cms_fac.csv")
    with f:
        for row in rd:
            seen += 1
            npi = (row.get("npi") or "").strip()
            if npi not in known:
                continue
            ccn = (row.get("facility affiliations certification number")
                   or row.get("facility_afl_ccn") or "").strip()
            if not ccn:
                continue
            kind = ((row.get("facility type") or row.get("facility_type") or "facility")
                    .strip().lower() or "facility")
            affs.append([f"npi:{npi}", kind, ccn, names.get(ccn, "")])
            kept += 1
            if len(affs) >= 5000:
                await flush()
                if progress and kept % 100000 < 5000:
                    await progress(f"facility: {kept:,} kept of {seen:,} scanned")
    await flush()
    n = await conn.fetchval(
        "SELECT count(*) FROM noesis_entity_affiliation WHERE kind != 'group_practice'")
    await conn.close()
    return {"scanned": seen, "kept_rows": kept, "facility_affiliations": n,
            "hospital_names": len(names)}


async def load_utilization(dsn: str, progress=None) -> dict:
    """Medicare by-Provider volume metrics with honest year-stamped labels (E-4)."""
    import asyncpg
    url, year = await catalog_csv_url(UTIL_TITLE)
    await download(url, "/tmp/cms_util.csv", progress)
    conn = await asyncpg.connect(dsn)
    known = await _known_npis(conn)
    seen = kept = 0
    rows = []

    async def flush():
        nonlocal rows
        if rows:
            await conn.executemany(
                """INSERT INTO noesis_entity_metric (entity_id, metric_key, metric_label,
                     value, unit, period, detail, source)
                   VALUES ($1,$2,$3,$4,$5,$6,'','cms_mupphy')
                   ON CONFLICT (entity_id, metric_key, period, detail) DO UPDATE SET
                     value = EXCLUDED.value, metric_label = EXCLUDED.metric_label,
                     retrieved_at = now()""", rows)
        rows = []

    f, rd = _reader("/tmp/cms_util.csv")
    with f:
        for row in rd:
            seen += 1
            npi = (row.get("rndrng_npi") or "").strip()
            if npi not in known:
                continue
            eid = f"npi:{npi}"
            try:
                srv = float(row.get("tot_srvcs") or 0)
                ben = float(row.get("tot_benes") or 0)
            except ValueError:
                continue
            if srv:
                rows.append([eid, "medicare_partb_services",
                             f"Original Medicare Part B services, {year}",
                             srv, "services", year])
            if ben:
                rows.append([eid, "medicare_beneficiaries",
                             f"Original Medicare Part B beneficiaries, {year}",
                             ben, "beneficiaries", year])
            kept += 1
            if len(rows) >= 5000:
                await flush()
                if progress and kept % 100000 < 5000:
                    await progress(f"utilization: {kept:,} kept of {seen:,} scanned ({year})")
    await flush()
    n = await conn.fetchval("SELECT count(*) FROM noesis_entity_metric")
    await conn.close()
    return {"scanned": seen, "kept_providers": kept, "metric_rows": n, "year": year}


LOADERS = {"dac": load_dac, "facility": load_facility, "utilization": load_utilization}
