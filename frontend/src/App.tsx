import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { playRimeAudio, speakWithBrowser, stopSpeaking } from "./audio/TtsPlayer";
import { SpeechService, type SpeechStatus } from "./speech/SpeechService";
import type { MemoryRecord, PipelineEvent, ServiceConfig, SessionState, TurnResponse } from "./types";
import {
  deriveContextMemo,
  derivePanelCopy,
  deriveProgress,
  deriveSessionPhase,
  deriveSupportLevel,
  deriveTimeline,
  deriveVoicePhase,
  deriveYouCanSay,
  SESSION_PILLS,
  VOICE_PILL,
  VOICE_PILLS,
  type PriorWrong,
  type SayAction,
} from "./present";
import { MemoryTimeline } from "./components/MemoryTimeline";
import { ReasoningWorkspace } from "./components/ReasoningWorkspace";
import { SystemView } from "./components/SystemView";
import { VoiceSessionPanel } from "./components/VoiceSessionPanel";
import { YouCanSay } from "./components/YouCanSay";

const STUDENT_KEY = "mathtalk.student";

export default function App() {
  const [config, setConfig] = useState<ServiceConfig | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [lastEvents, setLastEvents] = useState<PipelineEvent[]>([]);
  const [lastSpoken, setLastSpoken] = useState("");
  const [latency, setLatency] = useState(0);
  const [localVoice, setLocalVoice] = useState("idle");
  const [busy, setBusy] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsMode, setTtsMode] = useState<"rime" | "browser" | null>(null);
  const [ttsNote, setTtsNote] = useState("");
  const [micStatus, setMicStatus] = useState<SpeechStatus>("idle");
  const [started, setStarted] = useState(false);
  const [typed, setTyped] = useState("");
  const [history, setHistory] = useState<{ speaker: string; text: string }[]>([]);
  const [storedMemories, setStoredMemories] = useState<MemoryRecord[]>([]);
  const [initError, setInitError] = useState("");
  const [lastInterim, setLastInterim] = useState("");
  const [startTime, setStartTime] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [studentId] = useState(() => localStorage.getItem(STUDENT_KEY) || "demo-student-001");

  const speechRef = useRef<SpeechService | null>(null);
  const busyRef = useRef(false);
  const sessionRef = useRef<SessionState | null>(null);
  const speakingRef = useRef(false);
  const lastInterimRef = useRef(0);
  const priorWrongRef = useRef<Record<string, PriorWrong>>({});

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  useEffect(() => {
    if (!startTime) return;
    const id = window.setInterval(() => setElapsed(Date.now() - startTime), 1000);
    return () => window.clearInterval(id);
  }, [startTime]);

  /* ---------------- voice plumbing ---------------- */
  const reportVoice = useCallback(
    (status: string) => {
      setLocalVoice(status);
      if (sessionRef.current) api.setVoiceStatus(studentId, status).catch(() => {});
    },
    [studentId]
  );

  const refreshMemories = useCallback(() => {
    api
      .getMemories(studentId)
      .then((r) => setStoredMemories(r.memories as MemoryRecord[]))
      .catch(() => {});
  }, [studentId]);

  const beginListening = useCallback(() => {
    if (sessionRef.current?.paused) return;
    speechRef.current?.listen();
  }, []);

  const stopVoice = useCallback(() => {
    speechRef.current?.stop_listening();
    stopSpeaking();
    setSpeaking(false);
  }, []);

  /* ---------------- speaking (Rime primary) ---------------- */
  const speakText = useCallback(
    async (text: string) => {
      speakingRef.current = true;
      setSpeaking(true);
      reportVoice("SPEAKING");
      if (ttsMode === "rime") {
        try {
          const res = await api.speak(text);
          await playRimeAudio(res.audio, res.mime);
        } catch (e) {
          // Rime unavailable at runtime → browser fallback, surfaced honestly
          const msg = e instanceof ApiError ? e.message : "Rime unavailable";
          setTtsNote(`Rime failed at runtime (${msg}); using browser fallback.`);
          await speakWithBrowser(text);
        }
      } else {
        await speakWithBrowser(text);
      }
      speakingRef.current = false;
      setSpeaking(false);
      // return to listening (unless paused)
      if (!sessionRef.current?.paused) beginListening();
      reportVoice("LISTENING");
    },
    [ttsMode, reportVoice, beginListening]
  );

  /* ---------------- turn handling ---------------- */
  const applyResponse = useCallback(
    (r: TurnResponse) => {
      // Capture the previous (now superseded) analysis for the self-correction view.
      const prev = sessionRef.current;
      if (
        prev?.current_problem &&
        prev.verification_result &&
        prev.verification_result.verdict !== "correct"
      ) {
        priorWrongRef.current[prev.current_problem.problem_id] = {
          verdict: prev.verification_result.verdict,
          finalAnswer: prev.verification_result.student_answer ?? null,
          claims: (prev.verification_result.claims ?? []).map((c) => ({ text: c.text, status: c.status })),
        };
      }
      setSession(r.state);
      sessionRef.current = r.state;
      setLastEvents(r.pipeline_events || []);
      setLatency(r.latency_ms);
      if (r.spoken) {
        setLastSpoken(r.spoken);
        setHistory((prev) => [...prev, { speaker: "system", text: r.spoken }].slice(-80));
      }
      refreshMemories();
      // speech is fire-and-forget: it must never block the interaction loop
      if (r.spoken) void speakText(r.spoken);
    },
    [refreshMemories, speakText]
  );

  const sendTurn = useCallback(
    async (text: string, source: "speech" | "text") => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setHistory((prev) => [...prev, { speaker: "student", text }].slice(-80));
      reportVoice("PROCESSING");
      speechRef.current?.stop_listening();
      try {
        const r = await api.sendTurn(studentId, text, source);
        applyResponse(r);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "network error";
        setLastSpoken(`I had trouble reaching MathTalk: ${msg}. Please try again.`);
        setHistory((prev) => [...prev, { speaker: "system", text: `[error] ${msg}` }].slice(-80));
        reportVoice("LISTENING");
        beginListening();
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [studentId, applyResponse, reportVoice, beginListening]
  );

  const sendCommand = useCallback(
    async (intent: string, option?: string) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      reportVoice("PROCESSING");
      speechRef.current?.stop_listening();
      try {
        const r = await api.sendCommand(studentId, intent, option);
        applyResponse(r);
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : "network error";
        setLastSpoken(`Command failed: ${msg}`);
        setHistory((prev) => [...prev, { speaker: "system", text: `[error] ${msg}` }].slice(-80));
        reportVoice("LISTENING");
        beginListening();
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [studentId, applyResponse, reportVoice, beginListening]
  );

  const selectOption = useCallback(
    (label: string) => {
      // when a confirmation is pending, the two options are yes/no
      if (sessionRef.current?.pending_confirmation) {
        const low = label.toLowerCase();
        if (low === "yes" || low === "yep" || low.startsWith("yes")) return void sendCommand("confirm_yes");
        if (low === "no" || low === "nope" || low.startsWith("no")) return void sendCommand("confirm_no");
      }
      return void sendCommand("select_option", label);
    },
    [sendCommand]
  );

  const handleSayAction = useCallback(
    (item: SayAction) => {
      if (item.intent) void sendCommand(item.intent);
      else if (item.option) selectOption(item.option);
    },
    [sendCommand, selectOption]
  );

  const shownActions = session?.pending_confirmation
    ? ["Yes", "No"]
    : session?.available_actions || [];

  /* ---------------- speech service wiring ---------------- */
  useEffect(() => {
    const svc = new SpeechService({
      onFinal: (text) => {
        setLastInterim("");
        void sendTurn(text, "speech");
      },
      onInterim: (text) => {
        // Barge-in: if MathTalk is speaking and the student starts talking,
        // stop the current speech immediately.
        const now = Date.now();
        if (speakingRef.current && text.trim().length > 1 && now - lastInterimRef.current > 250) {
          lastInterimRef.current = now;
          stopSpeaking();
          speakingRef.current = false;
          setSpeaking(false);
        }
        setLastInterim(text);
      },
      onStatus: (status) => {
        setMicStatus(status);
        if (status === "unsupported") reportVoice("IDLE");
        if (status === "mic-error") {
          reportVoice("ERROR");
          setLastSpoken(
            "I couldn't access the microphone. You can still use the typed input below, or check your browser permissions."
          );
        }
      },
    });
    speechRef.current = svc;
    return () => {
      svc.cancel_listening();
    };
  }, [sendTurn, reportVoice]);

  /* ---------------- initialisation ---------------- */
  useEffect(() => {
    (async () => {
      try {
        const cfg = await api.getConfig();
        setConfig(cfg);
        setTtsMode(cfg.rime.configured ? "rime" : "browser");
        if (!cfg.rime.configured) {
          setTtsNote(
            "Rime is not configured (RIME_API_KEY missing) — using browser speech as a clearly-labelled fallback."
          );
        }
        const r = await api.startSession(studentId);
        setSession(r.state);
        sessionRef.current = r.state;
        setLastSpoken(r.spoken);
        setHistory([{ speaker: "system", text: r.spoken }]);
        refreshMemories();
      } catch (e) {
        setInitError(e instanceof ApiError ? e.message : String(e));
      }
    })();
  }, [studentId, refreshMemories]);

  /* ---------------- voice-first entry ---------------- */
  const startVoiceSession = useCallback(() => {
    setStarted(true);
    setStartTime(Date.now());
    speechRef.current?.listen();
    const welcome = lastSpoken || session?.last_spoken || "Welcome to MathTalk.";
    void speakText(welcome);
  }, [lastSpoken, session, speakText]);

  /* ---------------- keyboard shortcuts ---------------- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "button") return;
      const actions = session?.available_actions || [];
      const k = e.key.toLowerCase();
      if (k >= "1" && k <= "9") {
        const idx = parseInt(k, 10) - 1;
        if (actions[idx]) {
          e.preventDefault();
          void selectOption(actions[idx]);
          return;
        }
      }
      const map: Record<string, string> = {
        h: "help",
        r: "repeat",
        b: "go_back",
        g: "go_home",
        s: "stop",
        u: "resume",
        e: "end_session",
        n: "next_problem",
        t: "try_again",
      };
      if (map[k]) {
        e.preventDefault();
        void sendCommand(map[k]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [session, selectOption, sendCommand]);

  /* ---------------- demo reset ---------------- */
  const resetDemo = useCallback(async () => {
    stopVoice();
    priorWrongRef.current = {};
    try {
      await api.resetDemo(studentId);
      const r = await api.startSession(studentId, true);
      setStarted(true);
      setStartTime(Date.now());
      applyResponse(r);
      speechRef.current?.listen();
    } catch (e) {
      setInitError(e instanceof ApiError ? e.message : String(e));
    }
  }, [studentId, stopVoice, applyResponse]);

  /* ---------------- derived presentation ---------------- */
  const voice = session?.paused ? "PAUSED" : localVoice;
  const micUnavailable = micStatus === "unsupported" || micStatus === "mic-error";
  const phase = deriveVoicePhase(voice, speaking, busy, Boolean(session?.paused));
  const memoryActive = lastEvents.some((e) => e.stage === "memory" && e.ok);
  const priorWrong = session?.current_problem ? priorWrongRef.current[session.current_problem.problem_id] : undefined;
  const hasPriorWrong = Boolean(priorWrong);
  const sessionPhase = deriveSessionPhase(session, phase, memoryActive, hasPriorWrong);
  const copy = derivePanelCopy(sessionPhase, hasPriorWrong);
  const pill = VOICE_PILL[phase];
  const memo = deriveContextMemo(session, storedMemories);
  const steps = deriveTimeline(session, priorWrong);
  const progress = deriveProgress(session, elapsed);
  const support = deriveSupportLevel(session);
  const sayItems = deriveYouCanSay(session);
  const transcript = lastInterim || session?.reasoning_transcript || "";

  /* ---------------- render ---------------- */
  if (initError) {
    return (
      <div className="app-shell error-screen" role="alert">
        <h1>MathTalk could not start</h1>
        <p>{initError}</p>
        <p className="muted">
          Make sure the backend is running (<code>./run.sh</code>), then reload this page.
        </p>
      </div>
    );
  }

  if (!started) {
    return (
      <div className="app-shell start-screen">
        <main className="start-card" id="main">
          <p className="start-brand">
            MathTalk<span className="brand-dot">.</span>
          </p>
          <h1>Welcome to MathTalk</h1>
          <p>A voice-first, reasoning-aware mathematics tutor.</p>
          <p className="muted">
            MathTalk is fully operable by voice — no mouse or keyboard required. Your browser will ask
            for microphone permission.
          </p>
          <button className="start-btn" onClick={startVoiceSession} autoFocus>
            Start with microphone
          </button>
          {ttsNote && <p className="muted small">{ttsNote}</p>}
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="sr-announcer" aria-live="assertive">
        {lastSpoken || session?.last_spoken || ""}
      </div>
      <VoiceSessionPanel
        phase={phase}
        pill={pill}
        headline={copy.headline}
        subtitle={copy.subtitle}
        transcript={transcript}
        listening={phase === "listening"}
        memo={memo}
        studentId={studentId}
        sessionNumber={session?.session_number ?? null}
        micUnavailable={micUnavailable}
        voicePills={VOICE_PILLS}
        sessionPills={SESSION_PILLS}
        activeVoice={phase}
        activeSession={sessionPhase}
      />
      <main id="main" className="workspace">
        <ReasoningWorkspace
          session={session}
          steps={steps}
          tutorMessage={lastSpoken || session?.last_spoken || ""}
          progress={progress}
          support={support}
        />
        <YouCanSay items={sayItems} disabled={busy} onAction={handleSayAction} />
        <MemoryTimeline
          studentId={studentId}
          detected={Boolean(session?.misconception?.detected)}
          misconceptionType={session?.misconception?.misconception_type || ""}
          problemId={session?.current_problem?.problem_id || ""}
        />
        <SystemView
          session={session}
          config={config}
          events={lastEvents}
          memories={storedMemories}
          latency={latency}
          studentId={studentId}
          busy={busy}
          paused={Boolean(session?.paused)}
          actions={shownActions}
          typed={typed}
          onTypedChange={setTyped}
          onTypedSend={() => {
            if (typed.trim()) {
              void sendTurn(typed.trim(), "text");
              setTyped("");
            }
          }}
          onSelect={selectOption}
          onCommand={(i) => void sendCommand(i)}
          onReset={() => void resetDemo()}
          history={history}
        />
      </main>
    </div>
  );
}
