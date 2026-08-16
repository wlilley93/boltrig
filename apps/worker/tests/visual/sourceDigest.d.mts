export const SOURCE_SCOPE: string[];

export function sourceTreeDigest(
  repoRoot: string,
  scopes?: readonly string[],
): Promise<string>;
