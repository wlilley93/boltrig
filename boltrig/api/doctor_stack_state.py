"""Doctor checks for stack-owned local tool state roots."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from boltrig.config.environment import is_truthy
from boltrig.config.manifest import FleetManifest


@dataclass(frozen=True)
class StackStateCheck:
    name: str
    status: str
    message: str
    hint: str = ""


def stack_state_checks(
    env: Mapping[str, str], *, production: bool, manifest: FleetManifest
) -> tuple[StackStateCheck, ...]:
    checks: list[StackStateCheck] = []
    browser_needed = needs_browser_cli(manifest)
    browser_home = (env.get("BOLTRIG_BROWSER_CLI_HOME") or "").strip()

    if browser_needed:
        checks.append(
            _home_check("BOLTRIG_BROWSER_CLI_HOME", browser_home, "browser-cli", production)
        )
        checks.append(
            _bin_check(
                "BOLTRIG_BROWSER_CLI_BIN",
                env.get("BOLTRIG_BROWSER_CLI_BIN"),
                "browser-cli",
                production,
                env,
                default_command="browser-use",
            )
        )
    return tuple(checks)


def needs_browser_cli(manifest: FleetManifest) -> bool:
    """Whether this tenant declares browser automation at all.

    Public because it is no longer only a doctor question. The fleet entrypoint
    starts Chromium on this answer and the readiness gate requires the tool on
    it (``boltrig.fleet.browser_runtime``), so a second copy of the three limbs
    below would let the process that RUNS the browser and the gate that DEMANDS
    it drift apart.
    """
    stack = manifest.section("stack")
    if str(stack.get("browser_automation") or "").lower() == "browser_cli":
        return True
    browser = manifest.section("browser_cli")
    if is_truthy(str(browser.get("enabled") or "")):
        return True
    return any(adapter.id == "browser-cli" for adapter in manifest.adapters)


def _home_check(
    env_key: str, raw: str, tool: str, production: bool
) -> StackStateCheck:
    name = f"{_slug(tool)}_stack_home"
    default = f"/var/lib/boltrig/{tool}"
    if not raw:
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{env_key} is unset; compose defaults to {default}.",
            f"Set {env_key}={default} for non-compose production deployments.",
        )
    if _references_user_home(raw) or _is_personal_tool_state(raw, tool):
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{env_key} points at a user-owned {tool} state path.",
            f"Use a clean stack-owned root such as {default}; do not mount ~/.config, "
            "~/.local, or project-local agent state.",
        )
    expanded = Path(raw).expanduser()
    if not expanded.is_absolute():
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{env_key} is relative; production stack state must be absolute.",
            f"Use {default} or another service-owned absolute path.",
        )
    return StackStateCheck(name, "ok", f"{env_key} is stack-owned-looking.")


def _bin_check(
    env_key: str,
    raw: str | None,
    tool: str,
    production: bool,
    env: Mapping[str, str],
    *,
    default_command: str | None = None,
) -> StackStateCheck:
    name = f"{_slug(tool)}_stack_cli"
    command = (raw or default_command or tool).strip()
    default_bin = default_command or tool
    label = f"{env_key}={command}" if raw else f"default command '{default_bin}'"
    if not command:
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{env_key} is empty.",
            f"Set {env_key} to the shipped /usr/local/bin/{default_bin} or leave it unset.",
        )
    if _references_user_home(command) or _is_personal_tool_state(command, tool):
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{env_key} points at a user-owned {tool} binary path.",
            f"Use the stack-shipped /usr/local/bin/{default_bin}; do not use a workstation install.",
        )
    resolved = _resolve_command(command, env)
    if resolved is None:
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{label} does not resolve to an executable.",
            f"Ensure the deployed image ships /usr/local/bin/{default_bin}, or set {env_key}.",
        )
    if _references_user_home(resolved) or _is_personal_tool_state(resolved, tool):
        return StackStateCheck(
            name,
            "fail" if production else "warn",
            f"{label} resolves to a user-owned {tool} binary path.",
            f"Use the stack-shipped /usr/local/bin/{default_bin}; do not rely on a host profile.",
        )
    return StackStateCheck(name, "ok", f"{tool} CLI resolves to stack-owned-looking path.")


def _resolve_command(command: str, env: Mapping[str, str]) -> str | None:
    if "/" not in command and "\\" not in command:
        return shutil.which(command, path=env.get("PATH"))
    path = Path(command).expanduser()
    if not path.is_absolute():
        return None
    return str(path) if path.is_file() and _is_executable(path) else None


def _is_executable(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_mode & 0o111 != 0
    except OSError:
        return False


def _references_user_home(raw: str) -> bool:
    lowered = raw.strip().lower()
    return (
        lowered.startswith("~/")
        or lowered == "~"
        or "$home" in lowered
        or "${home}" in lowered
        or "%userprofile%" in lowered
    )


def _is_personal_tool_state(raw: str, tool: str) -> bool:
    lowered = raw.replace("\\", "/").strip().lower()
    aliases = _tool_aliases(tool)
    personal_fragments = tuple(
        fragment
        for alias in aliases
        for fragment in (
            f"/.config/{alias}",
            f"/.local/share/{alias}",
            f"/.local/state/{alias}",
            f"/library/application support/{alias}",
        )
    )
    if any(fragment in lowered for fragment in personal_fragments):
        return True
    names = "|".join(re.escape(alias) for alias in aliases)
    return bool(
        re.match(
            rf"^/(home|users)/[^/]+/(\.config|\.local|{names})",
            lowered,
        )
        or re.match(rf"^/root/(\.config|\.local|{names})", lowered)
    )


def _slug(value: str) -> str:
    return value.replace("-", "_")


def _tool_aliases(tool: str) -> tuple[str, ...]:
    if tool == "browser-cli":
        return ("browser-cli", "browser-use")
    return (tool,)
