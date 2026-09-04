import type { TimelineStep } from "../present";
import type { MathClaim } from "../types";

function eqParts(claim: MathClaim): { left: string; bad: string | null; whole: string } {
  const idx = claim.text.indexOf("=");
  if (idx > 0) {
    const rhs = claim.text.slice(idx + 1).trim();
    // Underline the numeric right-hand side when it is a plain value.
    if (/^-?\d+(\.\d+)?(\/\d+)?$/.test(rhs)) {
      return { left: claim.text.slice(0, idx + 1), bad: rhs, whole: claim.text };
    }
  }
  return { left: "", bad: null, whole: claim.text };
}

function indicator(step: TimelineStep): { glyph: string; cls: string } {
  if (step.status === "verified") return { glyph: "✓", cls: "step-ind-ok" };
  if (step.status === "self-corrected") return { glyph: "↻", cls: "step-ind-ok" };
  if (step.status === "needs-look") return { glyph: "?", cls: "step-ind-bad" };
  return { glyph: String(step.index), cls: "step-ind-pending" };
}

function badge(step: TimelineStep): { text: string; cls: string } | null {
  if (step.status === "verified") return { text: "✓ VERIFIED", cls: "step-badge-ok" };
  if (step.status === "self-corrected") return { text: "↻ SELF-CORRECTED", cls: "step-badge-ok" };
  if (step.status === "needs-look") return { text: "? NEEDS ANOTHER LOOK", cls: "step-badge-bad" };
  return null;
}

/** One reasoning-timeline step: title, badge, equation(s), verification, supportive callout. */
export function StepCard(props: { step: TimelineStep; last: boolean }) {
  const { step, last } = props;
  const ind = indicator(step);
  const b = badge(step);
  const flaggedClaim = step.flagged ? step.claims.find((c) => c.status === "contradicted") || step.claims[step.claims.length - 1] : undefined;

  return (
    <li className={`step ${step.status === "needs-look" ? "step-flagged" : ""}`}>
      <div className="step-rail" aria-hidden="true">
        <span className={`step-ind ${ind.cls}`}>{ind.glyph}</span>
        {!last && <span className="step-line" />}
      </div>

      <div className="step-body">
        <div className="step-head">
          <h3 className="step-title">
            {String(step.index).padStart(2, "0")} {step.title}
          </h3>
          {b && <span className={`step-badge ${b.cls}`}>{b.text}</span>}
        </div>

        {step.claims.length === 0 && step.status === "pending" && (
          <p className="step-pending">Waiting for this step…</p>
        )}

        {step.claims.map((c, i) => {
          const parts = eqParts(c);
          const bad = c === flaggedClaim || c.status === "contradicted";
          return (
            <div key={i} className={`eq${bad ? " eq-bad" : ""}`}>
              {step.selfCorrected && step.priorText && i === 0 && (
                <span className="eq-prior">{step.priorText}</span>
              )}
              {parts.bad && bad ? (
                <>
                  {parts.left} <span className="eq-underline">{parts.bad}</span>
                </>
              ) : (
                c.text
              )}
            </div>
          );
        })}

        {step.flagged && step.calloutBody && (
          <div className="callout">
            <span className="callout-icon" aria-hidden="true">
              ?
            </span>
            <div className="callout-body">
              <h4>{step.calloutTitle}</h4>
              <p>{step.calloutBody}</p>
            </div>
          </div>
        )}

        {step.patternTag && <span className="pattern-tag">{step.patternTag}</span>}

        {step.verificationLines.length > 0 && (
          <div className="ver-lines">
            {step.verificationLines.map((line, i) => (
              <p key={i} className="ver-line">
                <b>VERIFICATION</b> · {line}
              </p>
            ))}
          </div>
        )}
      </div>
    </li>
  );
}
