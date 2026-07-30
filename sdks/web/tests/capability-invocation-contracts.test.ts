import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BoltrigClient,
  buildCapabilityParams,
  compileCapabilityForm,
  projectCapabilityOutput,
} from "../src/index.js";

test("safe capability forms emit only declared typed parameters", () => {
  const contract = compileCapabilityForm({
    type: "object",
    additionalProperties: false,
    required: ["title", "settings"],
    properties: {
      title: { type: "string", minLength: 3 },
      priority: { type: "integer", minimum: 1, maximum: 5 },
      enabled: { type: "boolean" },
      tags: {
        type: "array",
        items: { type: "string" },
        maxItems: 3,
      },
      settings: {
        type: "object",
        additionalProperties: false,
        properties: {
          threshold: { type: "number" },
        },
      },
    },
  });
  assert.equal(contract.status, "ready");
  if (contract.status !== "ready") return;

  assert.deepEqual(
    buildCapabilityParams(contract, {
      "/title": "Review ticket",
      "/priority": "3",
      "/enabled": "false",
      "/tags": "urgent\ncustomer",
    }),
    {
      status: "ready",
      params: {
        title: "Review ticket",
        priority: 3,
        enabled: false,
        tags: ["urgent", "customer"],
        settings: {},
      },
    },
  );
});

test("generic capability forms refuse secrets, reserved names, open maps and composite schemas", () => {
  for (const schema of [
    {
      type: "object",
      properties: { api_key: { type: "string" } },
    },
    {
      type: "object",
      properties: { signingToken: { type: "string" } },
    },
    {
      type: "object",
      properties: { payload: { type: "string", contentMediaType: "application/octet-stream" } },
    },
    {
      type: "object",
      properties: { constructor: { type: "string" } },
    },
    {
      type: "object",
      additionalProperties: true,
      properties: { label: { type: "string" } },
    },
    {
      type: "object",
      properties: { target: { oneOf: [{ type: "string" }, { type: "number" }] } },
    },
    {
      type: "object",
      properties: {
        placements: {
          type: "array",
          items: { type: "object", properties: { x: { type: "number" } } },
        },
      },
    },
    {
      type: "object",
      properties: {
        labels: {
          type: "array",
          uniqueItems: true,
          items: { type: "string" },
        },
      },
    },
    {
      type: "object",
      properties: { priority: { type: "integer", minimum: 5, maximum: 1 } },
    },
  ]) {
    assert.equal(compileCapabilityForm(schema).status, "unavailable");
  }
});

test("string and string-array constraints return field errors instead of parameter values", () => {
  const contract = compileCapabilityForm({
    type: "object",
    additionalProperties: false,
    required: ["title", "labels"],
    properties: {
      title: { type: "string", minLength: 5, pattern: "^[A-Z]" },
      labels: {
        type: "array",
        items: { type: "string", minLength: 3 },
      },
    },
  });
  assert.equal(contract.status, "ready");
  if (contract.status !== "ready") return;
  assert.deepEqual(
    buildCapabilityParams(contract, { "/title": "no", "/labels": "x\nvalid" }),
    {
      status: "invalid",
      field_errors: {
        "/title": "Enter at least 5 characters.",
        "/labels": "Enter at least 3 characters.",
      },
    },
  );
});

test("capability output projection shows declared fields only and fails closed on secrets", () => {
  assert.deepEqual(
    projectCapabilityOutput(
      {
        type: "object",
        additionalProperties: false,
        properties: {
          ticket_id: { type: "string" },
          details: {
            type: "object",
            properties: { count: { type: "integer" } },
          },
        },
      },
      {
        ticket_id: "T-42",
        details: { count: 2, undeclared: "hidden" },
        raw_adapter_payload: "hidden",
      },
    ),
    {
      status: "visible",
      value: { ticket_id: "T-42", details: { count: 2 } },
    },
  );
  assert.deepEqual(
    projectCapabilityOutput(
      {
        type: "object",
        properties: {
          access_token: { type: "string" },
        },
      },
      { access_token: "do-not-render" },
    ),
    { status: "hidden", reason: "Output schema contains an unsafe field." },
  );
});

test("invoke normalizes denied, degraded and transport-unavailable receipts", async () => {
  const responses = [
    new Response('{"detail":"membership required"}', {
      status: 403,
      headers: { "content-type": "application/json" },
    }),
    new Response('{"status":"degraded","output":{"accepted":false}}', {
      status: 503,
      headers: { "content-type": "application/json" },
    }),
  ];
  const client = new BoltrigClient({
    fetch: async () => {
      const response = responses.shift();
      if (response) return response;
      throw new Error("gateway offline");
    },
  });
  const request = { noun: "ticket", verb: "ticket.create", params: {} };
  assert.deepEqual(
    await client.invoke(request),
    { status: "denied", reason: "membership required" },
  );
  assert.deepEqual(
    await client.invoke(request),
    { status: "degraded", output: { accepted: false } },
  );
  assert.deepEqual(
    await client.invoke(request),
    { status: "unavailable", reason: "gateway offline" },
  );
});

test("invoke approval state reads the caller-owned params-free projection", async () => {
  let url = "";
  let method = "";
  const client = new BoltrigClient({
    fetch: async (input, init) => {
      url = String(input);
      method = String(init?.method);
      return new Response('{"status":"approved"}', {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    },
  });
  assert.deepEqual(
    await client.invokeApprovalState("approval/42"),
    { status: "approved" },
  );
  assert.equal(url, "/v1/invoke/approvals/approval%2F42");
  assert.equal(method, "GET");
});
