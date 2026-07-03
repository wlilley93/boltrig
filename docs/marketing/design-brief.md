# Boltrig - design brief (north star, not a spec)

This describes what the site should FEEL like and what it must be true to. It is
deliberately not prescriptive: it sets the target, the guardrails, and the taste,
and leaves the execution (layout, type, motion mechanics, whether the brain stays)
to the designer's judgement. Where a real fork exists, it is marked "STEER" for the
Principal to decide.

No em dashes or en dashes anywhere in anything produced from this brief.

---

## 1. The one line

Boltrig is "autonomy you can prove." The site should make a skeptical engineer feel
that this is the calm, serious, in-control place where AI agents are allowed to do
real work because everything they do is checked and recorded. The overriding
feeling is EARNED TRUST, not excitement.

## 2. Who is on the other side of the screen

A platform, infrastructure, or security engineering leader who has seen a hundred
AI landing pages and distrusts all of them. They are precise, allergic to hype, and
reading for the catch. They arrived from a link or a search with a guarded, "prove
it" mindset and about eight seconds of patience. They are not a consumer to be
delighted; they are a professional to be convinced. If anything feels like theatre,
they close the tab and it confirms their prior that this is more vapor.

The secondary reader is a risk or compliance stakeholder who will be shown the page
by that engineer. They care about the record, the residency, the "who can do what,"
not the visuals. The visuals must not get in the way of them finding those.

## 3. Personality (and its opposites)

Aim for: composed, exact, quietly confident, engineered, honest, understated,
premium in the way good tools are premium (not in the way luxury ads are premium).
The vibe of a very well made instrument.

Avoid: playful, bubbly, "friendly startup," neon-hype, salesy, busy, magical,
maximalist, anything that feels like it is trying to impress you. Confidence here
is shown by restraint. The product's whole promise is control, so a loud or chaotic
site actively contradicts the pitch.

A test to apply to any choice: would this make a Staff engineer trust us more, or
would it make them roll their eyes? When unsure, choose the more restrained option.

## 4. The experience arc (what a visit should feel like, not how to build it)

The visit should move from a clear, immediate claim, to "here is the problem you
already feel," to "here is the one idea that fixes it," to proof, to a single quiet
next step. The reader should never wonder what Boltrig is (that is decided in the
first screen), never feel sold to, and never feel lost. Momentum should come from
clarity and from wanting to read the next line, not from spectacle pulling them
down the page. If a section exists only to be impressive, it should not exist.

By the end they should be able to say, unprompted, what Boltrig is and why the two
obvious alternatives fail them. That is the job. Everything visual serves it.

## 5. Mood and atmosphere

Dark, deep, and precise reads right for this audience and product (a control room,
an instrument at rest, a night-shift ops screen), but that is a direction, not a
mandate. Whatever the palette, the feeling should be: low noise, high signal, a lot
of calm negative space, one or two things glowing with intent rather than everything
competing. Light should feel deliberate, like it is pointing at what matters. Depth
and weight are welcome; flashiness is not. The page should feel like it could sit
open on a second monitor all day without tiring the eye.

STEER: dark-and-technical vs light-and-clinical (both can read "serious"). Default
assumption is dark. Say if you want to explore light.

## 6. Motion philosophy (this is load bearing, learn from the current site)

Motion must feel INTENTIONAL and COUPLED to what the person is doing. The current
site's motion made a viewer seasick because the scroll and the camera kept moving
after the input stopped - motion decoupled from intent. That is the one sin to never
repeat. Every movement should feel like a direct consequence of the reader's action
(their scroll, their hover, their click), resolve quickly, and then be still.
Stillness is the default state; motion is a brief, purposeful punctuation.

Prefer: small, fast, settled transitions; things that arrive and stop; motion that
reveals meaning (a value being checked, a record being written) rather than motion
for atmosphere. A little life is good (a slow, quiet ambient pulse is fine).
Anything that continues under its own momentum, parallax that fights the scroll, big
camera swings, or effects that make you brace yourself are wrong here. Respect
prefers-reduced-motion completely (a fully static, fully usable site). If in doubt,
less motion. The product is about control; the motion should feel controlled.

STEER: how alive vs how still. Default is "mostly still, with restraint." Say if you
want it more kinetic (and we will still keep it coupled and comfortable).

## 7. Typography (voice, not fonts)

The type should read like precise engineering documentation that happens to be
beautifully set: clear hierarchy, generous size for the few things that matter,
comfortable measure, nothing shouty. A restrained technical/monospace accent for
labels, values, and "receipts" can reinforce the instrument feel, used sparingly so
it stays a signal not a costume. Copy is short, declarative, and confident; the
type should let it breathe. One clear voice, not a ransom note of weights.

## 8. Color and light (direction, not hex)

Mostly quiet and neutral, with restraint, and a single disciplined accent that means
something (the "checked / allowed / recorded" idea). The accent should feel like a
status light, used where it carries meaning, not sprinkled for decoration. Contrast
must clear WCAG AA for real (the current site had to have two tones nudged to pass);
never sacrifice legibility for mood. Whatever the accent, it should feel closer to a
precise signal than to a brand splash.

STEER: the accent hue and how much of it. There is a current direction in the app
console tokens worth staying loosely consistent with, but the site can lead.

## 9. Layout, density, and rhythm

Spacious. Let the important claim own its screen. A steady, calm vertical rhythm with
real whitespace between ideas, not a dense wall and not an endless thin scroll of
one-liners. Each section should hold exactly one idea and feel finished. Alignment
and spacing should be visibly disciplined (this audience reads sloppy spacing as
sloppy engineering). The grid can be quietly present rather than hidden; a hint of
structure suits the brand.

## 10. The hero device / imagery (the biggest open question)

The site currently centers a 3D "particle brain" that the narrative scans as you
scroll. It is distinctive and on-theme (a mind doing work under supervision), and it
is the strongest single asset we have. But it is also the source of the discomfort
and it risks reading as decoration. Two honest directions, and this is a real fork:

- Evolve it: keep a brain/field as a calm, mostly-still presence that reacts subtly
  and meaningfully (it lights the region a claim is about, it shows a pulse of "an
  action checked"), never a ride. Motion earns its place by carrying meaning.
- Replace it: lead with the IDEA made visual - the single gate every action passes
  through, the append-only record filling in, the deny-by-default boundary. A
  precise diagram or a restrained live "proof" artifact can out-convince a pretty
  abstraction for exactly this audience.

Either can be world class. Prefer whichever more directly makes "every action is
checked and recorded" felt. Do not keep the brain only because it is impressive; keep
it only if it earns trust.

STEER: evolve the brain, replace it with a proof/diagram concept, or run both as
options to compare. This is the decision that most shapes the redesign.

## 11. Interaction and detail (where craft shows)

The small things carry the "well made instrument" feeling: precise hover states that
respond instantly and settle, focus states that are crisp and always visible,
buttons that feel like real controls, copy-to-clipboard on the technical bits,
tooltips that add signal. Nothing should lag, bounce, or overshoot. Detail should
reward a close look (the audience will look closely) without ever being needed to
understand the page.

## 12. Comfort and accessibility (non negotiable)

Real WCAG AA contrast, visible focus everywhere, 44px targets, full
prefers-reduced-motion support (static and complete), no motion that could induce
sickness or seizure, keyboard-navigable, semantic and screen-reader-correct. For
this audience an inaccessible site is also a credibility hit. Comfort is a feature.

## 13. What must stay true (guardrails, not taste)

- Honesty. Every claim must be true of the product as it exists. No invented
  metrics, customer logos, testimonials, or fake dashboards. Where we lack proof
  yet, say less rather than fake it. This audience punishes exaggeration hardest.
- The proof is "read the code / self-host it / pin it to your tests," not social
  proof we do not have.
- No self-signup: the real next step is "request access" and, for existing users,
  the console at app.boltrig.io. Do not design a fake signup funnel.
- Never any em or en dashes.
- The outer integration seams (a live model, a live IdP, live third-party tools) are
  "runs on yours," never shown as pre-wired.

## 14. How we will know it is right

- A skeptical Staff/Principal engineer reads the first screen and can say what
  Boltrig is and is not rolling their eyes.
- Someone can scroll the whole thing without bracing, on a laptop trackpad, and feel
  calmer, not queasier, at the bottom.
- A compliance reader can find "checked, permissioned, recorded, self-hosted" fast.
- It looks like it was made by the same people who would build a governed kernel:
  precise, restrained, trustworthy.
- Nothing on it feels like it is trying to impress you, and it is the most
  impressive one in the tab set anyway.

## 15. The open taste forks (please steer these; everything else the designer can own)

1. Dark-and-technical vs light-and-clinical (section 5). Default: dark.
2. How alive vs how still (section 6). Default: mostly still, always coupled.
3. The accent hue and how much (section 8).
4. The hero device: evolve the brain, replace it with a proof/diagram, or compare
   both (section 10). This is the big one.
5. Any references you love or references you hate (name a couple of sites or products
   whose feel you want, or want to avoid) - this single input calibrates taste faster
   than anything else here.
