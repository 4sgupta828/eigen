"""A polite public-web fetcher for the startup sources (stdlib only, synchronous — ingest runs in a thread).

Policy (docs/specs/startup-search.md §4.4): identified User-Agent with a contact address; robots.txt honoured
per host (cached); per-host pacing; a byte cap per page; no login walls, no bot-protection bypass, no proxies —
a 403 / 429 / challenge is reported as a failed fetch, never retried aggressively and never treated as absence.
`html_to_text` is a structural HTML → text reduction (scripts / styles dropped, block tags → newlines)."""
from __future__ import annotations

import gzip
import html as _html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

UA = "EigenStartupSearch/0.1 (+https://eigen-api-production.up.railway.app; sandeepgupta828@gmail.com)"
BYTE_CAP = 400_000
_lock = threading.Lock()
_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class Fetch:
    __slots__ = ("url", "status", "text", "final_url", "error", "content_type")

    def __init__(self, url: str, status: int = 0, text: str = "", final_url: str = "", error: str = "", content_type: str = ""):
        self.url, self.status, self.text, self.final_url, self.error, self.content_type = url, status, text, final_url or url, error, content_type

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and not self.error


def host_of(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or "").lower()


def _pace(host: str, min_gap: float) -> None:
    with _lock:
        last = _last_hit.get(host, 0.0)
        wait = last + min_gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.monotonic()


def robots_allows(url: str, *, timeout: int = 10) -> bool:
    """robots.txt for the host, cached; unreachable robots → allowed (the conventional reading); a robots
    file that disallows our UA or `*` → not fetched."""
    host = host_of(url)
    if not host:
        return False
    with _lock:
        rp = _robots.get(host, "miss")
    if rp == "miss":
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"{urllib.parse.urlsplit(url).scheme}://{host}/robots.txt", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(200_000).decode("utf-8", "ignore")
            rp.parse(body.splitlines())
        except Exception:   # noqa: BLE001 — no robots → allowed
            rp = None
        with _lock:
            _robots[host] = rp
    return True if rp is None else bool(rp.can_fetch(UA, url) or rp.can_fetch("*", url))


def get(url: str, *, timeout: int = 20, min_gap: float = 2.0, respect_robots: bool = True, accept: str = "text/html,application/json;q=0.9,*/*;q=0.5") -> Fetch:
    if respect_robots and not robots_allows(url):
        return Fetch(url, status=0, error="robots_disallow")
    _pace(host_of(url), min_gap)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(BYTE_CAP + 1)
            if r.headers.get("Content-Encoding", "").lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:   # noqa: BLE001
                    pass
            ctype = (r.headers.get("Content-Type") or "").lower()
            text = raw[:BYTE_CAP].decode("utf-8", "ignore")
            return Fetch(url, status=r.status, text=text, final_url=r.geturl(), content_type=ctype)
    except urllib.error.HTTPError as e:
        return Fetch(url, status=e.code, error=f"http_{e.code}")
    except Exception as e:   # noqa: BLE001
        return Fetch(url, status=0, error=type(e).__name__)


def get_json(url: str, **kw):
    f = get(url, accept="application/json", **kw)
    if not f.ok:
        return None
    try:
        return json.loads(f.text)
    except Exception:   # noqa: BLE001
        return None


_BLOCK = re.compile(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>|</tr>|</section>|</article>|</header>|</footer>")


def html_to_text(h: str, cap: int = 60_000) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", h or "")
    t = _BLOCK.sub("\n", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t)
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)          # NUL and other control bytes: Postgres text rejects them
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()[:cap]


def html_title(h: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h or "")
    return _html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()[:200] if m else ""


def links(h: str, base: str) -> list[tuple[str, str]]:
    """(absolute href, anchor text) for every <a> — structural."""
    out = []
    for m in re.finditer(r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', h or ""):
        href = _html.unescape(m.group(1)).strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
        out.append((urllib.parse.urljoin(base, href), _html.unescape(text)))
    return out


def registrable_domain(url_or_host: str) -> str:
    """A company's identity key: the host without `www.` (structural; two-level public suffixes such as
    `co.uk` keep three labels)."""
    h = url_or_host.strip().lower()
    if "://" in h or h.startswith("//"):
        h = host_of(h if "://" in h else "https:" + h)
    h = h.split("/")[0].split(":")[0]
    if h.startswith("www."):
        h = h[4:]
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else h
