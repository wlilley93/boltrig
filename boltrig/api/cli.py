"""The ``boltrig`` command line. Thin front door over the entrypoints.

    boltrig serve [--host H --port P]   start the kernel API
    boltrig worker                      start a fleet worker
    boltrig chat [--server URL]         chat with agents from the terminal
        [--via-gateway ...]             (head = the control API; gateway = a messaging surface)
    boltrig initiate --email E [...]    seat the founding OWNER (invite-only, VJS-COUNTY 7)
    boltrig set-password --email E      set/reset an EXISTING user's password (SSO -> session)
    boltrig smoke                       run the offline in-process smoke test
    boltrig check-invariants            run the invariant-binding gate (K-29/K-30)
    boltrig doctor                      static production-readiness checks
    boltrig version                     print the version
"""

from __future__ import annotations

import argparse
import os
import runpy
import sys

from boltrig import __version__


def _repo_script(name: str) -> str | None:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(here, "scripts", name)
    return path if os.path.exists(path) else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boltrig")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="start the kernel API")
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default: 127.0.0.1; pass 0.0.0.0 explicitly for containers)",
    )
    p_serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("worker", help="start a fleet worker")
    sub.add_parser(
        "fleet-health",
        help="readiness probe for a fleet worker (reads its signed tool receipt)",
    )

    _add_identity_parsers(sub)

    sub.add_parser("smoke", help="offline in-process smoke test")
    sub.add_parser("check-invariants", help="run the invariant-binding gate")

    _add_chat_parser(sub)

    p_opencode = sub.add_parser(
        "opencode-plugin", help="install OpenCode project-local integration files"
    )
    opencode_sub = p_opencode.add_subparsers(dest="opencode_cmd", required=True)
    p_oc_install = opencode_sub.add_parser(
        "install", help="write the Boltrig MCP plugin into an OpenCode config dir"
    )
    p_oc_install.add_argument("--dir", default=".opencode", help="OpenCode config directory")

    p_doctor = sub.add_parser("doctor", help="static production-readiness checks")
    p_doctor.add_argument(
        "--env-file",
        default=None,
        help="dotenv file to merge over the process environment (for example .env)",
    )
    p_doctor.add_argument(
        "--manifest",
        default="manifest.yaml",
        help="fleet manifest to inspect (default: manifest.yaml)",
    )
    p_doctor.add_argument(
        "--production",
        action="store_true",
        help="treat warnings that are deploy blockers as production failures",
    )
    p_doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    sub.add_parser("version", help="print version")

    return parser


def _add_identity_parsers(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """The tenant-scoped identity/admin commands (initiate, set-password, mint-token).

    Grouped out of ``_build_parser`` so the router stays small; each is a
    box-level operation (needs shell on the host) capped at the user's grants."""
    p_init = sub.add_parser("initiate", help="seat the founding OWNER (invite-only)")
    p_init.add_argument("--email", required=True, help="the owner's email (their login id)")
    p_init.add_argument(
        "--password", default=None,
        help="owner password (else BOLTRIG_INIT_PASSWORD, else an interactive prompt)",
    )
    p_init.add_argument(
        "--tenant", default=None,
        help="tenant to seat the owner in (default: BOLTRIG_SESSION_TENANT or 'default')",
    )
    p_init.add_argument(
        "--org-name", default=None,
        help="the founding organisation's display name (default: 'Boltrig')",
    )
    p_init.add_argument(
        "--workspace-name", default=None,
        help="the founding workspace's display name (default: the org name)",
    )

    p_setpw = sub.add_parser(
        "set-password",
        help="set/reset an EXISTING user's first-party password (SSO -> session bridge)",
    )
    p_setpw.add_argument("--email", required=True, help="the existing user's email")
    p_setpw.add_argument(
        "--password", default=None,
        help="new password (else BOLTRIG_INIT_PASSWORD, else an interactive prompt)",
    )
    p_setpw.add_argument("--tenant", default=None, help="tenant (default: session tenant)")

    p_mint = sub.add_parser(
        "mint-token",
        help="mint a Personal Access Token for an EXISTING user (box-level twin of POST /v1/me/tokens)",
    )
    p_mint.add_argument("--email", required=True, help="the existing user's email")
    p_mint.add_argument("--name", required=True, help="a label for the token")
    p_mint.add_argument(
        "--scope", default=None,
        help="comma-separated grant patterns (default: the user's own grants); "
             "narrowed to what the user actually holds",
    )
    p_mint.add_argument(
        "--ttl-days", type=int, default=None,
        help="lifetime in days (clamped to the PAT max; default if unset)",
    )
    p_mint.add_argument("--tenant", default=None, help="tenant (default: session tenant)")


def _add_chat_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p_chat = sub.add_parser(
        "chat",
        help="chat with agents from the terminal (thin client, never a runtime)",
        description=(
            "Chat with agents THROUGH the stack. Default (head) mode: "
            "PAT-authenticated SSE chat against the kernel API - the full "
            "control surface (tool stream, HITL approve/deny/answer inline). "
            "--via-gateway: a messaging surface over the channel gateway's "
            "generic JSON-lines adapter - channel semantics (addressing via "
            "--target or /target, outbound notifications), not the control API."
        ),
    )
    p_chat.add_argument(
        "--server", default=None,
        help="kernel API URL (default: BOLTRIG_CLI_SERVER, else the config file, "
        "else http://127.0.0.1:8000)",
    )
    p_chat.add_argument(
        "--token", default=None,
        help="a personal access token (default: BOLTRIG_CLI_TOKEN, else the "
        "config file; never logged)",
    )
    p_chat.add_argument(
        "--conversation", default=None,
        help="resume an existing conversation id (else a new one per session; "
        "the id is kept across turns)",
    )
    p_chat.add_argument(
        "--config", default=None,
        help="CLI config file (default: ~/.config/boltrig/cli.toml)",
    )
    p_chat.add_argument(
        "--via-gateway", action="store_true",
        help="connect through the channel gateway's generic adapter instead of "
        "the kernel API",
    )
    p_chat.add_argument(
        "--gateway-host", default="127.0.0.1",
        help="gateway listen host (default: 127.0.0.1)",
    )
    p_chat.add_argument(
        "--gateway-port", type=int, default=9090, help="gateway listen port (default: 9090)"
    )
    p_chat.add_argument(
        "--sender-id", default="cli",
        help="the sender id stamped on gateway frames (default: cli)",
    )
    p_chat.add_argument(
        "--target", default=None,
        help="(gateway) address the CoS or a named tier-2 subagent by slug",
    )


def _dispatch_identity(args: argparse.Namespace) -> int | None:
    """The tenant-scoped identity/admin commands, or None if not one of them.

    Grouped so each resolves the tenant the same way (flag, else the session
    tenant, else ``default``) and ``_dispatch`` stays a thin router."""
    if args.cmd not in ("initiate", "set-password", "mint-token"):
        return None
    from boltrig.config import load_settings

    tenant = args.tenant or load_settings().session_tenant or "default"
    if args.cmd == "initiate":
        from .initiate import initiate

        return initiate(
            args.email, password=args.password, tenant=tenant,
            org_name=args.org_name, workspace_name=args.workspace_name,
        )
    if args.cmd == "set-password":
        from .initiate import set_password

        return set_password(args.email, password=args.password, tenant=tenant)
    # mint-token
    from .mint_token import mint_token

    scope = [s for s in (args.scope or "").split(",") if s.strip()] or None
    return mint_token(
        args.email, tenant=tenant, name=args.name, scope=scope, ttl_days=args.ttl_days,
    )


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "version":
        print(__version__)
        return 0
    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("boltrig.api.asgi:app", host=args.host, port=args.port)
        return 0
    if args.cmd == "fleet-health":
        from .fleet_health import main as fleet_health_main

        return fleet_health_main()

    if args.cmd == "worker":
        from .worker import main as worker_main

        worker_main()
        return 0
    identity = _dispatch_identity(args)
    if identity is not None:
        return identity
    if args.cmd in ("smoke", "check-invariants"):
        script = _repo_script("smoke.py" if args.cmd == "smoke" else "check_invariants.py")
        if not script:
            print(f"script for '{args.cmd}' not found", file=sys.stderr)
            return 2
        runpy.run_path(script, run_name="__main__")
        return 0
    if args.cmd == "chat":
        from .chat_cli import run as chat_run

        return chat_run(args)
    if args.cmd == "opencode-plugin":
        from boltrig.fleet.opencode_plugin import install_opencode_plugin

        path = install_opencode_plugin(args.dir)
        print(path)
        return 0
    if args.cmd == "doctor":
        from .doctor import format_report, load_env_file, run_doctor

        env = dict(os.environ)
        if args.env_file:
            env = load_env_file(args.env_file, base=env)
        report = run_doctor(
            env=env,
            manifest_path=args.manifest,
            production=bool(args.production),
        )
        print(report.to_json() if args.json else format_report(report))
        return report.exit_code
    return 1


def main(argv: list[str] | None = None) -> int:
    return _dispatch(_build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
