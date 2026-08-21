"""MCP consumer adapter: how a consumed server's tools map onto VerbSpecs."""

async def test_list_shaped_tool_output_is_not_rejected():
    """An MCP tool returns arbitrary JSON - an array is as legal as an object.

    Asserting `{"type": "object"}` rejected every list-shaped tool at OUTPUT
    validation with `invalid output for '<verb>'`, long AFTER the call had already
    succeeded downstream: opbox's `list_matters` really did return the caller's
    matters and the kernel then threw the answer away, so the agent reported the
    tool "not responding successfully". Honour a declared outputSchema; otherwise
    accept any JSON rather than inventing a constraint the protocol does not make.
    """
    from boltrig.adapters.mcp_consumer import McpConsumerAdapter


    async def fake_rpc(payload):  # noqa: ANN001 - test double
        return {
            "result": {
                "tools": [
                    {"name": "list_matters", "description": "List matters", "inputSchema": {}},
                    {
                        "name": "get_matter",
                        "description": "Get one matter",
                        "inputSchema": {},
                        "outputSchema": {"type": "object"},
                    },
                ]
            }
        }

    # Injected through the CONSTRUCTOR seam rather than by replacing a private
    # method: discovery holds one connection across a page walk now, so it no
    # longer routes each request through _call, and a stub of that name would be
    # dead code the test could not notice.
    adapter = McpConsumerAdapter(
        "opbox", url="http://opbox.invalid/", allow_internal=True, rpc=fake_rpc
    )
    specs = {s.verb_id: s for s in await adapter.connect(None)}

    # No declared outputSchema => accept any JSON (an array must pass).
    assert specs["opbox.list_matters"].output_schema == {}
    # A declared outputSchema is honoured verbatim.
    assert specs["opbox.get_matter"].output_schema == {"type": "object"}
