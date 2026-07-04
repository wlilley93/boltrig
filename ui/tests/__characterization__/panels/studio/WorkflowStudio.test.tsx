import { afterEach, describe, it } from "vitest";
import { render } from "@testing-library/react";
import { WorkflowStudio } from "@/panels/studio/WorkflowStudio";
import { WorkflowForm } from "@/panels/studio/workflow/WorkflowForm";
import { UpsertWorkflowForm } from "@/panels/studio/workflow/forms/UpsertWorkflowForm";
import { ScheduleForm } from "@/panels/studio/workflow/forms/ScheduleForm";
import { TriggerForm } from "@/panels/studio/workflow/forms/TriggerForm";
import { ExecuteForm } from "@/panels/studio/workflow/forms/ExecuteForm";
import { RunsForm } from "@/panels/studio/workflow/forms/RunsForm";
import { VerbPalette } from "@/panels/studio/workflow/sidebar/VerbPalette";
import { WorkflowSidebar } from "@/panels/studio/workflow/sidebar/WorkflowSidebar";
import { clearApiMocks, mockApi } from "../../helpers";

const emptyFetchState = {
  data: null,
  error: null,
  errorStatus: null,
  loading: false,
  reload: () => {},
};

describe("WorkflowStudio", () => {
  afterEach(clearApiMocks);

  it("renders without crashing", () => {
    mockApi();
    render(<WorkflowStudio />);
  });

  it("WorkflowForm renders without crashing", () => {
    mockApi();
    render(<WorkflowForm />);
  });

  it("UpsertWorkflowForm renders without crashing", () => {
    render(<UpsertWorkflowForm onSaved={() => {}} />);
  });

  it("ScheduleForm renders without crashing", () => {
    render(<ScheduleForm wfOptions={[]} />);
  });

  it("TriggerForm renders without crashing", () => {
    render(<TriggerForm wfOptions={[]} />);
  });

  it("ExecuteForm renders without crashing", () => {
    render(<ExecuteForm wfOptions={[]} />);
  });

  it("RunsForm renders without crashing", () => {
    render(<RunsForm wfOptions={[]} />);
  });

  it("VerbPalette renders without crashing", () => {
    render(<VerbPalette caps={emptyFetchState} />);
  });

  it("WorkflowSidebar renders without crashing", () => {
    mockApi();
    render(<WorkflowSidebar workflows={emptyFetchState} caps={emptyFetchState} />);
  });
});
