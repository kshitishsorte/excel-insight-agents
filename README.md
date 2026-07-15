# excel-insight-agents

A small studio for cleaning messy spreadsheets that runs entirely on your own machine. You drop in an Excel file, a few local LLM agents work out how to clean it, it runs the analysis, and then you can talk to the result, by text or by voice. Nothing leaves your computer. No API keys, no database.

I built it because most "AI data cleaning" tools either ship your file off to someone else's server or hand back a black box you're supposed to trust. This does neither. The models run locally through Ollama, every actual change to your data is plain pandas you can read, and the reason for each decision is written down next to it.

> There's a longer, more technical write-up in [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).

## How it works

There are three agents with one job each, plus a couple more that turn up once you start asking questions.

The Correction agent gets a profile of every column (its type, how much is missing, skew, outliers, the placeholder junk like "N/A" and "-") and decides how to fix it. It only decides. The casting, filling and dropping is done by pandas, so the model can't quietly wreck your data.

A Verifier agent then reviews that plan. It's deliberately a different model family (Qwen cleans, Llama checks), and it never sees the cleaner's reasoning, only its decisions, so it forms its own opinion instead of agreeing out of politeness. If it objects, the cleaner gets another go at just the flagged columns, up to three rounds. When they genuinely can't agree, the app says so instead of pretending the data is fine.

The Insights agent does the EDA itself (correlations, distributions, outliers) and only hands the finished numbers to a model to write up. Same rule everywhere: if a number shows up in the app, pandas computed it. The LLM narrates, it never does the math.

Once the report is ready you can ask it things. "Which city has the highest average income?" makes it write pandas, run it on the cleaned data, and show you both the table and the code it used. "Why did you use the median for income?" gets an answer straight from the report. Ask for something the data doesn't contain and it tells you it doesn't know rather than guessing. There's a hands-free voice mode wired to the same pipeline, so you can say the question and hear the answer back.

## The models

Everything runs locally through Ollama. There's a one-time download, then no ongoing cost and no network calls.

| Job | Model | Family |
|---|---|---|
| Cleaning, insights, chat | qwen2.5:7b-instruct | Qwen |
| Verifying | llama3.1:8b | Llama |
| Speech to text | Whisper base.en (faster-whisper) | local |
| Text to speech | Piper (en_US-lessac-medium) | local |

Two different families is the point, not an accident. A verifier that's the same model as the cleaner mostly agrees with itself, which is useless. Qwen and Llama actually push back on each other.

The size (7-8B) is a compromise I landed on the hard way. This machine has no GPU, so every token is CPU work. 3B models were fast but cleaned sloppily, and they got *worse*, not better, when the verifier corrected them. Moving up to 7-8B fixed the quality. The price is that a full run takes ten to twenty minutes, and because both models won't fit in 16GB of RAM at once, Ollama swaps them in and out between rounds. If you want the speed back, switching to the 3B models is one line in `config.py`.

## Getting the models

Two things to set up once: Ollama for the language models, and the speech models for voice (those fetch themselves).

Install Ollama from [ollama.com](https://ollama.com) — one installer for macOS, Windows or Linux. With it running, pull the two models the app uses:

```bash
ollama pull qwen2.5:7b-instruct   # ~4.7 GB — cleaning, insights, chat
ollama pull llama3.1:8b           # ~4.9 GB — the independent verifier
```

That's roughly 10 GB, and it's the slow part of setup, so go make a coffee. By default Ollama keeps models in its own folder; if your system drive is tight, set `OLLAMA_MODELS` to somewhere with room before you pull (e.g. `OLLAMA_MODELS=D:\models`). Check they landed with:

```bash
ollama list      # should list qwen2.5:7b-instruct and llama3.1:8b
```

The voice models need nothing from you. The first time you turn voice on, the app downloads Whisper for listening (~140 MB) and a Piper voice for speaking (~60 MB) into the folder set by `VOICE_MODELS_DIR` (default `E:\LLM\voice`), then runs offline. Point that env var elsewhere if you'd rather. And if you want different models entirely, they're all named at the top of `backend/config.py`.

## Running it

With the models pulled (above), for normal use build the frontend once and let FastAPI serve the whole thing on one port:

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn backend.main:app
```

Then open http://localhost:8000.

If you're hacking on it, run the backend and the Vite dev server in two terminals instead:

```bash
uvicorn backend.main:app --reload      # terminal 1
cd frontend && npm run dev             # terminal 2, serves http://localhost:5173
```

Vite proxies the API and websocket through to the backend. The frontend is pinned to Vite 4 so it builds on Node 16; newer Node works too. The first time you switch voice on, the speech models download themselves (about 200MB), and it's offline after that. There's a synthetic messy file in `sample_data/` if you just want to watch it work.

## The one design rule

The LLM plans and narrates. Deterministic Python does everything else. Profiling, execution, the EDA math and the analysis queries are all pandas, numpy and scipy, and a few guardrails run no matter what the model decides:

- it can't cast a text column to numbers and blank it out,
- it won't fill a column that's more than half empty, because leaving it null is more honest than inventing values,
- categorical values that differ only by case get standardized to one Title-Cased spelling, so "DELHI", "delhi" and " Delhi " all end up as "Delhi".

Projects and chat history live in memory and vanish when you restart the server. No database, on purpose. It's a single-user tool that runs on your desk, not a service.

## What it won't do

It isn't fast. On CPU with 7-8B models a clean takes real minutes, and short of a GPU there's no clever fix.

The models are good, not flawless. Straightforward questions ("average income by city", "how many rows where X > 5") are reliable. A properly compound one ("which city has the most records and what share of the total is that") can still confuse the model, and when it does it tells you it couldn't compute the answer and shows the code it tried, instead of making something up.

It has no login and no rate limiting, because it's meant to run locally for one person. Don't put it on the open internet as-is.

## Stack

FastAPI, WebSockets, pandas/numpy/scipy, Ollama, faster-whisper and Piper on the backend. Vite, React, TypeScript and Tailwind on the frontend, with react-plotly for the charts and self-hosted fonts so it stays offline. The full layout and the reasoning behind each piece is in [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md).
