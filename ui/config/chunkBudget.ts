export const MAX_JS_CHUNK_BYTES = 500_000;

interface BundleOutput {
  type: string;
  fileName: string;
  code?: string;
}

export interface OversizedChunk {
  fileName: string;
  bytes: number;
}

/** Return emitted JavaScript chunks whose UTF-8 size exceeds the hard budget. */
export function oversizedChunks(
  bundle: Record<string, BundleOutput>,
  limit = MAX_JS_CHUNK_BYTES,
): OversizedChunk[] {
  return Object.values(bundle).flatMap((output) => {
    if (output.type !== "chunk" || typeof output.code !== "string") return [];
    const bytes = Buffer.byteLength(output.code, "utf8");
    return bytes > limit ? [{ fileName: output.fileName, bytes }] : [];
  });
}
