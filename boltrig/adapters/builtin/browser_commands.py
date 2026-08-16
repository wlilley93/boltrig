"""Fixed Browser Use scripts and their bounded parameter projection."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from boltrig.adapters.builtin.browser_contract import (
    DEFAULT_HOME,
    MAX_AX_NODES,
    MAX_COORDINATE,
    MAX_FRAME_DIMENSION,
    MAX_TEXT_BYTES,
)
from boltrig.adapters.builtin.browser_frames import bounded_int
from boltrig.adapters.builtin.script_base import base_env
from boltrig.adapters.egress import EgressBlocked, assert_egress_allowed

_PRIVATE_HOSTS = {"localhost", "localhost.localdomain"}
_CLOUD_POLICY_STACK = {"stack", "stack-owned", "stack_owned"}
_CLOUD_POLICY_DISABLED = {"", "0", "false", "no", "off", "disabled", "none"}
_STACK_CLOUD_ENV = {
    "BOLTRIG_BROWSER_CLOUD_API_KEY": ("BROWSER_USE_API_KEY", "BROWSER_USE_CLOUD_API_KEY"),
    "BOLTRIG_BROWSER_CLOUD_PROFILE_ID": ("BROWSER_USE_PROFILE_ID",),
    "BOLTRIG_BROWSER_CLOUD_PROJECT_ID": ("BROWSER_USE_PROJECT_ID",),
    "BOLTRIG_BROWSER_CLOUD_TEAM_ID": ("BROWSER_USE_TEAM_ID",),
}


def build_command(
    bin_path: str,
    verb: str,
    params: dict[str, Any],
    *,
    allowed_domains: tuple[str, ...],
    frame_path: str | None = None,
    expected_digest: str | None = None,
) -> tuple[list[str], str | None, dict[str, str]]:
    basic = _basic_command(bin_path, verb, params, allowed_domains)
    if basic is not None:
        return basic
    visual = _visual_command(
        bin_path,
        verb,
        params,
        allowed_domains=allowed_domains,
        frame_path=frame_path,
        expected_digest=expected_digest,
    )
    if visual is not None:
        return visual
    raise ValueError(f"unknown verb {verb}")


def _basic_command(
    bin_path: str,
    verb: str,
    params: dict[str, Any],
    allowed_domains: tuple[str, ...],
) -> tuple[list[str], str | None, dict[str, str]] | None:
    if verb == "browser.doctor":
        return [bin_path, "--doctor"], None, {}
    if verb == "browser.auth.status":
        return [bin_path, "auth", "status"], None, {}
    if verb == "browser.page.info":
        return [bin_path], _page_info_script(), name_env(params)
    if verb == "browser.tab.open":
        url = validate_url(str(params.get("url") or ""), allowed_domains)
        return [bin_path], _open_script(url), name_env(params)
    if verb == "browser.tabs.list":
        return [bin_path], _tabs_script(), name_env(params)
    if verb == "browser.inspect":
        limit = bounded_int(params.get("limit", 40), minimum=1, maximum=MAX_AX_NODES, name="limit")
        return [bin_path], _inspect_script(limit), name_env(params)
    if verb == "browser.remote.start":
        return (
            [bin_path],
            f"start_remote_daemon({json.dumps(clean_name(params.get('name')))})\n",
            {},
        )
    if verb == "browser.remote.stop":
        return [bin_path], f"stop_remote_daemon({json.dumps(clean_name(params.get('name')))})\n", {}
    return None


def _visual_command(
    bin_path: str,
    verb: str,
    params: dict[str, Any],
    *,
    allowed_domains: tuple[str, ...],
    frame_path: str | None,
    expected_digest: str | None,
) -> tuple[list[str], str | None, dict[str, str]] | None:
    path = required_path(frame_path)
    if verb == "browser.navigate":
        url = validate_url(str(params.get("url") or ""), allowed_domains)
        return [bin_path], _navigate_script(url, path), name_env(params)
    if verb in {"browser.tab.select", "browser.tab.close"}:
        target_id = clean_target_id(params.get("target_id"))
        script = _select_tab_script if verb == "browser.tab.select" else _close_tab_script
        return [bin_path], script(target_id, path), name_env(params)
    if verb == "browser.snapshot":
        return [bin_path], _snapshot_script(path), name_env(params)
    if verb in {"browser.click", "browser.type", "browser.scroll", "browser.key.press"}:
        if not expected_digest:
            raise ValueError("expected browser frame is required")
        action, cursor = browser_action(verb, params)
        return (
            [bin_path],
            _guarded_action_script(path, expected_digest, action=action, cursor=cursor),
            name_env(params),
        )
    return None


def process_env(extra_env: dict[str, str]) -> dict[str, str]:
    root = Path(os.environ.get("BOLTRIG_BROWSER_CLI_HOME") or DEFAULT_HOME)
    env = base_env() | {
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CACHE_HOME": str(root / "cache"),
    }
    env.update(_stack_cloud_env(os.environ))
    env.update(extra_env)
    return env


def _stack_cloud_env(source: Mapping[str, str]) -> dict[str, str]:
    policy = (source.get("BOLTRIG_BROWSER_CLOUD_POLICY") or "disabled").strip().lower()
    if policy in _CLOUD_POLICY_DISABLED or policy not in _CLOUD_POLICY_STACK:
        return {}
    out = {"BROWSER_USE_CLOUD": "true"}
    for source_key, child_keys in _STACK_CLOUD_ENV.items():
        value = (source.get(source_key) or "").strip()
        if value:
            out.update({child_key: value for child_key in child_keys})
    return out


def _page_info_script() -> str:
    return "import json\nprint(json.dumps(page_info(), default=str))\n"


def _open_script(url: str) -> str:
    return f"import json\nnew_tab({json.dumps(url)})\nprint(json.dumps(page_info(), default=str))\n"


def _frame_script_prelude() -> str:
    return (
        "import hashlib\n"
        "import json\n"
        "import os\n"
        "from PIL import Image\n"
        "def _boltrig_save_frame(path):\n"
        "    info = page_info()\n"
        "    raw = path + '.png'\n"
        f"    capture_screenshot(raw, full=False, max_dim={MAX_FRAME_DIMENSION})\n"
        "    with Image.open(raw) as source:\n"
        "        image = source.convert('RGB')\n"
        "        image.save(path, format='JPEG', quality=72, optimize=True)\n"
        "    os.unlink(raw)\n"
        "    with open(path, 'rb') as handle:\n"
        "        digest = hashlib.sha256(handle.read()).hexdigest()\n"
        "    return info, digest\n"
    )


def _snapshot_script(frame_path: str) -> str:
    return (
        _frame_script_prelude()
        + f"page, _digest = _boltrig_save_frame({json.dumps(frame_path)})\n"
        + "print(json.dumps({'status':'ok','page':page}, default=str))\n"
    )


def _navigate_script(url: str, frame_path: str) -> str:
    return (
        _frame_script_prelude()
        + f"goto_url({json.dumps(url)})\n"
        + "wait_for_load(timeout=10.0)\n"
        + f"page, _digest = _boltrig_save_frame({json.dumps(frame_path)})\n"
        + "print(json.dumps({'status':'ok','page':page}, default=str))\n"
    )


def _select_tab_script(target_id: str, frame_path: str) -> str:
    return (
        _frame_script_prelude()
        + f"switch_tab({json.dumps(target_id)})\n"
        + f"page, _digest = _boltrig_save_frame({json.dumps(frame_path)})\n"
        + "print(json.dumps({'status':'ok','page':page}, default=str))\n"
    )


def _close_tab_script(target_id: str, frame_path: str) -> str:
    return (
        _frame_script_prelude()
        + f"close_tab({json.dumps(target_id)})\n"
        + "ensure_real_tab()\n"
        + f"page, _digest = _boltrig_save_frame({json.dumps(frame_path)})\n"
        + "print(json.dumps({'status':'ok','page':page}, default=str))\n"
    )


def _tabs_script() -> str:
    return "import json\nprint(json.dumps(list_tabs(include_chrome=False), default=str))\n"


def _inspect_script(limit: int) -> str:
    return (
        "import json\n"
        "raw = cdp('Accessibility.getFullAXTree').get('nodes', [])\n"
        "allowed = {'button','checkbox','combobox','link','menuitem','radio','searchbox','slider','spinbutton','switch','tab','textbox'}\n"
        "nodes = []\n"
        "for item in raw:\n"
        "    role = str((item.get('role') or {}).get('value') or '').lower()\n"
        "    node_id = item.get('backendDOMNodeId')\n"
        "    if role not in allowed or not isinstance(node_id, int) or node_id < 1:\n"
        "        continue\n"
        "    name = str((item.get('name') or {}).get('value') or '')[:240]\n"
        "    nodes.append({'node_id':node_id,'role':role,'name':name})\n"
        f"    if len(nodes) >= {limit}: break\n"
        "print(json.dumps({'nodes':nodes}, default=str))\n"
    )


def _guarded_action_script(
    frame_path: str,
    expected_digest: str,
    *,
    action: str,
    cursor: dict[str, Any] | None,
) -> str:
    cursor_literal = json.dumps(cursor, separators=(",", ":")) if cursor is not None else "None"
    return (
        _frame_script_prelude()
        + f"page, actual = _boltrig_save_frame({json.dumps(frame_path)})\n"
        + f"if actual != {json.dumps(expected_digest)}:\n"
        + "    result = {'status':'stale_frame','page':page}\n"
        + "else:\n"
        + f"    {action}\n"
        + "    wait(0.15)\n"
        + f"    page, _digest = _boltrig_save_frame({json.dumps(frame_path)})\n"
        + f"    result = {{'status':'ok','page':page,'cursor':{cursor_literal}}}\n"
        + "print(json.dumps(result, default=str))\n"
    )


def browser_action(verb: str, params: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if verb == "browser.click":
        x = bounded_int(params.get("x"), minimum=0, maximum=MAX_COORDINATE, name="x")
        y = bounded_int(params.get("y"), minimum=0, maximum=MAX_COORDINATE, name="y")
        button = str(params.get("button") or "left")
        if button not in {"left", "right", "middle"}:
            raise ValueError("button is not allowed")
        return f"click_at_xy({x}, {y}, button={json.dumps(button)})", {
            "x": x,
            "y": y,
            "kind": "click",
        }
    if verb == "browser.type":
        value = str(params.get("text") or "")
        if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("text is too large")
        return f"type_text({json.dumps(value)})", None
    return _scroll_or_key_action(verb, params)


def _scroll_or_key_action(verb: str, params: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    if verb == "browser.scroll":
        x = bounded_int(params.get("x"), minimum=0, maximum=MAX_COORDINATE, name="x")
        y = bounded_int(params.get("y"), minimum=0, maximum=MAX_COORDINATE, name="y")
        dx = bounded_int(params.get("delta_x"), minimum=-10_000, maximum=10_000, name="delta_x")
        dy = bounded_int(params.get("delta_y"), minimum=-10_000, maximum=10_000, name="delta_y")
        return f"scroll({x}, {y}, dy={dy}, dx={dx})", {"x": x, "y": y, "kind": "scroll"}
    if verb == "browser.key.press":
        key = str(params.get("key") or "")
        allowed = {
            "Enter",
            "Tab",
            "Escape",
            "Backspace",
            "Delete",
            "ArrowLeft",
            "ArrowRight",
            "ArrowUp",
            "ArrowDown",
            "Home",
            "End",
            "PageUp",
            "PageDown",
        }
        if key not in allowed:
            raise ValueError("key is not allowed")
        return f"press_key({json.dumps(key)})", None
    raise ValueError(f"unsupported browser action {verb}")


def required_path(value: str | None) -> str:
    if not value:
        raise ValueError("browser frame path is unavailable")
    return value


def clean_target_id(value: Any) -> str:
    target_id = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", target_id):
        raise ValueError("invalid browser tab id")
    return target_id


def clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        raise ValueError("name must be 1-64 URL-safe characters")
    return name


def session_name(params: dict[str, Any]) -> str:
    return clean_name(params.get("name") or "workspace")


def name_env(params: dict[str, Any]) -> dict[str, str]:
    return {"BU_NAME": clean_name(params["name"])} if params.get("name") else {}


def validate_url(raw: str, allowed_domains: tuple[str, ...]) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be public http(s)")
    host = parsed.hostname.lower().rstrip(".")
    if host in _PRIVATE_HOSTS or host.endswith(".localhost"):
        raise ValueError("localhost browser navigation is not allowed")
    try:
        assert_egress_allowed(raw)
    except EgressBlocked as exc:
        raise ValueError(str(exc)) from exc
    if allowed_domains and not any(
        host == domain or host.endswith(f".{domain}") for domain in allowed_domains
    ):
        raise ValueError("domain is not allowed for browser navigation")
    return raw


def safe_command(argv: list[str]) -> list[str]:
    return argv[1:] if argv else []


def csv(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in (value or "").split(",") if item.strip())


def clean_executor_socket(value: str | None) -> str:
    socket_path = str(value or "").strip()
    if not socket_path:
        return ""
    if len(socket_path) > 240 or "\x00" in socket_path or not Path(socket_path).is_absolute():
        raise ValueError("browser executor socket must be a bounded absolute path")
    return socket_path
