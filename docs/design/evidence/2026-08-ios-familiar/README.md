# iPhone Familiar presence, simulator captures

Captured 2026-08-22 on the M4 (Xcode 26.6, iPhone 17 simulator) from the debug preview
workspace (`-boltrigPreview`), with the Familiar island page bundled (see
`ios/Boltrig/Resources/FamiliarIsland/familiar-island.manifest.json` for the shader sha and
source commit). The island renders the real shader inside the presence view; when the page is
missing or reports no WebGL, the SwiftUI badge shows instead.

- `chat-hero-light.png`: empty Chat, hero presentation (220 pt).
- `chat-conversation-light.png`: Chat with messages, conversation presentation (96 pt).
- `today-light.png`, `today-dark.png`: Today header presence (64 pt) and the badge in rows.
