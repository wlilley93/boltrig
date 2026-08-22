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
   *
   * boltrig.ai since 2026-08-18. THE DEFAULT IS THE ONE THAT SHIPS: the static
   * export is built by whoever runs `pnpm build`, and a build that forgets the
   * env var still emits a full set of canonicals, OG urls and a sitemap. Leaving
   * the old domain here would have every one of them name a host that 301s to
   * this one, which tells a crawler the redirect target is not the real page.
   */
  url: publicEnv.NEXT_PUBLIC_SITE_URL ?? "https://boltrig.ai",
  /** Default Open Graph / Twitter share image (path under `public/`). */
  ogImage: "/og-card.png",
  twitterHandle: "@boltrig",
  author: "Boltrig",
  /** Browser theme-color (address bar / PWA). */
  themeColor: "#04060d",
} as const;
