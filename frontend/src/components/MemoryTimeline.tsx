import { useEffect, useState } from "react";
import { api } from "../api";
import type { TimelineEntry } from "../types";

/**
 * Cross-session memory timeline for the current misconception.
 *
 * Pulls past occurrences of the same misconception type for the current
 * student from learner memory (read-only), so the "memory changes tutoring"
 * story is visible as one static artifact: the first occurrence got a generic
 * response, later occurrences a targeted, memory-based one, and a green node
 * marks a session where the student self-corrected. Fetched once per detected
 * misconception — never polled.
 */
export function MemoryTimeline(props: {
  studentId: string;
  detected: boolean;
  misconceptionType: string;
  problemId: string;
}) {
  const { studentId, detected, misconceptionType, problemId } = props;
  const [entries, setEntries] = useState<TimelineEntry[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!detected || !misconceptionType) {
      setEntries(null);
      setError(false);
      return;
    }
    let alive = true;
    setError(false);
    api
      .getMisconceptionTimeline(studentId, misconceptionType)
      .then((r) => {
        if (alive) setEntries(r.entries);
      })
      .catch(() => {
        if (alive) setError(true);
      });
    return () => {
      alive = false;
    };
  }, [studentId, detected, misconceptionType, problemId]);

  if (!detected || !misconceptionType) return null;

  const label = misconceptionType.replace(/_/g, " ");

  return (
    <section className="panel" aria-labelledby="timeline-title">
      <h2 id="timeline-title">Memory timeline — {label}</h2>
      {error ? (
        <p className="muted small">Could not load the memory timeline for this student.</p>
      ) : entries === null ? (
        <p className="muted small">Loading past occurrences…</p>
      ) : entries.length <= 1 ? (
        <div className="tl-first">
          <strong>First time seeing this misconception</strong>
          <span className="muted small">
            No past occurrences on record for this student — this encounter sets the baseline.
          </span>
        </div>
      ) : (
        <ol className="memory-timeline" aria-label={`Past occurrences of ${label}`}>
          {entries.map((e, i) => (
            <li key={`${e.timestamp}-${i}`} className={`tl-node kind-${e.response_kind}`}>
              <span className="tl-node-dot" aria-hidden="true" />
              <div className="tl-node-body">
                <span className="tl-node-title">
                  {e.problem_id || e.session_id.slice(0, 8) || "session"}
                </span>
                <span className="tl-node-sub">
                  {e.response_kind === "self_correction"
                    ? "self-corrected after targeted guidance"
                    : e.response_kind === "targeted"
                      ? "targeted response (memory-based)"
                      : "generic response"}
                </span>
                {e.detail && <span className="tl-node-detail">{e.detail}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}