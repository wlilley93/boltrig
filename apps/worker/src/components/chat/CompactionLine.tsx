/**
 * The point in a conversation where older turns stopped being sent verbatim.
 *
 * WHY INLINE RATHER THAN A FOOTNOTE. Compaction is an event at a POINT: above
 * this line the model receives a derived summary, below it the turns arrive
 * word for word. A notice at the end of the transcript states that a summary
 * exists and cannot say where it starts, which is the one thing a reader
 * actually needs in order to know what the assistant can still quote back.
 *
 * WHY IT IS STILL A `details`. The full derived summary is what the next turn
 * genuinely receives, and being able to read it is the difference between a
 * disclosure and a reassurance. The line is the trigger; the summary is behind
 * it. Closed by default, because the ordinary case is wanting to know THAT it
 * happened, not to audit the text.
 *
 * The whole transcript stays visible either way -- compaction changes what the
 * MODEL is sent, never what the record holds.
 */
export function CompactionLine({
  coveredCount,
  recentExactCount,
  summary,
}: {
  coveredCount: number;
  recentExactCount: number;
  summary?: string | null;
}) {
  return (
    <details className="compaction-line">
      <summary>
        <span aria-hidden="true" className="compaction-line-mark" />
        Context automatically compacted
      </summary>
      <div className="compaction-line-body">
        <p>
          The {coveredCount} message{coveredCount === 1 ? "" : "s"} above this point
          now reach the model as the summary below. The {recentExactCount} message
          {recentExactCount === 1 ? "" : "s"} after it are still sent word for word.
          Your full transcript is unchanged.
        </p>
        {summary ? <blockquote>{summary}</blockquote> : null}
      </div>
    </details>
  );
}
