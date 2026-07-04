import { navigate, useRoute } from "../router";
import { useStepSlide } from "./stepSlide/useStepSlide";
import {
  ActionCard,
  DescriptionCard,
  ParametersCard,
  ParentsCard,
  StepSlideFooter,
  StepSlideToolbar,
} from "./stepSlide/StepSlideParts";
import { EmptyState, FetchError, PageIntro } from "./ux";
import { ByChat } from "./uxFlow";

export function StepSlide({ stepKey }: { stepKey?: string }) {
  const route = useRoute();
  const wfid = route.segs[1];
  const stepId = stepKey ?? route.segs[3];
  const s = useStepSlide(wfid, stepId);

  if (!wfid || !stepId) {
    return <section className="panel au-step"><EmptyState title="No step selected" body="Open a workflow step from the automations row." /></section>;
  }
  if (s.detail.loading && !s.detail.data) {
    return <section className="panel au-step"><p className="muted">Loading step...</p></section>;
  }
  if (!s.step) {
    return (
      <section className="panel au-step">
        <FetchError error={s.detail.error} status={s.detail.errorStatus} onRetry={s.detail.reload} />
        <EmptyState
          title="Step not found"
          body={`No step named ${stepId} is present in ${wfid}.`}
          action={<button className="btn" onClick={() => navigate(`/automations/${encodeURIComponent(wfid)}`)}>Back to canvas</button>}
        />
      </section>
    );
  }

  return (
    <section className="panel au-step">
      <PageIntro
        title={<><code>{s.step.id}</code> <span className="badge">step</span></>}
        lead={`Editing ${wfid}. Step changes save the whole workflow definition through the governed control plane.`}
        how="The workflow still runs the last saved version until the save request is approved and applied."
        actions={
          <>
            <ByChat phrase={`Explain and improve step ${s.step.id} in workflow ${wfid}.`} />
            <button className="btn" onClick={() => navigate(`/automations/${encodeURIComponent(wfid)}`)}>
              Back to canvas
            </button>
          </>
        }
      />

      <FetchError error={s.capsError} status={s.capsErrorStatus} onRetry={s.capsReload} />

      <StepSlideToolbar
        stepId={s.step.id}
        onInsertBefore={s.insertBefore}
        onAppendAfter={s.appendAfter}
        onDelete={s.deleteStep}
      />

      <div className="au-step__grid">
        <ActionCard
          step={s.step}
          verbs={s.verbs}
          currentVerb={s.currentVerb}
          actionUnavailable={s.actionUnavailable}
          onChangeAction={s.changeAction}
        />
        <ParametersCard paramsText={s.paramsText} paramsError={s.paramsError} onUpdateParams={s.updateParams} />
        <ParentsCard step={s.step} parentOptions={s.parentOptions} onReplaceStep={s.replaceStep} />
        <DescriptionCard step={s.step} onReplaceStep={s.replaceStep} />
      </div>

      <StepSlideFooter
        wfid={wfid}
        error={s.error}
        pending={s.pending}
        dirty={s.dirty}
        saving={s.saving}
        onSave={() => void s.save()}
        onDiscard={s.discard}
        onApplied={s.onApplied}
        onDenied={s.onDenied}
      />
    </section>
  );
}
