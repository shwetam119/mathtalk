// Mirrors backend/app/models/schemas.py — single contract for voice + visual UI.

export interface TutoringStep {
  step_id: string;
  question: string;
  expected_op?: string | null;
  op_accept: string[];
  expected_expr?: string | null;
  hint: string;
  confirm: string;
}

export interface Problem {
  problem_id: string;
  topic: string;
  subtopic: string;
  difficulty: string;
  prompt: string;
  display: string;
  expected_answer: string;
  solution_steps: string[];
  concepts: string[];
  tutoring_steps: TutoringStep[];
  ask_question: string;
}

export interface StepWalk {
  problem_id: string;
  step_index: number;
  step_attempts: number;
  total_steps: number;
  started_from: string;
}

export interface MathClaim {
  text: string;
  operation?: string | null;
  expression?: string | null;
  expected?: string | null;
  computed?: string | null;
  status: string; // verified | contradicted | uncertain | unsupported
  reason: string;
  confidence: number;
}

export interface StructuredReasoning {
  concept: string;
  student_actions: string[];
  reasoning_pattern: string;
  mathematical_claims: MathClaim[];
  steps: string[];
  incorrect_steps: string[];
  final_answer?: string | null;
  reasoning_quality: string;
  confidence: number;
  raw_transcript: string;
  source: string;
}

export interface VerificationResult {
  claims: MathClaim[];
  student_answer?: string | null;
  expected_answer: string;
  final_answer_correct?: boolean | null;
  plan_valid?: boolean | null;
  verdict: string;
  correct_solution: string;
  reason: string;
}

export interface Misconception {
  detected: boolean;
  concept: string;
  misconception_type: string;
  evidence: string;
  affected_step: string;
  confidence: number;
  recommended_intervention: string;
  correct_answer_trap: boolean;
}

export interface Intervention {
  type: string;
  assistance_level: number;
  message: string;
  targeted: boolean;
  memory_based: boolean;
  next_actions: string[];
  reason: string;
}

export interface MemoryRecord {
  memory_id: string;
  student_id: string;
  session_id: string;
  problem_id: string;
  source_session: string;
  concept: string;
  topic: string;
  subtopic: string;
  memory_type: string;
  description: string;
  evidence: string;
  confidence: number;
  timestamp: number;
  status: string;
  metadata: Record<string, unknown>;
  score?: number | null;
}

export interface TimelineEntry {
  session_id: string;
  problem_id: string;
  label: string;
  memory_type: string; // misconception | self_correction
  response_kind: string; // generic | targeted | self_correction
  timestamp: number;
  detail: string;
}

export interface TimelineResponse {
  student_id: string;
  misconception_type: string;
  entries: TimelineEntry[];
}

export interface PipelineEvent {
  stage: string;
  label: string;
  detail: string;
  ok: boolean;
  t_ms: number;
}

export interface SessionProgress {
  problems_attempted: number;
  problems_correct: number;
  total_attempts: number;
  hints_used: number;
  by_problem: Record<string, { problem_id: string; attempts: number; correct: boolean; hints_used: number; resolved: boolean }>;
}

export interface TurnRecord {
  speaker: string;
  text: string;
  intent?: string | null;
  t: number;
}

export interface SessionState {
  student_id: string;
  session_id: string;
  session_number: number;
  app_state: string;
  state_history: string[];
  pending_confirmation: Record<string, unknown> | null;
  mode?: string | null;
  topic?: string | null;
  subtopic?: string | null;
  difficulty?: string | null;
  current_problem?: Problem | null;
  current_attempt: number;
  reasoning_transcript: string;
  input_type?: string | null;
  extracted_answer?: string | null;
  step_walk?: StepWalk | null;
  structured_reasoning?: StructuredReasoning | null;
  verification_result?: VerificationResult | null;
  misconception?: Misconception | null;
  retrieved_memories: MemoryRecord[];
  stored_memories: MemoryRecord[];
  selected_intervention?: Intervention | null;
  assistance_level: number;
  available_actions: string[];
  voice_status: string;
  voice_channel: string;
  voice_provider: string;
  paused: boolean;
  session_progress: SessionProgress;
  turns: TurnRecord[];
  last_pipeline_events: PipelineEvent[];
  last_spoken: string;
  last_error: string;
  latency_ms: number;
  version: number;
}

export interface TurnResponse {
  state: SessionState;
  spoken: string;
  pipeline_events: PipelineEvent[];
  ok: boolean;
  error: string;
  latency_ms: number;
}

export interface ServiceConfig {
  memory: { provider: string; reason: string; vector_size: number };
  rime: { provider: string; configured: boolean; missing: string[]; speaker: string; model: string; note: string };
  llm: { provider: string; configured: boolean; model: string; missing: string[] };
  stt: { provider: string; configured: boolean; missing: string[]; note: string };
  confirm_mode_selection: boolean;
  version: string;
}

export interface VoiceSpeakResponse {
  provider: string;
  mime: string;
  audio: string; // base64
}
