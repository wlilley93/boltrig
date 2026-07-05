// 📖 Docs: obsidian/frontend/components/common.md
"use client";

import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

import type { CookieConsent } from "../cookieStore";

export interface CookieConsentState {
  analytics: boolean;
  marketing: boolean;
  setAnalytics: Dispatch<SetStateAction<boolean>>;
  setMarketing: Dispatch<SetStateAction<boolean>>;
  handleSave: () => void;
}

export function useCookieConsent(
  open: boolean,
  consent: CookieConsent | null,
  savePreferences: (next: { analytics: boolean; marketing: boolean }) => void,
): CookieConsentState {
  // Pre-fill toggles as ON when no prior decision exists. Once a user has
  // saved a choice, that choice wins.
  const [analytics, setAnalytics] = useState<boolean>(consent?.analytics ?? true);
  const [marketing, setMarketing] = useState<boolean>(consent?.marketing ?? true);

  // Re-seed local toggles every time the modal opens so users see their saved
  // state, not whatever was in flight from a previous open.
  useEffect(() => {
    if (!open) return;
    setAnalytics(consent?.analytics ?? true);
    setMarketing(consent?.marketing ?? true);
  }, [open, consent]);

  const handleSave = () => savePreferences({ analytics, marketing });

  return { analytics, marketing, setAnalytics, setMarketing, handleSave };
}
