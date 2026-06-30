# Boltrig Pi sidecar

A standalone agent reasoning-loop service (Round Two, Epic RUN; SRS S5.3). It is
reached over HTTP by Boltrig's `PiRuntime`. It is deliberately NOT part of the
`boltrig` Python package: `boltrig/kernel` and `boltrig/models` import nothing from
here (severability). The only coupling is the wire protocol below.

## What it does

On `POST /run` the sidecar:

1. Connects to the run-scoped kernel MCP face (`initialize` + `tools/list`). The
   advertised tools are the ONLY tools the loop has (SEC-24).
2. Runs a thin loop up to `limits.max_steps`: it calls the pinned model
   (OpenAI-compatible `chat/completions` with tools); the model either speaks
   (text) or calls a tool; tool calls run over MCP `tools/call`; results feed
   back to the model; repeat.
3. Streams newline-delimited JSON events, then a `final` event.

It never crashes a request (P9, US-RUN-05): a missing / unreachable model or MCP
face degrades to a well-formed `final` event with a 200 response.

## Protocol

### `POST /run` request body

```json
{
  "prompt": "<composed prompt>",
  "mcp": { "url": "http://kernel:8000/v1/mcp", "token": "<run-scoped token>" },
  "model": { "endpoint": "<base_url or null>", "name": "<pinned model>", "api_key": "<optional>" },
  "limits": { "max_steps": 12 }
}
```

### `POST /run` response

`Content-Type: application/x-ndjson` - one JSON object per line, then a final
event:

```
{"type":"text_delta","delta":"..."}
{"type":"reasoning_delta","delta":"..."}
{"type":"tool_call","verb":"jira.create","input":{...},"status":"running"}
{"type":"tool_result","verb":"jira.create","status":"ok","output":{...}}
{"type":"final","output":{...},"summary":"...","tokens_used":N,"cost_micros":N,"new_work_items":[]}
```

`tool_result.status` mirrors the kernel's `_boltrig.status`: `ok`,
`pending_human`, `denied`, `degraded`, or `error`. On `pending_human` the loop
stops and returns a `final` whose `output._paused` summarises the pause.

### `GET /health`

```json
{ "status": "ok" }
```

## How the MCP connection works

The kernel MCP face is JSON-RPC 2.0 over HTTP. The sidecar POSTs to `mcp.url`
with header `x-boltrig-mcp-token: <mcp.token>`:

- `tools/list` -> `result.tools = [{name, description, inputSchema}, ...]`
- `tools/call` -> `result.{content, isError, _boltrig:{status, output|reason|hitl_request_id}}`

The token scopes the connection to one run (skill grants intersect tenant
ceiling, SEC-23), so the loop sees and can call only its own tools.

## Sandboxing notes (SEC-24, SEC-27)

- The sidecar has NO native filesystem / process / credential / network tools.
  Its only capability is "call a kernel verb over the scoped MCP connection".
- It never receives a tool credential. It is given only a model key and a
  run-scoped MCP token, both per request. Neither is ever logged or echoed into
  an event.
- Egress must be restricted at the network layer to exactly the kernel MCP
  endpoint and the model endpoint (see the `Dockerfile` header). The container
  holds no secrets and exposes only port 8090.

## Run it

```bash
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8090
# or
docker build -t boltrig-pi-sidecar . && docker run -p 8090:8090 boltrig-pi-sidecar
```

Importing the app needs no live kernel or model (those are per request only), so
`uvicorn app:app` starts cleanly offline.

## Where a real "Pi" loop slots in

This service is the integration point for the Pi open-source agent toolkit. The
loop is implemented directly (model + MCP tools) so it works with no external Pi
package installed and adds no hard dependency on an unavailable one. To adopt a
real Pi loop, replace the body of `run_loop` in `app.py` while keeping the same
inputs (the composed prompt, the MCP-derived tool list, the model config) and
emitting the same event stream (`text_delta` / `reasoning_delta` / `tool_call` /
`tool_result` / `final`). The MCP client and the event helpers can be reused
as-is.
