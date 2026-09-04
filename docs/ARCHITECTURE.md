# MathTalk — Architecture

## 1. Design principles

1. **One authoritative state.** A single `SessionState` object, mutated only by the state machine in `backend/app/state/state_machine.py`. The voice interface and the visual dashboard are two views over the same object via one REST API. No duplicated tutoring logic anywhere.
2. **The LLM can never touch state.** All navigation is resolved by the deterministic command parser (`backend/app/state/commands.py`). The LLM's only role is optional semantic interpretation of free-form reasoning — and its output is *validated* by deterministic rules.
3. **Mathematics is deterministic.** SymPy is the final authority. Verification results are structured (`verified | contradicted | uncertain | unsupported`) with reasons and confidence 1.0 where symbolic equality is proven. The LLM cannot override this.
4. **Diagnosis uses reasoning + verification + context**, never just the final answer. The correct-answer-with-flawed-reasoning case is explicitly detected.
5. **Memory must change behavior.** Retrieved Qdrant memories are inputs to the tutoring policy. With a relevant stored misconception, the policy emits a targeted intervention; without it, a generic one. This is proven by tests.
6. **Honest failures.** External services report their real status in `/api/health` and the UI. Fallbacks exist but never claim the real service succeeded.

## 2. State machine

States (`AppState`): `HOME`, `MODE_SELECTION`, `TOPIC_SELECTION`, `SUBTOPIC_SELECTION`, `DIFFICULTY_SELECTION`, `PROBLEM_PRESENTATION`, `REASONING`, `DIAGNOSIS`, `INTERVENTION`, `POST_RESPONSE_OPTIONS`, `NEXT_PROBLEM`, `REVIEW`, `ERROR_RECOVERY`, `END_SESSION`.

`SessionState` carries: `student_id`, `session_id`, `mode`, `topic`, `subtopic`, `difficulty`, `current_problem`, `current_attempt`, `reasoning_transcript`, `structured_reasoning`, `verification_result`, `misconception`, `retrieved_memories`, `selected_intervention`, `assistance_level`, `available_actions`, `voice_status`, `session_progress`, plus a state history for `GO_BACK`.

Transitions are explicit and whitelisted; `available_actions` is derived by the machine so both UIs always know the legal options, and every tutor response ends by speaking them (no dead ends).

## 3. Conversation manager

`POST /api/turn` is the single entry point. Flow:

1. Parse the transcript with the deterministic parser → an `Intent`.
2. `GO_BACK` / `GO_HOME` / `HELP` / `REPEAT` / `STOP` / `RESUME` / `END_SESSION` short-circuit to the state machine (state transitions are deterministic).
3. Navigational intents (`SELECT_*`) advance the state machine.
4. Reasoning intents run the full pipeline in `backend/app/services/engine.py`:

```
interpret(transcript, problem)
  → StructuredReasoning (concept, actions, claims, steps, final_answer, confidence)
verify(structured, problem)
  → VerificationResult (per-claim + overall verdict, expected answer)
detect(problem, structured, verification)
  → Misconception (type, evidence, affected step, confidence, recommended intervention)
retrieve_memories(student_id, problem)
  → scored memories from Qdrant/local store (strictly student-scoped)
policy(problem, reasoning, verification, misconception, memories, attempts, level)
  → Intervention (type, message, assistance level, next actions)
store/update memory (per session outcome)
generate response → spoken + shown
```

## 4. Reasoning interpretation

`backend/app/reasoning/interpreter.py`. Input: transcript + problem. Output: structured claims.

- Number/operation grammar extracts arithmetic actions: "add 6 and 14", "subtract 6 from both sides", "divide both sides by 2", "multiply by 3", "simplify 2x minus 3x", "solve for x", etc.
- Every extracted claim carries a `mathematical_formula` (sympy-parseable) and a `computed` value where computable.
- The final answer is the **last** computed value in the transcript.
- If an LLM is configured, its structured output is merged only after schema validation; the deterministic grammar is always the backbone.

## 5. Deterministic verification (SymPy)

`backend/app/mathematics/verifier.py`.

- Each claim is evaluated with sympy: arithmetic evaluation, symbolic equivalence (`simplify(a - b) == 0`), equation solving (`solve`), derived-equation checks (both sides transformed identically), and solution substitution into the original equation.
- Symbol identity is normalized (`Symbol("x", real=True)` shared across the whole pipeline) so expressions combine correctly.
- Returns `{status, claim, expected, reason, confidence}`; the overall verdict distinguishes `CORRECT`, `WRONG_ANSWER`, `CORRECT_ANSWER_FLAWED_REASONING`, `INCOMPLETE`, `AMBIGUOUS`.

## 6. Misconception detection

`backend/app/reasoning/misconception.py`. Nine families: sign errors, inverse-operation errors, equality manipulation, distribution errors, combining unlike terms, fraction denominator mistakes, whole-part confusion, formula selection, probability misconceptions.

Detection fuses (a) verified claim statuses, (b) the reasoning actions, (c) problem metadata (`common_misconceptions`). Evidence strings are concrete ("you added 6 and 14 instead of subtracting 6 from both sides") and each detection carries a `recommended_intervention` that feeds the tutoring policy.

Hero case: *"I add 6 and 14 to get 20 and then divide by 2"* on `2x + 6 = 14` → `inverse_operation` misconception, evidence citing the added terms, recommendation to undo the addition before dividing.

## 7. Learner memory (Qdrant)

`backend/app/services/memory.py`.

- Real Qdrant via the `qdrant-client` HTTP API when `QDRANT_URL` is set; otherwise a local file-backed store with the same interface (semantic-ish search via hashed feature vectors).
- `store_memory`, `retrieve_relevant_memories`, `update_memory`, `mark_memory_resolved`, `delete_memory`.
- Payload: `student_id`, `concept`, `topic`, `memory_type` (misconception / reasoning_pattern / intervention_success / progress / attempt), `confidence`, `timestamp`, `status`, `source_session`, `problem_id`.
- **Isolation:** every store/retrieve/delete call is scoped to `student_id`.
- Memories store meaningful evidence (misconception type, evidence text, session, problem) — not just "session happened".

## 8. Adaptive tutoring policy

`backend/app/tutoring/policy.py`.

Inputs: problem, reasoning, verification, misconception, attempt history, previous interventions, retrieved memories, difficulty, progress.

Outputs: `Intervention { type, message, assistance_level, next_actions }`.

Behavioral rules:
- Relevant retrieved misconception (same concept) ⇒ `TARGETED_INTERVENTION` — a message built from the stored evidence, e.g. "Before continuing, think about what operation would undo the addition on the left side."
- No memory ⇒ generic hint by problem.
- Correct answer + flawed reasoning ⇒ method-review intervention (never "wrong!").
- Correct ⇒ praise + next-problem/options.

## 9. Progressive assistance

`backend/app/tutoring/assistance.py`.

| Level | Name | Trigger |
|---|---|---|
| 0 | Independent attempt | start |
| 1 | Review my approach | first failure / request |
| 2 | Hint | second failure / request |
| 3 | Guided explanation | repeated failure / request |
| 4 | Detailed solution | 3+ failures / explicit request |

Escalation also considers explicit requests and learner memory. The solution is never revealed early; hints are step-based and never contain the final answer.

## 10. Speech: input, output, interruption

- **STT:** browser Web Speech API via `frontend/src/speech/SpeechService.ts` (no key). Optional server-side Whisper (`backend/app/services/stt.py`) when `STT_PROVIDER` is set. Handles silence, empty/low-confidence transcripts, mic failure, timeout.
- **TTS:** `backend/app/services/rime.py` — `POST users.rime.ai/v1/rime-tts`, Bearer token, `Accept: audio/wav`, body `{text, speaker, modelId}`. Audio returned to the browser and played by `frontend/src/audio/TtsPlayer.ts`.
- **Barge-in:** the player listens for mic activity while speaking; on speech start it stops playback immediately and the new utterance is processed. Server-side, the Rime call is cancellable via `httpx` timeouts; duplicate turns are rejected while one is in flight.

## 11. Frontend

- React + TypeScript + Vite. `App.tsx` orchestrates: polled `SessionState` (the single source of truth), typed or spoken input, Rime playback, keyboard shortcuts (`Ctrl+M` mic, `Ctrl+Enter` send, `Ctrl+R` repeat).
- Dashboard panels (all from backend state): pipeline visualization, current state, voice status, problem, live transcript, structured reasoning, verified claims, misconception, retrieved memories (with scores), selected intervention + assistance level, session progress, latency, service health badges.
- Accessibility: semantic landmarks, aria-live status regions, logical tab order, high-contrast styles, no color-only information, full keyboard operability, voice repetition of everything.

## 12. Honest failure recovery

Every external call is wrapped: Rime failure → fall back to browser speech *and say so*; Qdrant failure → local store with a status flag; LLM failure → deterministic engine; STT failure → typed input + clear error. `ERROR_RECOVERY` is a real state in the machine; the app never crashes and never fabricates a successful external response.

## 13. Security

- `.env` git-ignored; `.env.example` placeholders only; secrets server-side only; no credentials in logs; student-memory isolation enforced at the service layer; synthetic demo data; memory deletion via reset API.
