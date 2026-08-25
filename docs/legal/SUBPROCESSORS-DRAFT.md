# Boltrig subprocessors (DRAFT, 2026-08-22)

| Subprocessor | Location | Purpose | Data |
| --- | --- | --- | --- |
| The AI provider the account holder connects (one of 196 in the catalogue) | chosen by the account holder; may be outside the UK | generating replies and carrying out tasks | messages, text attachments, assembled context |
| Hetzner Online GmbH | Germany, Finland | hosting the service and its databases | all service data at rest |
| Cloudflare, Inc. | global edge; UK and EU points of presence | DNS, TLS termination, connection handling | connection metadata, content in transit at the edge |
| [Transactional email provider] | [location] | password reset and sign-in emails | email address, reset links |
| Channels the account holder connects (Slack, WhatsApp, Telegram, email) | per provider | delivering messages the account holder routes there | the routed messages |
| Apple (App Store, TestFlight) | worldwide | distributing the iPhone app; no service data | none beyond Apple's own |

Transfers outside the UK rely on the UK Extension to the EU-US Data Privacy Framework where the
provider is certified, otherwise on the UK IDTA or the Addendum to the EU SCCs. Where the account
holder chooses a provider in a country without adequacy, that choice is the account holder's.
