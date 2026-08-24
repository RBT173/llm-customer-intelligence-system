"""
Generates eval/evaluation_report.md from eval/results.json (produced by
eval.py). Run this after eval.py completes:

    python -m eval.generate_report
"""

import json
from pathlib import Path
from datetime import date

RESULTS_PATH = Path(__file__).parent / "results.json"
REPORT_PATH = Path(__file__).parent / "evaluation_report.md"


def pct(x):
    return f"{x:.1%}" if x is not None else "N/A"


def generate_report():
    if not RESULTS_PATH.exists():
        raise FileNotFoundError(
            f"{RESULTS_PATH} not found. Run `python -m eval.eval` first."
        )

    with open(RESULTS_PATH) as f:
        data = json.load(f)

    results = data["per_message_results"]
    n = len(results)

    if n == 0:
        raise ValueError("No successful results in results.json -- nothing to report.")

    intent_exact_rate = sum(r["intent_exact_match"] for r in results) / n
    intent_jaccard_avg = sum(r["intent_jaccard"] for r in results) / n
    routing_rate = sum(r["routing_correct"] for r in results) / n
    priority_rate = sum(r["priority_correct"] for r in results) / n
    issue_type_rate = sum(r["issue_type_correct"] for r in results) / n
    completeness_rate = sum(r["output_complete"] for r in results) / n

    retrieval_scored = [r for r in results if r["retrieval_correct"] is not None]
    retrieval_rate = (
        sum(r["retrieval_correct"] for r in retrieval_scored) / len(retrieval_scored)
        if retrieval_scored else None
    )

    consistency = data["consistency_results"]
    priority_stable_rate = (
        sum(c["priority_stable"] for c in consistency) / len(consistency) if consistency else None
    )
    routing_stable_rate = (
        sum(c["routing_stable"] for c in consistency) / len(consistency) if consistency else None
    )
    intent_jaccard_consistency_avg = (
        sum(c["intent_jaccard"] for c in consistency) / len(consistency) if consistency else None
    )

    # Identify the worst-performing messages for qualitative discussion
    routing_failures = [r for r in results if not r["routing_correct"]]
    priority_failures = [r for r in results if not r["priority_correct"]]

    # Ambiguity handling: did the model correctly flag needs_clarification
    # on messages the dataset marks as ambiguous/incomplete?
    DATA_PATH = Path(__file__).parent.parent / "data" / "customer_messages_dataset.json"
    with open(DATA_PATH) as f:
        dataset = json.load(f)
    ambiguous_ids = {e["id"] for e in dataset if e.get("is_ambiguous")}
    ambiguous_scored = [r for r in results if r["id"] in ambiguous_ids]
    if ambiguous_scored:
        correctly_flagged = sum(
            1 for r in ambiguous_scored
            if r["model_output"].get("needs_clarification") is True
        )
        ambiguous_summary = (
            f"{correctly_flagged}/{len(ambiguous_scored)} "
            f"({correctly_flagged/len(ambiguous_scored):.1%}) of ambiguous/incomplete "
            f"messages were correctly flagged with `needs_clarification: true` "
            f"rather than the model guessing a specific classification."
        )
    else:
        ambiguous_summary = "No ambiguous messages were scored in this run."

    report = f"""# Evaluation Report — LLM-Based Customer Intelligence System

**Date:** {date.today().isoformat()}
**Dataset:** {data['total_messages']} messages ({data['successful_runs']} scored, {data['failed_runs']} failed to process)

## 1. Output Quality

| Metric | Result |
|---|---|
| Intent exact-match rate | {pct(intent_exact_rate)} |
| Intent Jaccard similarity (avg) | {intent_jaccard_avg:.3f} |
| Routing correctness | {pct(routing_rate)} |
| Priority correctness | {pct(priority_rate)} |
| Issue type correctness | {pct(issue_type_rate)} |
| Structured output completeness | {pct(completeness_rate)} |

**Method:** Each message's model output was compared against its `ground_truth`
label in the dataset. Intent uses both exact-set match (strict) and Jaccard
similarity (partial credit for overlapping but non-identical intent sets,
since multi-intent messages can reasonably be tagged in more than one valid
way). Routing, priority, and issue type use exact string match. Completeness
checks that all required schema fields are present and non-empty.

**Failures observed:** {len(routing_failures)} routing errors, {len(priority_failures)} priority errors out of {n} scored messages.
{"See message IDs: " + ", ".join(str(r['id']) for r in routing_failures[:10]) + ("..." if len(routing_failures) > 10 else "") if routing_failures else "No routing errors observed."}

## 2. Retrieval Quality

| Metric | Result |
|---|---|
| Correct KB document retrieved | {pct(retrieval_rate)} ({len(retrieval_scored)} messages evaluated) |

**Method:** For the {len(retrieval_scored)} dataset messages flagged
`requires_retrieval`, we check whether the retrieval layer's top result(s)
included the `kb_reference` document specified in ground truth.

**Known limitation:** The retrieval layer (`src/retrieval.py`) uses
keyword/tag overlap scoring rather than semantic embeddings (no FAISS/Chroma
vector DB). This is a deliberate MVP trade-off — it works well for messages
with clear keyword signal but can retrieve an adjacent, loosely-related
document alongside (or instead of) the correct one, particularly for
messages whose wording differs significantly from the policy doc's
vocabulary. Retrieval quality would likely improve with a proper embedding-
based retriever, listed as a possible future improvement below.

## 3. Consistency Tests

| Metric | Result |
|---|---|
| Priority stable across paraphrases | {pct(priority_stable_rate)} |
| Routing stable across paraphrases | {pct(routing_stable_rate)} |
| Intent Jaccard similarity across paraphrases | {f"{intent_jaccard_consistency_avg:.3f}" if intent_jaccard_consistency_avg is not None else "N/A"} |

**Method:** The dataset includes {len(consistency)} paraphrase pairs — each a
reworded version of an existing message, expected to produce the same
priority and routing decision as the original despite different surface
wording. This tests prompt robustness: does the system's decision depend on
the underlying intent, or on incidental phrasing?

## 4. Discussion & Limitations

- **Model:** This system uses `openai/gpt-oss-120b` served via Groq's free
  API tier. No fine-tuning was performed (out of scope per spec Section 3).
- **Structured output:** Enforced via Groq's JSON mode plus client-side
  schema validation with one automatic retry on failure — not the stronger
  constrained-decoding guarantee available on some other providers, so
  occasional malformed-output failures are possible (see failed_runs above).
- **Ambiguous messages:** {ambiguous_summary}
- **Retrieval:** keyword-based, not semantic — see Section 2 above.

## 5. Suggested Future Improvements

1. Replace keyword-overlap retrieval with a real embedding-based vector
   store (FAISS or Chroma, as recommended in the spec's Technology
   Requirements) for better retrieval precision.
2. Run multiple trials per message (not just paraphrase pairs) to measure
   raw output variance at a fixed temperature.
3. Expand the paraphrase set beyond 6 pairs for a more statistically
   robust consistency measurement.
"""

    with open(REPORT_PATH, "w") as f:
        f.write(report)

    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    generate_report()
