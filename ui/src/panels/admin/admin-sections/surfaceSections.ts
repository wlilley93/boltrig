// Chat, evaluation, notification and personal-agent sections of the admin
// console register. These shape the user-facing surfaces and the eval harness.
import {
  NotificationDefaultsList,
  SkillsByRoleList,
} from "@/panels/admin/editors";
import { EVAL_TARGET_KIND } from "@/panels/admin/admin-sections/schemaConstants";
import type { AdminSection } from "@/panels/admin/admin-sections/types";

export const surfaceSections: ReadonlyArray<AdminSection> = [
  {
    key: "chat",
    label: "Chat",
    blurb: "The conversational layer and per-role bare-turn authority.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether the chat surface is active." },
        transport: {
          type: "string",
          enum: ["sse", "websocket"],
          description: "The streaming transport.",
        },
        retention_days: {
          type: "integer",
          minimum: 0,
          maximum: 3650,
          description: "Days to retain conversations.",
        },
        panel: { type: "boolean", description: "Show the Chat panel in the UI." },
        continuity: {
          type: "boolean",
          description: "Compose prior turns into the prompt for continuity.",
        },
        default_skills: {
          type: "array",
          items: { type: "string" },
          description: "Skills a bare chat turn spawns with for an unmapped role.",
        },
        skills_by_role: {
          type: "object",
          additionalProperties: true,
          description:
            "Per-role skill sets a bare chat turn spawns with (intersected with the caller's grants, so it can only reduce authority).",
          // Open key/value map (role -> skills): a typed key/value editor, not JSON.
          editor: SkillsByRoleList,
        },
      },
    },
  },
  {
    key: "evaluation",
    label: "Evaluation",
    blurb: "The eval harness and its suites.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether the eval harness is active." },
        suites: {
          type: "array",
          description: "Each suite's id, target kind and target ref.",
          items: {
            type: "object",
            properties: {
              id: { type: "string", description: "The suite id." },
              target_kind: {
                type: "string",
                enum: EVAL_TARGET_KIND,
                description: "What the suite evaluates.",
              },
              target_ref: {
                type: "string",
                description: "The target ref/pattern (e.g. ops/*).",
              },
            },
          },
        },
      },
    },
  },
  {
    key: "notifications",
    label: "Notifications",
    blurb: "Default channel routing per notification event.",
    schema: {
      type: "object",
      properties: {
        defaults: {
          type: "object",
          additionalProperties: true,
          description: "Per-event default channel routing (approval, escalation, budget_alert).",
          // Open key/value map (event -> {channel}): a typed key/value editor, not JSON.
          editor: NotificationDefaultsList,
        },
      },
    },
  },
  {
    key: "personal_agents",
    label: "Personal agents",
    blurb: "Org-level defaults for users' delegated personal agents.",
    schema: {
      type: "object",
      properties: {
        enabled: { type: "boolean", description: "Whether personal agents are available." },
        default_runtime: {
          type: "string",
          description: "The runtime a new personal agent uses by default.",
        },
        default_skills: {
          type: "array",
          items: { type: "string" },
          description: "The skills a new personal agent starts with.",
        },
      },
    },
  },
];
