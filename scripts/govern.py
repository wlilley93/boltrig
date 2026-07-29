#!/usr/bin/env python3
"""Drive one governed verb to completion headlessly, through the real gates.

    BOLTRIG_PAT=boltrig_pat_... scripts/govern.py control.adapter.activate \\
        --param adapter_id=opbox

WHY THIS EXISTS. A HIGH-consequence verb answers 202 `pending_human` and parks;
completing it means answering the approval and then re-invoking with the
approval id. Three HTTP calls, in a fixed order, with the approval id threaded
between them. Typed by hand that is tedious enough that the real workaround
becomes "open a browser", and an operator who must open a browser cannot let an
agent finish the job.

WHAT IT DOES NOT DO. It bypasses nothing. Every call goes through the same
kernel chokepoint the console uses: the grant check, the consequence gate, the
rate limit, four-eyes, and the audit row all still run. Whether the operator may
answer their OWN request is decided entirely by
``hitl_response_auth.approval_response_block`` - on a tenant with two or more
active author-tier users this script will simply be refused, exactly as a
browser would be. The only thing it removes is typing.

THE SOLE-AUTHOR EXEMPTION IS REPORTED, NEVER ASSUMED. When the approval was
admitted only because the tenant has exactly one active author, the kernel says
so and this prints it. That is a fact worth seeing every time: it means nobody
independent looked, which is lawful on a single-author tenant and is precisely
what stops being lawful the moment a second author appears
([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001, D2/D3/D4).

REFUSAL IS AN OUTCOME, NOT AN ERROR TO PAPER OVER. A 403 from the respond leg
means the caller is not a lawful approver. It is reported as such and the verb
is left parked for whoever is - never retried, never re-raised under another
identity.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:8000"


def _call(base: str, pat: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {pat}"}
    if data is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except ValueError:
            return e.code, {"detail": raw.decode(errors="replace")[:400]}


def _coerce(value: str):
    """`--param k=v` values are strings; accept JSON so objects and ints work."""
    try:
        return json.loads(value)
    except ValueError:
        return value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("verb", help="e.g. control.adapter.activate")
    ap.add_argument("--param", action="append", default=[], metavar="K=V",
                    help="repeatable; the value is parsed as JSON when it parses")
    ap.add_argument("--base", default=os.environ.get("BOLTRIG_BASE", DEFAULT_BASE))
    ap.add_argument("--notes", default="driven headlessly by scripts/govern.py")
    ap.add_argument("--dry-run", action="store_true",
                    help="raise the approval and STOP - do not answer it, do not execute")
    args = ap.parse_args()

    pat = os.environ.get("BOLTRIG_PAT", "").strip()
    if not pat:
        print("govern: set BOLTRIG_PAT (boltrig mint-token --scope <the verb>)", file=sys.stderr)
        return 2
    if not pat.startswith("boltrig_pat_"):
        # The trap that cost a whole diagnosis on 2026-07-29: a captured stderr
        # LABEL was passed as the bearer, failed this prefix test inside the
        # kernel, fell through to the session resolver, and returned "no session"
        # - which reads as "PATs do not work here" rather than "that is not a PAT".
        print("govern: BOLTRIG_PAT is not a PAT (expected the boltrig_pat_ prefix). "
              "Capture stdout only - the mint command prints its label on stderr.",
              file=sys.stderr)
        return 2

    params = {}
    for item in args.param:
        key, sep, value = item.partition("=")
        if not sep:
            print(f"govern: --param must be K=V, got {item!r}", file=sys.stderr)
            return 2
        params[key] = _coerce(value)

    noun = args.verb.split(".", 1)[0]
    body = {"noun": noun, "verb": args.verb, "params": params}

    status, out = _call(args.base, pat, "/v1/invoke", body)
    if status != 202 or out.get("status") != "pending_human":
        print(json.dumps({"stage": "invoke", "http": status, "result": out}, indent=2))
        return 0 if status < 400 else 1

    request_id = out["hitl_request_id"]
    print(f"govern: {args.verb} is held for approval ({request_id})", file=sys.stderr)
    if args.dry_run:
        print(json.dumps({"stage": "held", "hitl_request_id": request_id}, indent=2))
        return 0

    status, answer = _call(
        args.base, pat, f"/v1/hitl/{request_id}/respond",
        {"decision": "approve", "notes": args.notes},
    )
    if status == 403:
        print(json.dumps({
            "stage": "respond", "http": 403, "result": answer,
            "meaning": "this caller is not a lawful approver of their own request; "
                       "the verb stays parked for someone who is",
        }, indent=2))
        return 1
    if status != 200:
        print(json.dumps({"stage": "respond", "http": status, "result": answer}, indent=2))
        return 1
    if answer.get("sole_author_exemption"):
        print("govern: approved under the SOLE-AUTHOR EXEMPTION - nobody independent "
              "reviewed this. It lapses the moment a second author-tier user exists.",
              file=sys.stderr)
    if answer.get("ends_sole_author_exemption"):
        print("govern: and THIS approval ends that exemption. Every later high-consequence "
              "verb will need a second human ([2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001 D4).",
              file=sys.stderr)

    body["approval_id"] = request_id
    status, out = _call(args.base, pat, "/v1/invoke", body)
    print(json.dumps({"stage": "execute", "http": status, "result": out}, indent=2))
    return 0 if status < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
