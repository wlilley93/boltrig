import {
  CodeBlock,
  RunLink,
  runBadgeClass,
  stepBadgeClass,
} from "@/panels/shared";
import type { WorkflowRunRecord } from "@/api/types";

interface RunRecordProps {
  runResult: WorkflowRunRecord;
}

export function RunRecord({ runResult }: RunRecordProps) {
  return (
    <div className="form">
      <div className="form__title">Run record</div>
      <div className="kv">
        <span className={`badge ${runBadgeClass(runResult.status)}`}>
          {runResult.status}
        </span>
        <RunLink runId={runResult.run_id} />
        <span className="muted">
          {runResult.workflow_id} v{runResult.version}
        </span>
      </div>
      {runResult.steps.length === 0 ? (
        <p className="muted">No steps.</p>
      ) : (
        <ul className="verb-list">
          {runResult.steps.map((s, i) => (
            <li className="verb-row" key={`${s.id}-${i}`}>
              <div className="verb-row__main">
                <code className="verb-row__id">{s.id}</code>
                {s.action && <span className="muted">{s.action}</span>}
                <span className={`badge ${stepBadgeClass(s.status)}`}>
                  {s.status}
                </span>
              </div>
              {s.reason && (
                <div className="verb-row__meta">
                  <span className="muted">reason: {s.reason}</span>
                </div>
              )}
              {s.output !== undefined && <CodeBlock value={s.output} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
