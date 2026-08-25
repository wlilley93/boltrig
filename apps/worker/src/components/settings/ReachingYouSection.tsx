import { useEffect, useState } from "react";

import { client } from "../../client";
import type { MeNotificationItem, NotificationCatalogue } from "@wlilley93/boltrig-web-sdk";

import { SettingsGroup, SettingsRow, SettingsSelect, SettingsToggle } from "./rowKit";

/** "Reaching you" - which events reach a person, and where.
 *
 *  MOVED OUT OF CompactSections, not rewritten. That file is capped at its
 *  recorded size by the structural ratchet and this section was already carried
 *  in the debt catalogue as an over-limit function, so adding anything to the
 *  file meant either raising a ceiling - which the ratchet refuses - or doing
 *  what the catalogue's own reason asks for: "reduce by component without
 *  semantic reversion". Every line below is the same as it was.
 *
 *  The whole section is READ-ONLY today: `meNotifications` is not implemented
 *  against a Hermes cell, so the toggles are disabled rather than absent. That
 *  is deliberate - it says the routes exist and are not yours to change here,
 *  where hiding them would say they do not exist.
 */

function eventEnabled(prefs: MeNotificationItem[], eventType: string): boolean {
  return prefs.some((pref) => pref.event_type === eventType && pref.enabled);
}

function eventAvailable(catalogue: NotificationCatalogue, eventType: string): boolean {
  return catalogue.events.some((event) => event.id === eventType);
}

/** Read this member's notification routes, or say they cannot be read.
 *
 *  A HOOK, so the section below stays under the structural floor without any
 *  line of it changing meaning. The file it came from is capped at its recorded
 *  size and the ratchet refuses NEW debt files, so an extraction that carried
 *  an over-limit function would simply move the problem. This is the same split
 *  useAppearanceSettings already makes in the file next door.
 *
 *  `meNotifications` is absent against a Hermes cell, and absent is a property
 *  read - not a rejecting call - so the probe reports the feature missing and
 *  the section renders disabled rather than throwing during render.
 */
function useNotificationRoutes() {
  const [prefs, setPrefs] = useState<MeNotificationItem[]>([]);
  const [catalogue, setCatalogue] = useState<NotificationCatalogue>({
    events: [],
    transports: [],
  });
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    let cancelled = false;
    if (typeof client.meNotifications !== "function") {
      setState("unavailable");
      return;
    }
    void client.meNotifications()
      .then((result) => {
        if (cancelled) return;
        setPrefs(result.prefs);
        setCatalogue(result.catalogue);
        setState("ready");
      })
      .catch(() => { if (!cancelled) setState("unavailable"); });
    return () => { cancelled = true; };
  }, []);

  return { catalogue, prefs, state };
}

export function CompactReachingYouSection() {
  const { catalogue, prefs, state } = useNotificationRoutes();

  const approvalRoutes = prefs.filter((pref) => pref.event_type === "approval" && pref.enabled);
  const approvalDestinations = [...new Set(approvalRoutes.map((pref) => {
    const transport = catalogue.transports.find((item) => item.id === pref.channel);
    const target = transport?.targets.find((item) => item.id === pref.target);
    return [transport?.label ?? pref.channel, target?.label ?? pref.target].filter(Boolean).join(" · ");
  }))];
  const destinationOptions = approvalDestinations.length > 0
    ? approvalDestinations
    : [state === "loading" ? "Reading routes…" : "No verified route"];

  function eventRow(title: string, eventType: string, desc: string) {
    const available = state === "ready" && eventAvailable(catalogue, eventType);
    return (
      <SettingsRow
        control={(
          <SettingsToggle
            disabled
            label={title}
            on={available && eventEnabled(prefs, eventType)}
            onToggle={() => {}}
          />
        )}
        desc={desc}
        key={eventType}
        title={title}
      />
    );
  }

  return (
    <>
      <SettingsGroup
      advanced={[
        eventRow("Escalations", "escalation", "A sub-agent asked for more authority than it has."),
        eventRow("Budget warnings", "budget_warning", "Spend crossed the warning threshold."),
        eventRow("Failures", "failure", "A run failed or a connection degraded."),
        eventRow("Work completed", "work_status", "When requested or automatic work finishes."),
      ]}
      title="Reaching you"
      >
        {eventRow(
          "When something needs approving",
          "approval",
          "The one interruption worth having",
        )}
        <SettingsRow
          control={(
            <SettingsSelect
              disabled
              label="Send approval notifications to"
              onChange={() => {}}
              options={destinationOptions}
              value={destinationOptions[0]!}
            />
          )}
          title="Send those to"
        />
        <SettingsRow
          control={<span className="settings-value">Unavailable</span>}
          desc="Only approvals and failures get through"
          title="Quiet hours"
        />
      </SettingsGroup>
      {state === "unavailable" && (
        <span className="settings-visually-hidden">Notification routes could not be read.</span>
      )}
      <span className="settings-visually-hidden">Quiet hours are not available.</span>
    </>
  );
}
