// 📖 Docs: obsidian/frontend/components/common.md
"use client";

import { animated, useTransition } from "@react-spring/web";

import { useScroll } from "@/hooks/smooth-scroll/use-scroll";

import {
  CookiePreferencesPanel,
  TITLE_ID,
} from "./cookiePreferences/CookiePreferencesPanel";
import { useCookieConsent } from "./cookiePreferences/useCookieConsent";
import { useModalDismiss } from "./cookiePreferences/useModalDismiss";
import { useCookieStore } from "./cookieStore";

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
          <CookiePreferencesPanel
            onClose={closeModal}
            onRejectAll={rejectAll}
            onAcceptAll={acceptAll}
            consent={consentState}
          />
        </animated.div>
      </animated.div>
    ) : null,
  );
};
