#!/usr/bin/env bash
# Is the gate on the default branch actually green, right now?
#
# Written because four commits went onto a red `main` in ninety minutes without
# anyone noticing. Branch protection was ON the whole time; it just carries
# `enforce_admins: false` ([2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001, Order 3),
# so each push printed
#
#   remote: Bypassed rule violations for refs/heads/main:
#   remote: - 2 of 2 required status checks are expected.
#
# and went through. That message reads like routine chatter about checks not
# having finished yet. It is not. It is the gate reporting that it was overruled,
# and it is the ONLY notice you get.
#
# So this exists to ask the question directly instead of inferring it from a line
# that looks like noise. Run it after pushing, or before starting work on top of
# someone else's push.
#
# Usage:  gate-status.sh [ref]        (default: origin/HEAD's branch, else main)
#
# Exit 0 only when every workflow's latest completed run on that ref succeeded.

set -uo pipefail

BRANCH="${1:-}"
if [ -z "$BRANCH" ]; then
    BRANCH="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')"
    BRANCH="${BRANCH:-main}"
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "gate-status: gh CLI not available; cannot ask the remote" >&2
    exit 2
fi

sha="$(git rev-parse "origin/${BRANCH}" 2>/dev/null || true)"
if [ -z "$sha" ]; then
    echo "gate-status: no origin/${BRANCH}; run git fetch first" >&2
    exit 2
fi
short="${sha:0:8}"

# The LATEST completed run per workflow for that exact sha. Latest matters: a
# re-run turns a red commit green, and only the most recent verdict is the
# standing one.
#
# TWO CORRECTIONS, 2026-07-27, both of which had this script lying in a way that
# is worse than not having it:
#
#   1. It grouped by `.name`, the run's DISPLAY TITLE, not by workflow. For the
#      push-triggered gate those coincide, so it looked right. For Dependabot they
#      do not: every update job is titled "docker in /. - Update #1487545158", so
#      each became its own "workflow" row and any failed dependency job printed
#      GATE RED on a commit whose ci and security runs were both green. Observed
#      exactly that on main@c35c233d.
#
#   2. Dependabot runs are not a verdict about the commit at all. A dependency
#      updater failing to resolve a version says nothing about whether the tree
#      is sound, and a gate that cannot tell those apart teaches you to ignore it
#      - which is precisely the failure this script was written to prevent, since
#      the whole point is to notice a red main that a bypass message hid.
#
# So: filter to `push` (the event branch protection gates) and group by
# workflowName. A workflow_dispatch re-run keeps its original `push` event, so
# re-runs are still counted.
rows="$(gh run list --limit 40 \
        --json workflowName,event,status,conclusion,headSha,createdAt \
        --jq "[.[] | select(.headSha == \"$sha\")
                   | select(.event == \"push\")
                   | select(.status == \"completed\")]
              | group_by(.workflowName)
              | map(sort_by(.createdAt) | last)
              | .[] | \"\(.conclusion)\t\(.workflowName)\"" 2>/dev/null || true)"

if [ -z "$rows" ]; then
    # No verdict is NOT a pass. A commit whose checks never ran, or were
    # cancelled, carries no evidence, and treating "nothing red" as "green" is
    # exactly the confusion this script exists to remove.
    echo "gate-status: ${BRANCH}@${short} has NO completed run - unproven, not green"
    exit 1
fi

fail=0
echo "gate-status: ${BRANCH}@${short}"
while IFS=$'\t' read -r conclusion name; do
    [ -z "$name" ] && continue
    printf '  %-10s %s\n' "$conclusion" "$name"
    [ "$conclusion" = "success" ] || fail=1
done <<< "$rows"

if [ "$fail" -ne 0 ]; then
    echo "GATE RED on ${BRANCH}. Do not push over it: fix it, or find out who is."
    exit 1
fi
echo "GATE GREEN on ${BRANCH}"
