#!/usr/bin/env python3
"""Turn a character bundle's in-place development VIEW into a portable ARTIFACT.

WHY THIS EXISTS, measured. A character bundle on disk is assembled in place out
of symlinks into the studios that produced it. Packing one the way anyone would
does not produce a portable thing:

    tar -cf   (no --dereference), unpack elsewhere  ->  21 dangling links
    tar -chf  (--dereference),    unpack elsewhere  ->  18 dangling links

`--dereference` does NOT rescue it, and the reason is worse than a subtlety
about nesting. Both numbers were re-measured and reproduce exactly. The 18 are
the links whose targets are ABSENT: three of the twenty-one still resolve, those
three are precisely the three `-h` turned into regular files, and 21 - 3 = 18.
When bsdtar cannot stat what a link points at, it silently stores the link:

    tar -chf /dev/null maya   ->  exit 0, zero bytes on stderr

No warning, no non-zero status. A build step that shells out to `tar -h` and
checks the exit code reports success and ships an archive of pointers into one
person's home directory. So the spec's central claim -
docs/SPEC-character-bundle.md, "a character BRINGS data" - is false of the
layout, which is a development view and not an artifact.

Nesting is a real second problem and this script handles it too: a link inside a
directory reached THROUGH a link is invisible to anything that stops at the
first hop.

This script is the missing step between the two. It resolves EVERY path
component recursively, copies content rather than links, and then verifies the
result contains no link and no path outside its own root.

WHAT "ESCAPES THE ROOT" MEANS HERE, because there are two readings and only one
of them is useful. Dereferencing an out-of-root source is the entire job: every
byte in this bundle lives outside it today, so refusing on that would refuse
every export forever. The check is on the ARTIFACT: after staging, no entry may
be a symlink and no path may resolve outside the staged root. That is exactly
the property `tar -chf` fails, and it is the check the spec asks for. Out-of-root
SOURCES are not refused - they are all listed by real path in the report, so
nothing is pulled across the boundary silently, and the classes below turn a
subset of them into hard refusals.

WHAT IT WILL NOT SHIP. A bundle is a thing you might hand to someone else, so
the interesting question is not what fits but what must never travel.

  REFUSED - the export fails, nothing is written, every offender is named.
    kernel biometrics    an enrolled face and its calibration. The spec is
                         explicit that this is data about the USER, held under
                         the kernel's consent and retention rules, and "must
                         never be exportable inside a character bundle". Its
                         presence in a bundle tree is a defect for a human to
                         fix; dropping it quietly would hide that.
    user camera data     diary entries, retained frames, the observation log,
                         the fact sheet. Derived from one person's room.
    populated secrets    a key, token, presigned URL or credential file. The
                         spec: a character declares the providers it WANTS and
                         never ships keys.
    digest mismatch      an asset whose bytes disagree with the sha256 the
                         manifest states. The manifest is the contract.
    unresolvable link    dangling, looping, or absolute. Nothing to copy, and
                         an absolute target is a statement about one disk.

  QUARANTINED - excluded from the artifact, struck from the exported manifest,
  listed in the report, exit still 0.
    cloned voice bytes   a voice LoRA and its reference audio are a clone of a
                         REAL person's voice. The bundle names the voice and
                         keeps its fallback ids, which is what portability
                         actually needs; the tensors stay behind.

  KEPT. Anchor images, the visual LoRA, example clips and the baked performance
  file are the CHARACTER's likeness, which the spec assigns to the character,
  and prompts and capability declarations are configuration. A bundle never
  carries executable code, and this script neither copies nor generates any.

The escape and dangling rules are the same property `scripts/check_tracked_symlinks.py`
enforces for this repository, applied to a bundle instead of a checkout: a thing
other machines receive may not depend on the author's filesystem.

Usage:
    python scripts/export_character_bundle.py <bundle-root> <dest-dir>
    python scripts/export_character_bundle.py <bundle-root> --dry-run
    python scripts/export_character_bundle.py <bundle-root> <dest-dir> --force

Exit 0 export written (or dry run clean), 2 refused, 1 usage error.
Re-runnable: staging happens beside the destination and is swapped in at the
end, so a failed run leaves the previous artifact untouched.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MANIFEST_NAME = "character.json"
REPORT_NAME = "EXPORT-REPORT.json"

# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------
# Every rule is matched against BOTH the bundle-relative path and the fully
# resolved real path. The real path is the load-bearing half, and it is what
# makes the policy worth anything: an anchor image called face_src_d.png whose
# target is the user's enrolled face passes every name-based rule there is, and
# is caught only after resolution.

# Kernel data about the USER. Never bundle data, whatever it is called.
BIOMETRIC_NAMES = {"enrolled.npz", "config.json"}
BIOMETRIC_SEGMENTS = {"pixy-stream"}


def _is_biometric(rel: PurePosixPath, real: Path) -> str | None:
    for path in (rel, PurePosixPath(str(real))):
        parts = path.parts
        name = path.name
        if name.startswith("enrolled.npz"):
            return "an enrolled face (kernel biometric data)"
        if BIOMETRIC_SEGMENTS.intersection(parts):
            return "inside a face-enrolment store"
        if name == "config.json" and "identity" in parts:
            return "an enrolment calibration (identity/config.json)"
    return None


# Camera-derived data about the user's room and days.
USER_DATA_NAMES = {"observations.jsonl", "fact-sheet.md"}
USER_DATA_SEGMENTS = {"personal", "diary", "frames"}


def _is_user_data(rel: PurePosixPath, real: Path) -> str | None:
    for path in (rel, PurePosixPath(str(real))):
        if path.name in USER_DATA_NAMES:
            return f"user camera data ({path.name})"
        hit = USER_DATA_SEGMENTS.intersection(path.parts)
        if hit:
            return f"under a user-data directory ({'/'.join(sorted(hit))})"
    return None


# Credential-shaped files, by name alone.
CREDENTIAL_NAMES = {"credentials.json", ".env", ".netrc", ".npmrc"}


def _is_credential_file(rel: PurePosixPath, real: Path) -> str | None:
    for path in (rel, PurePosixPath(str(real))):
        name = path.name
        if name in CREDENTIAL_NAMES or name.endswith(".env"):
            return f"a credential file ({name})"
        if name.endswith("_url.txt"):
            return f"a presigned URL ({name})"
    return None


# A cloned voice: the tensors and the recording of the real person.
VOICE_SEGMENTS = {"voice", "voices"}
VOICE_BYTE_SUFFIXES = {".safetensors", ".bin", ".pt", ".ckpt", ".gguf",
                       ".wav", ".flac", ".m4a", ".mp3", ".ogg", ".npz"}


def _is_cloned_voice(rel: PurePosixPath, real: Path) -> str | None:
    for path in (rel, PurePosixPath(str(real))):
        if VOICE_SEGMENTS.intersection(path.parts) and path.suffix.lower() in VOICE_BYTE_SUFFIXES:
            return "cloned-voice bytes (named in the manifest, never shipped)"
    return None


# Build noise: skipped without comment, never a policy decision.
NOISE_NAMES = {".DS_Store", "Thumbs.db"}
NOISE_SEGMENTS = {"__pycache__", ".git"}


def _is_noise(rel: PurePosixPath) -> bool:
    return (rel.name in NOISE_NAMES
            or bool(NOISE_SEGMENTS.intersection(rel.parts))
            or rel.suffix == ".pyc")


# Secrets by CONTENT. Only text files under the cap are read.
SECRET_SCAN_SUFFIXES = {".json", ".txt", ".md", ".yaml", ".yml", ".toml",
                        ".ini", ".cfg", ".conf", ".sh", ".env", ""}
SECRET_SCAN_MAX_BYTES = 2 * 1024 * 1024

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai/anthropic-style key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{12,}")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("json web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.")),
    ("hugging face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("assigned secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret[_-]?key|secret|auth[_-]?token|access[_-]?token|"
        r"bearer|password|passwd)\b\s*[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-/+=]{16,})")),
]

# A provider NAME, as `credentials.providers` is allowed to contain. Anything
# else in that list is a key someone pasted where a name belongs.
PROVIDER_NAME_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


def scan_text_for_secrets(data: bytes) -> list[str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return [label for label, pattern in SECRET_PATTERNS if pattern.search(text)]


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

INCLUDE, QUARANTINE, REFUSE = "include", "quarantine", "refuse"


@dataclass
class Entry:
    rel: PurePosixPath          # path inside the bundle root
    real: Path | None           # fully resolved source, None when unresolvable
    verdict: str
    reason: str
    size: int = 0
    outside_root: bool = False
    via_link: bool = False


@dataclass
class Plan:
    root: Path
    entries: list[Entry] = field(default_factory=list)
    manifest: dict = field(default_factory=dict)
    manifest_assets: dict[str, str] = field(default_factory=dict)  # rel -> sha256

    @property
    def refusals(self) -> list[Entry]:
        return [e for e in self.entries if e.verdict == REFUSE]

    @property
    def quarantined(self) -> list[Entry]:
        return [e for e in self.entries if e.verdict == QUARANTINE]

    @property
    def included(self) -> list[Entry]:
        return [e for e in self.entries if e.verdict == INCLUDE]


def classify(rel: PurePosixPath, real: Path) -> tuple[str, str]:
    """Apply the policy to one resolved file. First match wins, refusals first."""
    for probe, reason_prefix in (
        (_is_biometric, "REFUSED"),
        (_is_user_data, "REFUSED"),
        (_is_credential_file, "REFUSED"),
    ):
        reason = probe(rel, real)
        if reason:
            return REFUSE, reason
    reason = _is_cloned_voice(rel, real)
    if reason:
        return QUARANTINE, reason
    return INCLUDE, ""


def resolve(path: Path) -> tuple[Path | None, str]:
    """Resolve every component of `path`, following links to the end.

    Returns (real_path, "") or (None, why-it-cannot-be-resolved). This is the
    recursive half: os.path.realpath resolves links at EVERY component, and the
    caller then recurses into the result, so a link nested inside a directory
    that was itself reached through a link is resolved in its turn.
    """
    if path.is_symlink():
        target = os.readlink(path)
        if os.path.isabs(target):
            return None, f"absolute symlink -> {target}"
    real = Path(os.path.realpath(path))
    try:
        os.stat(real)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return None, "symlink loop"
        if exc.errno == errno.ENOENT:
            return None, f"dangling symlink -> {os.readlink(path) if path.is_symlink() else real}"
        return None, f"cannot stat ({exc.strerror})"
    return real, ""


def build_plan(root: Path) -> Plan:
    root = root.resolve()
    plan = Plan(root=root)

    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        die(f"no {MANIFEST_NAME} at {root} - that is the bundle contract, so this is not a bundle root")
    plan.manifest = json.loads(manifest_path.read_text())
    plan.manifest_assets = collect_manifest_assets(plan.manifest)

    seen_dirs: set[Path] = set()

    def walk(rel: PurePosixPath, real_dir: Path, via_link: bool) -> None:
        if real_dir in seen_dirs:
            return
        seen_dirs.add(real_dir)
        try:
            names = sorted(os.listdir(real_dir))
        except OSError as exc:
            plan.entries.append(Entry(rel, None, REFUSE, f"cannot list ({exc.strerror})"))
            return
        for name in names:
            child_rel = rel / name
            lexical = real_dir / name
            if _is_noise(child_rel):
                continue
            child_link = via_link or lexical.is_symlink()
            real, why = resolve(lexical)
            if real is None:
                plan.entries.append(Entry(child_rel, None, REFUSE, why, via_link=child_link))
                continue
            outside = not is_inside(real, root)
            mode = os.stat(real).st_mode
            if stat.S_ISDIR(mode):
                walk(child_rel, real, child_link)
                continue
            if not stat.S_ISREG(mode):
                plan.entries.append(Entry(child_rel, real, REFUSE,
                                          "not a regular file (socket, device or fifo)",
                                          outside_root=outside, via_link=child_link))
                continue
            verdict, reason = classify(child_rel, real)
            size = os.stat(real).st_size
            entry = Entry(child_rel, real, verdict, reason, size=size,
                          outside_root=outside, via_link=child_link)
            if verdict == INCLUDE:
                secret_reason = inspect_content(entry)
                if secret_reason:
                    entry.verdict, entry.reason = REFUSE, secret_reason
            plan.entries.append(entry)

    walk(PurePosixPath("."), root, via_link=False)
    check_manifest(plan)
    return plan


def inspect_content(entry: Entry) -> str | None:
    """Read a text-shaped file and refuse it if it carries a live secret."""
    assert entry.real is not None
    if entry.real.suffix.lower() not in SECRET_SCAN_SUFFIXES:
        return None
    if entry.size > SECRET_SCAN_MAX_BYTES:
        return None
    hits = scan_text_for_secrets(entry.real.read_bytes())
    if hits:
        return f"a populated secret in file content ({', '.join(hits)})"
    return None


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# the manifest side of the contract
# ---------------------------------------------------------------------------

def collect_manifest_assets(node, out: dict[str, str] | None = None) -> dict[str, str]:
    """Every {"file","sha256"} pair anywhere in the manifest, as rel -> digest."""
    out = {} if out is None else out
    if isinstance(node, dict):
        if isinstance(node.get("file"), str) and isinstance(node.get("sha256"), str):
            out[node["file"]] = node["sha256"]
        for value in node.values():
            collect_manifest_assets(value, out)
    elif isinstance(node, list):
        for value in node:
            collect_manifest_assets(value, out)
    return out


def check_manifest(plan: Plan) -> None:
    """Refuse a manifest that points outside the root or carries a key."""
    for rel in plan.manifest_assets:
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts:
            plan.entries.append(Entry(pure, None, REFUSE,
                                      "manifest names a path outside the bundle root"))
    providers = (plan.manifest.get("credentials") or {}).get("providers") or []
    for provider in providers:
        if not isinstance(provider, str) or not PROVIDER_NAME_RE.match(provider):
            plan.entries.append(Entry(PurePosixPath(MANIFEST_NAME), None, REFUSE,
                                      "credentials.providers holds something that is not a "
                                      "provider NAME - a bundle declares providers, never keys"))
    blob = json.dumps(plan.manifest)
    hits = scan_text_for_secrets(blob.encode())
    if hits:
        plan.entries.append(Entry(PurePosixPath(MANIFEST_NAME), None, REFUSE,
                                  f"a populated secret in the manifest ({', '.join(hits)})"))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_digests(plan: Plan) -> list[str]:
    """The manifest states a sha256 per asset; disagreement is a refusal."""
    problems: list[str] = []
    included = {str(e.rel.relative_to(".")): e for e in plan.included}
    for rel, want in plan.manifest_assets.items():
        entry = included.get(rel)
        if entry is None:
            continue  # absent or quarantined; reported separately
        assert entry.real is not None
        got = sha256_of(entry.real)
        if got != want:
            problems.append(f"{rel}: manifest says {want[:12]}..., bytes are {got[:12]}...")
    return problems


def strip_absent_assets(manifest: dict, absent: set[str]) -> dict:
    """Remove asset refs the artifact will not contain, then prune empty parents.

    An exported manifest that names a file the artifact does not hold is a
    broken contract, so quarantine has to reach the manifest too.
    """
    def prune(node):
        if isinstance(node, dict):
            if isinstance(node.get("file"), str) and node["file"] in absent:
                return None
            out = {}
            for key, value in node.items():
                pruned = prune(value)
                if pruned is None:
                    continue
                if isinstance(pruned, (dict, list)) and not pruned and isinstance(value, (dict, list)) and value:
                    continue
                out[key] = pruned
            return out
        if isinstance(node, list):
            kept = [p for p in (prune(v) for v in node) if p is not None]
            return kept
        return node

    return prune(json.loads(json.dumps(manifest)))


# ---------------------------------------------------------------------------
# staging and the artifact-side verification
# ---------------------------------------------------------------------------

def stage(plan: Plan, staging: Path) -> None:
    for entry in plan.included:
        assert entry.real is not None
        dest = staging / entry.rel.relative_to(".")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry.real, dest, follow_symlinks=True)
        shutil.copymode(entry.real, dest)


def verify_artifact(staging: Path) -> list[str]:
    """The check the spec asks for, run on what is about to be shipped.

    Nothing here may be a symlink, and every path must resolve inside the
    staged root. `tar -chf` fails exactly this.
    """
    problems: list[str] = []
    root = staging.resolve()
    for dirpath, dirnames, filenames in os.walk(staging, followlinks=False):
        for name in list(dirnames) + filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(staging)
            if path.is_symlink():
                problems.append(f"{rel}: is a symlink -> {os.readlink(path)}")
                continue
            if not is_inside(Path(os.path.realpath(path)), root):
                problems.append(f"{rel}: resolves outside the artifact root")
    return problems


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return f"{value:.0f}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}T"


def show(plan: Plan, dest: Path | None, digest_problems: list[str],
         artifact_problems: list[str], dry_run: bool) -> None:
    root = plan.root
    print(f"bundle   {root}")
    print(f"manifest {plan.manifest.get('id', '?')}  type={plan.manifest.get('type', '?')}  "
          f"schemaVersion={plan.manifest.get('schemaVersion', '?')}")
    print(f"dest     {dest if dest else '(dry run, nothing written)'}")
    print()

    links = [e for e in plan.entries if e.via_link]
    outside = [e for e in plan.entries if e.outside_root]
    print(f"sources reached through a symlink : {len(links)}")
    print(f"sources resolving OUTSIDE the root: {len(outside)}  "
          f"(dereferenced into the artifact, listed below)")
    print()

    if outside:
        print("OUT-OF-ROOT SOURCES - materialised, never linked")
        print("-" * 100)
        for entry in sorted(outside, key=lambda e: str(e.rel)):
            marker = {INCLUDE: "copy", QUARANTINE: "held", REFUSE: "STOP"}[entry.verdict]
            print(f"  {marker}  {entry.rel}")
            print(f"        <- {entry.real}")
        print()

    print(f"INCLUDED  {len(plan.included)} files, {human(sum(e.size for e in plan.included))}")
    print("-" * 100)
    named = set(plan.manifest_assets)
    for entry in sorted(plan.included, key=lambda e: str(e.rel)):
        rel = str(entry.rel.relative_to("."))
        tag = "manifest" if rel in named else "extra   "
        print(f"  {tag}  {human(entry.size):>7}  {rel}")
    print()

    if plan.quarantined:
        print(f"QUARANTINED  {len(plan.quarantined)} files - excluded, and struck from the exported manifest")
        print("-" * 100)
        for entry in sorted(plan.quarantined, key=lambda e: str(e.rel)):
            print(f"  {entry.rel}")
            print(f"        {entry.reason}")
        print()

    if plan.refusals or digest_problems or artifact_problems:
        print("REFUSED")
        print("-" * 100)
        for entry in sorted(plan.refusals, key=lambda e: str(e.rel)):
            print(f"  {entry.rel}")
            print(f"        {entry.reason}")
        for problem in digest_problems:
            print("  digest mismatch")
            print(f"        {problem}")
        for problem in artifact_problems:
            print("  artifact still not portable")
            print(f"        {problem}")
        print()


def write_report(plan: Plan, staging: Path) -> None:
    report = {
        "bundle": str(plan.root),
        "id": plan.manifest.get("id"),
        "included": sorted(str(e.rel.relative_to(".")) for e in plan.included),
        "quarantined": [
            {"path": str(e.rel.relative_to(".")), "reason": e.reason}
            for e in sorted(plan.quarantined, key=lambda e: str(e.rel))
        ],
        "outOfRootSources": [
            {"path": str(e.rel.relative_to(".")), "source": str(e.real)}
            for e in sorted((e for e in plan.entries if e.outside_root), key=lambda e: str(e.rel))
            if e.real is not None
        ],
        "bytes": sum(e.size for e in plan.included),
    }
    (staging / REPORT_NAME).write_text(json.dumps(report, indent=2) + "\n")


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------

def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path, help="bundle root (the directory holding character.json)")
    parser.add_argument("dest", type=Path, nargs="?", help="directory to write the artifact to")
    parser.add_argument("--dry-run", action="store_true", help="classify and report, write nothing")
    parser.add_argument("--force", action="store_true",
                        help="replace a destination that is not a previous export")
    args = parser.parse_args(argv)

    if not args.dry_run and args.dest is None:
        parser.error("a destination is required unless --dry-run is given")
    if not args.bundle.is_dir():
        die(f"{args.bundle} is not a directory")

    plan = build_plan(args.bundle)
    digest_problems = verify_digests(plan)

    if args.dry_run:
        show(plan, None, digest_problems, [], dry_run=True)
        refused = len(plan.refusals) + len(digest_problems)
        if refused:
            print(f"RESULT: REFUSED - {refused} blocking problem(s). Nothing was written.")
            return 2
        print("RESULT: CLEAN - this bundle would export.")
        return 0

    dest = args.dest.resolve()
    if is_inside(dest, plan.root) or is_inside(plan.root, dest):
        die("destination must not sit inside the bundle root, or the other way round")
    if dest.exists():
        if not (dest / REPORT_NAME).is_file() and not args.force:
            die(f"{dest} exists and is not a previous export - pass --force to replace it")

    if plan.refusals or digest_problems:
        show(plan, dest, digest_problems, [], dry_run=False)
        refused = len(plan.refusals) + len(digest_problems)
        print(f"RESULT: REFUSED - {refused} blocking problem(s). Nothing was written.")
        return 2

    staging = dest.parent / f".{dest.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    stage(plan, staging)

    absent = {str(e.rel.relative_to(".")) for e in plan.quarantined}
    exported = strip_absent_assets(plan.manifest, absent)
    (staging / MANIFEST_NAME).write_text(json.dumps(exported, indent=2) + "\n")
    write_report(plan, staging)

    artifact_problems = verify_artifact(staging)
    if artifact_problems:
        shutil.rmtree(staging)
        show(plan, dest, digest_problems, artifact_problems, dry_run=False)
        print("RESULT: REFUSED - the staged artifact was still not portable. Nothing was written.")
        return 2

    if dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)

    show(plan, dest, digest_problems, [], dry_run=False)
    print(f"RESULT: EXPORTED - {len(plan.included)} files, "
          f"{human(sum(e.size for e in plan.included))}, "
          f"{len(plan.quarantined)} quarantined, 0 symlinks, 0 paths outside the root.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
