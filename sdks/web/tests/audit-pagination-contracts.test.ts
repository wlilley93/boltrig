import assert from "node:assert/strict";
import { test } from "node:test";

import { BoltrigClient } from "../src/index.js";

test("account activity and audit search expose bounded pagination parameters", async () => {
  const urls: string[] = [];
  const client = new BoltrigClient({
    fetch: async (input) => {
      urls.push(String(input));
      return new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });

  await client.meActivity({ limit: 8, offset: 16 });
  await client.auditSearch({
    query: "invoice", actor: "alice", security: true, eventType: "login_failure",
    limit: 100, offset: 200,
  });

  assert.deepEqual(urls, [
    "/v1/me/activity?limit=8&offset=16",
    "/v1/audit/search?query=invoice&actor=alice&security=1&event_type=login_failure&limit=100&offset=200",
  ]);
});
