import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { DevConsolePanel } from "@/panels/DevConsolePanel";
import { clearApiMocks, mockApi } from "../helpers";

describe("DevConsolePanel", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<DevConsolePanel />);
  });
});
