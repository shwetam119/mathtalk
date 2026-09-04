import type { MemoryRecord, PipelineEvent, ServiceConfig, SessionState } from "../types";
import {
  InputPanel,
  InterventionPanel,
  MemoryPanel,
  MisconceptionPanel,
  OptionsPanel,
  PipelineView,
  TranscriptLog,
} from "./Panels";

/**
 * Collapsible system view — preserves the DEMO 1.1 observability panels
 * (pipeline, diagnosis, intervention, memory, log) and the typed-input
 * fallback. Pure reuse of the existing Panels.tsx functionality.
 */
export function SystemView(props: {
  session: SessionState | null;
  config: ServiceConfig | null;
  events: PipelineEvent[];
  memories: MemoryRecord[];
  latency: number;
  studentId: string;
  busy: boolean;
  paused: boolean;
  actions: string[];
  typed: string;
  onTypedChange: (value: string) => void;
  onTypedSend: () => void;
  onSelect: (label: string) => void;
  onCommand: (intent: string) => void;
  onReset: () => void;
  history: { speaker: string; text: string }[];
}) {
  const {
    session,
    config,
    events,
    memories,
    latency,
    studentId,
    busy,
    paused,
    actions,
    typed,
    onTypedChange,
    onTypedSend,
    onSelect,
    onCommand,
    onReset,
    history,
  } = props;

  return (
    <details className="sysview">
      <summary>System view — pipeline · diagnosis · memory · log · typed input (teacher/judge detail)</summary>
      <div className="sysview-body">
        <OptionsPanel actions={actions} onSelect={onSelect} onCommand={onCommand} disabled={busy} paused={paused} />
        <section className="panel" aria-labelledby="typed-title">
          <h2 id="typed-title">Type instead (fallback)</h2>
          <div className="typed-row">
            <input
              type="text"
              value={typed}
              onChange={(e) => onTypedChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && typed.trim()) {
                  onTypedSend();
                }
              }}
              placeholder="Type your answer or a command…"
              aria-label="Typed input fallback"
              autoComplete="off"
            />
            <button
              className="ctrl-btn"
              onClick={onTypedSend}
              disabled={!typed.trim() || busy}
            >
              Send
            </button>
          </div>
          <div className="demo-row">
            <button className="ctrl-btn" onClick={onReset} title="Reset the demo learner">
              Reset demo learner
            </button>
            <span className="muted small">
              student: <code>{studentId}</code> · latency: {latency} ms
            </span>
          </div>
        </section>
        <InputPanel session={session} />
        <PipelineView events={events} />
        <MisconceptionPanel
          detected={Boolean(session?.misconception?.detected)}
          type={session?.misconception?.misconception_type || ""}
          confidence={session?.misconception?.confidence || 0}
          evidence={session?.misconception?.evidence || ""}
          trap={Boolean(session?.misconception?.correct_answer_trap)}
        />
        <InterventionPanel intervention={session?.selected_intervention} />
        <MemoryPanel
          retrieved={session?.retrieved_memories || []}
          stored={memories}
          provider={config?.memory?.provider || "…"}
          providerReason={config?.memory?.reason || "…"}
        />
        <TranscriptLog entries={history} />
      </div>
    </details>
  );
}
