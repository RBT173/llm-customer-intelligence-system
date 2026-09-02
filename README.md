
---

## Setup

**1. Requirements**: Python 3.10+ (the code uses modern type hints like `str | None`).

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

**Fastest option — just use the deployed version:**
Open [https://llm-customer-intelligence-frontend.onrender.com](https://llm-customer-intelligence-frontend.onrender.com) in any browser. No setup needed.

**Running locally instead:**
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

Interactive API docs (Swagger UI, local): `http://localhost:8000/docs`

---

## Running the evaluation

```bash
python -m eval.eval                # runs all 62 messages, writes eval/results.json
python -m eval.generate_report     # turns results.json into eval/evaluation_report.md
python -m eval.consistency_eval    # optional: multi-run variance study on a subset
```

A full `eval.eval` run takes roughly 10-15 minutes — calls are deliberately
paced (10s apart, plus automatic backoff on rate limits) to stay within
Groq's free-tier token budget. It also supports resuming: if the daily
token limit is hit mid-run, re-running the same command later picks up
where it left off instead of re-scoring already-completed messages.

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

A full 62-message run using Groq's plain JSON mode (`response_format: json_object`),
even with an explicit list of allowed values in the prompt, produced a
**53.3% intent exact-match rate** and **30/62 successful completions** — the
model frequently produced plausible-sounding but invalid values (e.g.
`"Fraud Department"` instead of the fixed `"Fraud Team"` enum value),
triggering schema-validation failures even after a retry.

Switching to **tool/function calling** — defining the schema as a callable
tool and forcing the model to call it — produced meaningfully more reliable
adherence to the fixed taxonomy, since models are more strongly trained to
conform function arguments to a provided schema than to follow prose
instructions in a system prompt. See `eval/results_json_mode.json`
(baseline) vs `eval/results.json` (current) for the raw data, and
`eval/evaluation_report.md` for the full comparison.

### 3. Rate limiting

Groq's free tier caps at 8,000 tokens/minute and 200,000 tokens/day. Early
evaluation runs hit both limits — each call (large system prompt + retrieved
policy context) uses roughly 1,400-1,800 tokens. Fixed with: pacing calls
10 seconds apart as a baseline, `engine.py` catching 429 responses and
parsing Groq's suggested wait time out of the error message (handling both
the "Xs" and "Xm Ys" formats Groq uses for per-minute vs. per-day limits),
and a resume feature in `eval.py` so a daily-limit interruption doesn't
waste quota re-scoring already-completed messages on the next run.

### 4. Retrieval: keyword matching, not embeddings

`retrieval.py` is intentionally an MVP: it scores knowledge base documents by
tag-phrase and body-token overlap with the incoming message, weighting tag
matches 3x higher than body-content matches. Dependency-light (no vector DB),
but has real limits — see below.

### 5. Frontend and deployment

The frontend (`frontend/index.html`) is a standalone HTML/CSS/JS console with
no build step, deployed as a separate Render Static Site pointed at the live
API. Both the backend and frontend are independently deployed so the whole
system is reachable through a browser with no local setup — see the links at
the top of this document.

---

## Known limitations

| Limitation | Impact | Would fix with |
|---|---|---|
| Retrieval is keyword-based, not semantic | Misses synonym/stemming cases (e.g. "fees" vs "fee") | FAISS or Chroma + embeddings |
| No fine-tuning performed | — | Out of scope per spec Section 3 |
| Structured output validated client-side, not schema-compiled | Occasional retry/failure under load | Provider-native structured outputs |
| Ambiguity handling not perfect | `needs_clarification` not always set correctly | See ambiguity metric in evaluation report |
| No authentication on the deployed API | Anyone with the URL can call it | See `PRODUCTION.md` |

For a fuller discussion of what would need to change before this could
handle real customer data, see [`PRODUCTION.md`](PRODUCTION.md).

---

## Deliverables checklist (Section 12)

| Deliverable | Status |
|---|---|
| Dataset of customer messages | ✅ `data/customer_messages_dataset.json` (62 messages) |
| Fully working system (API) | ✅ `src/`, deployed live |
| Architecture diagram | ✅ `architecture.md` |
| Evaluation report | ✅ `eval/evaluation_report.md` |
| README with setup/usage instructions | ✅ this file |
| RAG implementation *(optional)* | ✅ `src/retrieval.py` + `knowledge_base/` |
| API deployment *(optional)* | ✅ backend + frontend both deployed on Render |
| Docker setup *(optional)* | ⬜ not done — not prioritized given deployment already covers the production-extension goal |