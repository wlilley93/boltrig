import assert from "node:assert/strict";
import { test } from "node:test";

import { BoltrigClient } from "../src/index.js";

test("federated search uses the canonical same-origin kernel contract", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  const client = new BoltrigClient({
    csrfToken: () => "search-csrf",
    fetch: async (input, init) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({
        query: "apollo",
        limit: 5,
        results: [],
        sources: [],
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.federatedSearch({
    query: " apollo ",
    limit: 5,
    sources: ["conversations", "knowledge", "memory"],
  });

  assert.equal(requests.length, 1);
  assert.equal(requests[0]?.url, "/v1/search");
  assert.equal(requests[0]?.init?.method, "POST");
  assert.equal(
    new Headers(requests[0]?.init?.headers).get("x-boltrig-csrf"),
    "search-csrf",
  );
  assert.deepEqual(JSON.parse(String(requests[0]?.init?.body)), {
    query: " apollo ",
    limit: 5,
    sources: ["conversations", "knowledge", "memory"],
  });
});
