#!/usr/bin/env sh
# Keeps the phone's bundled provider catalogue byte-identical to the web's snapshot.
# The web copy is the source of truth (models.dev, MIT; see THIRD_PARTY_NOTICES.md);
# OnboardingTests pins the revision so a drift fails the build on the M4.
#
# Usage: ios/scripts/sync-provider-catalogue.sh          copies web -> ios
#        ios/scripts/sync-provider-catalogue.sh --check  exits 1 when the copies differ
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
source_file="$repo/apps/worker/src/components/onboarding/modelsDevCatalogue.json"
target_file="$repo/ios/Boltrig/Resources/ProviderCatalogue.json"

if [ ! -f "$source_file" ]; then
  echo "sync-provider-catalogue: missing $source_file" >&2
  exit 2
fi

if [ "${1:-}" = "--check" ]; then
  if cmp -s "$source_file" "$target_file"; then
    echo "provider catalogue: ios copy matches the web snapshot"
    exit 0
  fi
  echo "provider catalogue: ios copy differs from the web snapshot; run $0" >&2
  exit 1
fi

cp "$source_file" "$target_file"
echo "provider catalogue: copied $(wc -c < "$target_file" | tr -d ' ') bytes to ios/Boltrig/Resources/ProviderCatalogue.json"
