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

  const problem = session?.current_problem;
  const completed = session?.session_progress.problems_correct ?? 0;
  const totalProblems = Math.max(progress.total, 1);
  const progressPercent = Math.min(100, Math.round((progress.current / totalProblems) * 100));
  const transcriptLabel = lastInterim || session?.reasoning_transcript || "Tap the microphone or explain your next step aloud.";
  const tutorMessage = lastSpoken || session?.last_spoken || "I'm ready when you are.";
  const statusText = phase === "speaking" ? "AI Tutor is Speaking" : phase === "thinking" ? "AI Tutor is Thinking" : phase === "paused" ? "Voice Paused" : "AI Tutor is Listening";
  const primaryAction = shownActions[0] || "Continue";
  const historyItems = history.filter((item) => item.speaker === "student").slice(-3).reverse();

  const readAloud = (text: string) => void speakText(text);
  const toggleVoice = () => {
    if (phase === "listening") {
      stopVoice();
      reportVoice("IDLE");
      return;
    }
    if (!started) {
      startVoiceSession();
      return;
    }
    beginListening();
    reportVoice("LISTENING");
  };

  return (
    <div className="tutor-app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="sr-announcer" aria-live="assertive">
        {lastSpoken || session?.last_spoken || ""}
      </div>
      <header className="topbar">
        <div className="brand-lockup" aria-label="MathTalk Practice Tutor">
          <span className="brand-mark" aria-hidden="true">∿</span>
          <span className="brand-name">MathTalk</span>
          <span className="brand-divider" />
          <span className="brand-copy"><strong>MathTalk</strong><small>Practice Tutor</small></span>
        </div>
        <div className="top-actions">
          <button className={`voice-status ${phase === "listening" ? "is-listening" : ""}`} onClick={toggleVoice} aria-pressed={phase === "listening"}>
            <span aria-hidden="true">♩</span> {phase === "listening" ? "Voice Active" : "Start Voice"}
          </button>
          <button className="icon-button" onClick={() => readAloud(tutorMessage)} aria-label="Replay tutor response">◖))</button>
          <button className="avatar" aria-label="Student profile">M</button>
        </div>
      </header>

      <main id="main" className="page-content">
        <section className="session-card" aria-label="Voice session progress">
          <div className="session-topline"><span>◉ &nbsp;Voice Session</span><div className="access-tools"><button aria-label="Decrease text size">A−</button><button aria-label="Increase text size">A+</button><button aria-label="Contrast settings">◐</button></div></div>
          <h1>Good morning, {studentId === "demo-student-001" ? "Maya" : "there"}</h1>
          <div className="problem-progress"><strong>▣ &nbsp;Problem {progress.current} of {totalProblems}{problem?.subtopic ? ` • ${problem.subtopic}` : ""}</strong><strong>{progressPercent}% Completed</strong></div>
          <div className="progress-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent}><span style={{ width: `${progressPercent}%` }} /></div>
        </section>

        <section className="surface problem-card" aria-labelledby="problem-heading">
          <div className="section-heading"><span className="eyebrow">▣ &nbsp; Current Problem</span><button className="listen-button" onClick={() => readAloud(problem?.prompt || problem?.display || "")}>◖)) &nbsp;Listen</button></div>
          <div className="equation-box"><span id="problem-heading">{problem?.ask_question || "Choose a practice mode to begin"}</span><strong>{problem?.display || "MathTalk is ready"}</strong></div>
          <div className="spoken-equivalent"><span aria-hidden="true">◉</span><div><strong>Spoken Equivalent:</strong><p>“{problem?.prompt || "Tell me what you would like to practice."}”</p></div></div>
        </section>

        <section className="surface voice-deck" aria-label="Voice input">
          <span className={`voice-badge ${phase}`}>{phase === "thinking" ? "◌" : phase === "speaking" ? "◖))" : "◌"} &nbsp;{statusText}…</span>
          <button className={`microphone ${phase}`} onClick={toggleVoice} disabled={busy} aria-label={phase === "listening" ? "Stop listening" : "Start listening"}>♩</button>
          <div className="sound-bars" aria-hidden="true"><i /><i /><i /><i /><i /></div>
          <p className="voice-prompt">Tap mic or say <strong>“Hey MathTalk”</strong> to speak</p>
          <div className="student-said"><span aria-hidden="true">♧</span><div><strong>You said:</strong><p>“{transcriptLabel}”</p></div></div>
          <label className="typed-entry"><span className="visually-hidden">Type your reasoning</span><input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Or type your reasoning" onKeyDown={(e) => { if (e.key === "Enter" && typed.trim()) { void sendTurn(typed.trim(), "text"); setTyped(""); } }} /><button onClick={() => { if (typed.trim()) { void sendTurn(typed.trim(), "text"); setTyped(""); } }} disabled={!typed.trim() || busy}>Send</button></label>
          {micUnavailable && <p className="notice">Microphone unavailable. You can continue with typed reasoning.</p>}
        </section>

        <section className="surface tutor-card" aria-labelledby="tutor-heading">
          <div className="tutor-header"><div className="tutor-title"><span className="tutor-icon" aria-hidden="true">▣</span><div><h2 id="tutor-heading">MathTalk Tutor</h2><span>● Voice Verified Response</span></div></div><button className="replay" onClick={() => readAloud(tutorMessage)}>◴ 0.8x &nbsp; ↻ Repeat</button></div>
          <div className="tutor-response">{tutorMessage}</div>
          <ol className="step-list">
            {steps.map((step) => <li key={step.id} className={`learning-step ${step.status}`}><span className="step-number">{step.status === "verified" ? "✓" : step.index}</span><div><strong>{step.index === 1 ? "Step 1" : step.status === "pending" ? `Step ${step.index}` : "Current Focus"}: {step.title}</strong><p>{step.claims.map((claim) => claim.text).join(" · ") || step.calloutBody || "Tell MathTalk what you would do next."}</p></div>{step.status !== "pending" && <button onClick={() => readAloud(step.claims.map((claim) => claim.text).join(". ") || step.calloutBody)} aria-label={`Listen to ${step.title}`}>◖))</button>}</li>)}
            {steps.length === 0 && <li className="learning-step pending"><span className="step-number">1</span><div><strong>Your next step</strong><p>Explain how you would solve the equation.</p></div></li>}
          </ol>
        </section>

        <section className="action-area" aria-label="Learning actions">
          <button className="primary-action" disabled={busy} onClick={() => selectOption(primaryAction)}>✓ &nbsp;{primaryAction}</button>
          <div className="secondary-actions"><button onClick={() => void sendCommand("REQUEST_HINT")} disabled={busy}>♧ &nbsp;Need Hint</button><button onClick={() => void sendCommand("REPEAT")} disabled={busy}>↻ &nbsp;Repeat Question</button></div>
        </section>

        <section className="surface voice-log" aria-labelledby="log-heading"><div className="log-heading"><h2 id="log-heading">▧ &nbsp; Today’s Voice Log</h2><span>{completed} Solved</span></div>{historyItems.length ? historyItems.map((item, index) => <article key={`${item.text}-${index}`}><strong>{item.text}</strong><small>Voice response {historyItems.length - index} • {session?.verification_result?.verdict === "correct" ? "verified" : "in progress"}</small></article>) : <article><strong>Your spoken work will appear here</strong><small>MathTalk checks each step, not just the answer.</small></article>}</section>
      </main>
      <nav className="bottom-nav" aria-label="Primary navigation"><button className="active">⌂<span>Practice</span></button><button onClick={() => document.getElementById("log-heading")?.scrollIntoView({ behavior: "smooth" })}>♧<span>History</span></button><button onClick={() => document.querySelector(".session-card")?.scrollIntoView({ behavior: "smooth" })}>⌁<span>Progress</span></button><button onClick={() => void resetDemo()}>☷<span>Reset</span></button></nav>
    </div>
  );
}
