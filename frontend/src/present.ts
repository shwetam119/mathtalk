/**
 * present.ts — pure presentation derivations.
 *
 * This module is the ONLY place where raw application state (SessionState,
 * MemoryRecord, pipeline events) is transformed into the visual model of the
 * approved UI (voice phase, headline copy, reasoning timeline, support level,
 * progress, context memo, "You can say" actions).
 *
 * Rules:
 *  - No network, no backend, no mutations.
 *  - Everything is derived from real state — nothing is mocked or fabricated.
 *  - The only constant is the approved demo-set size used purely for the
 *    progress-bar visual (segment/dot count), matching the approved design.
 */
import type { MathClaim, MemoryRecord, SessionState } from "./types";

/* ------------------------------------------------------------------ */
/* Constants (presentation only)                                       */
/* ------------------------------------------------------------------ */

/** Approved demo set size for the progress visual ("Problem 3 of 6", six segments). */
export const PROBLEM_SET_TOTAL = 6;

export const SUPPORT_LEVEL_LABELS = [
  "Independent",
  "Review approach",
  "Hint",
  "Guided explanation",
  "Detailed solution",
];

/** Friendly misconception copy used for pattern tags, callouts and the context memo. */
export const MISCONCEPTION_META: Record<string, { label: string; tendency: string; callout: string }> = {
  inverse_operation: {
    label: "inverse operations",
    tendency: "a tendency to add when subtracting is required",
    callout: "Your balance is right — check the operation",
  },
  equality_manipulation: {
    label: "keeping the equation balanced",
    tendency: "a tendency to change one side without the other",
    callout: "Keep both sides equal",
  },
  sign_error: {
    label: "sign errors",
    tendency: "a tendency to mix up plus and minus",
    callout: "Check the sign",
  },
  combine_unlike_terms: {
    label: "combining like terms",
    tendency: "a tendency to combine terms that don't match",
    callout: "Only like terms combine",
  },
  distribution_error: {
    label: "distribution",
    tendency: "a tendency to multiply only part of a bracket",
    callout: "Multiply every term in the bracket",
  },
  fraction_denominator: {
    label: "fraction denominators",
    tendency: "a tendency to add denominators directly",
    callout: "Common denominator first",
  },
  whole_part_confusion: {
    label: "whole-part confusion",
    tendency: "a tendency to confuse the total with the part",
    callout: "Favorable over total",
  },
  adding_probabilities: {
    label: "combining probabilities",
    tendency: "a tendency to add probabilities instead of multiplying",
    callout: "Multiply, don't add",
  },
  order_of_operations_error: {
    label: "order of operations",
    tendency: "a tendency to evaluate left to right",
    callout: "Precedence first",
  },
  arithmetic_error: {
    label: "arithmetic slips",
    tendency: "small arithmetic slips",
    callout: "Small slip — recompute",
  },
  unclear_reasoning: {
    label: "working through the steps",
    tendency: "a tendency to skip steps",
    callout: "Let's check the method",
  },
  formula_selection: {
    label: "formula selection",
    tendency: "a tendency to reach for the wrong formula",
    callout: "Check the formula",
  },
};

const DEFAULT_META = { label: "that pattern", tendency: "a pattern we are working on", callout: "Let's look closer" };

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

/* ------------------------------------------------------------------ */
/* Voice phase                                                         */
/* ------------------------------------------------------------------ */

export type VoicePhase = "ready" | "listening" | "thinking" | "speaking" | "paused" | "error";

export function deriveVoicePhase(voice: string, speaking: boolean, busy: boolean, paused: boolean): VoicePhase {
  if (paused) return "paused";
  if (speaking) return "speaking";
  if (busy || /processing/i.test(voice)) return "thinking";
  if (/listening/i.test(voice)) return "listening";
  if (/error/i.test(voice)) return "error";
  return "ready";
}

export const VOICE_PILL: Record<VoicePhase, string> = {
  ready: "READY",
  listening: "MICROPHONE OPEN",
  thinking: "THINKING",
  speaking: "TUTOR SPEAKING",
  paused: "MICROPHONE PAUSED",
  error: "MIC CHECK",
};

export const VOICE_PILLS = [
  { id: "ready", label: "Ready", glyph: "◇" },
  { id: "listening", label: "Listening", glyph: "●" },
  { id: "thinking", label: "Thinking", glyph: "◐" },
  { id: "speaking", label: "Speaking", glyph: "▶" },
] as const;

export const SESSION_PILLS = [
  { id: "reviewing", label: "Reviewing", glyph: "◈" },
  { id: "one-step", label: "One step to revisit", glyph: "⚑" },
  { id: "guiding", label: "Guiding", glyph: "◎" },
  { id: "your-turn", label: "Your turn", glyph: "✎" },
  { id: "solved", label: "Solved", glyph: "✓" },
  { id: "saved", label: "Saved", glyph: "◍" },
  { id: "retry", label: "Let's retry", glyph: "↻" },
] as const;

/* ------------------------------------------------------------------ */
/* Session phase (headline / walkthrough indicator)                    */
/* ------------------------------------------------------------------ */

export type SessionPhase =
  | "ready"
  | "listening"
  | "your-turn"
  | "reviewing"
  | "one-step"
  | "guiding"
  | "retry"
  | "solved"
  | "saved";

export interface PanelCopy {
  headline: string;
  subtitle: string;
}

const HEADLINES: Record<SessionPhase, PanelCopy> = {
  ready: { headline: "Ready", subtitle: "Say “Practice” to begin, or choose an option below." },
  listening: { headline: "Listening", subtitle: "Take your time. Explain your thinking out loud." },
  "your-turn": { headline: "Your turn", subtitle: "Tell me how you'd solve it — I'll check each step as you go." },
  reviewing: { headline: "Reviewing", subtitle: "Let's look at the method together before continuing." },
  "one-step": { headline: "One step to revisit", subtitle: "Your approach is sound. One step needs another look." },
  guiding: { headline: "Guiding", subtitle: "Let's take it one step at a time — no rush." },
  retry: { headline: "Let's try again", subtitle: "Small fix, then you're there. Focus on the flagged step." },
  solved: { headline: "Solved", subtitle: "Great work — your reasoning is verified." },
  saved: { headline: "Saved", subtitle: "What we learned is stored for next time." },
};

export function deriveSessionPhase(
  session: SessionState | null,
  phase: VoicePhase,
  memoryActive: boolean,
  hasPriorWrong: boolean
): SessionPhase {
  if (!session) return "ready";
  const verdict = session.verification_result?.verdict;
  const problem = Boolean(session.current_problem);

  if (verdict === "correct") return "solved";
  if (problem && session.step_walk) return "one-step";
  if (problem && session.misconception?.detected && verdict && verdict !== "correct") return "one-step";
  if (session.app_state === "INTERVENTION" && verdict && verdict !== "correct") return "retry";
  if (session.app_state === "REVIEW" || session.app_state === "DIAGNOSIS") return "reviewing";
  if (problem && session.assistance_level >= 2 && session.assistance_level <= 3) return "guiding";
  if (problem) return phase === "listening" ? "listening" : "your-turn";
  if (phase === "listening") return "listening";
  if (memoryActive) return "saved";
  return "ready";
}

export function derivePanelCopy(phase: SessionPhase, hasPriorWrong: boolean): PanelCopy {
  const copy = HEADLINES[phase];
  if (phase === "solved" && hasPriorWrong) {
    return { headline: copy.headline, subtitle: "You corrected that yourself. That is the part that lasts." };
  }
  return copy;
}

/* ------------------------------------------------------------------ */
/* Reasoning timeline                                                  */
/* ------------------------------------------------------------------ */

export type StepBucket = "strategy" | "undo-constant" | "solve" | "compute" | "other";

export interface TimelineStep {
  id: string;
  index: number;
  title: string;
  bucket: StepBucket;
  claims: MathClaim[];
  status: "verified" | "needs-look" | "pending" | "self-corrected";
  flagged: boolean;
  calloutTitle: string;
  calloutBody: string;
  patternTag: string;
  selfCorrected: boolean;
  priorText: string | null;
  verificationLines: string[];
}

export interface PriorWrong {
  verdict: string;
  finalAnswer: string | null;
  claims: { text: string; status: string }[];
}

const LINEAR_SKELETON: { id: string; bucket: StepBucket; title: string }[] = [
  { id: "strategy", bucket: "strategy", title: "Isolation strategy" },
  { id: "undo-constant", bucket: "undo-constant", title: "Undoing the constant" },
  { id: "solve", bucket: "solve", title: "Solving for x" },
];

const GENERIC_SKELETON: { id: string; bucket: StepBucket; title: string }[] = [
  { id: "setup", bucket: "strategy", title: "Set up" },
  { id: "work", bucket: "compute", title: "Work through" },
  { id: "final", bucket: "solve", title: "Final answer" },
];

function normEq(s: string | null | undefined): string {
  return (s || "").replace(/\s+/g, "");
}

function skeletonFor(problem: { concepts?: string[] }): { id: string; bucket: StepBucket; title: string }[] {
  const concept = problem.concepts?.[0] || "";
  return concept === "linear_equation" ? LINEAR_SKELETON : GENERIC_SKELETON;
}

/** Deterministically bucket one extracted claim into a timeline step. */
export function bucketClaim(claim: { text: string; operation?: string | null; expression?: string | null }, problem?: { display?: string } | null): StepBucket {
  const text = normEq(claim.text);
  const expr = normEq(claim.expression || "");
  const disp = problem ? normEq(problem.display) : "";

  if (disp && (text === disp || expr === disp || (text.length > disp.length && text.includes(disp)))) return "strategy";
  if (claim.operation === "solve") return "solve";
  if (/^x\s*=\s*-?\d/.test(text) || /x\s*=\s*-?\d/.test(expr)) return "solve";
  if (claim.operation === "add" || claim.operation === "subtract") return "undo-constant";
  if (/^\d*x\s*=\s*-?\d/.test(text) || /^\d*x\s*=\s*-?\d/.test(expr)) return "undo-constant";
  if (claim.operation === "divide") return "solve";
  if (claim.operation === "multiply") return "compute";
  return "other";
}

export function bucketClaimText(text: string, problem?: { display?: string } | null): StepBucket {
  return bucketClaim({ text, operation: undefined, expression: undefined }, problem);
}

function mapAffectedStep(affected: string): StepBucket | null {
  if (!affected) return null;
  const t = affected.toLowerCase();
  if (t.includes("isolation") || t.includes("constant") || t.includes("equality") || t.includes("balance") || t.includes("first")) {
    return "undo-constant";
  }
  if (t.includes("approach") || t.includes("plan") || t.includes("overall")) return "strategy";
  if (t.includes("solve") || t.includes("answer") || t.includes("coefficient") || t.includes("x")) return "solve";
  return null;
}

export function deriveTimeline(session: SessionState | null, priorWrong?: PriorWrong | null): TimelineStep[] {
  if (!session) return [];
  const problem = session.current_problem;
  if (!problem) return [];

  const claims: MathClaim[] =
    session.verification_result?.claims?.length
      ? session.verification_result.claims
      : session.structured_reasoning?.mathematical_claims ?? [];

  const cards: TimelineStep[] = skeletonFor(problem).map((s, i) => ({
    id: s.id,
    index: i + 1,
    title: s.title,
    bucket: s.bucket,
    claims: [],
    status: "pending",
    flagged: false,
    calloutTitle: "",
    calloutBody: "",
    patternTag: "",
    selfCorrected: false,
    priorText: null,
    verificationLines: [],
  }));

  for (const c of claims) {
    const b = bucketClaim(c, problem);
    const card = cards.find((k) => k.bucket === b) || cards.find((k) => k.bucket === "compute") || cards[cards.length - 1];
    if (card) card.claims.push(c);
  }

  const misconception = session.misconception;
  const verification = session.verification_result;
  const finalWrong = verification?.final_answer_correct === false;
  const planInvalid = verification?.plan_valid === false;

  // Which card is the problematic step?
  let flagged: TimelineStep | undefined;
  if (misconception?.detected) {
    const affectedText = normEq(misconception.affected_step);
    const affectedBucket = mapAffectedStep(affectedText);
    if (affectedBucket) flagged = cards.find((k) => k.bucket === affectedBucket);
    if (!flagged && affectedText) flagged = cards.find((k) => k.claims.some((c) => normEq(c.text) === affectedText));
    if (!flagged && misconception.correct_answer_trap) flagged = cards.find((k) => k.bucket === "strategy");
    if (!flagged) flagged = cards.find((k) => k.claims.length) || cards[0];
  } else if (claims.some((c) => c.status === "contradicted")) {
    flagged = cards.find((k) => k.claims.some((c) => c.status === "contradicted")) || cards[cards.length - 1];
  }

  for (const card of cards) {
    const contradicted = card.claims.some((c) => c.status === "contradicted");
    const isFlagged = card === flagged;
    if (!card.claims.length) {
      card.status = "pending";
    } else if (contradicted || isFlagged || (planInvalid && finalWrong && card.bucket === "solve")) {
      card.status = "needs-look";
    } else {
      card.status = "verified";
    }
    card.verificationLines = card.claims.map((c) => c.reason).filter(Boolean);
  }

  // Self-correction: a verified card that differs from the previous wrong attempt.
  if (priorWrong && priorWrong.claims.length) {
    for (const card of cards) {
      if (card.status !== "verified" || !card.claims.length) continue;
      const prior = priorWrong.claims.find((p) => bucketClaimText(p.text, problem) === card.bucket);
      if (prior && !card.claims.some((c) => normEq(c.text) === normEq(prior.text))) {
        card.selfCorrected = true;
        card.priorText = prior.text;
        card.status = "self-corrected";
      }
    }
  }

  // Supportive callout on the flagged step (real guidance, never "How did you get there?").
  if (flagged) {
    flagged.flagged = true;
    if (misconception?.detected) {
      const meta = MISCONCEPTION_META[misconception.misconception_type] || DEFAULT_META;
      flagged.calloutTitle = misconception.correct_answer_trap ? "Your answer is right — let's check your method" : meta.callout;
      flagged.calloutBody =
        misconception.recommended_intervention ||
        flagged.claims.find((c) => c.status === "contradicted")?.reason ||
        "Let's look at this step together — what operation undoes what's there?";
      flagged.patternTag = `PATTERN ${meta.label}`;
    } else {
      const bad = flagged.claims.find((c) => c.status === "contradicted");
      // Guided step-walk question is the most supportive real guidance available.
      const stepIdx = session.step_walk?.step_index ?? 0;
      const guided = problem.tutoring_steps?.[stepIdx];
      flagged.calloutTitle = "Focus on this step";
      flagged.calloutBody =
        (guided?.question || bad?.reason || "Compare this step with what you did — small fix, then you're there.").replace(
          /^Not quite\.\s*/,
          ""
        );
      flagged.patternTag = "";
    }
  }

  return cards;
}

/* ------------------------------------------------------------------ */
/* Progress / support level                                            */
/* ------------------------------------------------------------------ */

export interface ProgressModel {
  current: number;
  total: number;
  solved: number;
  segments: ("done" | "current" | "todo")[];
  dots: ("done" | "current" | "todo")[];
  time: string;
}

export function deriveProgress(session: SessionState | null, elapsedMs: number): ProgressModel {
  const total = PROBLEM_SET_TOTAL;
  const attempted = session?.session_progress?.problems_attempted ?? 0;
  const solved = session?.session_progress?.problems_correct ?? 0;
  const current = Math.min(attempted + 1, total);
  const segments = Array.from({ length: total }, (_, i): "done" | "current" | "todo" =>
    i < solved ? "done" : i === current - 1 ? "current" : "todo"
  );
  const dots = Array.from({ length: total }, (_, i): "done" | "current" | "todo" =>
    i < solved ? "done" : i === current - 1 ? "current" : "todo"
  );
  const minutes = Math.floor(elapsedMs / 60000);
  const seconds = Math.floor((elapsedMs % 60000) / 1000);
  const time = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return { current, total, solved, segments, dots, time };
}

export interface SupportModel {
  level: number; // 0..4 (backend AssistanceLevel)
  of: number;
  label: string;
}

export function deriveSupportLevel(session: SessionState | null): SupportModel {
  const level = session?.assistance_level ?? 0;
  return { level, of: 5, label: SUPPORT_LEVEL_LABELS[level] || "Independent" };
}

/* ------------------------------------------------------------------ */
/* Context memo                                                        */
/* ------------------------------------------------------------------ */

export interface ContextMemoModel {
  title: string;
  body: string;
  note?: string;
}

export function deriveContextMemo(session: SessionState | null, stored: MemoryRecord[]): ContextMemoModel {
  const retrieved = session?.retrieved_memories?.length ?? 0;
  if (!stored.length) {
    return {
      title: "CONTEXT MEMO",
      body: "New learner — no history yet. We'll build your learning profile as we go.",
      note: retrieved ? `${retrieved} memory record${retrieved === 1 ? "" : "s"} retrieved this turn.` : undefined,
    };
  }
  const misconceptions = stored
    .filter((m) => m.memory_type === "misconception" && m.status === "active")
    .sort((a, b) => b.timestamp - a.timestamp);
  const pick = misconceptions[0] || [...stored].sort((a, b) => b.timestamp - a.timestamp)[0];
  const meta = MISCONCEPTION_META[String(pick.metadata?.misconception_type ?? "")] || DEFAULT_META;
  const day = DAYS[new Date(pick.timestamp * 1000).getDay()] || "your last visit";
  const body = `Resuming where you stopped on ${day}: ${meta.label}. We noted ${meta.tendency}, so this session starts there.`;
  const note = retrieved
    ? `${retrieved} record${retrieved === 1 ? "" : "s"} retrieved this turn — shaping today's support.`
    : `${stored.length} stored memory record${stored.length === 1 ? "" : "s"} for this learner.`;
  return { title: "CONTEXT MEMO", body, note };
}

/* ------------------------------------------------------------------ */
/* You can say                                                         */
/* ------------------------------------------------------------------ */

export interface SayAction {
  key: string;
  label: string;
  intent?: string;
  option?: string;
  primary?: boolean;
}

const FRIENDLY_LABELS: Record<string, string> = {
  Hint: "Give me a hint",
  "Try again": "I'll try again",
  "Repeat the problem": "Repeat that",
  "Review my approach": "Review my approach",
  "Show the solution": "Show the solution",
  "Next problem": "Next problem",
  Review: "Review session",
  "End session": "End session",
  "Practice more": "Practice more",
  "Start a new session": "Start a new session",
};

const SELECTION_STATES = [
  "HOME",
  "MODE_SELECTION",
  "TOPIC_SELECTION",
  "SUBTOPIC_SELECTION",
  "DIFFICULTY_SELECTION",
  "REVIEW",
  "END_SESSION",
];

export function deriveYouCanSay(session: SessionState | null): SayAction[] {
  if (!session) return [];
  if (session.paused) return [{ key: "resume", label: "Resume", intent: "resume", primary: true }];
  if (session.pending_confirmation) {
    return [
      { key: "yes", label: "Yes", intent: "confirm_yes", primary: true },
      { key: "no", label: "No", intent: "confirm_no" },
    ];
  }

  const state = session.app_state;
  const inProblem = Boolean(session.current_problem) && !SELECTION_STATES.includes(state);
  const actions = session.available_actions || [];
  const items: SayAction[] = [];

  if (inProblem) items.push({ key: "repeat", label: "Repeat that", intent: "repeat" });

  for (const a of actions) {
    const label = FRIENDLY_LABELS[a] || a;
    if (items.some((i) => i.label === label)) continue;
    items.push({ key: `opt-${a}`, label, option: a });
  }

  if (inProblem && !items.some((i) => i.label === "Go back a step")) {
    items.push({ key: "back", label: "Go back a step", intent: "go_back" });
  }

  const canRetry = inProblem && (
    Boolean(session.step_walk) ||
    (Boolean(session.verification_result) && session.verification_result!.verdict !== "correct")
  );
  if (canRetry) {
    // Always offer the retry path when a step needs revisiting (the approved
    // primary action), even when available_actions does not list "Try again".
    const retry = items.find((i) => i.label === "I'll try again");
    if (retry) retry.primary = true;
    else items.push({ key: "try-again", label: "I'll try again", intent: "try_again", primary: true });
  } else {
    const next = items.find((i) => i.label === "Next problem");
    if (next) next.primary = true;
    else if (items.length && !items[0].primary) items[0].primary = true;
  }

  return items;
}
