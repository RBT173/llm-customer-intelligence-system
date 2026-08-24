# LLM-Based Customer Intelligence System

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688)
![Groq](https://img.shields.io/badge/LLM-Groq%20gpt--oss--120b-orange)
![Status](https://img.shields.io/badge/status-working-brightgreen)

**PIO-TECH Internship Program — Task 3 (Upgraded 2026 Version)**

A production-oriented pipeline that takes a raw customer message and turns it
into structured, actionable intelligence: detected intent, priority, extracted
entities, a routing recommendation, and a policy-grounded response — using an
LLM plus a lightweight retrieval layer over a small internal knowledge base.

📐 **[Architecture diagram →](architecture.md)**
📊 **[Evaluation report →](eval/evaluation_report.md)**

---

## Table of Contents

- [What this actually is](#what-this-actually-is)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Running the system](#running-the-system)
- [Running the evaluation](#running-the-evaluation)
- [Design decisions and what changed along the way](#design-decisions-and-what-changed-along-the-way)
- [Known limitations](#known-limitations)
- [Deliverables checklist](#deliverables-checklist-section-12)

---

## What this actually is

| Component | Detail |
|---|---|
| **API** | FastAPI service exposing `POST /process-customer-message` |
| **LLM** | Groq's free API — `openai/gpt-oss-120b` via **tool/function calling** (not plain prompting) |
| **Retrieval** | Keyword/tag-overlap matcher over 8 hand-written policy docs — MVP, not a vector DB |
| **Dataset** | 62 hand-labeled customer messages — disputes, fraud, account queries, multi-intent, ambiguous, retrieval-requiring |
| **Evaluation** | Automated script scoring the live system against ground truth (spec Section 10) |

---

## Project structure
Got it — here's the raw content. Open README.md in VS Code, select all (Ctrl+A), delete, then paste this directly:

markdown
# LLM-Based Customer Intelligence System

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-API-009688)
![Groq](https://img.shields.io/badge/LLM-Groq%20gpt--oss--120b-orange)
![Status](https://img.shields.io/badge/status-working-brightgreen)

**PIO-TECH Internship Program — Task 3 (Upgraded 2026 Version)**

A production-oriented pipeline that takes a raw customer message and turns it
into structured, actionable intelligence: detected intent, priority, extracted
entities, a routing recommendation, and a policy-grounded response — using an
LLM plus a lightweight retrieval layer over a small internal knowledge base.

📐 **[Architecture diagram →](architecture.md)**
📊 **[Evaluation report →](eval/evaluation_report.md)**

---

## Table of Contents

- [What this actually is](#what-this-actually-is)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Running the system](#running-the-system)
- [Running the evaluation](#running-the-evaluation)
- [Design decisions and what changed along the way](#design-decisions-and-what-changed-along-the-way)
- [Known limitations](#known-limitations)
- [Deliverables checklist](#deliverables-checklist-section-12)

---

## What this actually is

| Component | Detail |
|---|---|
| **API** | FastAPI service exposing `POST /process-customer-message` |
| **LLM** | Groq's free API — `openai/gpt-oss-120b` via **tool/function calling** (not plain prompting) |
| **Retrieval** | Keyword/tag-overlap matcher over 8 hand-written policy docs — MVP, not a vector DB |
| **Dataset** | 62 hand-labeled customer messages — disputes, fraud, account queries, multi-intent, ambiguous, retrieval-requiring |
| **Evaluation** | Automated script scoring the live system against ground truth (spec Section 10) |

---

## Project structure

llm-customer-intelligence-system/
├── config/
│ └── intent_taxonomy.json # canonical intents, routing teams, priority levels
├── data/
│ ├── customer_messages_dataset.json # 62 labeled messages (source of truth)
│ └── customer_messages_dataset.csv # same data, flattened, for quick review
├── knowledge_base/
│ ├── knowledge_base.json # 8 policy docs, structured (used by retrieval.py)
│ └── kb-00X_*.md # same docs as readable markdown
├── src/
│ ├── input.py # FastAPI app / API layer
│ ├── prompts.py # system prompt + JSON schema construction
│ ├── engine.py # Groq API call, tool calling, validation, retry
│ ├── retrieval.py # keyword-based RAG retrieval
│ └── logger.py # request/output logging
├── eval/
│ ├── eval.py # runs dataset through the live system
│ └── generate_report.py # turns results.json into evaluation_report.md
├── architecture.md # pipeline diagram (ASCII)
├── requirements.txt
└── README.md


---

## Setup

**1. Requirements**: Python 3.10+ (the code uses `X | None` type hints).

**2. Install dependencies:**
```bash
pip install -r requirements.txt
```

**3. Get a free Groq API key** — no credit card required:
[console.groq.com/keys](https://console.groq.com/keys) → Create API Key

**4. Set it as an environment variable:**

| Platform | Command |
|---|---|
| macOS/Linux | `export GROQ_API_KEY=gsk_your_key_here` |
| Windows (session only) | `$env:GROQ_API_KEY = "gsk_your_key_here"` |
| Windows (**permanent**, recommended) | `[System.Environment]::SetEnvironmentVariable("GROQ_API_KEY", "gsk_your_key_here", "User")` — then open a new terminal |

---

## Running the system

**Start the API:**
```bash
uvicorn src.input:app --reload --port 8000
```

**Health check:**
```bash
curl http://localhost:8000/health
```

**Process a message:**
```bash
curl -X POST http://localhost:8000/process-customer-message \
  -H "Content-Type: application/json" \
  -d '{"message": "I was charged twice for the same transaction."}'
```

**Expected response shape:**
```json
{
  "intent": ["Billing Issue", "Dispute"],
  "issue_type": "Duplicate Charge",
  "priority": "High",
  "entities": ["duplicate transaction"],
  "routing": "Billing Department",
  "suggested_action": "Open a dispute case, verify transaction logs...",
  "response": "Based on our Dispute & Refund Resolution Policy...",
  "needs_clarification": false,
  "clarifying_question": ""
}
```

📎 Interactive API docs (Swagger UI): `http://localhost:8000/docs`

---

## Running the evaluation

```bash
python -m eval.eval            # runs all 62 messages, writes eval/results.json
python -m eval.generate_report # turns results.json into eval/evaluation_report.md
```

⏱️ A full run takes roughly **10-15 minutes** — calls are deliberately paced
(10s apart, plus automatic backoff on rate limits) to stay within Groq's
free-tier token budget.

---

## Design decisions and what changed along the way

This project went through a few real iterations worth documenting, since they
reflect actual engineering trade-offs rather than a first-draft-is-final build.

### 1. Model backend: Anthropic → local Ollama → Groq

The first version called the Anthropic API directly. That's not free, so the
system was rebuilt around **local inference (Ollama)** per the spec's Section 9
suggestion. That conflicts with wanting a **deployed public API** — Render's
free tier has 512MB RAM, nowhere near enough to run an 8B local model. The
system settled on **Groq's free cloud API**: genuinely free, runs an
open-weight model (`openai/gpt-oss-120b`, Groq's recommended replacement after
retiring its Llama endpoints), and is reachable from a deployed server.

### 2. Structured output: `response_format=json_object` → tool/function calling

| Approach | Intent exact-match | Successful runs |
|---|---|---|
| `response_format=json_object` (baseline) | 53.3% | 30/62 |
| Tool/function calling (final) | *see [evaluation_report.md](eval/evaluation_report.md)* | *see report* |

The JSON-mode baseline, even with an explicit list of allowed values in the
prompt, frequently produced invalid values (e.g. `"Fraud Department"` instead
of the fixed `"Fraud Team"` enum value) — plausible-sounding but not in the
taxonomy, triggering schema-validation failures even after a retry.

Switching to **tool/function calling** — defining the schema as a callable
tool and forcing the model to call it — produced meaningfully more reliable
adherence to the fixed taxonomy, since models are more strongly trained to
conform function arguments to a provided schema than to follow prose
instructions in a system prompt. Raw data: `eval/results_json_mode.json`
(baseline) vs `eval/results.json` (current).

### 3. Rate limiting

Groq's free tier caps at 8,000 tokens/minute. Early evaluation runs hit this
constantly — each call (large system prompt + retrieved policy context) uses
roughly 1,400-1,800 tokens. Fixed by pacing calls 10 seconds apart as a
baseline, and having `engine.py` catch 429 responses specifically, parse
Groq's suggested wait time out of the error message, and back off
automatically before retrying — rather than just failing.

### 4. Retrieval: keyword matching, not embeddings

`retrieval.py` is intentionally an MVP: it scores knowledge base documents by
tag-phrase and body-token overlap with the incoming message, weighting tag
matches 3x higher than body-content matches. Dependency-light (no vector DB),
but has real limits — see below.

---

## Known limitations

| Limitation | Impact | Would fix with |
|---|---|---|
| Retrieval is keyword-based, not semantic | Misses synonym/stemming cases (e.g. "fees" vs "fee") | FAISS or Chroma + embeddings |
| No fine-tuning performed | — | Out of scope per spec Section 3 |
| Structured output validated client-side, not schema-compiled | Occasional retry/failure under load | Provider-native structured outputs |
| Ambiguity handling not perfect | `needs_clarification` not always set correctly | See ambiguity metric in evaluation report |

---

## Deliverables checklist (Section 12)

| Deliverable | Status |
|---|---|
| Dataset of customer messages | ✅ `data/customer_messages_dataset.json` (62 messages) |
| Fully working system (API) | ✅ `src/` |
| Architecture diagram | ✅ `architecture.md` |
| Evaluation report | ✅ `eval/evaluation_report.md` |
| README with setup/usage instructions | ✅ this file |
| RAG implementation *(optional)* | ✅ `src/retrieval.py` + `knowledge_base/` |
| Docker setup *(optional)* | ⬜ not done |
| API deployment *(optional)* | ⬜ not done |