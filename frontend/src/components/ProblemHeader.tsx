import type { ProgressModel, SupportModel } from "../present";
import type { SessionState } from "../types";

/** Workspace header: brand, problem, progress bar, step dots, support level. */
export function ProblemHeader(props: {
  session: SessionState | null;
  progress: ProgressModel;
  support: SupportModel;
}) {
  const { session, progress, support } = props;
  const problem = session?.current_problem;
  const topic = session?.topic || "";
  const subtopic = session?.subtopic || "";

  return (
    <header className="ph">
      <div className="ph-top">
        <span className="brand">
          MathTalk<span className="brand-dot">.</span>
        </span>
        {subtopic && (
          <span className="ph-meta">
            {topic ? `${topic.toUpperCase()} · ` : ""}
            {subtopic.toUpperCase()}
          </span>
        )}
      </div>

      <h1 className="ph-problem">
        {problem ? (
          <>
            Problem {progress.current} of {progress.total}
            {problem.display ? <> — {problem.display}</> : ""}
          </>
        ) : (
          "Ready to begin"
        )}
      </h1>

      <div className="ph-progress">
        <div className="ph-left">
          <div className="segments" aria-hidden="true">
            {progress.segments.map((s, i) => (
              <span key={i} className={`seg seg-${s}`} />
            ))}
          </div>
          <span className="ph-count">
            {progress.current}/{progress.total} · {progress.time}
          </span>
        </div>
        <div className="ph-right">
          <div className="dots" aria-hidden="true">
            {progress.dots.map((d, i) => (
              <span key={i} className={`dot dot-${d}`}>
                {d === "current" ? i + 1 : ""}
              </span>
            ))}
          </div>
          <span className="support-chip">
            SUPPORT LEVEL {support.level + 1} OF {support.of} · {support.label.toUpperCase()}
          </span>
        </div>
      </div>
    </header>
  );
}
