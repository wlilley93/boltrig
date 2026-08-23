# iPhone Familiar presence, simulator captures

Captured 2026-08-22 on the M4 (Xcode 26.6, iPhone 17 simulator) from the debug preview
workspace (`-boltrigPreview`), with the Familiar island page bundled (see
`ios/Boltrig/Resources/FamiliarIsland/familiar-island.manifest.json` for the shader sha and
source commit). The island renders the real shader inside the presence view; when the page is
missing or reports no WebGL, the SwiftUI badge shows instead.

- `chat-hero-light.png`: empty Chat, hero presentation (220 pt).
- `chat-conversation-light.png`: Chat with messages, conversation presentation (96 pt).
- `today-light.png`, `today-dark.png`: Today header presence (64 pt) and the badge in rows.
- `chat-composer-attach-light.png`: empty Chat with the composer's add button (photos and files);
  the island is live in the hero presentation.

Budgets measured the same day on the simulator (unified log, `ai.boltrig.app` subsystem):
page 163,384 bytes; `ready` 1.0 s after the load began; hero 59 to 60 fps; conversation 30 fps;
0 frames while another app is in front; 1 fps with Reduce Motion on; the WebContent process
holds 20.6 MB; one phenotype reading every 3 s while a surface holds the presence.

Setup captures (2026-08-22, later), from the stub preview (`-boltrigOnboarding -boltrigStep
name|provider|vision|ready`): `setup-name-light.png`, `setup-provider-light.png`,
`setup-vision-light.png`, `setup-ready-light.png` (the Ready step carries the live island).
