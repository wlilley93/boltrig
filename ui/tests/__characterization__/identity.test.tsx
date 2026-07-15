import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { identityHeaders } from "@/api/transport";
import { IdentityBar } from "@/app/IdentityBar";
import { getIdentity, resetIdentity, updateIdentity } from "@/identity";

afterEach(() => {
  cleanup();
  resetIdentity();
});

describe("development identity parity", () => {
  it("sends tier, delegation, and role-scope verbs with the existing identity headers", () => {
    updateIdentity({
      tenant: "acme",
      subject: "worker-7",
      role: "agent",
      actorTier: "ephemeral",
      onBehalfOf: "alice",
      departments: "support,billing",
      grants: "",
      verbs: "ticket.read,conversation.read",
    });

    expect(identityHeaders()).toEqual({
      "x-boltrig-tenant": "acme",
      "x-boltrig-subject": "worker-7",
      "x-boltrig-grants": "",
      "x-boltrig-role": "agent",
      "x-boltrig-departments": "support,billing",
      "x-boltrig-tier": "ephemeral",
      "x-boltrig-obo": "alice",
      "x-boltrig-verbs": "ticket.read,conversation.read",
    });
  });

  it("exposes the expanded context as structured controls and resets it", () => {
    render(<IdentityBar />);
    fireEvent.change(screen.getByLabelText("Actor tier"), { target: { value: "tier1" } });
    fireEvent.change(screen.getByLabelText("On behalf of"), { target: { value: "bob" } });
    expect(getIdentity().actorTier).toBe("tier1");
    expect(getIdentity().onBehalfOf).toBe("bob");

    fireEvent.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(getIdentity().actorTier).toBe("human");
    expect(getIdentity().onBehalfOf).toBe("");
    expect(getIdentity().verbs).toBe("");
  });
});
