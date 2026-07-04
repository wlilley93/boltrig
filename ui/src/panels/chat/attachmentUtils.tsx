import type { ChatAttachment } from "@/api/types";

function isTextAttachment(mediaType: string): boolean {
  return (mediaType || "").toLowerCase().startsWith("text/");
}

// Base64-encode raw bytes in chunks: btoa over one huge binary string can blow
// the call stack on a large file.
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function decodeTextAttachment(data: string): string {
  try {
    const bin = atob(data);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return "";
  }
}

export function encodeFile(file: File): Promise<ChatAttachment> {
  return file.arrayBuffer().then((buf) => ({
    name: file.name || "attachment",
    media_type: file.type || "application/octet-stream",
    data: bytesToBase64(new Uint8Array(buf)),
    size: file.size,
  }));
}

export function isTextAttachmentType(mediaType: string): boolean {
  return isTextAttachment(mediaType);
}

export function decodeAttachmentText(data: string): string {
  return decodeTextAttachment(data);
}

export { formatBytes } from "@/panels/chat/formatting";
