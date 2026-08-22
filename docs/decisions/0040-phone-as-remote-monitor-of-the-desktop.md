# 0040 - The phone is a remote monitor of the signed desktop

- Status: proposed (Will's direction, 2026-08-22; not yet built)
- Date: 2026-08-22
- Extends: 0027 (browser cloud agent and desktop local agent), 0021 (desktop
  device boundary)

## Context

Decision 0027 fixed two execution contexts: a task started in the browser is a
cloud task; a task started in the signed desktop app is a local task whose
reasoning loop and shell live on that computer. It left one door explicitly
closed for later: "Cross-surface continuation requires an explicit future
import/export contract; it is never inferred."

The iPhone app (`ios/`) is a third surface. As shipped it is a client of the
hosted kernel with the same account: it sees the linked computers
(`GET /v1/devices`), approves for the account, and can disconnect a computer.
It cannot start or watch a local task on that computer. The only server path
that reaches a desktop today is the cloud-issued `device.command.run` lease,
which 0027 keeps deliberately narrow: no shell, output discarded, and an
approval that a different person must give (`boltrig/device_leases.py`
materialises "the sole lease admitted by one consumed, independent approval").
A single-person tenant cannot satisfy that from any surface.

Will's direction (2026-08-22): "the phone is a proxy for the desktop. Maybe it
needs a device lease, but the permissions should be exactly the same, and the
phone is just an extension of the monitor remotely."

## Decision (proposed)

A phone signed in to the same account as an enrolled, running desktop may act
as that desktop's remote monitor:

1. **Same account, same person, same permissions.** What the person can do at
   the desktop's keyboard, they can do from the phone, and nothing more. The
   desktop's own device-side posture (`always_ask`, `risk_based`,
   `full_access`, held in the OS keychain) governs a phone-originated local
   task exactly as it governs a local one. The phone never widens a grant and
   never receives a server or provider secret.
2. **A local task, started remotely.** A task the phone starts against a linked
   desktop is a local task in 0027's sense: the desktop's pinned App Server
   runs it, in a root the person bound on that desktop. It is not a cloud task
   and never falls back to one. Receipts say `local`.
3. **The grant is a signed remote-session lease, not `device.command.run`.**
   The kernel issues a short-lived, revocable lease bound to the account, the
   phone's credential, the device id and the bound root; the desktop verifies
   it like every other lease. Because the approver is the same person at
   the phone, this lease does not require an independent approver; its
   admission is the account's interactive credential plus the desktop's
   device-side posture. The lease carries no command of its own: the commands
   come from the local reasoning loop, approved on the desktop's terms.
4. **Approvals and output reach the phone.** App Server approval requests that
   the desktop would show in its own window are mirrored to the phone for the
   phone-originated task; answers from either surface are equivalent. The
   phone shows the task's receipts and text the same way it shows a cloud
   turn; raw local paths stay opaque ids, as in 0027.
5. **Absence is typed and visible.** A desktop that is off, not enrolled, or
   not running its local agent makes the phone say so; nothing is queued to a
   cloud runtime in its place.

## What this needs, in order

- A kernel contract for the remote-session lease (issue, verify, revoke,
  expiry) and the transport by which the desktop's local agent receives a
  phone-originated task and returns its events (the device agent already
  processes signed leases; the task channel is new).
- Sole-author relief scoped to this lease kind only: the independent-approver
  rule for `device.command.run` is unchanged.
- Phone: a "Work on {computer}" choice when a linked computer is on, the
  approval card for mirrored App Server requests, and receipts that say local.
- A published desktop download address from the kernel so the phone and the
  web stop carrying a build-time constant.

## Not decided here

Whether a lease is needed at all when the phone and the desktop hold the same
account (Will: "maybe"); the lease is proposed because it gives revocation
per phone and a signed verification on the desktop without putting those
powers in the account cookie, the same reasoning 0027 gives for the
per-computer key.
