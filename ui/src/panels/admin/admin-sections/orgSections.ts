// Org structure and hierarchy sections of the admin console register.
import { RoleMappingList } from "@/panels/admin/editors";
import { AGENT_NODE_PROPERTIES } from "@/panels/admin/admin-sections/schemaConstants";
import type { AdminSection } from "@/panels/admin/admin-sections/types";

export const orgSections: ReadonlyArray<AdminSection> = [
  {
    key: "identity",
    label: "Identity & roles",
    blurb: "IdP group to role and scope mappings - the RBAC source of truth.",
    preserves:
      "OIDC endpoints (issuer, audience, JWKS) are deploy-time wiring and stay operator-only; they are preserved untouched.",
    schema: {
      type: "object",
      properties: {
        provider: {
          type: "string",
          enum: ["oidc"],
          description: "The identity provider protocol.",
        },
        role_mappings: {
          type: "array",
          description:
            "Each entry maps an IdP group to a role and a permission scope (all / departments / nouns / verbs). This is the RBAC source of truth.",
          // Dedicated typed editor: IdP-group field + role select + a structured
          // scope sub-editor (the generic array path cannot express the scope union).
          editor: RoleMappingList,
        },
      },
    },
  },
  {
    key: "hierarchy",
    label: "Org hierarchy & budgets",
    blurb: "The durable agent org chart and each tier's spend budget.",
    schema: {
      type: "object",
      properties: {
        tier1: {
          type: "object",
          description: "The single top-tier agent (chief of staff).",
          properties: AGENT_NODE_PROPERTIES,
        },
        tier2: {
          type: "array",
          description:
            "The department heads under tier 1, each with its own runtime, skills and budget.",
          items: { type: "object", properties: AGENT_NODE_PROPERTIES },
        },
      },
    },
  },
];
