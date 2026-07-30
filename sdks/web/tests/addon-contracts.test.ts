import assert from "node:assert/strict";
import { test } from "node:test";

import { BoltrigClient, type AddonsResponse } from "../src/index.js";

test("runtime add-ons use the authenticated canonical inventory route", async () => {
  let requested = "";
  const canonical: AddonsResponse = {
    scope: { tenant_id: "tenant-a", workspace_id: "workspace-a" },
    addons: [{
      id: "opbox",
      version: "1.0.0",
      installation: "installed",
      activation: "active",
      contributions: {
        harness: true,
        adapter: true,
        consequence_hint: true,
      },
      configuration: {
        status: "unverified",
        requirements: [{
          id: "opbox-adapter",
          kind: "adapter",
          required: true,
          status: "unverified",
          reason: "health_unverified",
          evidence: "cached_adapter_health",
        }],
      },
      runtime: { status: "unverified", reason: "health_unverified" },
    }],
  };
  const client = new BoltrigClient({
    fetch: async (input) => {
      requested = String(input);
      return new Response(JSON.stringify(canonical), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  assert.deepEqual(await client.addons(), canonical);
  assert.equal(requested, "/v1/addons");
});
