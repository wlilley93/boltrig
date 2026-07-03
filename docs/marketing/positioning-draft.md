# Boltrig positioning and landing-page rewrite (DRAFT for review)

Status: DRAFT. Nothing here is published. This document applies the agents-final
growth-marketing frameworks (audience-and-positioning, competitor-and-differentiation,
brand-strategy-architect, brand-story-writer, landing-page-match-writer, hook-writer)
to Boltrig as it actually exists in this repository. Every capability claim is
grounded in `README.md`, `docs/ARCHITECTURE.md`, `docs/invariants.md`, the site
`features.ts`, and `docs/first-party-login.md`. Where a claim would need real
customer data, a benchmark, or a logo, it is marked `[needs real data]` rather
than invented.

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
implemented and tested.

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

- **Axis 1: ungoverned <-> governed-by-construction.** DIY frameworks sit at the
  ungoverned end (you add governance yourself). Boltrig sits at the far governed
  end (one chokepoint, nothing routes around it).
- **Axis 2: their cloud <-> your infrastructure.** Closed platforms sit at "their
  cloud." Boltrig sits at "your infrastructure, one self-hosted image."
- **Axis 3: trust the agent <-> prove the runtime.** Everyone else asks you to
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

### Proof points

1. One dispatch chokepoint in code (`kernel/dispatch.py`), one ordered path, no
   side door. Verifiable by reading the repo.
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

### Risks and gaps (be honest internally)

- The strongest proofs are "read the code" proofs, not customer proofs. Until
  there are named deployments, benchmarks, or a third-party audit, the marketing
  proof section is `[needs real data]` for logos, metrics, and testimonials.
- Some outer legs are seams (live Hatchet, live IdP, live third-party adapters,
  on-box model). Copy must describe the governance core as done and describe those
  as "runs on your IdP / your model / your systems," not imply they are shipped and
  wired for the reader out of the box.
- "Governed operating system for AI agents" is a strong line but abstract on its
  own. It needs the buyer problem next to it to land (see the critique in section 6).

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
- `[needs real data]`: customer names, deployment counts, throughput/latency
  numbers, a third-party security attestation. Do not fabricate any of these.

---

## 5. Landing-page rewrite

This preserves the existing scroll experience: the fixed WebGL particle brain
behind animated story chapters, then the static features catalogue. The rewrite
sharpens the hero and the section flow so a first-time visitor learns, within the
first screen, what Boltrig is, who it is for, why not the alternatives, and what to
do next. The particle brain stays as the hero visual and carries the "living
workforce under one gate" idea: the brain is the standing fleet, the pre-execute
scan/takeover chapter is the checkpoint. Do not throw the visual away; it is the
brand's strongest asset.

### 5a. Hero headline options (pick one)

1. **Run AI agents in production. Prove every move they make.**
   (Direct value + the buyer's real fear in one line. Recommended.)
2. **Autonomy you can put your name to.**
   (The current line. Evocative and on-brand, but abstract on its own. Keep as the
   poetic secondary, not the primary, or pair it with subhead option 1.)
3. **A workforce of AI agents, and one gate they cannot go around.**
   (Names the two pillars. Strong for a visitor who already knows the category.)

Recommendation: lead with (1) as the H1 for a cold visitor, and let the existing
"Autonomy you can put your name to." live on as the arrival-chapter kicker inside
the scroll. That keeps the poetry without asking the headline to do the explaining.

### 5b. Hero subhead options (pick one)

1. **Boltrig is a self-hosted platform that runs a standing workforce of AI agents
   and routes every action they take through one audited, permissioned checkpoint.
   Autonomous work, on your infrastructure, with the receipts.**
2. **A governed operating system for AI agents: one gate for every action, a
   workforce that does real work, and a tamper-evident record of all of it. Runs
   on your own infrastructure.**
3. **Put agents to work on the jobs that matter. Every action is identified,
   permissioned, approved when it counts, and recorded, through one gate the agents
   cannot bypass.**

Recommendation: subhead (1). It states category, mechanism, and the two proof
words ("your infrastructure", "the receipts") in one read.

### 5c. Primary and secondary CTA

The product is invite-only with no self-signup, and self-hosted. The CTA must not
promise a one-click free trial that does not exist.

- **Primary CTA: `Request access`** (or `Book a walkthrough`). Honest for an
  invite-only product and appropriate for a considered, security-led purchase.
- **Secondary CTA: `Read the architecture`** linking to the public architecture /
  invariants docs. This buyer converts on inspectability, so let them inspect.
- Keep `Open the console` (linking to `app.boltrig.io`) only for the returning /
  already-provisioned visitor, for example in the top nav, not as the primary hero
  CTA for a cold visitor who has no login.

### 5d. Section flow and copy

The scroll narrative maps almost one-to-one onto the classic hero -> problem ->
how -> differentiators -> proof -> CTA flow. Here is the flow with copy.

**Section 1 - Hero (the arrival chapter, brain at rest)**
- Kicker: `> Boltrig`
- H1: Run AI agents in production. Prove every move they make.
- Subhead: Boltrig is a self-hosted platform that runs a standing workforce of AI
  agents and routes every action they take through one audited, permissioned
  checkpoint. Autonomous work, on your infrastructure, with the receipts.
- Readouts (keep the format): `workforce: STANDING` / `actions: GOVERNED` /
  `deploy: SELF-HOSTED`
- CTA: [ Request access ]   secondary: Read the architecture

**Section 2 - Problem (new or reframed chapter, before the checkpoint)**
- Kicker: `> The Problem`
- Title: Agents are ready for real work. Your safety layer is not.
- Body: Handing an AI agent access to production systems, customer data, or money
  means one of two bad bets today. Wire up your own framework and you are
  hand-building auth, secrets, approvals, budgets, and logging you can never fully
  prove. Hand it to a closed platform and your data runs on someone else's cloud,
  behind governance you cannot see or self-host. Neither one survives a security
  review with a straight face.
- Readouts: `DIY: unprovable` / `closed cloud: off-site`

**Section 3 - How it works (the checkpoint chapter, the pre-execute takeover)**
- Kicker: `> The Checkpoint`
- Title: One gate. Every action.
- Body: Chat, webhook, or schedule: every agent action passes one audited
  checkpoint before anything happens. Identity, grants, consequence, human
  approval when it counts, rate limits, and safe retries, in that fixed order.
  Credentials resolve inside the gate and never reach the agent. Budgets stop
  runaway spend. Every action, and every denial, leaves exactly one tamper-evident
  record. There is no side door.
- Readouts (keep): `gates: ORDERED` / `default: DENY` / `side doors: NONE`

**Section 4 - The workforce (the network chapter, brain lit up)**
- Kicker: `> The Workforce`
- Title: A workforce, not a chatbot.
- Body: A Chief of Staff routes each request to the right department head. Heads
  spawn short-lived workers carrying exactly the skills the job needs. Every task
  runs on the cheapest model that can do it well, and work marked sensitive never
  leaves your infrastructure. Budgets are reserved before the work starts, not
  reconciled after the bill lands.
- Readouts (keep): `org chart: STANDING` / `sensitive data: STAYS LOCAL`

**Section 5 - Differentiators (the operation + fabric chapters)**
- Kicker: `> Why Boltrig`
- Title: Governed by construction. Open at every edge.
- Body: See every piece of agent and human work on one board, open any run and
  walk every step it took, and draw workflows on a canvas that run through the same
  gate as everything else. Expose granted capabilities to outside agents as MCP
  tools with the full checkpoint applied, and plug external tool servers in as new
  capabilities, inert until you review and activate them. New integrations are
  data, not code changes.
- Readouts (keep): `mcp: IN / OUT` / `new tools: OFF BY DEFAULT` /
  `runs: INSPECTABLE`

**Section 6 - Proof (the finale chapter, brain resolves)**
- Kicker: `> Provably Governed`
- Title: Provably governed. Yours to run.
- Body: One self-hosted deploy: kernel, database, console, on your own
  infrastructure. Enterprise SSO maps your people to roles, or run first-party
  invite-only access as the only door. The audit record proves what happened, and
  every governance guarantee is pinned to a machine-checked test in CI. Not "trust
  the agent." Check the runtime.
- Readouts (keep): `deploy: SELF-HOSTED` / `guarantees: CI-PINNED`
- `[needs real data]`: if/when there are named customers, a deployment count, or a
  third-party attestation, this is where a single honest proof line or logo strip
  belongs. Do not add one until it is real.

**Section 7 - Features catalogue (unchanged structure, keep as is)**
- The existing six-group catalogue (`features.ts`) is accurate, concrete, and
  well-written. Keep it verbatim. Only swap the closing button.
- Closing CTA: primary `[ Request access ]`, secondary `Read the architecture`.
  Reserve `Open the console` for returning users.

### 5e. Meta description rewrite

- Current: "The governed operating system for AI agents: one audited checkpoint
  for every action, a standing agent workforce, self-hosted on your infrastructure."
- Proposed: "Run a workforce of AI agents in production and prove every move they
  make. Boltrig routes every agent action through one audited, permissioned gate,
  self-hosted on your own infrastructure." (Leads with the outcome and the buyer's
  fear; keeps the mechanism and the self-hosted proof.)

---

## 6. Honest critique of the current site copy

The current site is genuinely good: the writing is disciplined, concrete, and free
of hype, the visual is distinctive, and the features catalogue is accurate. The
issues are about sharpness and sequence, not quality.

1. **The hero leads with poetry, not the buyer's problem.**
   - Before (arrival): "Autonomy you can put your name to." + "Boltrig is the
     governed operating system for AI agents. A standing workforce of agents does
     real work on your behalf, and a control plane checks every move they make."
   - Issue: beautiful, but a cold visitor does not yet know what problem this
     solves or that it is for them. "Governed operating system for AI agents" is a
     category assertion before the visitor feels the pain.
   - After: keep "Autonomy you can put your name to." as the arrival kicker, and
     make the H1 do the explaining: "Run AI agents in production. Prove every move
     they make." Then the standing-workforce sentence.

2. **There is no explicit "why not the alternatives" anywhere.**
   - Issue: the site says what Boltrig is, never what it is instead of. The buyer
     is actively comparing it to DIY frameworks and closed platforms and the page
     never addresses that choice.
   - After: add the Problem chapter (section 2 above) that names the two bad bets
     (unprovable DIY, off-site closed cloud). This is the single most important
     missing block.

3. **The CTA assumes access the cold visitor does not have.**
   - Before: "Open the console" / "[ Open_The_Console ]" linking to
     `app.boltrig.io`.
   - Issue: the product is invite-only with no self-signup. A first-time visitor
     clicking "Open the console" hits a wall. The page never offers the actual
     next step.
   - After: primary CTA "Request access" (or "Book a walkthrough"); secondary
     "Read the architecture"; reserve "Open the console" for returning users in the
     nav.

4. **"Provable" is the strongest differentiator and it is buried in the last
   chapter.**
   - Issue: "every governance guarantee is pinned to a machine-checked test in CI"
     is the line closed competitors cannot match and DIY cannot claim. It appears
     only in the finale.
   - After: promote "prove every move" into the H1 and the meta description, and
     let the finale pay it off. Make provability a through-line, not a footnote.

5. **The two audiences appear once, late, and only in the features header.**
   - Before (features header): "Built for engineering, platform and security
     leaders who want autonomous agents in production without losing control."
   - Issue: this is the sharpest audience callout on the whole site and it is 90%
     of the way down. Move a version of it near the top so the right visitor
     self-identifies early.

6. **Minor: the readout chips are great, keep them, and add one deploy chip to the
   hero** (`deploy: SELF-HOSTED`) so the "your infrastructure" proof is visible
   above the fold, not only in the finale.

### Net: the single biggest change

Add an explicit problem/alternatives beat and lead the hero with the buyer's
outcome ("Run AI agents in production. Prove every move they make."), instead of
opening on the abstract category line. The site currently tells a beautiful story
about what Boltrig is; it does not yet tell the visitor what goes wrong without it,
why the two obvious alternatives fail them, or what to do next. Fixing those three
things (problem beat, outcome-led hero, honest CTA) is the highest-leverage rewrite
and requires no change to the visual or the accurate features catalogue.

---

## 7. What is deliberately NOT claimed (honesty ledger)

- No customer names, logos, testimonials, user counts, or revenue.
- No performance, latency, throughput, or cost-savings numbers.
- No third-party security certification or audit (SOC 2, ISO, pen-test) unless and
  until one exists.
- The outer integration legs (live Hatchet run-resume at scale, a live IdP against
  a specific provider, live third-party adapter credentials, an on-box inference
  model) are described as "runs on yours," never as pre-wired for the reader.
- Every item above is a `[needs real data]` slot: fill only with verifiable fact.
