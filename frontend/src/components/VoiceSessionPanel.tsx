import type { ContextMemoModel } from "../present";
import type { VoicePhase } from "../present";
import { ContextMemo } from "./ContextMemo";
import { VoiceOrb } from "./VoiceOrb";

interface WalkPill {
  id: string;
  label: string;
  glyph: string;
}

/**
 * Dark left panel: voice orb, status pill, headline, live transcription,
 * context memo and the live "DEMO WALKTHROUGH · UI STATES" indicator.
 */
export function VoiceSessionPanel(props: {
  phase: VoicePhase;
  pill: string;
  headline: string;
  subtitle: string;
  transcript: string;
  listening: boolean;
  memo: ContextMemoModel;
  studentId: string;
  sessionNumber: number | null;
  micUnavailable: boolean;
  voicePills: readonly WalkPill[];
  sessionPills: readonly WalkPill[];
  activeVoice: string;
  activeSession: string;
}) {
  const {
    phase,
    pill,
    headline,
    subtitle,
    transcript,
    listening,
    memo,
    studentId,
    sessionNumber,
    micUnavailable,
    voicePills,
    sessionPills,
    activeVoice,
    activeSession,
  } = props;

  return (
    <aside className="voice-panel">
      <header className="vp-header">
        <span className="vp-dot" aria-hidden="true" />
        <span>MATHTALK • VOICE SESSION</span>
      </header>

      <div className="vp-center">
        <VoiceOrb phase={phase} />
        <div className={`vp-pill ${phase === "speaking" ? "vp-pill-speaking" : phase === "listening" ? "vp-pill-listening" : ""}`}>
          {phase === "speaking" ? "✓" : phase === "listening" ? "●" : "◇"} {pill}
        </div>
        <h2 className="vp-headline">{headline}</h2>
        <p className="vp-subtitle">{subtitle}</p>
      </div>

      <div className="vp-transcript" aria-live="polite" aria-label="Live transcription">
        <p className="vp-label">LIVE TRANSCRIPTION</p>
        <div className="vp-transcript-box">
          <span className="vp-bar" aria-hidden="true" />
          <p className={transcript ? "" : "vp-placeholder"}>
            {transcript || (listening ? "Listening…" : "No speech yet.")}
            {listening && <span className="vp-cursor" aria-hidden="true" />}
          </p>
        </div>
      </div>

      {micUnavailable && (
        <p className="vp-micnote" role="status">
          Microphone unavailable — type in the system view below, or check browser permissions.
        </p>
      )}

      <div className="vp-memo">
        <ContextMemo title={memo.title} body={memo.body} note={memo.note} />
      </div>

      <footer className="vp-footer">
        <p className="vp-session">
          student <code>{studentId}</code>
          {sessionNumber ? ` · session #${sessionNumber}` : ""}
        </p>
        <div className="vp-walk">
          <p className="vp-label">DEMO WALKTHROUGH · UI STATES</p>
          <div className="vp-pill-row" role="group" aria-label="Voice states">
            {voicePills.map((p) => (
              <span key={p.id} className={`walk-pill ${p.id === activeVoice ? "walk-active" : ""}`}>
                <span className="walk-glyph" aria-hidden="true">
                  {p.glyph}
                </span>
                {p.label}
              </span>
            ))}
          </div>
          <div className="vp-pill-row" role="group" aria-label="Session states">
            {sessionPills.map((p) => (
              <span key={p.id} className={`walk-pill ${p.id === activeSession ? "walk-active" : ""}`}>
                <span className="walk-glyph" aria-hidden="true">
                  {p.glyph}
                </span>
                {p.label}
              </span>
            ))}
          </div>
        </div>
      </footer>
    </aside>
  );
}
