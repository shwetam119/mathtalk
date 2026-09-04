# MathTalk

**Voice-first, reasoning-aware, memory-augmented mathematics tutoring for visually impaired students.**

MathTalk is a learning environment you operate **entirely by voice**. The student speaks their reasoning; MathTalk interprets *what they did and why*, verifies the mathematics deterministically, identifies the underlying misconception, recalls the student's learning history from Qdrant, and adapts its tutoring — then speaks back through Rime TTS. A visual dashboard observes the **same** application state for residual-vision users, teachers, and judges.

> **Core principle:** the student can complete the entire learning loop with voice alone — no mouse, no keyboard. The voice interface and the visual interface read and modify the *same* central state; there is no duplicated business logic.

---

## What makes MathTalk different

MathTalk is **not** a chatbot that asks "what's your answer?" and grades it. It understands **reasoning**:

| Student says | Naive bot | MathTalk |
|---|---|---|
| *"I add 6 and 14 to get 20 and then divide by 2."* (2x + 6 = 14) | "Wrong. Answer: 4." | "I see that you added 6 and 14, then divided. Before dividing, think about what operation would **undo** the addition on the left side." |
| *"I subtract 6 from both sides, so 2x = 8, then divide both sides by 2, so x = 4."* | "Correct." | "Correct — and your method is exactly right: you applied the inverse operation to both sides." |
| *"I subtract 6 from 14 and divide by 2, so x = 4."* | "Correct." | "Your final answer is correct, but let's check your method…" (correct answer + flawed reasoning is caught) |

The system distinguishes correct answer + correct reasoning, correct answer + flawed reasoning, incorrect answer + partial reasoning, and misconception-driven errors — and **stores what it learns in persistent learner memory that changes future tutoring behavior across sessions.**

---

## Architecture

```
STUDENT
  │  (microphone)
  ▼
SPEECH-TO-TEXT            Web Speech API (browser) or server-side Whisper (optional)
  ▼
VOICE COMMAND / CONVERSATION MANAGER      deterministic intent parser (LLM can't touch state)
  ▼
CENTRAL APPLICATION STATE MACHINE          one authoritative SessionState
  ▼
CURRENT LEARNING CONTEXT + PROBLEM          structured problem engine (5 topics)
  ▼
STUDENT NATURAL-LANGUAGE REASONING
  ▼
REASONING INTERPRETER                        LLM-assisted, deterministic fallback
  ▼
STRUCTURED MATHEMATICAL CLAIMS
  ▼
DETERMINISTIC MATHEMATICAL VERIFIER         SymPy — the final authority
  ▼
MISCONCEPTION DETECTOR                      9 misconception families
  ▼
QDRANT LEARNER MEMORY                        real Qdrant, or local file-backed store
  ▼
ADAPTIVE TUTORING POLICY                     rule-driven, memory-aware
  ▼
PROGRESSIVE ASSISTANCE                       Level 0 → 4, never dumps the solution early
  ▼
NATURAL-LANGUAGE RESPONSE                    always ends with contextual options (no dead ends)
  ▼
RIME TTS                                     primary speech output (browser fallback only when unconfigured)
  ▼
STUDENT
```

**Layers:**

- `backend/` — Python + FastAPI modular monolith: state machine, command parser, problem engine, SymPy verifier, reasoning interpreter, misconception detector, Qdrant memory service, tutoring policy, progressive assistance, Rime TTS, session manager, REST API.
- `frontend/` — React + TypeScript + Vite: accessible dashboard, Web Speech mic input, Rime audio playback with **barge-in** (speaking over the tutor stops Rime and starts a new turn), keyboard shortcuts, screen-reader friendly.
- `scripts/`, `run.sh` / `run.bat` — one-click launcher and demo reset.

### Folder structure

```
MathTalk/
├── backend/
│   ├── app/
│   │   ├── api/routes.py        # REST API (single source of truth for both UIs)
│   │   ├── core/config.py       # env-driven settings, secrets never leave server
│   │   ├── core/logging.py
│   │   ├── models/schemas.py    # pydantic models: SessionState, claims, interventions…
│   │   ├── state/               # state_machine.py, commands.py (deterministic parser), sessions.py
│   │   ├── services/            # engine.py (pipeline), memory.py (Qdrant+local), llm.py, rime.py, stt.py
│   │   ├── mathematics/         # problems.py (problem engine), verifier.py (SymPy)
│   │   ├── reasoning/           # interpreter.py, misconception.py
│   │   ├── tutoring/            # policy.py (adaptive), assistance.py (progressive), responses.py
│   │   └── main.py              # FastAPI app
│   ├── tests/                   # unit, integration, API E2E
│   └── requirements.txt
├── frontend/
│   ├── src/                     # App.tsx, api.ts, speech/, audio/, components/, styles.css
│   └── package.json
├── run.sh / run.bat             # one-click launcher
├── reset-demo.sh / reset-demo.bat
├── .env.example                 # placeholders only — never real secrets
└── README.md
```

---

## Prerequisites

- **Python 3.10+** (3.13 recommended) — for the backend
- **Node.js 18+** and **npm** — for the frontend
- **Network access** — to install dependencies (and, optionally, to reach Rime / Qdrant / an LLM)

Everything runs locally with zero external credentials. The only hardware requirement is a **microphone** for the voice experience (and speakers for speech output).

---

## Installation

```bash
# 1. Clone / enter the project directory
cd MathTalk

# 2. (Optional but recommended) configure services
cp .env.example .env
#    edit .env — see "Environment variables" below

# 3. Launch
./run.sh          # macOS / Linux
run.bat           # Windows
```

`run.sh` does everything: checks runtime, creates the backend virtualenv, installs backend + frontend dependencies, checks configuration, starts the backend, waits for `/api/health`, starts the frontend, and opens your browser.

If you prefer manual setup:

```bash
# Backend
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8020

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

---

## Environment variables

All secrets are **server-side only** — never exposed to browser JavaScript, never logged, never committed. Copy `.env.example` to `.env` and fill in what you have; the app runs fine with everything empty.

| Variable | Purpose | Required |
|---|---|---|
| `RIME_API_KEY` | Real Rime TTS speech output (https://rime.ai) | No* |
| `RIME_API_URL`, `RIME_SPEAKER`, `RIME_MODEL_ID` | Rime endpoint / voice tuning | No |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` | Real Qdrant vector memory | No* |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | LLM-assisted reasoning interpretation | No |
| `GEMMA_API_KEY`, `GEMMA_BASE_URL`, `GEMMA_MODEL` | Gemma 4 provider (with `LLM_PROVIDER=gemma`) | No |
| `LLM_USE_FOR_RESPONSES` | Route tutor wording through the LLM when configured | No |
| `STT_PROVIDER`, `STT_BASE_URL`, `STT_API_KEY`, `STT_MODEL` | Server-side speech-to-text (Whisper) | No |
| `BACKEND_HOST`, `BACKEND_PORT`, `FRONTEND_ORIGIN` | Server wiring | No |
| `DEMO_STUDENT_ID`, `CONFIRM_MODE_SELECTION`, `MAX_ATTEMPTS_BEFORE_SOLUTION` | Demo / tutoring tuning | No |

\* *Without `RIME_API_KEY` the app uses a clearly-labelled browser-speech fallback and reports Rime as **disabled** — it never claims Rime is working when it isn't. Without `QDRANT_URL` it uses a file-backed local vector store with the identical interface and behavior.*

---

## External services

| Service | What it does | Credential needed? | If missing |
|---|---|---|---|
| **Rime TTS** | Primary speech output | `RIME_API_KEY` | Browser-speech fallback, labelled "Rime disabled" in the UI and `/api/health` |
| **Qdrant** | Persistent learner-memory vectors | `QDRANT_URL` (+ key if secured) | Local file-backed store, same API + behavior, labelled in `/api/health` |
| **LLM (OpenAI-compatible)** | Semantic reasoning interpretation | `LLM_API_KEY` + `LLM_PROVIDER` | Deterministic rule-based reasoning engine (fully functional) |
| **Web Speech API** | Speech-to-text | none (browser) | Mic error surfaced; typed input always available |
| **Server STT (Whisper)** | Optional server-side STT | `STT_API_KEY` + `STT_PROVIDER` | Browser Web Speech API |

**Honest reporting:** `/api/health` and the dashboard report the *actual* status of each external service. There are no fabricated successes.

---

## Voice-first usage

The app launches into a spoken welcome:

> "Welcome to MathTalk. What would you like to do? Option 1: Learn. Option 2: Practice. Option 3: Test. Option 4: Review. Please say the option number or name."

The core learning loop is fully voice-operated:

1. Say the **mode** (e.g. *"Practice"*), confirm with *"yes"*.
2. Say a **topic** (*"Algebra"*), a **subtopic** (*"Linear equations"*), a **difficulty** (*"Easy"*).
3. A problem is presented. Say *"Tell me how you would solve it"* and speak your reasoning step by step.
4. MathTalk interprets, verifies, diagnoses, recalls memory, and **speaks** its response with contextual options.
5. Say *"hint"*, *"try again"*, *"next problem"*, *"review"*, or a global command at any time.

**Global voice commands** (deterministic — an LLM can never drive state):

- `help` / "I need help"
- `repeat` / "say that again"
- `go back` / "back"
- `go home` / "home"
- `stop` / "pause" — pauses listening
- `resume` / "continue"
- `end session` / "finish"
- Numbered selection: "1", "one", "option one", "first option"

**Barge-in:** while Rime is speaking, just start talking — Rime stops instantly, your new speech is captured, and the new turn is processed. Old responses never continue after interruption.

**Keyboard (for residual-vision users / teachers):** `Ctrl+M` toggles the mic, `Ctrl+Enter` submits typed input, `Ctrl+R` repeats the last response. Every control is reachable by Tab and operable with Enter/Space; focus order is logical; live regions announce state changes.

---

## Intelligence & interaction upgrade

Beyond the original architecture, MathTalk now understands *short, natural
speech* and coaches step by step:

- **One-word answers are first-class inputs.** "4", "56", "four", "x equals
  four", "three quarters", "negative five", "5x" are all recognised as direct
  answers in context and verified deterministically with SymPy. Spoken math is
  normalised ("three-fourths" → 3/4, "two point five" → 2.5, "twenty five
  percent" → 25/100, "x equals four" → x = 4).
- **Contextual input understanding.** Every open utterance is classified
  (DIRECT_ANSWER / REASONING / QUESTION / REQUEST_FOR_HELP / CONFIRMATION /
  REJECTION / …) using state + problem + the tutor's last question. "Yes"
  after "Would you like a hint?" is a confirmation, not an answer.
- **Step-focused tutoring after a wrong answer.** Instead of "How did you get
  there?" or dumping the solution, MathTalk walks the student through the
  problem one question at a time and verifies each step: "Not quite. What
  should we do with the 6?" → "Subtract." → "Exactly. What does that leave?"
  → "2x equals 8" → "Good. Now what should we do with the 2?" → "Divide by 2"
  → "Exactly. So what is x?" → "4" → "Correct! Well done."
- **Supportive handling of uncertainty.** "I don't know" / "I'm stuck" gets a
  small next action, never a dead end. Wrong steps offer a hint with a
  yes/no confirmation; repeated mistakes escalate through the existing
  assistance levels to the full verified solution.
- **Gemma 4 integration** (optional, through the existing LLM abstraction):
  contextual classification, reasoning interpretation and natural response
  wording. The LLM never decides mathematics or state — SymPy verifies, the
  state machine transitions, and every Gemma failure falls back to the
  deterministic engine.

## The Session 1 → Session 2 hero demonstration ("Never Start From Zero")

This is the core differentiator, and it is **not** scripted — every step runs through the real pipeline with real state.

**Session 1** (fresh demo learner):
1. Enter Practice → Algebra → Linear equations → Easy.
2. The student gives **flawed reasoning** on 2x + 6 = 14: *"I add 6 and 14 to get 20 and then divide by 2."*
3. The interpreter extracts the claims, SymPy verifies them, and the misconception detector identifies **inverse-operation error**.
4. The tutor gives a *generic* intervention ("Review your approach"), then **stores a memory** in Qdrant (or the local store): misconception `inverse_operation`, concept `linear_equations`, evidence, confidence, session id.

**Session 2** (same student identity, e.g. after `./reset-demo.sh` and a fresh run — or simply a new session):
1. A **related** problem is presented (e.g. 3x + 4 = 19 — the engine excludes the previous problem).
2. Qdrant retrieves the Session 1 memory.
3. The tutoring policy sees the relevant misconception and produces a **targeted, memory-based intervention**: *"Before continuing, think about what operation would undo the addition on the left side."* — instead of the generic hint.
4. The student self-corrects; the memory is updated (not deleted) and carries into future sessions.

The dashboard shows `MEMORY STORED` in Session 1 and `MEMORY RETRIEVED` + `TARGETED INTERVENTION · MEMORY-BASED` in Session 2 — rendered from actual runtime state, never hardcoded strings.

---

## One-click launcher

```bash
./run.sh            # macOS / Linux — dev mode (Vite dev server + backend)
./run.sh prod       # production mode (frontend built and served by backend)
run.bat             # Windows
```

The launcher checks runtime → dependencies → configuration → Qdrant reachability → starts backend → waits for `/api/health` → starts frontend → waits for HTTP → opens the browser. It never silently fails; every check prints a useful message.

## Demo reset

```bash
./reset-demo.sh                 # resets demo-student-001 (memories + sessions)
./reset-demo.sh some-student    # resets a specific student
reset-demo.bat                  # Windows
```

Resets: session state, Qdrant/local memories for the demo learner, demo progress counters. The Session 1 → Session 2 demonstration is then reproducible from zero.

---

## Testing

```bash
cd backend
.venv/bin/python -m pytest tests -q          # full suite
.venv/bin/python -m pytest tests/unit -q     # unit tests
.venv/bin/python -m pytest tests/integration -q   # integration + API E2E
```

Coverage includes:

- **Unit:** state transitions, command parsing, reasoning schema, SymPy verification, misconception detection, tutoring policy, progressive assistance, Qdrant/local memory, memory isolation, intervention selection.
- **Integration:** speech→state, reasoning→verification, verification→diagnosis, diagnosis→tutoring, Qdrant→tutoring, Rime lifecycle, **Session 1 → Session 2 behavior change** (with memory ⇒ targeted intervention; without memory ⇒ generic intervention).
- **API E2E:** the full 20-step workflow against a live FastAPI server, including the two-session memory demonstration.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Rime is disabled" in the dashboard | `RIME_API_KEY` not set. Set it in `.env` (https://rime.ai). Browser speech is used meanwhile. |
| "Using local memory store" | `QDRANT_URL` not set (or Qdrant unreachable). Either set it or accept the local store — behavior is identical. |
| Mic does nothing | Browser mic permission denied; check the address bar. Typed input always works as a fallback. |
| Port already in use | MathTalk defaults to backend **8020**, frontend **5173** (deliberately not 8000). Override with `MATHTALK_BACKEND_PORT` / `MATHTALK_FRONTEND_PORT`. |
| No speech heard | Speakers/volume; ensure the Rime response actually rendered (see the dashboard "Speech output" status). |
| The browser doesn't auto-open | Open the printed URL manually. |
| Backend won't start | Check `backend/.venv` exists and `pip install -r backend/requirements.txt` succeeded. |

---

## API surface (all JSON)

- `GET  /api/health` — service status incl. honest Rime/Qdrant/LLM/STT availability
- `GET  /api/readiness` — backend ready?
- `POST /api/session/start` — start/reuse a session for a `student_id`
- `GET  /api/session/state` — the authoritative `SessionState`
- `POST /api/turn` — the single conversational entry point (text in → full pipeline → spoken response out)
- `POST /api/repeat` — repeat the last response
- `POST /api/demo/reset` — reset a demo student's memories + progress

Both UIs (voice and visual) talk to this one API and share one state machine.

---

## Security

- Secrets live only in environment variables / `.env` (git-ignored); `.env.example` contains placeholders only.
- No API keys ever reach browser JavaScript; all external calls happen server-side.
- Credentials are never logged and never committed.
- Learner memories are **isolated by `student_id`** — retrieval filters strictly by student.
- Synthetic demo student data only; memory deletion is exposed via the reset API.

## Known limitations

- **Rime requires a real API key** to be exercised end-to-end; without it, the browser-speech fallback is used (clearly labelled). The Rime client itself is covered by unit tests with mocked HTTP.
- **Qdrant requires a running Qdrant instance**; without it the local file-backed vector store (same interface) is used. Vector-search *behavior* (retrieval scoring, memory influence) is identical and tested.
- **LLM interpretation is optional.** Without an LLM key, reasoning interpretation uses the deterministic rule engine, which is robust for the demo content but has a narrower linguistic surface than a model.
- **Web Speech API** (browser STT) is Chrome/Edge-first; typed input covers other browsers.
- Misconception detection is strongest on the demo content set (arithmetic, algebra, linear equations, fractions, probability) and generalizes heuristically beyond it.
