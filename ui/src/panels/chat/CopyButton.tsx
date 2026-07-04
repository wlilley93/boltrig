import { useState } from "react";

import { Icon } from "@/panels/chat/icons";
import { copyText } from "@/panels/chat/text";

interface CopyButtonProps {
  text: string;
  label?: string;
  className?: string;
  iconOnly?: boolean;
}

export function CopyButton({
  text,
  label = "Copy",
  className = "btn btn--ghost btn--sm",
  iconOnly = false,
}: CopyButtonProps): JSX.Element {
  const [copied, setCopied] = useState(false);

  async function copy() {
    const ok = await copyText(text);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <button
      type="button"
      className={iconOnly ? `${className} chat-msg__action--icon` : className}
      aria-label={copied ? "Copied" : label}
      style={iconOnly ? { width: 26, height: 26 } : undefined}
      onClick={() => void copy()}
    >
      {iconOnly ? <Icon name="copy" size={16} /> : copied ? "Copied" : label}
    </button>
  );
}

export { type CopyButtonProps };
