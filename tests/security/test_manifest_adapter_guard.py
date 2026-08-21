"""A stale manifest module_ref must not take down the boot.

Before the guard, ``_register_manifest_adapters`` imported each declared
module with no try/except, so one manifest entry naming a retired module
(the herdr fossil, decision 0020) raised out of ``apply_manifest`` and left
the kernel unbootable - the exact failure class control_rehydrate.py already
documents from the beelink on 2026-07-30. The loader's own ``load_module``
has always caught-and-continued (``loader.py``); this pins the same contract
one level up: the bad entry is skipped loudly, every later entry still
registers.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from boltrig.config.manifest_apply import _register_manifest_adapters


class _RecordingKernel:
    def __init__(self) -> None:
        self.registered: list[str] = []

    async def register_adapter(self, tenant: str, adapter: object) -> None:
        self.registered.append(getattr(adapter, "id", type(adapter).__name__))


def _manifest_with(*adapters: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(adapters=list(adapters))


@pytest.mark.security
async def test_a_stale_module_ref_is_skipped_and_later_adapters_still_register() -> None:
    kernel = _RecordingKernel()
    manifest = _manifest_with(
        # Bad entry FIRST, so the assertion below proves continuation rather
        # than accidental ordering.
        SimpleNamespace(id="fossil", module_ref="boltrig.adapters.builtin.does_not_exist:build"),
        SimpleNamespace(id="familiar", module_ref="boltrig.adapters.builtin.familiar:build"),
    )

    await _register_manifest_adapters(kernel, manifest, "tenant-a")

    assert kernel.registered == ["familiar"]


@pytest.mark.security
async def test_a_broken_factory_is_skipped_not_fatal() -> None:
    kernel = _RecordingKernel()
    manifest = _manifest_with(
        # The module imports but the named factory is absent - the getattr
        # raises instead of the import, proving the guard covers the whole
        # load, not just importlib.
        SimpleNamespace(id="halffossil", module_ref="boltrig.adapters.builtin.familiar:no_such_factory"),
    )

    await _register_manifest_adapters(kernel, manifest, "tenant-a")

    assert kernel.registered == []
