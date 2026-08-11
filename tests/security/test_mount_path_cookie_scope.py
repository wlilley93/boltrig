"""Session cookies are scoped to the console's mount, not to the whole host.

A console mounted at ``<host>/boltrig`` shares an origin with whatever else that
host serves. On a tenant box that is the Opbox app, so a cookie set with
``Path=/`` is attached to every request to that host and the console's session
secret is handed to an application that took no part in issuing it.

These tests pin three things, and the third is the one that has failed before in
this codebase: that the middleware is actually INSTALLED by ``install_security``,
not merely defined. A hook that exists but is not wired is the shape of several
past defects here.

They also pin the REFUSAL: ``X-Forwarded-Prefix`` is a client-settable header, so
it is honoured only under ``BOLTRIG_TRUST_FORWARDED_PREFIX``, exactly as
``client_ip`` refuses ``X-Forwarded-For`` by default. The default-deny case is a
negative control - a middleware that always honoured the header would pass every
positive assertion here and quietly trust a forgeable header in production.
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from boltrig.kernel.web_security import (
    forwarded_prefix,
    install_security,
    scope_set_cookie,
)

MOUNT_HEADER = "X-Forwarded-Prefix"


# --- the pure rewrite --------------------------------------------------------


def test_a_session_cookie_is_rescoped_to_the_mount():
    out = scope_set_cookie(
        "boltrig_session=abc; Path=/; HttpOnly; Secure; SameSite=strict", "/boltrig"
    )
    assert "Path=/boltrig;" in out
    assert "Path=/;" not in out
    # The protections that make the cookie safe must survive the rewrite.
    assert "HttpOnly" in out and "Secure" in out and "SameSite=strict" in out


def test_the_readable_csrf_cookie_is_rescoped_too():
    # If only the session cookie moved, the SPA would stop being able to read the
    # CSRF mirror at the mount and every mutating request would fail.
    out = scope_set_cookie("boltrig_csrf=t; Path=/; Secure", "/boltrig")
    assert "Path=/boltrig" in out


def test_a_cookie_with_no_path_is_given_one():
    # A cookie set without Path defaults to the request's directory, which is not
    # the mount. State it rather than inherit it.
    assert "Path=/boltrig" in scope_set_cookie("boltrig_session=abc; HttpOnly", "/boltrig")


def test_an_unrelated_cookie_is_left_exactly_alone():
    value = "some_other_cookie=abc; Path=/; HttpOnly"
    assert scope_set_cookie(value, "/boltrig") == value


# --- the refusal (negative controls) -----------------------------------------


class _Req:
    def __init__(self, value: str | None):
        self.headers = {} if value is None else {"x-forwarded-prefix": value}


def test_the_header_is_ignored_without_the_deployment_opt_in():
    # THE negative control. Without this, a middleware that always honoured the
    # header satisfies every other test in this file.
    assert forwarded_prefix(_Req("/boltrig"), env={}) == ""


def test_the_header_is_honoured_when_the_edge_is_trusted():
    env = {"BOLTRIG_TRUST_FORWARDED_PREFIX": "1"}
    assert forwarded_prefix(_Req("/boltrig"), env=env) == "/boltrig"
    assert forwarded_prefix(_Req("/boltrig/"), env=env) == "/boltrig"


@pytest.mark.parametrize("value", ["/boltrig/legacy", "/apps/boltrig", "/a/b/c/d"])
def test_a_NESTED_mount_is_honoured(value):
    """This assertion used to be its opposite, and the opposite failed OPEN.

    A single-segment pattern rejects `/boltrig/legacy`, and rejecting means
    falling back to `Path=/` - the whole-host scope this middleware exists to
    close. So the conservative-looking choice quietly reinstated the widening.
    The Worker is the root presentation, so a legacy nested mount is still a
    real shape this middleware must handle.

    The rule this encodes: when the fallback for "unrecognised" is the PERMISSIVE
    branch, narrowing what you recognise makes the control weaker, not stronger.
    """
    env = {"BOLTRIG_TRUST_FORWARDED_PREFIX": "1"}
    assert forwarded_prefix(_Req(value), env=env) == value


@pytest.mark.parametrize(
    "value",
    [
        "boltrig",             # no leading slash
        "/../etc",             # traversal
        "/boltrig; Path=/",    # header injection into the cookie attributes
        "//x",                 # empty segment
        "/a/b/c/d/e",          # deeper than any real mount
        "/" + "x" * 200,       # unbounded
        "",
    ],
)
def test_a_prefix_we_do_not_recognise_is_not_honoured(value):
    # Ignored, never sanitised: a shape we do not recognise is one we do not act on.
    env = {"BOLTRIG_TRUST_FORWARDED_PREFIX": "1"}
    assert forwarded_prefix(_Req(value), env=env) == ""


# --- installed, not merely defined -------------------------------------------


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/v1/login")
    def login() -> JSONResponse:
        resp = JSONResponse({"status": "ok"})
        resp.set_cookie("boltrig_session", "s", path="/", httponly=True)
        resp.set_cookie("boltrig_csrf", "c", path="/")
        return resp

    install_security(app, env={"BOLTRIG_ALLOWED_HOSTS": "*"})
    return app


def test_install_security_wires_the_middleware(monkeypatch):
    monkeypatch.setenv("BOLTRIG_TRUST_FORWARDED_PREFIX", "1")
    res = TestClient(_app()).get("/v1/login", headers={MOUNT_HEADER: "/boltrig"})
    cookies = res.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert all("Path=/boltrig" in c for c in cookies), cookies


def test_the_standalone_console_at_the_root_is_unchanged(monkeypatch):
    # app.boltrig.io serves at "/" and sends no prefix. Nothing may move.
    monkeypatch.setenv("BOLTRIG_TRUST_FORWARDED_PREFIX", "1")
    res = TestClient(_app()).get("/v1/login")
    cookies = res.headers.get_list("set-cookie")
    assert all("Path=/;" in c or c.rstrip().endswith("Path=/") for c in cookies), cookies


def test_an_untrusted_edge_cannot_move_the_cookie(monkeypatch):
    monkeypatch.delenv("BOLTRIG_TRUST_FORWARDED_PREFIX", raising=False)
    res = TestClient(_app()).get("/v1/login", headers={MOUNT_HEADER: "/boltrig"})
    cookies = res.headers.get_list("set-cookie")
    assert all("Path=/boltrig" not in c for c in cookies), cookies
