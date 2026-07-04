import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { MemoryPanel } from "@/panels/MemoryPanel";
import { clearApiMocks, mockApi } from "../helpers";

describe("MemoryPanel", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<MemoryPanel />);
  });
});
