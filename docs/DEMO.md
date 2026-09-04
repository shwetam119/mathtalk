# MathTalk — Hackathon Demo Procedure (2–3 minutes)

## Setup (before the judges arrive)

```bash
./reset-demo.sh      # wipe demo-student-001 memories + sessions
./run.sh             # one click: deps, backend, frontend, browser
```

Keep the dashboard visible. For the "real services" story, set `RIME_API_KEY` (and optionally `QDRANT_URL`) in `.env` before launching; the demo works identically without them (fallbacks are clearly labelled).

## The hero demo: "Never Start From Zero"

### Session 1 (~60–75 s)

1. **Launch.** The app speaks: *"Welcome to MathTalk… Option 1: Learn. Option 2: Practice. Option 3: Test. Option 4: Review."* *(Voice-first from second zero.)*
2. Say **"Practice"** → confirm **"yes"**.
3. Say **"Algebra"** → **"Linear equations"** → **"Easy"**.
4. The problem is spoken: `2x + 6 = 14`. Say *"Tell me how you would solve it."*
5. The student speaks **flawed reasoning**: *"I add 6 and 14 to get 20 and then divide by 2."*
6. Watch the dashboard render the pipeline live: transcript → structured claims → **SymPy verification** → **misconception: inverse operation** → generic intervention → **memory stored**.
7. Rime speaks the diagnosis and options.
8. Say **"hint"** → progressive assistance level 2 → say **"try again"** and give correct reasoning: *"I subtract 6 from both sides, so 2x equals 8, then divide both sides by 2, so x equals 4."*
9. MathTalk confirms the method is right; **Session 1 memory updated.**

### Session 2 (~45–60 s)

1. Say **"end session"**, then **"practice"** again (or run `./reset-demo.sh` + relaunch for a fresh boot; same student identity either way).
2. Say **"Algebra"** → **"Linear equations"** → **"Easy"**.
3. A **related** problem appears (`3x + 4 = 19`) — the engine deliberately excludes the previous problem.
4. Give the same flawed reasoning pattern.
5. **The money shot:** Qdrant retrieves the Session 1 memory (visible on the dashboard with scores) and the tutoring policy emits a **targeted, memory-based intervention**: *"Before continuing, think about what operation would undo the addition on the left side."* — not the generic hint.
6. The student self-corrects immediately. Close with the end-of-session summary mentioning that what was learned will carry into the next session.

### Judge talking points

- **Voice-first & complete:** the entire loop ran on speech; no mouse needed.
- **Reasoning, not answers:** point at the "correct answer + flawed reasoning" case in Session 1 step 7.
- **Deterministic math:** SymPy verdicts shown per claim, with reasons.
- **Memory changes behavior:** compare Session 1's generic intervention with Session 2's targeted one — same student, same mistake type, different tutor response because of stored memory.
- **Honest engineering:** the service badges show the *real* status of Rime/Qdrant/LLM — no fake successes.
- **Resilience:** if you have 20 extra seconds, press `Ctrl+R` to repeat, speak while Rime is talking to show barge-in, or say "help".

## Failure-mode snacks (optional, 20 s)

- Say "help" → spoken command list.
- Say "back" → state machine goes back one step.
- Speak over the tutor → Rime stops instantly (barge-in).
- Type gibberish → graceful recovery message, never a crash.
