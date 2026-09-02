// Characters beyond the ones Boltrig ships.
//
// The registry is an extension point (components/characters.ts), and until this
// file existed it was an extension point nothing could reach: registration was
// a function no plugin could call, on a build no plugin could join. This is the
// join. It is imported once, for its side effects — each module below registers
// itself.
//
// EXPLICIT IMPORTS ONLY, NEVER A DIRECTORY GLOB. Vite emits every matched
// module as a production chunk even when the surrounding branch is DEV-only, so
// a glob would ship every installed companion to every user. One line per
// character you actually want in this build, and a matching dependency in
// package.json.
//
// The public build deliberately adds nothing here: Boltrig ships Familiar and
// Jarvis, and no operator- or developer-owned companion code. A separately
// reviewed private distribution can add explicit imports in its own entrypoint;
// it must not modify this stock module or the public package graph.

export {};
