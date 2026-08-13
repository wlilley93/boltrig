import type { ChatAttachment } from "@wlilley93/boltrig-web-sdk";

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

export function downloadAttachment(attachment: ChatAttachment) {
  try {
    const raw = atob(attachment.data);
    const bytes = Uint8Array.from(raw, (character) => character.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], {
      type: attachment.media_type || "application/octet-stream",
    }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = attachment.name || "attachment";
    anchor.click();
    URL.revokeObjectURL(url);
  } catch {
    // Persisted metadata can outlive an unavailable/corrupt inline payload.
    // The message remains readable; never navigate to attacker-controlled data.
  }
}

export function attachmentIdentity(attachment: ChatAttachment): string {
  return [
    attachment.name,
    attachment.media_type,
    attachment.size ?? "",
    attachment.data,
  ].join("\u0000");
}

export function formatBytes(value: number): string {
  if (value < 1_024) return `${value} B`;
  if (value < 1_048_576) return `${Math.ceil(value / 1_024)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}

export function modelReadable(mediaType: string, patterns: string[]): boolean {
  const normalized = mediaType.toLowerCase();
  return patterns.some((pattern) => (
    pattern.endsWith("/*")
      ? normalized.startsWith(pattern.slice(0, -1).toLowerCase())
      : normalized === pattern.toLowerCase()
  ));
}
