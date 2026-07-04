import type { ReactNode } from "react";

import { greetingFor, whenText } from "@/panels/chat/formatting";

export { greetingFor, whenText };

export function toolLabel(verb: string): string {
  const clean = verb.replace(/^control\./, "").replace(/\./g, " ");
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

export function copyText(text: string): Promise<boolean> {
  return new Promise((resolve) => {
    void (async () => {
      try {
        if (navigator.clipboard) {
          await navigator.clipboard.writeText(text);
          resolve(true);
          return;
        }
      } catch {
        /* fall through to the textarea fallback */
      }
      try {
        const el = document.createElement("textarea");
        el.value = text;
        el.setAttribute("readonly", "true");
        el.style.position = "fixed";
        el.style.left = "-9999px";
        document.body.appendChild(el);
        el.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(el);
        resolve(ok);
      } catch {
        resolve(false);
      }
    })();
  });
}

export function withChildren(node: ReactNode, children: ReactNode): ReactNode {
  return (
    <>
      {node}
      {children}
    </>
  );
}
