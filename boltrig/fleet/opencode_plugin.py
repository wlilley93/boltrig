"""Install the project-local OpenCode plugin that consumes Boltrig MCP env."""

from __future__ import annotations

from pathlib import Path

PLUGIN_NAME = "boltrig-mcp.js"

PLUGIN_SOURCE = """\
import { tool } from "@opencode-ai/plugin"

const NAME = process.env.BOLTRIG_MCP_SERVER_NAME || "boltrig-kernel"
const URL = process.env.BOLTRIG_MCP_URL || ""
const TOKEN = process.env.BOLTRIG_MCP_TOKEN || ""

async function rpc(method, params = {}) {
  if (!URL || !TOKEN) {
    return { error: "boltrig_mcp_unconfigured" }
  }
  const res = await fetch(URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-boltrig-mcp-token": TOKEN,
    },
    body: JSON.stringify({ jsonrpc: "2.0", id: Date.now(), method, params }),
  })
  return await res.json()
}

function stableJson(value) {
  return JSON.stringify(value, null, 2)
}

export const BoltrigMcpPlugin = async ({ client }) => {
  if (client?.app?.log) {
    await client.app.log({
      body: {
        service: "boltrig-mcp",
        level: URL && TOKEN ? "info" : "warn",
        message: URL && TOKEN ? "Boltrig MCP handoff enabled" : "Boltrig MCP handoff missing",
        extra: { server: NAME, configured: Boolean(URL && TOKEN) },
      },
    })
  }
  return {
    tool: {
      boltrig_mcp_status: tool({
        description: "Show whether the scoped Boltrig MCP handoff is available.",
        args: {},
        async execute() {
          return stableJson({ server: NAME, configured: Boolean(URL && TOKEN) })
        },
      }),
      boltrig_mcp_list: tool({
        description: "List Boltrig MCP tools granted to this OpenCode run.",
        args: {},
        async execute() {
          return stableJson(await rpc("tools/list"))
        },
      }),
      boltrig_mcp_call: tool({
        description: "Call one granted Boltrig MCP tool through the kernel chokepoint.",
        args: {
          name: tool.schema.string(),
          arguments_json: tool.schema.string(),
        },
        async execute(args) {
          let parsed = {}
          try {
            parsed = args.arguments_json ? JSON.parse(args.arguments_json) : {}
          } catch {
            return stableJson({ error: "invalid_arguments_json" })
          }
          return stableJson(await rpc("tools/call", { name: args.name, arguments: parsed }))
        },
      }),
    },
  }
}
"""


def plugin_path(config_dir: str | Path) -> Path:
    """The project/custom OpenCode plugin path for Boltrig MCP."""
    return Path(config_dir).expanduser() / "plugins" / PLUGIN_NAME


def install_opencode_plugin(config_dir: str | Path) -> Path:
    """Write the local plugin without changing global OpenCode config."""
    path = plugin_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PLUGIN_SOURCE, encoding="utf-8")
    return path
