import { useEffect, useState } from "react";

import { currentProductName, subscribeProductName } from "../productName";

/**
 * The product's name in the brand face.
 *
 * The FACE never changes: "Opbox Agents" and "Boltrig" are the same wordmark
 * in the same typeface beside the same mark, because they are the same
 * product. Only the word differs, and which word is the kernel's answer rather
 * than this bundle's (see ../productName).
 *
 * This SUBSCRIBES and never fetches. bootstrapProductName() in main.tsx asks
 * once per page load, so mounting a wordmark costs nothing.
 */
export function BrandWordmark({ className = "" }: { className?: string }) {
  const [name, setName] = useState(currentProductName);
  useEffect(() => subscribeProductName(setName), []);
  return <span className={`boltrig-wordmark ${className}`.trim()}>{name}</span>;
}
