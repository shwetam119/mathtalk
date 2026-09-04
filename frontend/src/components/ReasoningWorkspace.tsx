import type { ProgressModel, SupportModel, TimelineStep } from "../present";
import type { SessionState } from "../types";
import { ProblemHeader } from "./ProblemHeader";
import { StepCard } from "./StepCard";

/** Light right workspace: problem header + reasoning timeline. */
export function ReasoningWorkspace(props: {
  session: SessionState | null;
  steps: TimelineStep[];
  tutorMessage: string;
  progress: ProgressModel;
  support: SupportModel;
}) {
  const { session, steps, tutorMessage, progress, support } = props;
  const quote = session?.reasoning_transcript || "";

  return (
    <section className="workspace-inner" aria-label="Reasoning workspace">
      <ProblemHeader session={session} progress={progress} support={support} />

      <div className="rs-head">
        <h2>REASONING WORKSPACE</h2>
        <p>Each step of your spoken method is checked on its own — not just the final answer.</p>
      </div>

      {tutorMessage && (
        <div className="tutor-msg">
          <span className="tutor-tag">MATHTALK</span>
          <p>{tutorMessage}</p>
        </div>
      )}

      {quote && (
        <blockquote className="student-quote" aria-label="Student reasoning">
          “{quote}”
        </blockquote>
      )}

      <ol className="timeline">
        {steps.length === 0 && (
          <li className="timeline-empty">
            No reasoning yet — say how you'd solve the problem, or use the options below.
          </li>
        )}
        {steps.map((s, i) => (
          <StepCard key={s.id} step={s} last={i === steps.length - 1} />
        ))}
      </ol>
    </section>
  );
}
