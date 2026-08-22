"""What this deployment calls itself, and why it is not a build flag."""

from __future__ import annotations

from dataclasses import dataclass

from boltrig.branding import BOLTRIG, OPBOX_AGENTS, product_identity, product_name


@dataclass(frozen=True)
class _Addon:
    name: str


def test_a_boltrig_shipping_alone_is_called_boltrig():
    assert product_name(addons=()) == BOLTRIG


def test_an_opbox_provisioned_boltrig_is_called_opbox_agents():
    assert product_name(addons=(_Addon("opbox"),)) == OPBOX_AGENTS


def test_another_addon_does_not_rename_the_product():
    # The rename keys off the OPBOX addon specifically, not off "any addon is
    # active". A future second addon must not silently rebrand the product.
    assert product_name(addons=(_Addon("billandben"),)) == BOLTRIG


def test_opbox_alongside_another_addon_still_renames():
    assert product_name(addons=(_Addon("billandben"), _Addon("opbox"))) == OPBOX_AGENTS


def test_the_core_pulses_on_either_setup():
    # The Principal's instruction: the dot pulses always, on either setup. It is
    # REPORTED rather than assumed by the client so there is one source for it
    # instead of a second copy of the policy in the bundle.
    assert product_identity(addons=())["pulse"] is True
    assert product_identity(addons=(_Addon("opbox"),))["pulse"] is True


def test_identity_carries_the_name_it_reports():
    assert product_identity(addons=(_Addon("opbox"),))["product_name"] == OPBOX_AGENTS


def test_the_branding_route_answers_without_a_session():
    """The sign-in screen renders before anyone has one.

    A branding route behind auth would leave the login page unable to say what
    the product is called, which is the one surface that most needs to.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from boltrig.kernel.health_routes import register_health_routes

    app = FastAPI()
    register_health_routes(app, get_kernel=lambda: None)

    response = TestClient(app).get("/v1/branding")

    assert response.status_code == 200
    assert response.json() == {"product_name": product_name(), "pulse": True}
