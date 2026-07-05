// 📖 Docs: obsidian/frontend/components/common.md
"use client";

import Link from "next/link";
import { animated, useTransition } from "@react-spring/web";

import { useScroll } from "@/hooks/smooth-scroll/use-scroll";

import { CookieButton } from "./CookieButton";
import { CookieCategoryList } from "./cookiePreferences/CookieCategoryList";
import { useCookieConsent } from "./cookiePreferences/useCookieConsent";
import { useModalDismiss } from "./cookiePreferences/useModalDismiss";
import { useCookieStore } from "./cookieStore";

const TITLE_ID = "cookie-preferences-title";

export const CookiePreferencesModal = () => {
  const open = useCookieStore((s) => s.modalOpen);
  const consent = useCookieStore((s) => s.consent);
  const closeModal = useCookieStore((s) => s.closeModal);
  const acceptAll = useCookieStore((s) => s.acceptAll);
  const rejectAll = useCookieStore((s) => s.rejectAll);
  const savePreferences = useCookieStore((s) => s.savePreferences);

  const stopScroll = useScroll((s) => s.stop);
  const startScroll = useScroll((s) => s.start);

  const consentState = useCookieConsent(open, consent, savePreferences);
  useModalDismiss(open, closeModal, stopScroll, startScroll);

  // Spring-driven mount/unmount for backdrop + panel.
  const transitions = useTransition(open, {
    from: { opacity: 0, scale: 0.94 },
    enter: { opacity: 1, scale: 1 },
    leave: { opacity: 0, scale: 0.94 },
    config: { tension: 320, friction: 32 },
  });

  return transitions((style, isOpen) =>
    isOpen ? (
      <animated.div
        className="fixed inset-0 z-[100] font-sans"
        style={{ opacity: style.opacity }}
      >
        <div
          aria-hidden
          onMouseDown={closeModal}
          className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        />
        <animated.div
          role="dialog"
          aria-modal="true"
          aria-labelledby={TITLE_ID}
          style={{
            transform: style.scale.to((s) => `translate(-50%, -50%) scale(${s})`),
          }}
          className="absolute left-1/2 top-1/2 flex max-h-[calc(100dvh-1.5rem)] w-[calc(100vw-1.5rem)] max-w-[560px] flex-col gap-5 overflow-hidden rounded-xl border border-foreground/10 bg-background p-5 text-foreground shadow-2xl sm:p-7"
        >
          <header className="flex items-start justify-between gap-3">
            <h2 id={TITLE_ID} className="text-xl font-medium leading-tight">
              Cookie preferences
            </h2>
            <button
              type="button"
              onClick={closeModal}
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

          <CookieCategoryList s={consentState} />

          <footer className="mt-1 flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
            <CookieButton variant="secondary" onClick={rejectAll}>
              Reject all
            </CookieButton>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center">
              <CookieButton variant="secondary" onClick={consentState.handleSave}>
                Save preferences
              </CookieButton>
              <CookieButton onClick={acceptAll}>Accept all</CookieButton>
            </div>
          </footer>
        </animated.div>
      </animated.div>
    ) : null,
  );
};
