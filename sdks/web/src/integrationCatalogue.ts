import type { IntegrationCatalogueEntry } from "./types.js";

type Seed = Omit<
  IntegrationCatalogueEntry,
  "certification" | "description" | "auth"
> & {
  auth?: IntegrationCatalogueEntry["auth"];
  description?: string;
};

const entries: Seed[] = [
  { id: "telegram", label: "Telegram", category: "communications", transport: "channel_gateway" },
  { id: "slack", label: "Slack", category: "communications", transport: "channel_gateway", auth: ["oauth2"] },
  { id: "email", label: "Email", category: "communications", transport: "channel_gateway", auth: ["manual_secret"] },
  { id: "gmail", label: "Gmail", category: "communications", transport: "rest" },
  { id: "outlook", label: "Outlook", category: "communications", transport: "rest" },
  { id: "discord", label: "Discord", category: "communications", transport: "channel_gateway" },
  { id: "whatsapp", label: "WhatsApp", category: "communications", transport: "channel_gateway" },

  { id: "google-calendar", label: "Google Calendar", category: "work", transport: "rest" },
  { id: "github", label: "GitHub", category: "work", transport: "rest" },
  { id: "gitlab", label: "GitLab", category: "work", transport: "rest" },
  { id: "jira", label: "Jira", category: "work", transport: "rest" },
  { id: "monday", label: "monday.com", category: "work", transport: "rest" },
  { id: "confluence", label: "Confluence", category: "work", transport: "rest" },
  { id: "zendesk", label: "Zendesk", category: "work", transport: "rest" },
  { id: "linear", label: "Linear", category: "work", transport: "rest" },
  { id: "asana", label: "Asana", category: "work", transport: "rest" },
  { id: "clickup", label: "ClickUp", category: "work", transport: "rest" },

  { id: "dropbox", label: "Dropbox", category: "storage_design", transport: "rest" },
  { id: "box", label: "Box", category: "storage_design", transport: "rest" },
  { id: "google-drive", label: "Google Drive", category: "storage_design", transport: "rest" },
  { id: "notion", label: "Notion", category: "storage_design", transport: "rest" },
  { id: "docusign", label: "DocuSign", category: "storage_design", transport: "rest" },
  { id: "canva", label: "Canva", category: "storage_design", transport: "rest" },
  { id: "figma", label: "Figma", category: "storage_design", transport: "rest" },
  { id: "descript", label: "Descript", category: "storage_design", transport: "rest" },

  { id: "hubspot", label: "HubSpot", category: "crm_sales", transport: "rest" },
  { id: "salesforce", label: "Salesforce", category: "crm_sales", transport: "rest" },
  { id: "attio", label: "Attio", category: "crm_sales", transport: "rest" },
  { id: "close", label: "Close", category: "crm_sales", transport: "rest" },
  { id: "apollo", label: "Apollo", category: "crm_sales", transport: "rest" },
  { id: "hunter", label: "Hunter", category: "crm_sales", transport: "rest" },
  { id: "clay", label: "Clay", category: "crm_sales", transport: "rest" },

  { id: "stripe", label: "Stripe", category: "finance", transport: "rest" },
  { id: "quickbooks", label: "QuickBooks", category: "finance", transport: "rest" },

  { id: "datadog", label: "Datadog", category: "analytics_operations", transport: "rest" },
  { id: "posthog", label: "PostHog", category: "analytics_operations", transport: "rest" },
  { id: "mixpanel", label: "Mixpanel", category: "analytics_operations", transport: "rest" },
  { id: "amplitude", label: "Amplitude", category: "analytics_operations", transport: "rest" },
  { id: "pagerduty", label: "PagerDuty", category: "analytics_operations", transport: "rest" },

  {
    id: "playwright-browser",
    label: "Browser automation",
    category: "browser",
    transport: "browser",
    auth: [],
  },
];

/**
 * Presentation metadata ported from the reviewed OpenWorker catalogue.
 *
 * Every entry begins `uncertified` on purpose. This list is not a connection
 * registry and never carries a secret; the server is authoritative for
 * certification and tenant connection records.
 */
export const WORKER_INTEGRATION_CATALOGUE: readonly IntegrationCatalogueEntry[] =
  Object.freeze(
    entries.map((entry) => ({
      ...entry,
      auth: entry.auth ?? ["oauth2"],
      description: entry.description ?? `Connect ${entry.label} through a governed Boltrig adapter.`,
      certification: "uncertified" as const,
    })),
  );
