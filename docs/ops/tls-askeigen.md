# askeigen.com TLS — why Cloudflare is in front, and what to check in November

Written 2026-09-11 after a full afternoon on it. Read this before "simplifying" the DNS.

## The symptom

Chrome: *"Your connection to this site is not secure"* on `https://askeigen.com/`, while `curl` and
`openssl` both reported `Verify return code: 0 (ok)`. That contradiction is the whole story: the tools
accepted a chain macOS happened to tolerate; Chrome is stricter and was right.

## The cause

Railway issued the apex a certificate from a Let's Encrypt hierarchy that terminates in a root **no
browser trust store carries**:

```
askeigen.com     CN=askeigen.com  ->  Let's Encrypt YR1/YR2  ->  ISRG Root YR      (untrusted)
www.askeigen.com CN=www...        ->  Let's Encrypt YE2      ->  Root YE -> ISRG Root X2   (trusted)
asknoesis.com    CN=asknoesis.com ->  Let's Encrypt YE1      ->  Root YE -> ISRG Root X2   (trusted)
```

Verified directly: the macOS system store holds `ISRG Root X1` and `ISRG Root X2` and has **zero**
entries matching `Root YR`.

Same Railway account, same service, minutes apart — `www` drew the good hierarchy and the apex did
not. We do not control which chain ACME issues; there is no Railway or Cloudflare setting for it.

## What did NOT fix it

- `railway domain certificate retry` — refused: *"only available after certificate issuance fails"*.
  Railway considers a well-formed certificate with an untrusted root to be VALID.
- Delete + re-add the custom domain. Done **three times**. New serial each time, fresh issuance each
  time, `Root YR` all three times (YR2, then YR1, then YR1).
- A complete teardown of both the Railway domains and every Cloudflare record, rebuilt from scratch.
  Same result for the apex — though it did fix `www`, which had never been a Railway domain at all
  and was 404ing.

## What fixed it

**The Cloudflare proxy (orange cloud) on both hostnames.** Visitors terminate TLS against
Cloudflare's Google Trust Services certificate; Railway's untrusted chain only exists on the
Cloudflare-to-origin hop, where no browser trust store is consulted.

This is a legitimate production configuration, not a hack. It is also now load-bearing: **turning the
proxy off returns the apex to "Not secure"** until Railway issues a trusted chain.

## Current state

| | |
|---|---|
| Railway | `askeigen.com` + `www.askeigen.com`, both port **8080**, both certificates VALID |
| Cloudflare | two CNAMEs, each to its OWN Railway target, both **proxied** |
| Visitor-facing cert | Cloudflare's (GTS Root R4) on the apex; trusted on both |

`www` currently SERVES the site rather than redirecting, so the same content sits at two URLs. Making
the apex canonical needs a Cloudflare Redirect Rule, which needs a token with Rules permission.

## Two things to do, and one to check

1. **Confirm SSL/TLS mode is "Full"** (Cloudflare -> SSL/TLS -> Overview). On **Flexible** the
   Cloudflare-to-Railway hop runs in the clear while the padlock still shows — the worst of both.
   A DNS-scoped API token cannot read this setting; it has to be checked in the dashboard.
2. **~10 November 2026 — renewal.** The origin certificates expire 10 Dec and Railway renews about
   30 days out. With the proxy ON, the ACME challenge may not reach the origin — that is exactly what
   blocked issuance on the morning of 2026-09-11. On **Full** an expired origin certificate is
   harmless; on **Full (strict)** it takes the site down. Either stay on Full, or grey-cloud both
   records for ten minutes while it renews.
3. **Retry the apex then, not now.** Railway reissues at renewal anyway, so a fresh roll of the dice
   costs nothing extra at that moment. If it lands on a trusted hierarchy, the proxy becomes optional
   and the renewal fragility goes away. Doing it today would mean breaking a working production site
   on a gamble that has lost three times.

## If it needs escalating

Railway support, with this evidence: two domains on one account and one service, issued minutes
apart, one trusted and one not. Domain IDs are in `railway domain list -s eigen-api`.
