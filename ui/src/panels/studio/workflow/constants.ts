export const TZ_OPTIONS = [
  "UTC",
  "Europe/London",
  "Europe/Paris",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
].map((z) => ({ value: z, label: z }));

export const CRON_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "Hourly", value: "0 * * * *" },
  { label: "Daily 9am", value: "0 9 * * *" },
  { label: "Weekdays 9am", value: "0 9 * * 1-5" },
  { label: "Mondays 9am", value: "0 9 * * 1" },
];
