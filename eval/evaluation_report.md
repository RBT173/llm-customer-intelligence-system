# Evaluation Report — LLM-Based Customer Intelligence System

**Date:** 2026-09-02
**Dataset:** 62 messages (62 scored, 0 failed to process)

## 1. Output Quality

| Metric | Result |
|---|---|
| Intent exact-match rate | 41.9% |
| Intent Jaccard similarity (avg) | 0.594 |
| Routing correctness | 71.0% |
| Priority correctness | 58.1% |
| Issue type correctness | 19.4% |
| Structured output completeness | 100.0% |

**Method:** Each message's model output was compared against its `ground_truth`
label in the dataset. Intent uses both exact-set match (strict) and Jaccard
similarity (partial credit for overlapping but non-identical intent sets,
since multi-intent messages can reasonably be tagged in more than one valid
way). Routing, priority, and issue type use exact string match. Completeness
checks that all required schema fields are present and non-empty.

**Failures observed:** 18 routing errors, 26 priority errors out of 62 scored messages.
See message IDs: 10, 11, 12, 14, 17, 18, 20, 30, 33, 35...

## 2. Retrieval Quality

| Metric | Result |
|---|---|
| Correct KB document retrieved | 78.6% (14 messages evaluated) |

**Method:** For the 14 dataset messages flagged
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
| Priority stable across paraphrases | 50.0% |
| Routing stable across paraphrases | 66.7% |
| Intent Jaccard similarity across paraphrases | 0.417 |

**Method:** The dataset includes 6 paraphrase pairs — each a
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
- **Ambiguous messages:** 13/14 (92.9%) of ambiguous/incomplete messages were correctly flagged with `needs_clarification: true` rather than the model guessing a specific classification.
- **Retrieval:** keyword-based, not semantic — see Section 2 above.

## 5. Suggested Future Improvements

1. Replace keyword-overlap retrieval with a real embedding-based vector
   store (FAISS or Chroma, as recommended in the spec's Technology
   Requirements) for better retrieval precision.
2. Run multiple trials per message (not just paraphrase pairs) to measure
   raw output variance at a fixed temperature.
3. Expand the paraphrase set beyond 6 pairs for a more statistically
   robust consistency measurement.
