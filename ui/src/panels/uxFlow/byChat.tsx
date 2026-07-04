/** ByChat (N16, P32): the parity law made visible.
 * Always-visible label per AMENDMENTS item 7. Prefills the chat composer with
 * the phrase (one-shot module store) and moves the deck; never auto-sends.
 */

import { setComposerPrefill } from "@/composerPrefill";
import { navigate } from "@/router";

export function ByChat({ phrase }: { phrase: string }) {
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm ux-bychat"
      title={phrase}
      onClick={() => {
        setComposerPrefill(phrase);
        navigate("/chat");
      }}
    >
      Do this in chat
    </button>
  );
}
