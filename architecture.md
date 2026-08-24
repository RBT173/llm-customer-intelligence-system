# Architecture — LLM-Based Customer Intelligence System

        +------------------------------------------------------+
        |                    CLIENT REQUEST                    |
        |                                                      |
        |     Raw customer message (chat / email / ticket)     |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |                 1. INPUT / API LAYER                 |
        |                                                      |
        |      FastAPI  ·  POST /process-customer-message      |
        |                     src/input.py                     |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |             2. PROMPT ENGINEERING LAYER              |
        |                                                      |
        |           Uses config/intent_taxonomy.json           |
        |          Builds system prompt + JSON Schema          |
        |    Injects retrieved policy context into message     |
        |                    src/prompts.py                    |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |         3. KNOWLEDGE LAYER — RAG (optional)          |
        |                                                      |
        |      Uses knowledge_base/*.json (8 policy docs)      |
        | Keyword / tag-overlap retrieval (MVP — no vector DB) |
        |                   src/retrieval.py                   |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |                4. LLM REASONING LAYER                |
        |                                                      |
        |            Groq API — openai/gpt-oss-120b            |
        |  Tool / function calling (schema-constrained args)   |
        |        429 backoff + retry · validation retry        |
        |                    src/engine.py                     |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |             5. OUTPUT STRUCTURING LAYER              |
        |                                                      |
        |    jsonschema validation against required schema     |
        |        src/engine.py — _parse_and_validate()         |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |                   6. LOGGING LAYER                   |
        |                                                      |
        |   Requests, outputs, latency -> stdout + log file    |
        |                    src/logger.py                     |
        +------------------------------------------------------+
                                    |
                                    v
        +------------------------------------------------------+
        |               STRUCTURED JSON RESPONSE               |
        |                                                      |
        |   intent, priority, routing, grounded response...    |
        +------------------------------------------------------+

========================================================================
                    EVALUATION PIPELINE
========================================================================
+----------------------+ +----------------------+ +----------------------+
| LABELED DATASET | | eval.py | | generate_report.py |
| | | | | |
| 62 messages, | --> | Runs each message | --> | Writes |
| ground_truth | |scores vs ground_truth| | evaluation_report.md |
+----------------------+ | -> results.json | +----------------------+
+----------------------+Metrics tracked:
  - Intent exact-match & Jaccard overlap
  - Routing / Priority / Issue-type accuracy
  - Output completeness
  - Retrieval doc-match rate (14 retrieval-flagged messages)
  - Consistency across 6 paraphrase pairs
  - Ambiguity handling: needs_clarification correctness (14 ambiguous messages)

Approach comparison documented:
  response_format=json_object (baseline)  vs.  tool/function calling (final)
  -> see eval/results_json_mode.json vs eval/results.json, and evaluation_report.md


------------------------------------------------------------------------
Out of scope (per Task 3 spec, Section 3): fine-tuning foundation
models, full production deployment at scale, external integrations
with live banking systems.
------------------------------------------------------------------------
**Notes:**
- Layer 2 (Prompt Engineering) reads its allowed values from
  `config/intent_taxonomy.json` — the canonical list of intents, routing
  teams, and priority levels.
- Layer 3 (Knowledge/RAG) reads from `knowledge_base/*.json` — 8 policy
  documents used for grounded responses.

