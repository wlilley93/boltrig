import { describe, it } from "vitest";
import { render } from "@testing-library/react";
import { AuthGate } from "@/panels/AuthGate";
import { navigate } from "@/router";

describe("AuthGate", () => {
  it("renders the public accept-invite page without crashing", () => {
    navigate("/accept-invite?token=test-token");
    render(
      <AuthGate>
        <div>App</div>
      </AuthGate>,
    );
  });
});
