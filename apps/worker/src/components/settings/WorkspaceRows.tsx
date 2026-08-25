/** The rows about the WORKSPACE, rather than about the agent.
 *
 *  Extracted rather than added to CompactSections, which is a recorded
 *  structural-debt file whose own entry says to reduce it "by component without
 *  semantic reversion". Growing it to add a component would have been the exact
 *  move that entry exists to refuse - and these two rows are one subject, so
 *  they are one component.
 */
import { useEffect, useState } from "react";

import { copySensitiveText } from "../../clipboard";
import { planeJson } from "../../hermes/http";

import { SettingsRow } from "./rowKit";

/** Where this console came from, and the way back to it.
 *
 *  A PLAIN LINK, NOT A CLIENT CALL. Everything else in this file asks the
 *  agent; this asks for a different page of the same site. The workspace view
 *  is served by the control plane at the same origin, so the session cookie
 *  travels with an ordinary navigation and the person arrives already signed
 *  in. Routing it through the client would mean inventing a method for
 *  "navigate", and an absent one would hide the only way back.
 *
 *  WHY THE WAY BACK MATTERS. This console is what "/" opens once a team box is
 *  answering, which is the right default - people want their agent. But
 *  everything ABOUT the box lives on the other side: the address a desktop
 *  client connects to, the members of the team, and adding another box. Without
 *  a door here, arriving at the agent would be one-way for exactly the people
 *  who have one.
 *
 *  It renders unconditionally rather than probing for anything. There is no
 *  call that can fail, and a door that hides itself when it cannot verify the
 *  room behind it is worse than one that opens onto a page saying why.
 */
function WorkspacesRow() {
  return (
    <SettingsRow
      control={(
        // An ANCHOR wearing the button's own class, not a button that
        // navigates. It carries the same weight visually and still behaves
        // like a link: middle-click and open-in-new-tab work, and it shows its
        // destination on hover. A button would take all three away for nothing.
        <a className="settings-kit-button" href="/?workspace">
          Open
        </a>
      )}
      desc="Your team boxes, the address each answers on, and adding another."
      title="Your workspaces"
    />
  );
}

/** The address a desktop client connects to.
 *
 *  WHY IT IS HERE AS WELL AS ON THE WORKSPACE PAGE. Connecting a desktop client
 *  is something you do while sitting in this console, and the address is the
 *  one thing you cannot guess: it is derived from the workspace name, not from
 *  the name itself, and a rename does not move it. Sending somebody to another
 *  page to copy a string and come back is the kind of trip a settings panel
 *  exists to save.
 *
 *  ONE SOURCE, NOT TWO. It reads the same /api/me the workspace page reads
 *  rather than keeping its own copy, so there is no second place for the
 *  address to be wrong. A cached or hard-coded host would be a string that
 *  looks authoritative and drifts silently.
 *
 *  IT SAYS WHEN IT CANNOT ANSWER, in three distinguishable ways: still reading,
 *  no box answering yet, and could not ask. A single "unavailable" would make a
 *  box that is merely still starting look like a fault, and the difference
 *  decides whether waiting is the right thing to do.
 *
 *  THE ADDRESS ALONE REACHES NOTHING - a client needs a token beside it - and
 *  the row says so. Presenting it as sufficient invites a support conversation
 *  that begins "it says unauthorised".
 */
function ConnectAddressRow() {
  const [state, setState] = useState<"reading" | "ready" | "starting" | "unavailable">("reading");
  const [address, setAddress] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    planeJson<{
      tenant_gateway_id?: string | null;
      gateways?: { gateway_id?: string; host?: string; status?: string }[];
    }>("/api/me")
      .then((me) => {
        if (!active) return;
        const rows = me.gateways ?? [];
        // tenant_gateway_id first: on a tenant address the control plane is the
        // only thing that knows which workspace this hostname belongs to, and
        // the browser must not parse it out of the hostname itself.
        const mine = me.tenant_gateway_id
          ? rows.find((row) => row.gateway_id === me.tenant_gateway_id)
          : rows[0];
        if (mine?.host && mine.status === "ready") {
          setAddress(`https://${mine.host}`);
          setState("ready");
        } else {
          setState("starting");
        }
      })
      .catch(() => {
        if (active) setState("unavailable");
      });
    return () => {
      active = false;
    };
  }, []);

  async function copy() {
    setMessage(await copySensitiveText(address)
      ? "Address copied."
      : "The address could not be copied. Select it and copy it by hand.");
  }

  const description = state === "ready"
    ? `${address} - paste this into a desktop app. It needs an access token beside it; the address on its own reaches nothing.`
    : state === "starting"
      ? "Available once your box is answering."
      : state === "reading"
        ? "Reading your workspace…"
        : "Your workspace could not be read.";

  return (
    <SettingsRow
      control={state === "ready" ? (
        <button className="settings-kit-button" onClick={copy} type="button">
          Copy
        </button>
      ) : undefined}
      desc={message || description}
      title="Desktop app"
    />
  );
}


/** Both rows, so the section that uses them imports one thing.
 *
 *  A fragment and not a group: the caller already owns the group these belong
 *  to, and wrapping them in a second one would draw a divider through a single
 *  subject.
 */
export function WorkspaceRows() {
  return (
    <>
      <WorkspacesRow />
      <ConnectAddressRow />
    </>
  );
}
