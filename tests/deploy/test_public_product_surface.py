"""The published template must be portable and companion-closed."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from scripts.validate_public_product import ROOT, validate


_INPUTS = (
    ".env.example",
    "manifest.example.yaml",
    "apps/worker/Dockerfile",
    "apps/worker/package.json",
    "apps/worker/pnpm-lock.yaml",
    "apps/worker/src/characterPlugins.ts",
    "apps/worker/src/components/characters.ts",
    "apps/worker/src/main.tsx",
)


def _public_fixture(root: Path) -> None:
    for relative in _INPUTS:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)


@pytest.mark.security
def test_public_product_template_is_byo_and_familiar_jarvis_only() -> None:
    """Keep personal deployment values and third-party companion chunks out."""
    validate()


@pytest.mark.security
@pytest.mark.parametrize(
    "private_value",
    (
        "100.108.41.109",
        "mac-mini-m1",
        "qwen3vl-abliterated",
    ),
)
def test_public_product_rejects_private_dev_inference_routes(
    tmp_path: Path, private_value: str
) -> None:
    _public_fixture(tmp_path)
    manifest = tmp_path / "manifest.example.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + f"\n# private route: {private_value}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        validate(tmp_path)


@pytest.mark.security
@pytest.mark.parametrize(
    ("relative", "needle"),
    (
        (
            "apps/worker/src/characterPlugins.ts",
            '\nimport "@example/private-character";\n',
        ),
        (
            "apps/worker/src/characterPlugins.ts",
            '\nexport * from "@example/private-character";\n',
        ),
        (
            "apps/worker/package.json",
            '\n"private-character": "file:../../../private/character"\n',
        ),
        (
            "apps/worker/pnpm-lock.yaml",
            "\n  private-character: file:../../../private/character\n",
        ),
    ),
)
def test_public_product_rejects_external_character_build_inputs(
    tmp_path: Path, relative: str, needle: str
) -> None:
    _public_fixture(tmp_path)
    target = tmp_path / relative
    if relative.endswith("package.json"):
        source = target.read_text(encoding="utf-8")
        source = source.replace('"dependencies": {', f'"dependencies": {{{needle},', 1)
        target.write_text(source, encoding="utf-8")
    else:
        target.write_text(target.read_text(encoding="utf-8") + needle, encoding="utf-8")

    with pytest.raises(ValueError):
        validate(tmp_path)
