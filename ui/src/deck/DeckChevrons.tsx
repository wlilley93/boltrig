import { navigate } from "@/router";
import { CHEVRON_PATH, navTarget, type DeckRow, type Dir } from "@/deck/types";

interface DeckChevronsProps {
  rows: DeckRow[];
  activeKey: string;
}

export function DeckChevrons({ rows, activeKey }: DeckChevronsProps) {
  return (
    <>
      {(["left", "right", "up", "down"] as Dir[]).map((dir) => {
        const t = navTarget(rows, activeKey, dir);
        if (!t) return null;
        return (
          <button
            key={dir}
            type="button"
            className={`deck__chevron deck__chevron--${dir}`}
            aria-label={`${t.label} (${dir})`}
            title={`${t.label} (${dir})`}
            onClick={() => navigate(t.path)}
          >
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d={CHEVRON_PATH[dir]} />
            </svg>
          </button>
        );
      })}
    </>
  );
}
