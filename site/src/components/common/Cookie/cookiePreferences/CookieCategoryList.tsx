// 📖 Docs: obsidian/frontend/components/common.md
"use client";

import { animated, useSpring } from "@react-spring/web";

import type { CookieConsentState } from "./useCookieConsent";

type CategoryKey = "necessary" | "analytics" | "marketing";

interface Category {
  key: CategoryKey;
  title: string;
  body: string;
  required?: boolean;
}

const CATEGORIES: Category[] = [
  {
    key: "necessary",
    title: "Strictly necessary",
    body: "Required for the site to work: sign-in, security, page navigation. These can't be turned off.",
    required: true,
  },
  {
    key: "analytics",
    title: "Analytics",
    body: "Anonymised usage stats so we know which pages help and which fall flat. No personal profile is built.",
  },
  {
    key: "marketing",
    title: "Marketing",
    body: "Lets us measure ad performance and re-show content you didn't get to finish reading. Opt out anytime.",
  },
];

export function CookieCategoryList({ s }: { s: CookieConsentState }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto py-1">
      {CATEGORIES.map((c) => {
        const value =
          c.key === "necessary" ? true : c.key === "analytics" ? s.analytics : s.marketing;
        const setValue =
          c.key === "analytics"
            ? s.setAnalytics
            : c.key === "marketing"
              ? s.setMarketing
              : undefined;
        return (
          <div
            key={c.key}
            className="flex items-start justify-between gap-4 rounded-[10px] border border-foreground/10 px-4 py-3.5"
          >
            <div className="flex min-w-0 flex-col gap-1">
              <h3 className="text-sm font-medium leading-snug">{c.title}</h3>
              <p className="text-xs leading-relaxed text-foreground/60">
                {c.body}
              </p>
            </div>
            <Toggle
              on={value}
              disabled={c.required}
              label={c.title}
              onChange={setValue ? () => setValue((v) => !v) : undefined}
            />
          </div>
        );
      })}
    </div>
  );
}

interface ToggleProps {
  on: boolean;
  disabled?: boolean;
  onChange?: () => void;
  label: string;
}

const Toggle = ({ on, disabled, onChange, label }: ToggleProps) => {
  // Knob slides on a spring - track colour snaps (a state change, not motion).
  const knob = useSpring({ x: on ? 20 : 0, config: { tension: 320, friction: 26 } });

  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      aria-disabled={disabled || undefined}
      disabled={disabled}
      onClick={onChange}
      className={`relative h-6 w-11 shrink-0 rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground ${
        on ? "bg-foreground" : "bg-foreground/15"
      } ${disabled ? "cursor-not-allowed opacity-55" : "cursor-pointer"}`}
    >
      <animated.span
        style={{ transform: knob.x.to((v) => `translateX(${v}px)`) }}
        className="absolute left-[3px] top-[3px] block h-[18px] w-[18px] rounded-full bg-background shadow"
      />
    </button>
  );
};
