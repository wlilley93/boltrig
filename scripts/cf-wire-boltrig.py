#!/usr/bin/env python3
"""Idempotently wire every Boltrig hostname onto the configured production host
Cloudflare tunnel: a proxied DNS CNAME per host -> <tunnel>.cfargotunnel.com, and
a tunnel public-hostname ingress rule per host -> http://localhost:80 (the host
Caddy routes by hostname). Minimal calls (the token got rate-flagged by rapid
probing during the initial bring-up). Reads CLOUDFLARE_API_TOKEN +
CLOUDFLARE_ACCOUNT_ID from the env.

boltrig.ai IS THE PRODUCT DOMAIN as of 2026-08-18. boltrig.io and boltrig.dev
were the originals and are now redirect sources only.

Layout served by the host Caddy:
  boltrig.ai / www.boltrig.ai   -> /srv/boltrig-marketing (the landing page)
  app.boltrig.ai                -> 127.0.0.1:8622 (Worker, with 8620 as fallback)
  dev.boltrig.ai                -> 127.0.0.1:1420 + :8629 (the Worker preview)
  boltrig.io / www.boltrig.io   -> 301 to https://boltrig.ai
  app.boltrig.io                -> 301 to https://app.boltrig.ai
  dev.boltrig.io                -> 301 to https://dev.boltrig.ai
  boltrig.dev / www.boltrig.dev -> 301 to https://boltrig.ai

A REDIRECT SOURCE STILL NEEDS ITS DNS RECORD AND ITS INGRESS RULE. The 301 is
issued by Caddy on the box, so the request has to reach the box first: dropping
a retired hostname from this table does not retire it, it breaks it. Retiring
one for real means removing its Caddy vhost and its DNS record together, and
the standing reason not to is that inbound links to boltrig.io predate .ai.
"""
import json
import os
import sys
import urllib.error
import urllib.request

TOK = os.environ["CLOUDFLARE_API_TOKEN"]
ACC = os.environ["CLOUDFLARE_ACCOUNT_ID"]
TUN = "d7bbe973-cefa-4269-82e2-b0df7673317c"
ZONES = {"boltrig.ai": "b077bd6e8e8dca4b53316bf6e3a80d25",
         "boltrig.io": "f7d8f1a9e9798510472b2b8b2664e361",
         "boltrig.dev": "c9dd24626a9cf83beef3b5f77cf4bba2"}
HOSTS = {  # hostname -> zone
    "boltrig.ai": "boltrig.ai",
    "www.boltrig.ai": "boltrig.ai",
    "app.boltrig.ai": "boltrig.ai",
    "dev.boltrig.ai": "boltrig.ai",
    "boltrig.io": "boltrig.io",
    "www.boltrig.io": "boltrig.io",
    "app.boltrig.io": "boltrig.io",
    "dev.boltrig.io": "boltrig.io",
    "boltrig.dev": "boltrig.dev",
    "www.boltrig.dev": "boltrig.dev",
}


def api(method, path, body=None):
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4" + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:
            return {"success": False, "errors": [{"message": f"HTTP {e.code}"}]}


def main():
    # 1) DNS CNAMEs (idempotent)
    for host, zname in HOSTS.items():
        zid = ZONES[zname]
        ex = api("GET", f"/zones/{zid}/dns_records?name={host}")
        if not ex.get("success"):
            print(f"DNS {host}: read failed -> {ex.get('errors')}")
            if ex.get("errors", [{}])[0].get("code") == 10000:
                print("  -> token is throttled or lacks scope on this zone; stop and retry later")
                return 2
            continue
        if ex.get("result"):
            record = ex["result"][0]
            target = f"{TUN}.cfargotunnel.com"
            if (record.get("type"), record.get("content"), record.get("proxied")) == (
                "CNAME", target, True
            ):
                print(f"DNS {host}: present ({record['type']})")
                continue
            d = api(
                "PUT",
                f"/zones/{zid}/dns_records/{record['id']}",
                {"type": "CNAME", "name": host, "content": target, "proxied": True, "ttl": 1},
            )
            print(f"DNS {host}: reconciled -> {'ok' if d.get('success') else d.get('errors')}")
            continue
        d = api("POST", f"/zones/{zid}/dns_records",
                {"type": "CNAME", "name": host, "content": f"{TUN}.cfargotunnel.com",
                 "proxied": True, "ttl": 1})
        print(f"DNS {host}: {'created' if d.get('success') else d.get('errors')}")

    # 2) tunnel ingress (single GET, single PUT)
    cur = api("GET", f"/accounts/{ACC}/cfd_tunnel/{TUN}/configurations")
    if not cur.get("success"):
        print(f"ingress: GET failed -> {cur.get('errors')}")
        return 2
    cfg = (cur.get("result") or {}).get("config") or {}
    ingress = cfg.get("ingress") or [{"service": "http_status:404"}]
    have = {r.get("hostname") for r in ingress}
    body = [r for r in ingress if r.get("hostname")]
    catch = [r for r in ingress if not r.get("hostname")] or [{"service": "http_status:404"}]
    added = [h for h in HOSTS if h not in have]
    for h in added:
        body.append({"hostname": h, "service": "http://localhost:80"})
    if added:
        cfg["ingress"] = body + catch
        put = api("PUT", f"/accounts/{ACC}/cfd_tunnel/{TUN}/configurations", {"config": cfg})
        print(f"ingress: added {added} -> {'ok' if put.get('success') else put.get('errors')}")
    else:
        print("ingress: all hosts already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
