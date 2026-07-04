import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { WorkflowStudio } from "@/panels/studio/WorkflowStudio";
import { clearApiMocks, mockApi } from "../../helpers";

describe("WorkflowStudio", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<WorkflowStudio />);
  });
});
