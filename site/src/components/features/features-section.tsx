import { FEATURE_GROUPS } from "@/data/features";
import { Inview } from "@/components/animation/springs/in-view";

/**
 * The post-story features section: a static, semantic catalogue of what the
 * platform actually ships, grouped into six themes (`src/data/features.ts`).
 * Renders after the scroll narrative in normal document flow. It sits above the
 * fixed brain canvas (`relative z-10 bg-black`) so it fully occludes the scene,
 * and keeps the site's console look: `>` prompt kickers, `▸` row markers,
 * hairline `border-white/10` frames on a black field. Server Component; the only
 * client leaves are the `<Inview>` reveals (mode `once`, spring-based).
 */
export const FeaturesSection = () => {
  return (
    <section
      id="features"
      aria-labelledby="features-title"
      className="relative z-10 border-t border-white/10 bg-black px-6 py-24 md:px-16 md:py-32 lg:px-24"
    >
      <div className="mx-auto w-full max-w-6xl">
        <Inview
          tag="header"
          mode="once"
          from={{ opacity: 0, y: 24 }}
          to={{ opacity: 1, y: 0 }}
          config={{ tension: 90, friction: 24 }}
          className="max-w-2xl"
        >
          <p className="mb-6 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.42em] text-white/70 md:text-sm">
            <span aria-hidden className="text-brain-sky/45">
              &gt;
            </span>
            What_You_Get
          </p>
          <h2
            id="features-title"
            className="text-[2rem] font-semibold leading-[1.16] tracking-tight text-white md:text-[2.6rem]"
          >
            AI agents that finish work, with controls your team can defend.
          </h2>
          <p className="mt-6 text-lg leading-relaxed text-white/90">
            Boltrig is for teams that want agents doing real operational work:
            triage, updates, renewals, checks, workflows and handoffs. The
            architecture is there, but the value is simpler: faster work, less
            manual coordination and a clear record of what changed.
          </p>
        </Inview>

        <div className="mt-14 grid grid-cols-1 gap-5 md:mt-16 md:grid-cols-2 md:gap-6 xl:grid-cols-3">
          {FEATURE_GROUPS.map((group) => (
            <Inview
              key={group.id}
              tag="article"
              mode="once"
              from={{ opacity: 0, y: 20 }}
              to={{ opacity: 1, y: 0 }}
              config={{ tension: 90, friction: 24 }}
              className="flex flex-col rounded-md border border-white/10 bg-brain-void/60 p-6 md:p-7"
            >
              <h3 className="text-lg font-semibold tracking-tight text-white">{group.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/60">{group.hook}</p>
              <ul className="mt-6 space-y-4 border-t border-white/10 pt-5">
                {group.items.map((item) => (
                  <li key={item.name} className="flex items-baseline gap-2.5 text-sm leading-relaxed">
                    <span aria-hidden className="text-brain-sky/40">
                      &#9656;
                    </span>
                    <span>
                      <span className="font-semibold text-brain-sky/90">{item.name}.</span>{" "}
                      <span className="text-white/70">{item.outcome}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Inview>
          ))}
        </div>

        <div className="mt-16 flex flex-wrap items-center justify-center gap-4 md:mt-20">
          <a
            href="mailto:access@boltrig.io?subject=Boltrig%20access%20request"
            className="inline-flex items-center gap-2.5 border border-brain-sky/50 bg-brain-sky/10 px-7 py-3.5 text-xs font-semibold uppercase tracking-[0.28em] text-brain-sky backdrop-blur-md hover:border-brain-sky hover:bg-brain-sky/20 hover:text-white"
          >
            <span aria-hidden>&#9656;</span>
            <span>[ Request_Access ]</span>
          </a>
          <a
            href="https://app.boltrig.io"
            className="inline-flex items-center gap-2.5 border border-brain-sky/25 px-7 py-3.5 text-xs font-semibold uppercase tracking-[0.28em] text-brain-sky/80 backdrop-blur-md hover:border-brain-sky/60 hover:text-white"
          >
            <span>Open the console</span>
          </a>
        </div>
      </div>
    </section>
  );
};
