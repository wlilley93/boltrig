import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { DevConsolePanel } from "@/panels/DevConsolePanel";
import { InvokeSection } from "@/panels/devConsole/InvokeSection";
import { SpawnSection } from "@/panels/devConsole/SpawnSection";
import { clearApiMocks, mockApi } from "../helpers";

describe("DevConsolePanel", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<DevConsolePanel />);
  });

  it("renders InvokeSection", () => {
    mockApi();
    render(<InvokeSection caps={{ data: null, error: null, errorStatus: null, loading: false, reload: () => {} }} />);
  });

  it("renders SpawnSection", () => {
    mockApi();
    render(<SpawnSection skillsList={{ data: null, error: null, errorStatus: null, loading: false, reload: () => {} }} />);
  });
});
