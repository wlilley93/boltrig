# 0002 - Nankle consolidation: conditioned standalone (VJS County Court)

Status: in force
Order: [2026] VJS-CC NANKLE-CONSOLIDATION 001
Court: Vibe Justice System, County Court (First Instance, District Judge Atkin)
Filed: SUBMISSION-2026-06-28-nankle-consolidation (digest sha256:fe57060...b681331)

## Context

Nankle implements the same chokepoint + noun/verb + capability + audit doctrine
that the estate already implements in Rust (agent-kernel-doctrine, the Opbox
kernel) and elsewhere (Phoenix, Hermes). The consolidation-over-fragmentation
principle raised a genuine, first-impression question: may a fourth conforming
implementation persist as its own repository, or must it be folded in? Per the
governance model this fork went to the court, not to the Principal.

## Ruling

**Conditioned standalone.** Nankle may persist as its own, independently-cloneable
repository. The single-source precedents (VJS-PC 10/19; ACT-CONSOLIDATION-FRAMEWORK
ss.20-21) govern unity of *law*, not the coexistence of conforming *code*
implementations of one doctrine; they were distinguished, not extended. The
doctrine's own "Building a new kernel" chapter and its several standalone exemplars
(Agent libOS, Opbox, Hermes, VJS) show multiplicity is doctrine-as-designed. The
consolidation principle's legitimate core (one source of doctrine, no silent
parallel, controlled drift) binds as conditions.

## The binding conditions (and how this repo satisfies them)

| # | Directive | Compliance in this repo |
| --- | --- | --- |
| D1 | Declare agent-kernel-doctrine the sole source of K-1..K-30; author no doctrine here | README "Governance" section; ARCHITECTURE doctrine-source note |
| D2 | Key every K-* invariant to the doctrine's Appendix A | Note atop `tests/invariants.yaml`; canonical-source note in `docs/invariants.md` |
| D3 | Keep the K-29/K-30 gate at debt 0 in required CI | `.github/workflows/ci.yml` runs `check_invariants.py` + pytest + UI build |
| D4 | Track (never compete with) the doctrine's unified capability primitive | ARCHITECTURE note on `nankle/models/grants.py`; tracked obligation |
| D5 | Stay severable; kernel + models import nothing from sibling kernels | `tests/security/test_severability.py` enforces it (build-red on coupling) |
| D6 | Be named in agent-kernel-doctrine as the Python/FastAPI reference exemplar; keep decision 0001 | Cross-link added to the doctrine README; `0001-greenfield-build.md` retained |
| D7 | No forked codebase; difference between installs is config (P7) | Manifest-driven; one image, config-only variation |

Breach of any condition converts the licence and routes Nankle to governed-subtree
consolidation under `agent-kernel-doctrine/reference-implementations/python-fastapi/nankle/`.

The full order and opinion live in the VJS register:
`.vjs/court/orders/2026-VJS-CC-NANKLE-CONSOLIDATION-001.yaml` (+ `-opinion.md`).
