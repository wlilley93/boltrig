import type { ReactNode } from "react";

import type { CompanionChoice } from "./companionCatalogue";

/**
 * One companion at a time, with chevrons to walk between them.
 *
 * NOT A CYCLE, and the chevrons say so. There is no left chevron on the first
 * companion and no right chevron on the last -- they are ABSENT rather than
 * disabled, because a greyed-out control still says "there is something that
 * way, but not for you", and here there is simply nothing that way. A rail that
 * wrapped would also make the dots lie about where you are in a short list.
 *
 * ACCESSIBILITY LIVES ON THE DOTS. The big card shows one companion, so a
 * screen-reader user walking the card alone would never learn the others exist.
 * The dots are the real control: a radiogroup carrying every companion by name,
 * arrow-navigable, with the card as its visible expression. That is why the
 * card itself is not a button -- two overlapping controls for one choice is
 * worse for everyone than one control and a picture.
 */
export function CompanionCarousel({
  items,
  index,
  onIndex,
  art,
  footer,
}: {
  items: readonly CompanionChoice[];
  index: number;
  onIndex: (next: number) => void;
  /** The stage for the active companion. */
  art: ReactNode;
  /** Optional controls under the art -- the skin pills, when there are skins. */
  footer?: ReactNode;
}) {
  const active = items[index];
  if (!active) return null;
  const first = index === 0;
  const last = index === items.length - 1;

  const step = (delta: number) => {
    const next = index + delta;
    // Clamped, not wrapped: walking off the end of a two-item rail and landing
    // back at the start is disorienting in a way it never is in a long carousel.
    if (next >= 0 && next < items.length) onIndex(next);
  };

  return (
    <div className="companion-rail">
      <div className="companion-viewport">
        {!first && (
          <button
            aria-label={`Show ${items[index - 1]?.name}`}
            className="companion-chevron left"
            onClick={() => step(-1)}
            type="button"
          >
            <Chevron direction="left" />
          </button>
        )}

        <article className="companion-card" data-companion={active.id}>
          <span className="companion-art" aria-hidden="true">{art}</span>
          <div className="companion-copy">
            <strong>{active.name}</strong>
            <span>{active.blurb}</span>
            <small>{active.note}</small>
            {footer}
          </div>
        </article>

        {!last && (
          <button
            aria-label={`Show ${items[index + 1]?.name}`}
            className="companion-chevron right"
            onClick={() => step(1)}
            type="button"
          >
            <Chevron direction="right" />
          </button>
        )}
      </div>

      <CompanionDots items={items} index={index} onIndex={onIndex} step={step} />
    </div>
  );
}

/**
 * The rail's real control. The card shows one companion, so walking the card
 * alone would never reveal the others exist; this is a radiogroup carrying
 * every companion by name, arrow-navigable, and the card is its visible
 * expression.
 */
function CompanionDots({
  items,
  index,
  onIndex,
  step,
}: {
  items: readonly CompanionChoice[];
  index: number;
  onIndex: (next: number) => void;
  step: (delta: number) => void;
}) {
  return (
    <div
      aria-label="Companion"
      className="companion-dots"
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          event.preventDefault();
          step(-1);
        } else if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          event.preventDefault();
          step(1);
        }
      }}
      role="radiogroup"
    >
      {items.map((choice, i) => (
        <button
          aria-checked={i === index}
          className={`companion-dot${i === index ? " active" : ""}`}
          key={choice.id}
          onClick={() => onIndex(i)}
          role="radio"
          tabIndex={i === index ? 0 : -1}
          type="button"
        >
          <span className="onboarding-visually-hidden">{choice.name}</span>
        </button>
      ))}
    </div>
  );
}

function Chevron({ direction }: { direction: "left" | "right" }) {
  // Drawn rather than typed: a "‹" is a font's opinion about weight and
  // position, and it lands off-centre in the circle at most sizes.
  const d = direction === "left" ? "M14.5 5 8 12l6.5 7" : "M9.5 5 16 12l-6.5 7";
  return (
    <svg aria-hidden="true" fill="none" height="24" viewBox="0 0 24 24" width="24">
      <path d={d} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
    </svg>
  );
}
