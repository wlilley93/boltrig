# Legal drafts (not published, for review)

Drafts prepared 2026-08-22 from the inventory in `docs/IOS-LAUNCH-READINESS.md` section 3,
grounded in what the code does. None of these is published anywhere; each needs the legal entity
and contact details filled in (marked `[...]`) and a lawyer's review before it goes to
`https://boltrig.ai/privacy`, `https://boltrig.ai/terms` and the security page. The app and the
marketing site already link those addresses.

- `PRIVACY-POLICY-DRAFT.md`: what is collected, where it goes, how long it is kept, rights.
- `TERMS-DRAFT.md`: invite-only access, what the agent may do on your behalf, costs, warranty.
- `SUBPROCESSORS-DRAFT.md`: the third parties, their locations and purposes (also the DPA annex).
- `security.txt-draft`: the `/.well-known/security.txt` text once a mailbox exists.

Facts the drafts rely on (each read in the repository on 2026-08-22): deleted conversations are
hard-purged after 30 days by `boltrig/fleet/retention.py`; provider keys are sealed at rest by
`boltrig/store/sealing.py`; attachments are capped at 25 MiB by `boltrig/kernel/web_security.py`;
erasure today is per conversation and per memory, and export is an account summary
(`boltrig/kernel/platform_routes/privacy_policy.py`); the model catalogue lists 196 providers
(`apps/worker/src/components/onboarding/modelsDevCatalogue.json`); hosting is on Hetzner,
fronted by Cloudflare. Where the code does not yet do what a policy must promise (a retention
schedule for everything else, account deletion, a full export), the draft says so in a bracketed
note rather than promising it.
