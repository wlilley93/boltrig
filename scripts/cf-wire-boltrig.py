#!/usr/bin/env python3
"""Idempotently wire the boltrig.io / boltrig.dev hostnames onto the jellytot-prod
Cloudflare tunnel: a proxied DNS CNAME per host -> <tunnel>.cfargotunnel.com, and
a tunnel public-hostname ingress rule per host -> http://localhost:80 (the host
Caddy routes by hostname). Minimal calls (the token got rate-flagged by rapid
probing during the initial bring-up). Reads CLOUDFLARE_API_TOKEN +
CLOUDFLARE_ACCOUNT_ID from the env.

Layout served by the host Caddy:
  boltrig.io / www.boltrig.io  -> /srv/boltrig-marketing (the landing page)
  app.boltrig.io               -> 127.0.0.1:8620 (the console UI)
  boltrig.dev / www.boltrig.dev-> 301 redirect to https://boltrig.io
"""
import json
import os
import sys
import urllib.error
import urllib.request

TOK = os.environ["CLOUDFLARE_API_TOKEN"]
ACC = os.environ["CLOUDFLARE_ACCOUNT_ID"]
TUN = "d7bbe973-cefa-4269-82e2-b0df7673317c"
ZONES = {"boltrig.io": "f7d8f1a9e9798510472b2b8b2664e361",
         "boltrig.dev": "c9dd24626a9cf83beef3b5f77cf4bba2"}
HOSTS = {  # hostname -> zone
    "boltrig.io": "boltrig.io",
    "www.boltrig.io": "boltrig.io",
    "app.boltrig.io": "boltrig.io",
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
            print(f"DNS {host}: present ({ex['result'][0]['type']})")
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
