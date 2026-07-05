// 📖 Docs: obsidian/frontend/components/common.md
"use client";

import Link from "next/link";

import { CookieButton } from "../CookieButton";
import { CookieCategoryList } from "./CookieCategoryList";
import type { CookieConsentState } from "./useCookieConsent";

export const TITLE_ID = "cookie-preferences-title";

export function CookiePreferencesPanel({
  onClose,
  onRejectAll,
  onAcceptAll,
  consent,
}: {
  onClose: () => void;
  onRejectAll: () => void;
  onAcceptAll: () => void;
  consent: CookieConsentState;
}) {
  return (
    <>
      <header className="flex items-start justify-between gap-3">
        <h2 id={TITLE_ID} className="text-xl font-medium leading-tight">
          Cookie preferences
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close cookie preferences"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-foreground/10 text-foreground hover:bg-foreground/5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path
              d="M4 4l8 8M12 4l-8 8"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </header>

      <p className="text-sm leading-relaxed text-foreground/60">
        Choose which categories of cookies we&apos;re allowed to use. You can
        change this any time. See our{" "}
        <Link
          href="/privacy-policy"
          target="_blank"
          rel="noopener noreferrer"
          className="text-foreground underline underline-offset-2"
        >
          privacy policy
        </Link>
        .
      </p>

      <CookieCategoryList s={consent} />

      <footer className="mt-1 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
        <CookieButton variant="secondary" onClick={onRejectAll}>
          Reject all
        </CookieButton>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
          <CookieButton variant="secondary" onClick={consent.handleSave}>
            Save preferences
          </CookieButton>
          <CookieButton onClick={onAcceptAll}>Accept all</CookieButton>
        </div>
      </footer>
    </>
  );
}
