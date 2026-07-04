/**
 * Site-wide configuration: the single source of truth for SEO.
 *
 * Consumed by the metadata generator, `robots.ts`, `sitemap.ts`, and the
 * JSON-LD structured-data helper. Update the placeholder values per project.
 */
import { publicEnv } from "@/env";

export const siteConfig = {
  name: "Boltrig",
  description:
    "Boltrig lets teams delegate operational work to AI agents while keeping approvals, permissions, credentials and audit evidence under control.",
  /**
   * Public origin, no trailing slash. Drives canonical URLs, OG tags, the
   * sitemap, and JSON-LD. Set `NEXT_PUBLIC_SITE_URL` in production.
   */
  url: publicEnv.NEXT_PUBLIC_SITE_URL ?? "https://boltrig.io",
  /** Default Open Graph / Twitter share image (path under `public/`). */
  ogImage: "/og-card.png",
  twitterHandle: "@boltrig",
  author: "Boltrig",
  /** Browser theme-color (address bar / PWA). */
  themeColor: "#04060d",
} as const;
