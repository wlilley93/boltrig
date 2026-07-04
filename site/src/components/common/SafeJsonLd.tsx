import React from "react";

/**
 * Serialize structured data as JSON-LD and escape closing script tags so a
 * dynamic value cannot break out of the script block. The value is JSON-
 * stringified, then `</script>` is escaped to `\\u003c/script>`.
 */
export function SafeJsonLd({ data }: { data: unknown }) {
  const json = JSON.stringify(data).replace(/</g, "\\u003c");
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: json }}
    />
  );
}
