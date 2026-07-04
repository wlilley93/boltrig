export const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

export const PLATFORM_OPTIONS = [
  { value: "webhook", label: "Webhook" },
  { value: "msteams", label: "MS Teams" },
];

export const UNPAIRED_OPTIONS = [
  { value: "reject", label: "Reject" },
  { value: "ignore", label: "Ignore" },
  { value: "pair", label: "Pair" },
];

export const ROLE_OPTIONS = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
  { value: "superadmin", label: "Superadmin" },
];

export const ENABLED_OPTIONS = [
  { value: "true", label: "Enabled" },
  { value: "false", label: "Disabled" },
];
