# How it works, in detail

This is the long version of the README: which models I picked and why, how the pieces fit together, what each agent actually does, and the decisions I'd want to explain if you asked "why is it built like that." If you just want to run it, the README has you covered. This is for reading the code with a map in hand.

## What happens when you use it

1. You make a project and upload a messy `.xlsx`.
2. The Correction agent looks at each column and decides how to fix it: the right type, which junk values count as missing, how to fill the gaps or whether to fill them at all. It only decides. pandas does the actual work.
3. The Verifier agent, a different model, reviews those decisions. It doesn't see the cleaner's reasoning, only what it decided, so it can't just nod along. It gets up to three rounds to push back. If they still disagree at the end, the app says so.
4. The Insights agent runs the EDA itself (correlations, distributions, outliers), pulls out the key findings, and writes a plain-English summary.
5. The Analysis Canvas on the right fills in live as each agent finishes.
6. Then you can chat about the report, ask questions that run real pandas on the cleaned data, or talk to it hands-free.

Everything runs locally. Projects and chat history live in memory and disappear when you restart the server. There's no database, which was a choice and not an oversight: it's a tool for one person on one machine.

## The models, and why these ones

All the language models run through a local Ollama. Speech runs locally too. Nothing goes to a cloud service.

| Role | Model | Family | Why |
|---|---|---|---|
| Correction (cleaner) | `qwen2.5:7b-instruct` | Alibaba Qwen | Good at strict JSON and at reasoning about types and imputation, which is the whole cleaning plan. |
| Insights (narrative + takeaways) | `qwen2.5:7b-instruct` | Qwen | Faithful at summarising numbers it's handed. |
| Chat / Analysis (Q&A + pandas) | `qwen2.5:7b-instruct` | Qwen | Follows instructions and writes noticeably less-buggy pandas. |
| Verifier (independent review) | `llama3.1:8b` | Meta Llama | A genuinely different family, so the second opinion isn't the same weights re-reading their own work. |

Two different families is the point. The verifier only earns its keep if it disagrees. If it were the same model as the cleaner, its "review" would mostly repeat the cleaner's own assumptions back at it. Qwen and Llama are different enough to actually catch each other's mistakes.

The size, 7-8B, I landed on the hard way. This machine has no GPU, so every token is CPU work. I started on 3B models because they're quick, and they mostly worked, but they cleaned carelessly and, more annoyingly, tended to make things worse when the verifier corrected them. Moving up to 7-8B fixed that. The cost is honest: a full run is nine to thirteen minutes, and since both models don't fit in 16GB of RAM together, Ollama swaps them in and out between rounds. I didn't go past 8B because on four CPU cores a 14B model turns a run into half an hour with the RAM pinned, and nobody would use that. Switching back to the 3B tier is one line in `backend/config.py`.

For voice:

| Role | Engine / model | Why |
|---|---|---|
| Speech to text | `faster-whisper`, Whisper `base.en` (CTranslate2, int8) | Accurate, and transcribes a short utterance in one to three seconds on CPU. |
| Text to speech | `Piper`, `en_US-lessac-medium` | A local neural voice that synthesises faster than real time on CPU. |

Both download once (about 200MB, into `VOICE_DIR`, `E:\LLM\voice` by default) and run offline after that.

A note on voice cloning: the speaking voice is swappable, and a local cloning setup could slot in. But cloning is only for your own voice or one you have permission to use. It won't clone an identifiable person without consent. That's impersonation, and it's off the table on purpose.

### Keeping the models factual

A few settings push them toward precise instead of creative:

- Greedy sampling (temperature 0, low top_p). Same input, same output.
- Every agent that writes gets the same instruction: if the answer isn't in what you were given, say you don't know. Don't invent numbers.
- The verifier has to cite the number behind any complaint (the skew, the percent missing) so it can't flag problems that aren't there.
- The part that matters most: the numbers are honest by construction. Analysis answers come from real pandas, report stats are computed in code, and the model only writes them up. It can't make a figure up because it never computes one.

## The shape of it

```
┌───────────────────────────── Browser (React SPA) ─────────────────────────────┐
│  Sidebar (projects)     Chat thread + voice     Analysis Canvas (live report)  │
└───────────────┬───────────────────────────────────────────────┬───────────────┘
                │ REST (/api/*)                                   │ WebSocket (/ws/projects/{id})
                ▼                                                 ▼
┌──────────────────────────────── FastAPI backend ──────────────────────────────┐
│  main.py            REST + WebSocket + serves built frontend (single process)  │
│  state/             in-memory project store (no DB)                            │
│  ws/                one socket per project: pipeline progress + chat + voice   │
│  voice/             faster-whisper (STT) + Piper (TTS)                         │
│                                                                                │
│  ── the multi-agent pipeline ──                                               │
│  pipeline/profiling → agents/cleaner → pipeline/execute → agents/verifier ↺    │
│                     → pipeline/eda + reporting/findings → agents/insights      │
│  agents/analysis    (routes a question → writes pandas → runs it safely)       │
│  agents/chat        (grounded, streaming Q&A over the report)                  │
│  agents/base        stateless Ollama wrapper (JSON mode, retries, streaming)   │
└───────────────────────────────────┬────────────────────────────────────────────┘
                                     │ HTTP (localhost:11434)
                                     ▼
                          ┌────────────────────┐
                          │  Ollama (local)    │  qwen2.5:7b-instruct
                          │                    │  llama3.1:8b
                          └────────────────────┘
```

The stack: Python 3.13 with FastAPI, Uvicorn and WebSockets on the backend; pandas, numpy, scipy, openpyxl and plotly for the data work; the official `ollama` client for the models; faster-whisper, piper-tts and onnxruntime for voice. The frontend is Vite 4, React 18, TypeScript and Tailwind, with react-plotly for charts and self-hosted fonts so nothing is fetched from a CDN. Vite is pinned to 4 so it builds on the machine's Node 16; newer Node is fine.

You can run it two ways. Normally: build the frontend once with `npm run build`, then `uvicorn backend.main:app` serves the API and the built app on one port. For development: `uvicorn backend.main:app --reload` in one terminal and `npm run dev` in another, with Vite proxying `/api` and `/ws` to the backend.

## Where things live

```
excel-insight-agents/
├── backend/
│   ├── main.py                 # FastAPI: REST + WebSocket + serves frontend/dist
│   ├── config.py               # models, OLLAMA_HOST, sampling, MAX_VERIFY_ITERATIONS, voice
│   ├── agents/
│   │   ├── base.py             # stateless Ollama wrapper: JSON mode, pydantic, retries, streaming
│   │   ├── cleaner_agent.py    # plans the cleaning (the model plans, pandas executes)
│   │   ├── verifier_agent.py   # independent review (different family, reasoning withheld)
│   │   ├── insights_agent.py   # narrative + takeaways over computed numbers
│   │   ├── analysis_agent.py   # routes a data question → writes pandas → runs it safely
│   │   └── chat_agent.py       # grounded, streaming Q&A over the report
│   ├── pipeline/
│   │   ├── profiling.py        # per-column profiling (no model)
│   │   ├── execute.py          # applies the cleaning plan + safety guards (no model)
│   │   ├── eda.py              # EDA math + Plotly figure builders
│   │   └── orchestrator.py     # the full workflow incl. the 3-round verifier loop
│   ├── reporting/
│   │   ├── report_builder.py   # overview / cleaning-log / HTML export
│   │   ├── findings.py         # the deterministic "key findings"
│   │   └── serialize.py        # PipelineResult → JSON (+ dark Plotly) + chat grounding text
│   ├── state/project_store.py  # in-memory projects, no persistence
│   ├── voice/speech.py         # offline STT (faster-whisper) + TTS (Piper)
│   └── ws/project_socket.py    # one WS per project: queued pipeline, chat, voice loop
├── frontend/                   # Vite + React + TS + Tailwind
│   └── src/
│       ├── App.tsx             # layout + all the state
│       ├── components/         # Sidebar, ChatThread, AnalysisCanvas, VoiceControl, ReportTabs/…
│       ├── lib/{api,websocket,useVoice}.ts
│       └── styles/tokens.css   # dark design tokens + the gradient glow
├── sample_data/                # a synthetic messy test file + its generator
├── app_streamlit_legacy.py     # the retired first version, kept for reference
├── requirements.txt
└── PROJECT_OVERVIEW.md         # this file
```

## The pipeline, step by step

One rule runs through all of it:

> The model decides. Code does.
> Profiling, execution, the EDA math and the analysis queries are all pandas, numpy and scipy. The model plans the cleaning, reviews it, and narrates the results. It never touches a raw row or computes a statistic.

```
upload → profile → [plan] → execute → [review] ──approved?──▶ EDA → findings → [narrative] → report
                     ▲                     │ no (≤3 rounds)
                     └──── targeted revision ◀─┘
```

**Profiling (no model).** For each column, code works out the current type, a few sample values, how much is missing, how many unique values, the placeholder junk ("N/A", "-", "?", "unknown"), and for anything numeric the min/max/mean/median/mode, the skew, and an IQR outlier count. That compact profile, not the raw dataframe, is what the model sees. It keeps the prompt small and keeps your data out of the model.

**The Correction agent.** Given those profiles, it returns strict JSON for each column: the corrected type, which placeholder tokens to treat as missing, an imputation strategy (mean, median, mode, leave null, drop the row, a constant, forward fill), and a justification. The prompt bakes in the sensible defaults: median for skewed numbers, mode for categories, leave or drop anything more than half empty.

**Execution (no model).** Code applies the plan in pandas and records a before-and-after for every column. It also runs a few guards that fire no matter what the model asked for:

- Case and whitespace get standardised. "DELHI", "delhi" and " Delhi " all become "Delhi" (Title Case, with short acronyms like USA left alone). The profiler spots the variants, the cleaner is told to mark those columns categorical, and the verifier flags it if the cleaner forgets.
- A text column can't be cast to numbers and blanked out. If the cast would destroy most of the values, the column stays text.
- A mostly-empty column won't be imputed. Filling 75% of a column with one value isn't cleaning, it's making things up, so it's left null.

All three show up in the report. Nothing happens behind your back.

**The verifier and the loop.** The verifier sees cold facts only: the original profiles and what the cleaner decided (type, strategy, resulting missing percent). It never sees *why* the cleaner chose that, so it has to judge each decision on its own merits. It's told to go looking for problems and to cite the number behind each one.

The loop runs up to three rounds. Clean, execute, review. If the verifier approves, stop. If not, hand the cleaner only the flagged columns plus its own current decision, and ask it to change just what was flagged and leave the rest alone. Log every round. If they still can't agree after three, keep the latest cleaning and show the disagreement rather than hiding it.

Two fixes make this loop trustworthy, and both came out of watching it fail. The first is handing the cleaner its previous decision when it revises; without that, it re-derived each flagged column from scratch and broke things the verifier never complained about. The second is a deterministic filter that throws out any verifier complaint the current cleaning already satisfies. At temperature 0 the verifier kept re-raising issues the cleaner had already fixed, so the loop never converged and correct columns got marked "unresolved." With the filter, a normal run approves in a round or two and nothing gets falsely flagged.

**The Insights agent.** Code computes the EDA (describe stats, Pearson and Spearman correlations with significance, the top correlated pairs, category counts, skew, outliers) and builds the charts as dark-themed Plotly figures. Code also derives the key findings as exact, readable cards. Only then does the model write the narrative and three to five takeaways, using only those computed numbers.

## Chatting with the result

Two agents handle conversation, both stateless (the full message list is rebuilt every turn, so nothing leaks between calls).

The Analysis agent handles anything that needs a fresh calculation. Ask "which city has the highest average income" and a deterministic router recognises it as a compute question, the model writes a line of pandas, and the backend runs it against the cleaned dataframe in a locked-down namespace: `pd`, `np`, `df` only, no imports, no files, no network. You get the real table and the exact code. Numeric-looking text columns get coerced first, obviously-broken code gets repaired and retried a few times, and if it genuinely can't compute the answer it says so instead of faking one.

The Chat agent handles questions about the cleaning, the verification or the EDA. It answers only from the computed report, streams token by token, and admits when the report doesn't cover something.

The router is mostly regex, with the model only breaking ties. "How many per", "average by", "which X has the most", correlations and percentages go to compute. "Why did you use the median", "what strategy" go to the grounded report.

## Voice

Once a report exists you can talk to it. It's a turn-based loop that reuses the same analysis router, so a spoken question runs the same pandas and speaks the real answer back.

```
mic → in-browser VAD detects an utterance → faster-whisper (STT)
    → same chat/analysis pipeline → Piper (TTS) → play reply → resume listening
```

Turn-taking uses an in-browser voice-activity detector, and the mic is muted while the agent is thinking or speaking so it never hears itself. Spoken replies are kept short so the synthesis stays quick, but the full text and any table still land in the chat thread. The UI shows where it is at each moment: transcribing, thinking, speaking, idle.

## Backend decisions worth knowing

- In-memory, no database. State lives on the process and resets on restart. Fine for a single-user local tool.
- One pipeline at a time. On a CPU-only box a global lock keeps two runs from fighting over the cores; a second upload waits its turn.
- Blocking work stays off the event loop. The agent, pandas and speech work runs in a thread pool, and progress is pushed back to the async side and out over the project's WebSocket.
- The server-to-client WebSocket events are `status` (with the verifier round), `message`, `report_ready`, `chat_status`, `chat_token`, `chat_done`, `error`, `status_change`, and the voice ones: `voice_state`, `voice_transcript`, `voice_audio`.
- Nothing leaves the machine. No cloud calls anywhere. The only network traffic is the one-time model downloads.

## The frontend look

Dark, restrained, with one deliberate flourish. Near-black surfaces, a slate-and-indigo palette, Space Grotesk for headings, Inter for the UI, JetBrains Mono for numbers. The flourish is the Analysis Canvas: a pinned panel on the right with a slow gradient glow that pulses while the agents work and settles once the report is done, so you never have to scroll back through chat to find it. It's responsive (collapses to drawers on narrow screens), the focus states are visible for keyboard use, and `prefers-reduced-motion` turns the animation off.

## How it got here

It didn't start like this.

1. It began as a Streamlit app: one file, the whole pipeline working. That's still in the repo as `app_streamlit_legacy.py` for reference.
2. Then I rebuilt it as a FastAPI backend and a React frontend, a projects-and-live-chat interface with the pinned canvas, moving the tested pipeline into `backend/` without changing it.
3. Added editable project names, then the real analysis capability: chat that runs pandas and returns actual results instead of hand-waving.
4. Added the hands-free voice mode.
5. Upgraded the models from 3B to 7-8B for better cleaning, and fixed the verifier loop so it converges instead of regressing.
6. Tightened it for precision, greedy sampling and the refuse-don't-fabricate rules, so it says "I don't know" rather than guessing.

## What it doesn't do well

- It's slow. 7-8B on CPU means a clean takes real minutes, plus the RAM swap between models each round. The 3B tier trades that back for lower quality.
- The small models have a ceiling. Single-metric questions are reliable. A genuinely compound one ("which city has the most records and what percentage of the total") can still throw the model, though when it does it says it couldn't work it out and shows the code it tried, rather than inventing a number.
- No persistence. Restart and the projects are gone.
- Voice is English-only right now, with the current Whisper and Piper models. Both are swappable in `config.py`.
