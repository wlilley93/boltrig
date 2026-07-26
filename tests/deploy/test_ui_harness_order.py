"""The UI browser-test harness, as [2026] VJS-COUNTY 2 ordered it.

This order is unusual in that four of its five directives are about the HARNESS
rather than about the product: an exactly-pinned Playwright, a hermetic
Chromium-only config, a gating CI job, and a clean runtime image. Only D3 - the
smoke spec itself - lives in the UI suite, and it is bound there.

The other four were enforceable by nothing, which is a particular kind of exposed:
a browser-test harness that quietly loosens is one that keeps reporting green
while proving less. A caret on the Playwright pin makes a "frozen lockfile" build
resolve a different browser; a second project in the config doubles the surface
the smoke claims to cover; a CI job that stops being required still shows up in the
run list; and a runtime image that gains the build stage's node_modules ships a
toolchain to every tenant.

Checked against the files themselves rather than against a description of them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.security

_REPO = Path(__file__).resolve().parents[2]
_UI = _REPO / "ui"


def test_playwright_is_an_exactly_pinned_dev_dependency() -> None:
    """[2026] VJS-COUNTY 2 D1.

    "Exact pinned devDependency and regenerate the lockfile so a frozen-lockfile
    build still resolves." A range would let the browser driver move underneath a
    build that is meant to be reproducible, and `--frozen-lockfile` would not
    complain - it pins what the lockfile says, and the lockfile follows the range.
    """
    manifest = json.loads((_UI / "package.json").read_text(encoding="utf-8"))
    version = (manifest.get("devDependencies") or {}).get("@playwright/test")
    assert version, "@playwright/test is not a devDependency of ui/package.json"
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
        f"@playwright/test is '{version}', not an exact pin - COUNTY 2 D1 required "
        "an exact version so a frozen-lockfile build resolves the same browser"
    )
    lock = (_UI / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert f"@playwright/test@{version}" in lock or f"'{version}'" in lock, (
        f"the lockfile does not resolve @playwright/test@{version}; it was pinned "
        "but not regenerated, so --frozen-lockfile will fail or resolve something else"
    )


def test_the_playwright_config_is_chromium_only_and_hermetic() -> None:
    """[2026] VJS-COUNTY 2 D2.

    "Chromium-only config with a webServer serving the built UI, no credentials,
    no external egress." The egress half is checked the only way a static read
    can: every URL the config waits on is loopback. A config that pointed at a
    deployed environment would still pass a smoke and prove nothing about the
    build under test.
    """
    config = (_UI / "playwright.config.ts").read_text(encoding="utf-8")

    projects = re.search(r"projects:\s*\[(.*?)\]", config, re.DOTALL)
    assert projects, "the config declares no projects block"
    for browser in ("firefox", "webkit"):
        assert browser not in projects.group(1), (
            f"the config declares a {browser} project; COUNTY 2 D2 ordered Chromium only"
        )
    assert "chromium" in projects.group(1)

    assert "webServer:" in config, "no webServer: the smoke would run against nothing"
    urls = re.findall(r"url:\s*[`'\"]([^`'\"]+)", config)
    assert urls, "the webServer declares no url to wait on"
    for url in urls:
        assert "127.0.0.1" in url or "localhost" in url, (
            f"the harness waits on {url}, which is not loopback - COUNTY 2 D2 required "
            "no external egress, and a smoke pointed off-box proves nothing about the "
            "build under test"
        )


def test_the_e2e_smoke_is_a_gating_ci_job() -> None:
    """[2026] VJS-COUNTY 2 D4.

    "A gating CI job running the smoke as a required status check." The job
    existing is not the point - a job that runs and is ignored is exactly the
    shape of a green that means nothing. What makes it gating is that the
    aggregate gate job REQUIRES its result, which is what this reads.
    """
    workflow = (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^  ui-e2e:", workflow, re.MULTILINE), (
        "there is no ui-e2e job in ci.yml"
    )
    assert re.search(r"needs\.ui-e2e\.result.*=.*success", workflow), (
        "the ui-e2e job runs but no gate asserts its result, so it cannot fail the "
        "build - COUNTY 2 D4 required it to be a REQUIRED check, not merely present"
    )


def test_the_ui_runtime_image_is_nginx_and_dist_only() -> None:
    """[2026] VJS-COUNTY 2 D5.

    "Prove runtime image hygiene - nginx plus dist only - and keep ignore-scripts
    in the Docker build stage." Two separate claims: the tenant-facing image
    carries no toolchain, and the build never runs an arbitrary package's install
    script.
    """
    dockerfile = (_UI / "Dockerfile").read_text(encoding="utf-8")
    assert "--ignore-scripts" in dockerfile, (
        "the build stage no longer passes --ignore-scripts, so any dependency's "
        "install script runs with the build's privileges"
    )

    stages = re.split(r"^FROM ", dockerfile, flags=re.MULTILINE)[1:]
    runtime = [s for s in stages if "AS runtime" in s.splitlines()[0]]
    assert runtime, "the Dockerfile declares no runtime stage"
    body = runtime[0]
    assert body.lstrip().startswith("nginx:"), (
        f"the runtime stage is not nginx: {body.splitlines()[0]}"
    )
    copied = re.findall(r"^COPY --from=\S+\s+(\S+)", body, re.MULTILINE)
    assert copied, "the runtime stage copies nothing from the build stage"
    for source in copied:
        assert source.rstrip("/").endswith("dist"), (
            f"the runtime image copies {source} out of the build stage; COUNTY 2 D5 "
            "required dist ONLY, so a tenant-facing image never carries the toolchain"
        )
