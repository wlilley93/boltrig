// The one definition of "the source tree this evidence describes".
//
// It lived twice — once in capture-current.mjs, which WRITES the digest into the
// receipt, and once in manifest.test.ts, which recomputes it to check the receipt
// still describes the tree. Two copies of a hashing scheme are two things free to
// drift, and the drifted state is the dangerous one: the test would go green about
// a rule the capture no longer follows. One module, imported by both.
//
// WHAT COUNTS, and why it is the git INDEX rather than the filesystem.
//
// This used to walk the directory, so every untracked file on disk changed the
// digest. That made the binding unusable in two directions at once:
//
//   - Unrelated work in progress under apps/worker/src invalidated a receipt that
//     was still perfectly accurate about the source, and blocked the push until
//     someone re-captured to say nothing.
//   - It could never agree with CI anyway. CI checks out refs/pull/N/merge — a
//     clean tree with no untracked files in it — so a digest that counted them was
//     describing a tree that existed on exactly one machine.
//
// The index is the honest line. `git add` is the moment a file becomes part of the
// source rather than somebody's scratch: a staged new file counts, an untracked one
// does not, and an uncommitted EDIT to a tracked file still counts because its
// content is read from the working tree. So the digest answers "what would this
// commit contain", which is the question the evidence is making a claim about.
//
// A new component that has not been `git add`ed is therefore invisible here. That
// is deliberate and it is the same blindness CI has; the alternative was a check
// that is precise about a tree nobody else can reproduce.

import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { lstat, readFile, readlink } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

/** The directories whose contents the capture is bound to. */
export const SOURCE_SCOPE = ["apps/worker/src", "apps/worker/tests/visual"];

/**
 * Paths git knows about under `scopes`, repo-relative and sorted.
 *
 * `-z` because a filename may contain a newline; git would otherwise quote it and
 * the split would be wrong for exactly the file most likely to be adversarial.
 * Deleted-but-staged entries are skipped rather than failing the read: the index
 * lists them, the working tree does not have them, and a digest is not the right
 * place to complain about that.
 */
async function indexedPaths(repoRoot, scopes) {
  const { stdout } = await execFileAsync(
    "git", ["ls-files", "-z", "--", ...scopes], { cwd: repoRoot, maxBuffer: 64 * 1024 * 1024 },
  );
  return stdout.split("\0").filter(Boolean).sort();
}

/**
 * sha256 over every indexed path in scope and its CURRENT contents.
 *
 * The framing bytes (`path\0`, then `file\0…\0` or `symlink\0target\0`) are
 * unchanged from the original filesystem walk, so only the membership rule moved.
 */
export async function sourceTreeDigest(repoRoot, scopes = SOURCE_SCOPE) {
  const digest = createHash("sha256");
  for (const relativePath of await indexedPaths(repoRoot, scopes)) {
    const absolute = join(repoRoot, relativePath.split("/").join(sep));
    let metadata;
    try {
      metadata = await lstat(absolute);
    } catch {
      continue;   // staged deletion: in the index, gone from disk
    }
    digest.update(`${relative(repoRoot, absolute).split(sep).join("/")}\0`);
    if (metadata.isSymbolicLink()) {
      digest.update(`symlink\0${await readlink(absolute)}\0`);
    } else {
      digest.update("file\0");
      digest.update(await readFile(absolute));
      digest.update("\0");
    }
  }
  return digest.digest("hex");
}
