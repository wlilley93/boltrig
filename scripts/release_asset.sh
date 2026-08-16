#!/usr/bin/env bash
# Upload an immutable release asset once, or reuse an existing exact/verified one.
# Never deletes or replaces release evidence.

set -euo pipefail

mode="${1:-}"
local_asset="${2:-}"
image_ref="${3:-}"

case "$mode" in
  exact|cyclonedx|provenance) ;;
  *) echo "usage: $0 {exact|cyclonedx|provenance} FILE [IMAGE@sha256]" >&2; exit 2 ;;
esac

for name in GITHUB_REPOSITORY RELEASE_ID RELEASE_TAG; do
  if [ -z "${!name:-}" ]; then
    echo "required release identity $name is missing" >&2
    exit 1
  fi
done
if [ ! -f "$local_asset" ]; then
  echo "release asset does not exist: $local_asset" >&2
  exit 1
fi
if [ "$mode" != exact ]; then
  for name in RELEASE_COMMIT CERTIFICATE_IDENTITY CERTIFICATE_ISSUER; do
    if [ -z "${!name:-}" ]; then
      echo "required evidence identity $name is missing" >&2
      exit 1
    fi
  done
  if [[ ! "$image_ref" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]]; then
    echo "semantic evidence requires one immutable GHCR image digest" >&2
    exit 1
  fi
fi

asset_name="$(basename -- "$local_asset")"
case "$asset_name" in
  ""|.|..|*/*) echo "invalid release asset name" >&2; exit 1 ;;
esac

work_dir="$(mktemp -d)"
release_json="$work_dir/release.json"
downloaded="$work_dir/$asset_name"
verified="$work_dir/verified-attestations.json"
cleanup() {
  rm -f "$release_json" "$downloaded" "$verified"
  rmdir "$work_dir"
}
trap cleanup EXIT

load_release() {
  gh api "/repos/$GITHUB_REPOSITORY/releases/$RELEASE_ID" > "$release_json"
  if ! jq -e --arg tag "$RELEASE_TAG" \
    '.draft == true and .tag_name == $tag' "$release_json" >/dev/null; then
    echo "release $RELEASE_ID is not the expected unpublished draft $RELEASE_TAG" >&2
    exit 1
  fi
}

asset_id() {
  local count
  count="$(jq --arg name "$asset_name" \
    '[.assets[]? | select(.name == $name)] | length' "$release_json")"
  if [ "$count" -gt 1 ]; then
    echo "draft contains duplicate immutable assets named $asset_name" >&2
    exit 1
  fi
  jq -r --arg name "$asset_name" \
    '[.assets[]? | select(.name == $name) | .id] | .[0] // empty' "$release_json"
}

download_asset() {
  local id="$1"
  gh api -H 'Accept: application/octet-stream' \
    "/repos/$GITHUB_REPOSITORY/releases/assets/$id" > "$downloaded"
}

verify_cyclonedx() {
  local candidate="$1"
  local digest="${image_ref##*@sha256:}"
  jq -e '
    .bomFormat == "CycloneDX"
    and (.specVersion | type == "string" and length > 0)
    and (.version | type == "number")
  ' "$candidate" >/dev/null
  cosign verify-attestation \
    --type cyclonedx \
    --output json \
    --certificate-identity "$CERTIFICATE_IDENTITY" \
    --certificate-oidc-issuer "$CERTIFICATE_ISSUER" \
    --certificate-github-workflow-repository "$GITHUB_REPOSITORY" \
    --certificate-github-workflow-ref "refs/tags/$RELEASE_TAG" \
    --certificate-github-workflow-sha "$RELEASE_COMMIT" \
    "$image_ref" > "$verified"
  if ! jq -e -s --slurpfile asset "$candidate" --arg digest "$digest" '
    [
      .[]
      | if type == "array" then .[] else . end
      | select(.payload | type == "string")
      | (.payload | @base64d | fromjson)
      | select(any(.subject[]?; .digest.sha256 == $digest))
      | .predicate
    ]
    | any(. == $asset[0])
  ' "$verified" >/dev/null; then
    echo "$asset_name is not the predicate of a trusted attestation for $image_ref" >&2
    exit 1
  fi
}

verify_provenance() {
  local candidate="$1"
  jq -e 'type == "object"' "$candidate" >/dev/null
  gh attestation verify "oci://$image_ref" \
    --repo "$GITHUB_REPOSITORY" \
    --bundle "$candidate" \
    --signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml" \
    --source-digest "$RELEASE_COMMIT" \
    --source-ref "refs/tags/$RELEASE_TAG" \
    --predicate-type 'https://slsa.dev/provenance/v1' >/dev/null
}

verify_asset() {
  local candidate="$1"
  case "$mode" in
    exact)
      if ! cmp -s "$local_asset" "$candidate"; then
        echo "immutable release asset $asset_name differs from this run" >&2
        exit 1
      fi
      ;;
    cyclonedx) verify_cyclonedx "$candidate" ;;
    provenance) verify_provenance "$candidate" ;;
  esac
}

# A generated predicate or bundle may contain timestamps, so byte equality is
# not meaningful. Prove both the new and any existing evidence against the
# exact subject and workflow identity instead.
if [ "$mode" != exact ]; then
  verify_asset "$local_asset"
fi

load_release
id="$(asset_id)"
if [ -z "$id" ]; then
  # Do not use --clobber: a network error after a successful upload is resolved
  # by readback below, while an unrelated error remains a refusal.
  gh release upload "$RELEASE_TAG" "$local_asset" \
    --repo "$GITHUB_REPOSITORY" || true
  load_release
  id="$(asset_id)"
  if [ -z "$id" ]; then
    echo "immutable release asset $asset_name was not uploaded" >&2
    exit 1
  fi
fi

download_asset "$id"
verify_asset "$downloaded"
echo "reused immutable release asset $asset_name"
