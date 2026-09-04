import type { VoicePhase } from "../present";

/**
 * Large voice orb. Pure presentation: the variant is derived from real
 * voice/speaking/busy state by the parent via present.ts.
 */
export function VoiceOrb(props: { phase: VoicePhase }) {
  const { phase } = props;
  const animated = phase === "listening" || phase === "thinking";
  return (
    <div className={`orb orb-${phase}`} role="status" aria-live="polite" aria-label={`Voice state: ${phase}`}>
      {animated && (
        <>
          <span className="orb-ring" aria-hidden="true" />
          <span className="orb-ring" aria-hidden="true" />
          <span className="orb-ring" aria-hidden="true" />
        </>
      )}
      {phase === "speaking" && (
        <div className="orb-bars" aria-hidden="true">
          <span className="orb-bar" style={{ animationDelay: "0ms" }} />
          <span className="orb-bar" style={{ animationDelay: "140ms" }} />
          <span className="orb-bar" style={{ animationDelay: "280ms" }} />
          <span className="orb-bar" style={{ animationDelay: "70ms" }} />
          <span className="orb-bar" style={{ animationDelay: "210ms" }} />
        </div>
      )}
      <span className="orb-core" aria-hidden="true">
        <span className="orb-dot" />
      </span>
    </div>
  );
}
