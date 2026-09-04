import type {
  Intervention,
  MemoryRecord,
  PipelineEvent,
  Problem,
  ServiceConfig,
  SessionState,
  StructuredReasoning,
  VerificationResult,
} from "../types";

/* ------------------------------------------------------------------ */
/* Status bar                                                          */
/* ------------------------------------------------------------------ */
export function StatusBar(props: {
  session: SessionState | null;
  config: ServiceConfig | null;
  localVoice: string;
  ttsMode: "rime" | "browser" | null;
}) {
  const { session, config, localVoice, ttsMode } = props;
  const voice = session?.paused ? "PAUSED" : (localVoice || session?.voice_status || "IDLE");
  return (
    <header className="statusbar" role="banner">
      <div className="statusbar-title">
        <h1>MathTalk</h1>
        <span className="subtitle">voice-first mathematics tutor</span>
      </div>
      <ul className="statusbar-chips" aria-label="System status">
        <li className="chip">
          <span className="chip-label">State</span>
          <strong>{session?.app_state?.replace(/_/g, " ") || "…"}</strong>
        </li>
        <li className="chip">
          <span className="chip-label">Session</span>
          <strong>#{session?.session_number ?? "…"}</strong>
        </li>
        <li className="chip">
          <span className="chip-label">Mode</span>
          <strong>{session?.mode || "—"}</strong>
        </li>
        <li className="chip">
          <span className="chip-label">Topic</span>
          <strong>{session?.topic || "—"}</strong>
        </li>
        <li className="chip">
          <span className="chip-label">Difficulty</span>
          <strong>{session?.difficulty || "—"}</strong>
        </li>
        <li className={`chip voice-${voice.toLowerCase()}`}>
          <span className="chip-label">Voice</span>
          <strong>{voice}</strong>
        </li>
        <li className="chip">
          <span className="chip-label">Memory</span>
          <strong>{config?.memory?.provider || "…"}</strong>
        </li>
        <li className={`chip ${ttsMode === "rime" ? "ok" : "warn"}`}>
          <span className="chip-label">TTS</span>
          <strong>{ttsMode === "rime" ? "Rime" : "browser fallback"}</strong>
        </li>
        <li className="chip">
          <span className="chip-label">LLM</span>
          <strong>{config?.llm?.configured ? config.llm.provider : "deterministic"}</strong>
        </li>
      </ul>
    </header>
  );
}

/* ------------------------------------------------------------------ */
/* Voice indicator                                                     */
/* ------------------------------------------------------------------ */
export function VoiceIndicator(props: { voice: string }) {
  const v = props.voice.toLowerCase();
  return (
    <div className={`voice-indicator ${v}`} role="status" aria-live="polite">
      <span className="voice-dot" aria-hidden="true" />
      <span>
        {v === "speaking" && "MathTalk is speaking"}
        {v === "processing" && "Processing your answer…"}
        {v === "listening" && "Listening — go ahead and speak"}
        {v === "paused" && "Paused"}
        {!["speaking", "processing", "listening", "paused"].includes(v) && "Voice idle"}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Pipeline stepper                                                    */
/* ------------------------------------------------------------------ */
const STAGES: { key: string; label: string }[] = [
  { key: "stt", label: "Speech → text" },
  { key: "interpreter", label: "Reasoning interpretation" },
  { key: "verifier", label: "Mathematical verification (SymPy)" },
  { key: "misconception", label: "Misconception detection" },
  { key: "memory", label: "Qdrant learner memory" },
  { key: "policy", label: "Adaptive tutoring policy" },
  { key: "response", label: "Natural-language response" },
];

export function PipelineView(props: { events: PipelineEvent[] }) {
  const byStage = new Map(props.events.map((e) => [e.stage, e]));
  return (
    <section className="panel" aria-labelledby="pipeline-title">
      <h2 id="pipeline-title">AI pipeline</h2>
      <ol className="pipeline">
        {STAGES.map((s, i) => {
          const ev = byStage.get(s.key);
          return (
            <li key={s.key} className={`pipe-step ${ev ? (ev.ok ? "done" : "error") : "pending"}`}>
              <span className="pipe-index" aria-hidden="true">
                {ev ? (ev.ok ? "✓" : "!") : i + 1}
              </span>
              <div className="pipe-body">
                <span className="pipe-label">{ev?.label || s.label}</span>
                {ev && <span className="pipe-detail">{ev.detail}</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Problem                                                             */
/* ------------------------------------------------------------------ */
export function ProblemPanel(props: { problem: Problem | null | undefined }) {
  const p = props.problem;
  if (!p) {
    return (
      <section className="panel" aria-labelledby="problem-title">
        <h2 id="problem-title">Problem</h2>
        <p className="muted">No problem yet — navigate to Practice to begin.</p>
      </section>
    );
  }
  return (
    <section className="panel problem-panel" aria-labelledby="problem-title">
      <h2 id="problem-title">Problem</h2>
      <p className="problem-prompt">{p.prompt}</p>
      {p.display && <code className="problem-display">{p.display}</code>}
      <div className="meta-row">
        <span className="tag">{p.subtopic}</span>
        <span className="tag">{p.difficulty}</span>
        {p.concepts.map((c) => (
          <span key={c} className="tag muted-tag">
            {c}
          </span>
        ))}
      </div>
      <p className="answer-hint">
        Expected answer: <strong>{p.expected_answer}</strong> (shown on the dashboard for
        teachers/judges — never spoken to the student).
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Input understanding (direct answers, step walk)                    */
/* ------------------------------------------------------------------ */
export function InputPanel(props: {
  session: SessionState | null | undefined;
}) {
  const s = props.session;
  const verdict = s?.verification_result?.verdict;
  const step = s?.step_walk;
  return (
    <section className="panel" aria-labelledby="input-title">
      <h2 id="input-title">Input understanding</h2>
      <div className="meta-row">
        <span className="tag">input type: {s?.input_type ? s.input_type.replace(/_/g, " ") : "—"}</span>
        {s?.extracted_answer != null && s.extracted_answer !== "" && (
          <span className="tag">student answer: <code>{s.extracted_answer}</code></span>
        )}
        {verdict && (
          <span className={`status-pill ${verdict === "correct" ? "ok" : "bad"}`}>
            {verdict === "correct" ? "✓ CORRECT" : `✗ ${verdict.toUpperCase()}`}
          </span>
        )}
      </div>
      {step && (
        <p className="muted small">
          Guided step walk · step {step.step_index + 1} of {step.total_steps}
          {step.step_attempts > 0 ? ` · ${step.step_attempts} attempt(s) on this step` : ""}
        </p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Reasoning + verification                                            */
/* ------------------------------------------------------------------ */
const CLAIM_STATUS = {
  verified: "ok",
  contradicted: "bad",
  uncertain: "warn",
  unsupported: "muted",
} as Record<string, string>;

export function ReasoningPanel(props: {
  transcript: string;
  reasoning: StructuredReasoning | null | undefined;
  verification: VerificationResult | null | undefined;
}) {
  const { transcript, reasoning, verification } = props;
  return (
    <section className="panel" aria-labelledby="reasoning-title">
      <h2 id="reasoning-title">Student reasoning</h2>
      <p className="reasoning-transcript">“{transcript || "—"}”</p>
      {reasoning && (
        <div className="reasoning-block">
          <div className="meta-row">
            <span className="tag">{reasoning.concept}</span>
            <span className="tag">{reasoning.reasoning_quality}</span>
            <span className="tag">source: {reasoning.source}</span>
          </div>
          {reasoning.student_actions.length > 0 && (
            <div className="actions-row">
              {reasoning.student_actions.map((a) => (
                <code key={a} className="action-chip">
                  {a}
                </code>
              ))}
            </div>
          )}
          <table className="claims-table">
            <caption className="visually-hidden">Verified mathematical claims</caption>
            <thead>
              <tr>
                <th scope="col">Claim</th>
                <th scope="col">Status</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {(reasoning.mathematical_claims.length ? reasoning.mathematical_claims : []).map((c, i) => (
                <tr key={i}>
                  <td>
                    <code>{c.text}</code>
                  </td>
                  <td>
                    <span className={`status-pill ${CLAIM_STATUS[c.status] || "muted"}`}>{c.status}</span>
                  </td>
                  <td className="muted">{c.reason}</td>
                </tr>
              ))}
              {reasoning.mathematical_claims.length === 0 && (
                <tr>
                  <td colSpan={3} className="muted">
                    No mathematical claims extracted.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          {verification && (
            <div className="verdict-row">
              <span className={`status-pill ${verification.verdict === "correct" ? "ok" : "bad"}`}>
                verdict: {verification.verdict}
              </span>
              <span className="muted">
                final answer: {verification.student_answer ?? "—"} · expected: {verification.expected_answer} ·
                plan valid: {verification.plan_valid === null ? "—" : String(verification.plan_valid)}
              </span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Misconception                                                       */
/* ------------------------------------------------------------------ */
function confidenceLevel(confidence: number): "low" | "mid" | "high" {
  if (confidence < 0.7) return "low"; // red/orange
  if (confidence <= 0.85) return "mid"; // amber
  return "high"; // green
}

export function MisconceptionPanel(props: {
  detected: boolean;
  type: string;
  confidence: number;
  evidence: string;
  trap: boolean;
}) {
  const { detected, type, confidence, evidence, trap } = props;
  return (
    <section className="panel" aria-labelledby="misconception-title">
      <h2 id="misconception-title">Misconception diagnosis</h2>
      {detected ? (
        <>
          <div className="meta-row">
            <span className="status-pill bad">{type.replace(/_/g, " ")}</span>
            {confidence > 0 && (
              <span
                className={`confidence-badge ${confidenceLevel(confidence)}`}
                title={evidence || "Confidence of the misconception diagnosis"}
              >
                {Math.round(confidence * 100)}% confidence
              </span>
            )}
            {trap && <span className="status-pill warn">correct answer trap</span>}
          </div>
          {evidence && <p className="evidence">{evidence}</p>}
        </>
      ) : (
        <p className="muted">No misconception detected.</p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Intervention                                                        */
/* ------------------------------------------------------------------ */
const LEVELS = ["Independent", "Review approach", "Hint", "Guided explanation", "Detailed solution"];

export function InterventionPanel(props: { intervention: Intervention | null | undefined }) {
  const iv = props.intervention;
  return (
    <section className="panel" aria-labelledby="intervention-title">
      <h2 id="intervention-title">Tutor intervention</h2>
      {iv ? (
        <>
          <div className="meta-row">
            <span className="status-pill ok">{iv.type.replace(/_/g, " ")}</span>
            <span className="tag">assistance: {LEVELS[iv.assistance_level] ?? iv.assistance_level}</span>
            {iv.memory_based && <span className="status-pill ok">memory-based</span>}
            {iv.targeted && !iv.memory_based && <span className="status-pill warn">targeted</span>}
          </div>
          <p className="intervention-message">{iv.message}</p>
          <p className="muted small">policy reason: {iv.reason}</p>
        </>
      ) : (
        <p className="muted">No intervention selected yet.</p>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Memory                                                              */
/* ------------------------------------------------------------------ */
export function MemoryPanel(props: {
  retrieved: MemoryRecord[];
  stored: MemoryRecord[];
  provider: string;
  providerReason: string;
}) {
  const { retrieved, stored, provider, providerReason } = props;
  return (
    <section className="panel" aria-labelledby="memory-title">
      <h2 id="memory-title">Learner memory</h2>
      <p className="muted small">
        backend: <strong>{provider}</strong> ({providerReason})
      </p>
      <h3>Retrieved this turn</h3>
      {retrieved.length === 0 ? (
        <p className="muted">None.</p>
      ) : (
        <ul className="memory-list">
          {retrieved.map((m) => (
            <li key={m.memory_id} className="memory-item">
              <div className="memory-head">
                <code>{m.memory_type}</code>
                <span className="tag">{m.status}</span>
                <span className="tag">score {(m.score ?? 0).toFixed(2)}</span>
              </div>
              <p className="memory-desc">{m.description}</p>
              <p className="muted small">
                {m.concept} · {m.topic} · {m.source_session || m.session_id}
              </p>
            </li>
          ))}
        </ul>
      )}
      <h3>Stored for this learner</h3>
      {stored.length === 0 ? (
        <p className="muted">None yet — solve a problem to create memories.</p>
      ) : (
        <ul className="memory-list">
          {stored.slice(0, 12).map((m) => (
            <li key={m.memory_id} className="memory-item">
              <div className="memory-head">
                <code>{m.memory_type}</code>
                <span className="tag">{m.status}</span>
              </div>
              <p className="memory-desc">{m.description}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Options + controls                                                  */
/* ------------------------------------------------------------------ */
export function OptionsPanel(props: {
  actions: string[];
  onSelect: (label: string) => void;
  onCommand: (intent: string) => void;
  disabled: boolean;
  paused: boolean;
}) {
  const { actions, onSelect, onCommand, disabled, paused } = props;
  return (
    <section className="panel" aria-labelledby="options-title">
      <h2 id="options-title">Say or select an option</h2>
      {paused ? (
        <p className="muted">Session paused. Say “resume” or press U.</p>
      ) : (
        <div className="option-grid" role="group" aria-label="Available options">
          {actions.map((a, i) => (
            <button
              key={a}
              className="option-btn"
              onClick={() => onSelect(a)}
              disabled={disabled}
              aria-label={`Option ${i + 1}: ${a}`}
            >
              <span className="option-num">{i + 1}</span>
              {a}
            </button>
          ))}
        </div>
      )}
      <div className="controls-row" role="group" aria-label="Global commands">
        <button className="ctrl-btn" onClick={() => onCommand("help")} title="H" aria-label="Help">
          Help
        </button>
        <button className="ctrl-btn" onClick={() => onCommand("repeat")} title="R" aria-label="Repeat last message">
          Repeat
        </button>
        <button className="ctrl-btn" onClick={() => onCommand("go_back")} title="B" aria-label="Go back">
          Back
        </button>
        <button className="ctrl-btn" onClick={() => onCommand("go_home")} title="G" aria-label="Go home">
          Home
        </button>
        <button className="ctrl-btn" onClick={() => onCommand(paused ? "resume" : "stop")} title="S/U" aria-label="Stop or resume">
          {paused ? "Resume" : "Stop"}
        </button>
        <button className="ctrl-btn" onClick={() => onCommand("end_session")} title="E" aria-label="End session">
          End
        </button>
      </div>
      <p className="muted small">
        Keyboard: <kbd>1–9</kbd> options · <kbd>H</kbd> help · <kbd>R</kbd> repeat · <kbd>B</kbd> back ·{" "}
        <kbd>G</kbd> home · <kbd>S</kbd> stop · <kbd>U</kbd> resume · <kbd>E</kbd> end
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Transcript log                                                      */
/* ------------------------------------------------------------------ */
export function TranscriptLog(props: { entries: { speaker: string; text: string }[] }) {
  return (
    <section className="panel" aria-labelledby="log-title">
      <h2 id="log-title">Conversation log</h2>
      {props.entries.length === 0 ? (
        <p className="muted">No turns yet.</p>
      ) : (
        <ul className="log-list">
          {props.entries.map((e, i) => (
            <li key={i} className={`log-entry ${e.speaker}`}>
              <span className="log-speaker">{e.speaker === "system" ? "MathTalk" : "Student"}:</span>{" "}
              <span>{e.text}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
