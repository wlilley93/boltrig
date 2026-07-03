# Boltrig positioning and landing-page copy (hardened, ship-ready)

**Final hero headline:** Run AI agents in production. Prove every move they make.

**Final positioning statement:** For engineering and security leaders who need to
run autonomous AI agents on real production systems and data, Boltrig is a
self-hosted, governed agent-orchestration platform that routes every agent action
through one audited, permissioned checkpoint the agents cannot bypass, and keeps a
tamper-evident record of all of it. Unlike DIY agent frameworks, which leave
governance as hand-built homework, and unlike closed AI platforms, which run your
agents and your data on someone else's cloud, Boltrig is governed by construction
and runs entirely on your own infrastructure, with every guarantee pinned to a
machine-checked test.

This document is the shipped source of truth for the boltrig.io copy. Every
capability claim is grounded in `README.md`, `docs/ARCHITECTURE.md`,
`docs/invariants.md`, the site `features.ts`, and `docs/first-party-login.md`. No
customer names, logos, testimonials, counts, benchmarks, or third-party
attestations appear here, because none exist yet. Nothing is invented to fill a
gap; where there is no verifiable fact, there is no claim.

Style rule honoured throughout: no em dashes or en dashes anywhere. Spaced
hyphens, commas, colons, and parentheses only.

---

## 0. What Boltrig actually is (ground truth, so the copy stays honest)

Boltrig is a self-hostable, governed agent-orchestration kernel plus a standing
agent fleet and a React console. The load-bearing, tested core:

- **One dispatch chokepoint.** Every external action funnels through a single
  ordered path (`kernel/dispatch.py`): resolve, schema-validate, grant-check,
  HITL gate, rate-limit, idempotency, in-kernel credential resolution, execute,
  output-validate, audit. There is no side door.
- **A tamper-evident audit.** Every action writes exactly one append-only,
  hash-chained record regardless of outcome (denials included).
- **Deny-by-default least privilege.** Caller grants intersect a tenant ceiling,
  deny-dominant, fail-closed, re-checked on every call.
- **A human-in-the-loop gate that cannot be bypassed** on high-consequence verbs.
- **Kernel-held credentials.** Secrets resolve inside the chokepoint at the moment
  of use; agents never see a key.
- **Policy-as-data / config-as-data.** One image, many tenants; everything
  org-specific is a manifest plus env. Adding an integration is data, not a core
  edit.
- **Multi-tenancy.** `tenant_id` on every table, designed for FORCE ROW LEVEL
  SECURITY, tenant isolation enforced.
- **A permanent fleet that spawns ephemerals.** A Chief of Staff over department
  heads takes work in and spawns short-lived workers, picking the cheapest capable
  runtime, reserving budget first, enforcing recursion depth.
- **Sensitive-to-local model routing.** Sensitive data is blocked from non-local
  endpoints and any misroute is audited.
- **Guarantees pinned to CI.** Every governance claim maps to a machine-checked
  test; a binding-invariant gate runs at debt 0.
- **Open at the edges.** MCP in and out: expose granted capabilities to outside
  agents with the full chokepoint applied, and plug external tool servers in as
  new capabilities (inert until reviewed).
- **First-party invite-only auth or enterprise OIDC SSO.** No self-signup.

Be honest about the seams (do not market these as live): a running Hatchet engine,
a live IdP pointed at real Azure AD / Okta / Google, live third-party adapter
credentials, and an on-box inference model are integration legs that need their
service or credentials to exercise. The governance core that would use them is
implemented and tested. The copy describes those legs as "runs on your IdP / your
model / your systems," never as pre-wired for the reader out of the box.

**One-sentence honest summary:** Boltrig lets a team run a real workforce of AI
agents in production while every single action those agents take is checked,
permissioned, and recorded through one gate the agents cannot go around.

---

## 1. Target audience

### Primary audience profile (four layers)

- **Surface (who they are).** The platform, infrastructure, or security engineering
  leader (Head of Platform, Staff/Principal engineer, Head of Security or a
  security-minded CTO) at a company that has moved past AI demos and now wants
  agents doing real, consequential work: touching production systems, customer
  data, money, or regulated records. Company profile: security-conscious or
  regulated (fintech, legal, healthcare, gov-adjacent, B2B SaaS handling sensitive
  data), or any team that has to answer to an auditor or a customer security
  review.
- **Goal (what they are trying to accomplish).** Put autonomous agents into
  production on jobs that matter, and be able to prove, at any time, exactly what
  those agents did and were allowed to do. They want leverage without handing an
  LLM an unsupervised blank cheque over their systems.
- **Frustration (what blocks them today).** Two bad options. Option one: a DIY
  agent framework (LangChain, LangGraph, AutoGen, CrewAI, raw SDKs) where they
  bolt on their own auth, secrets handling, approvals, rate limits, and logging,
  and can never quite prove it is airtight. Option two: a closed vendor platform
  that runs the agents on someone else's cloud, where the data leaves the building
  and the governance is a black box they cannot inspect or self-host. Neither
  survives a security review cleanly.
- **Hidden belief (what they hold that most peers do not).** They do not believe
  "agents will behave if we prompt them well." They believe the model is the wrong
  place to put the safety, and that governance has to be a property of the
  runtime, enforced below the agent, or it is theatre. They would rather have a
  boring, provable gate than a clever, trust-me agent.

### Secondary audiences

- **The compliance / risk / audit stakeholder** who signs off on the deployment.
  They care about the tamper-evident record, deny-by-default, data residency, and
  the CI-pinned guarantees, not the agent cleverness.
- **The technical founder / applied-AI lead** who wants to ship agent products
  without rebuilding the entire safety substrate first.

### Jobs to Be Done

| Job type | Job description | Priority |
| --- | --- | --- |
| Functional | Run autonomous agents against real production systems and data | High |
| Functional | Prove, on demand, exactly what every agent did and was permitted to do | High |
| Functional | Keep sensitive data and secrets inside our own infrastructure | High |
| Functional | Add a new integration or agent without re-touching the safety core | Medium |
| Emotional | Sleep at night: not fear a runaway agent, a leaked key, or a surprise bill | High |
| Social | Pass a customer security review or an internal audit without flinching | High |
| Social | Be the leader who shipped agents responsibly, not the one who caused the incident | Medium |

### Audience insight statement

Engineering and security leaders believe that if they just prompt and fine-tune
carefully enough, their agents will stay in bounds. But what they actually need is
a runtime that makes staying in bounds structurally impossible to avoid, so safety
does not depend on the agent choosing to behave.

---

## 2. Competitive landscape and differentiation

### The three alternatives (honest, not strawman)

| Alternative | Who it serves | Its real strength | Its gap for this buyer |
| --- | --- | --- | --- |
| **DIY agent frameworks** (LangChain, LangGraph, AutoGen, CrewAI, raw model SDKs) | Developers building agent apps from parts | Maximum flexibility, huge ecosystem, fast to a prototype | Governance is the builder's homework. Auth, secrets, approvals, rate limits, budgets, and an audit trail are all bolted on by hand, inconsistently, and are never provably airtight. There is no single chokepoint by construction. |
| **Closed / hosted AI agent platforms** (managed vendor agent clouds) | Teams who want agents fast without running infrastructure | Turnkey, polished, low ops burden | The agents run on the vendor's cloud. Data leaves the building, governance is a black box you cannot inspect or self-host, and you cannot pin the guarantees to your own tests. Fails data-residency and "prove it" requirements. |
| **Workflow / RPA and iPaaS tools** (Zapier-class, n8n, orchestration suites) | Automation teams wiring deterministic steps | Mature connectors, visual building, reliable for fixed flows | Built for deterministic automation, not reasoning agents acting with judgement. No least-privilege model over autonomous action, no agent workforce, no consequence gate designed for an LLM making a call you did not pre-script. |

### The competitive map

- **Axis 1: ungoverned to governed-by-construction.** DIY frameworks sit at the
  ungoverned end (you add governance yourself). Boltrig sits at the far governed
  end (one chokepoint, nothing routes around it).
- **Axis 2: their cloud to your infrastructure.** Closed platforms sit at "their
  cloud." Boltrig sits at "your infrastructure, one self-hosted image."
- **Axis 3: trust the agent to prove the runtime.** Everyone else asks you to
  trust the agent's behaviour. Boltrig moves the proof to the runtime and pins it
  to CI.

The white space no one owns: **governed by construction AND self-hosted AND
provable.** Closed platforms give you polish but not your-infra or inspectability.
DIY gives you your-infra but not governance-by-construction. Boltrig is the only
one of the three positioned to hold all three at once.

### Differentiation statement

Boltrig is the agent-orchestration platform for engineering and security leaders
who want autonomous agents in production without moving their data off-site or
hand-building a safety layer they can never fully prove.

(Test: a competitor cannot honestly say this. DIY frameworks cannot claim "without
hand-building a safety layer." Closed platforms cannot claim "without moving your
data off-site." It is falsifiable and specific.)

### Proof points (all "read the repo" verifiable)

1. One dispatch chokepoint in code (`kernel/dispatch.py`), one ordered path, no
   side door.
2. Every action writes one append-only hash-chained audit row, denials included.
3. Deny-by-default grants intersecting a tenant ceiling, fail-closed, re-checked
   per call.
4. A HITL gate on high-consequence verbs that cannot be bypassed.
5. Credentials resolve inside the kernel; agents never receive a key.
6. Sensitive data is blocked from non-local model endpoints and misroutes are
   audited.
7. Every governance guarantee is pinned to a machine-checked test; a
   binding-invariant gate runs at debt 0 in CI.
8. Self-hosted as one image (kernel, database, console); one image, many tenants,
   config-as-data.

The strongest proofs today are code proofs, not customer proofs. That is a
strength for this buyer: they can inspect and self-host rather than take a vendor's
word. Until there are named deployments or a third-party audit, no logo strip,
metric, or testimonial appears on the site.

---

## 3. Positioning statement (the canonical one)

> **For engineering and security leaders who need to run autonomous AI agents on
> real production systems and data, Boltrig is a self-hosted, governed
> agent-orchestration platform that routes every agent action through one audited,
> permissioned checkpoint the agents cannot bypass, and keeps a tamper-evident
> record of all of it. Unlike DIY agent frameworks, which leave governance as
> hand-built homework, and unlike closed AI platforms, which run your agents and
> your data on someone else's cloud, Boltrig is governed by construction and runs
> entirely on your own infrastructure, with every guarantee pinned to a
> machine-checked test.**

Three-question test:
- **Is it true?** Yes. Every clause maps to implemented, tested code in the repo.
- **Is it different?** Yes. It names the exact trade-off each alternative forces
  and refuses both.
- **Does the audience care?** Yes. "Prove what the agents did" and "keep the data
  on our infra" are the two things that decide whether agents ship in a
  security-conscious org.

### Brand essence (three to six words)

**Autonomy you can prove.**

### Personality / voice (trait pairs, for whoever writes the site)

- Precise, not pedantic.
- Serious, not grim.
- Confident, not hype. (No "revolutionary," no "game-changing," no exclamation
  marks.)
- Technical, not gatekeeping. (An engineer trusts it; a CISO can follow it.)
- Calm, not corporate.

The current site voice (terminal kickers, `>` prompts, `STANDING` / `GOVERNED`
readouts, hairline frames on black) already hits this register well. Keep it.

---

## 4. Message hierarchy

### The one line (lead message)

**Run AI agents in production. Prove every move they make.**

Alternate one-liners (all true, pick per surface):
- Autonomy you can put your name to.
- A workforce of AI agents, and one gate they cannot go around.
- Autonomous agents, governed by construction, on your own infrastructure.

### The three pillars

1. **One gate, every action.** Every agent action passes a single audited,
   permissioned checkpoint in a fixed order. Deny by default, credentials never
   leave the kernel, high-consequence work waits for a human, and every action
   (including every denial) leaves one tamper-evident record. There is no side
   door.

2. **A workforce, not a chatbot.** A standing org of agents (a Chief of Staff over
   department heads) takes work in and spawns short-lived workers with exactly the
   skills the job needs, on the cheapest capable model, with sensitive work kept
   on local models. Budgets stop runaway spend before it happens.

3. **Yours to run, and provable.** One self-hosted image (kernel, database,
   console) on your own infrastructure. Your identity provider, your models, your
   data residency. Every governance guarantee is pinned to a machine-checked test
   in CI, so "it is governed" is something you can check, not something you have to
   take on faith.

### Proof points (per pillar)

- Pillar 1: the ordered dispatch path; hash-chained audit; deny-dominant grants;
  the un-bypassable HITL gate; kernel-held credentials.
- Pillar 2: Chief-of-Staff routing; skills-as-data library; cheapest-capable model
  routing; sensitive-to-local routing with audited misroutes; hard budget stops.
- Pillar 3: single-image self-host; OIDC SSO or first-party invite-only auth;
  policy-as-data (one manifest per tenant); binding-invariant gate at debt 0 in CI.
- Cross-cutting: MCP in and out; visual workflow canvas; the work board and run
  inspector; new integrations as data, not core edits.

---

## 5. Landing-page copy (as shipped)

This preserves the existing scroll experience: the fixed WebGL particle brain
behind animated story chapters, then the static features catalogue. The hero leads
with the buyer's outcome, a problem-and-alternatives beat is folded into the
narrative, and the CTA is honest for an invite-only, self-hosted product. The
particle brain stays as the hero visual and carries the "living workforce under one
gate" idea: the brain is the standing fleet, the pre-execute scan/takeover chapter
is the checkpoint.

### 5a. Hero headline

**Run AI agents in production. Prove every move they make.**

(Direct value plus the buyer's real fear in one line. The old poetic line,
"Autonomy you can put your name to," is retained only as an alternate one-liner in
section 4, not as the H1, so the headline does the explaining for a cold visitor.)

### 5b. Hero subhead (as shipped in the arrival panel body)

Boltrig runs a standing workforce of AI agents and routes every action they take
through one audited, permissioned gate. Autonomous work on your own infrastructure,
with a tamper-evident record of everything they did and were allowed to do.

### 5c. Primary and secondary CTA

The product is invite-only with no self-signup, and self-hosted. The CTA must not
promise a one-click free trial that does not exist, and must not send a cold
visitor with no login straight at the console wall.

- **Primary CTA: `Request access`.** Honest for an invite-only product and
  appropriate for a considered, security-led purchase. It opens a pre-addressed
  email to the access inbox rather than a fake self-signup form.
- **Secondary CTA: `Open the console`** linking to `https://app.boltrig.io`.
  Reserved for the returning, already-provisioned visitor (top nav and the finale),
  never the primary path for a cold visitor.

### 5d. Section flow (the seven scroll panels, as shipped)

The scroll narrative keeps its seven panels and their fixed ids/kind/order (the
camera keyframes are index-aligned to them). Copy per panel:

1. **arrival (hero, brain at rest)** - kicker `> Boltrig`; H1 "Run AI agents in
   production. Prove every move they make."; the subhead above; readouts
   `workforce: STANDING` / `actions: GOVERNED` / `deploy: SELF-HOSTED`. The
   persistent header carries `Request access` (primary) and `Open console`
   (secondary) above the fold.
2. **cortex (the checkpoint, brain)** - "One gate. Every action." Every action
   passes one audited checkpoint before anything happens, in a fixed order, with
   credentials resolved inside the gate and no side door.
3. **signals (in-flight, takeover)** - "Checked before anything happens." Each
   request is an intent in transit, weighed against its grants and consequences
   before a single side effect lands; every action, denials included, leaves one
   tamper-evident record.
4. **network (the workforce, brain lit up)** - "A workforce, not a chatbot." Chief
   of Staff routes to department heads that spawn short-lived workers on the
   cheapest capable model; sensitive work stays local; budgets are reserved first.
5. **vision (the operation, brain)** - "Every job on one board." Draw workflows on
   a canvas, run them on a schedule or events, watch all agent and human work on
   one board, and open any run to walk every step, with provenance on every fact.
6. **balance (the fabric, brain)** - "It governs agents you did not build." Expose
   granted capabilities as MCP tools with the full checkpoint, plug external tool
   servers in inert until reviewed; integrations are data, not code.
7. **whole (in production, finale)** - "Provably governed. Yours to run." One
   self-hosted deploy; enterprise SSO or first-party invite-only access; the audit
   record proves what happened; every guarantee pinned to a machine-checked test in
   CI. Finale CTA: `Request access`.

### 5e. Meta description (as shipped)

"Run a workforce of AI agents in production and prove every move they make. Boltrig
routes every agent action through one audited, permissioned gate, self-hosted on
your own infrastructure."

---

## 6. What is deliberately NOT claimed (honesty ledger)

- No customer names, logos, testimonials, user counts, or revenue.
- No performance, latency, throughput, or cost-savings numbers.
- No third-party security certification or audit (SOC 2, ISO, pen-test), because
  none exists yet.
- The outer integration legs (live Hatchet run-resume at scale, a live IdP against
  a specific provider, live third-party adapter credentials, an on-box inference
  model) are described as "runs on yours," never as pre-wired for the reader.
- When any of the above becomes a verifiable fact, it may be added as a single
  honest line. Until then, the site stands on "read the code, self-host it, check
  the runtime," which is the proof this buyer actually values.
