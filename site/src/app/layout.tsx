import type { Metadata, Viewport } from "next";

import {
  generateMetadata,
  generateViewport,
} from "@/utils/seo/generate-page-metadata";
import { getSiteStructuredData } from "@/utils/seo/structured-data";

import { LazyCookie } from "@/components/common/Cookie";
import { SafeJsonLd } from "@/components/common/SafeJsonLd";
import { AdaptiveGrid } from "@/components/common/grid";
import { ReducedMotion } from "@/components/common/reduced-motion";
import { SiteHeader } from "@/components/common/site-header";
import { ScrollLayout } from "@/layouts/scroll-layout";

import "@/app/globals.css";

export const metadata: Metadata = generateMetadata();
export const viewport: Viewport = generateViewport();

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        {/* Boltrig typefaces (Google Fonts): IBM Plex Sans for copy, JetBrains
            Mono for terminal chrome - resolved via `--font-sans` / `--font-mono`
            in globals.css. Matches the product console. */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased">
        <SafeJsonLd data={getSiteStructuredData()} />
        <SiteHeader />
        <ScrollLayout>
          <AdaptiveGrid />
          <ReducedMotion />
          <LazyCookie />
          {children}
        </ScrollLayout>
      </body>
    </html>
  );
}
