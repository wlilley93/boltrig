import assert from "node:assert/strict";
import test from "node:test";

import {
  DISPLAY_OBJECT_SCHEMA,
  DISPLAY_OBJECT_TEMPLATES,
  normalizeEvents,
  parseDisplayObject,
  type ChatEvent,
} from "../src/index.js";

function slackDraft() {
  return {
    schema: DISPLAY_OBJECT_SCHEMA,
    id: "do_slack_1",
    kind: "slack.message.draft",
    title: "Draft update for #launch",
    status: "draft",
    revision: 1,
    data: {
      channel_id: "slack-primary",
      workspace_label: "Acme",
      recipient: "#launch",
      body: "The release candidate is ready for review.",
    },
    actions: [
      { id: "edit", label: "Edit", intent: "edit", style: "secondary" },
      { id: "send", label: "Send", intent: "send", style: "primary", requires_confirmation: true },
    ],
    provenance: { run_id: "run-1", agent_address: "chief-of-staff" },
  } as const;
}

test("catalogue is broad, unique and still a closed set", () => {
  const kinds = DISPLAY_OBJECT_TEMPLATES.map((template) => template.kind);
  assert.ok(kinds.length >= 60);
  assert.equal(new Set(kinds).size, kinds.length);
  assert.ok(kinds.includes("email.draft"));
  assert.ok(kinds.includes("data.map"));
  assert.ok(kinds.includes("custom.card"));
});

test("parser accepts reviewed editable communication cards", () => {
  const parsed = parseDisplayObject(slackDraft());

  assert.equal(parsed?.kind, "slack.message.draft");
  assert.equal(parsed?.actions?.[1]?.intent, "send");
  assert.equal(parsed?.provenance?.agent_address, "chief-of-staff");
});

test("custom cards may put all composition in reviewed top-level blocks", () => {
  const parsed = parseDisplayObject({
    schema: DISPLAY_OBJECT_SCHEMA,
    id: "do_custom_1",
    kind: "custom.card",
    title: "Launch health",
    data: {},
    blocks: [{ type: "metrics", items: [{ label: "Ready", value: "92%" }] }],
  });

  assert.equal(parsed?.blocks?.[0]?.type, "metrics");
});

test("parser refuses arbitrary UI code and unsafe URLs", () => {
  assert.equal(parseDisplayObject({
    ...slackDraft(), kind: "raw.html", data: { html: "<script>run()</script>" },
  }), null);
  assert.equal(parseDisplayObject({
    ...slackDraft(), data: { ...slackDraft().data, url: "javascript:run()" },
  }), null);
  assert.equal(parseDisplayObject({
    ...slackDraft(), blocks: [{ type: "table", columns: ["Name"] }],
  }), null);
  assert.equal(parseDisplayObject({
    ...slackDraft(), data: { ...slackDraft().data, url: "https://user:secret@example.com" },
  }), null);
});

test("normalizer retains display objects in stream order", () => {
  const object = parseDisplayObject(slackDraft());
  assert.ok(object);
  const turn = normalizeEvents([
    { type: "text_delta", delta: "I prepared the update." },
    { type: "display_object", run_id: "run-1", object },
    { type: "message_end", run_id: "run-1" },
  ] as ChatEvent[]);

  assert.equal(turn.displayObjects.length, 1);
  assert.equal(turn.displayObjects[0]?.object.title, "Draft update for #launch");
  assert.deepEqual(turn.timeline.map((item) => item.kind), ["display_object"]);
});
