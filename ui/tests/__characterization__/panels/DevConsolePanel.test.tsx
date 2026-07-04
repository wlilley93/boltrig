import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { DevConsolePanel } from "@/panels/DevConsolePanel";
import { InvokeSection } from "@/panels/devConsole/InvokeSection";
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
});
