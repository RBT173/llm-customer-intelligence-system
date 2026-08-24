"""
Evaluation Script - Section 10 (Evaluation Methodology).

Runs every message in data/customer_messages_dataset.json through the
full pipeline (retrieval -> LLM reasoning) and scores the result against
each message's ground_truth, covering:

  1. Output Quality
     - Intent detection accuracy (exact-set match + partial/Jaccard overlap)
     - Routing correctness (exact match)
     - Priority correctness (exact match)
     - Structured output completeness (all required fields present & non-empty)

  2. Retrieval Quality (for the 14 messages flagged requires_retrieval)
     - Whether the retriever pulled the expected kb_reference document

  3. Consistency Tests (for the 6 paraphrase pairs)
     - Whether a paraphrased message produces the same priority/routing/
       intent as its original (same input -> stable output behavior)

Usage:
    export GROQ_API_KEY=gsk_...
    python -m eval.eval

Writes eval/results.json (raw per-message results) and prints a summary.
Rate-limited to stay under Groq's free-tier 30 requests/minute cap.
"""

import json
import time
from pathlib import Path

from src.engine import process_message, EngineError, DailyLimitExceeded
from src.retrieval import retrieve_context

DATA_PATH = Path(__file__).parent.parent / "data" / "customer_messages_dataset.json"
RESULTS_PATH = Path(__file__).parent / "results.json"

# Groq free tier: 8,000 tokens/minute (TPM), not just a request-count limit.
# Each call in this pipeline (large system prompt + KB context) uses roughly
# 1,400-1,800 tokens, so pacing by request count alone isn't enough --
# space calls further apart to stay under the token budget. engine.py also
# handles 429s with automatic backoff as a safety net on top of this.
SECONDS_BETWEEN_CALLS = 10


def jaccard(a: list[str], b: list[str]) -> float:
    """Set overlap similarity between two label lists, order-independent."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def check_completeness(result: dict) -> bool:
    required = [
        "intent", "issue_type", "priority", "entities",
        "routing", "suggested_action", "response",
        "needs_clarification", "clarifying_question",
    ]
    for field in required:
        if field not in result:
            return False
        if field in ("intent", "entities") and not isinstance(result[field], list):
            return False
        if field not in ("intent", "entities", "needs_clarification") and result[field] == "":
            # empty string only acceptable for clarifying_question when not needed
            if field != "clarifying_question":
                return False
    return True


def score_message(entry: dict, result: dict, retrieved_ids: list[str]) -> dict:
    gt = entry["ground_truth"]

    intent_jaccard = jaccard(result.get("intent", []), gt["intent"])
    intent_exact = set(result.get("intent", [])) == set(gt["intent"])
    routing_correct = result.get("routing") == gt["routing"]
    priority_correct = result.get("priority") == gt["priority"]
    issue_type_correct = result.get("issue_type") == gt["issue_type"]
    complete = check_completeness(result)

    retrieval_correct = None
    if entry["requires_retrieval"]:
        expected = entry.get("kb_reference")
        retrieval_correct = expected in retrieved_ids if expected else None

    return {
        "id": entry["id"],
        "intent_exact_match": intent_exact,
        "intent_jaccard": round(intent_jaccard, 3),
        "routing_correct": routing_correct,
        "priority_correct": priority_correct,
        "issue_type_correct": issue_type_correct,
        "output_complete": complete,
        "retrieval_correct": retrieval_correct,
        "model_output": result,
    }


def run_evaluation(resume: bool = True):
    with open(DATA_PATH) as f:
        dataset = json.load(f)

    # Resume support: if results.json already exists, skip messages that
    # already succeeded, and only (re-)attempt failures/missing ones.
    # This matters because Groq's free tier has a 200,000 token/day limit --
    # re-running everything from scratch every time wastes quota on
    # messages that already scored correctly.
    already_succeeded = {}
    if resume and RESULTS_PATH.exists():
        with open(RESULTS_PATH) as f:
            prior = json.load(f)
        already_succeeded = {r["id"]: r for r in prior.get("per_message_results", [])}
        if already_succeeded:
            print(f"Resuming: {len(already_succeeded)} message(s) already succeeded in a prior run, skipping them.")

    all_results = list(already_succeeded.values())
    failures = []
    scored_by_id = dict(already_succeeded)

    for i, entry in enumerate(dataset):
        if entry["id"] in already_succeeded:
            continue

        print(f"[{i+1}/{len(dataset)}] Processing message {entry['id']}...")

        try:
            retrieved = retrieve_context(entry["message"])
            retrieved_ids = [d["id"] for d in retrieved] if retrieved else []
            result = process_message(entry["message"], retrieved)
        except DailyLimitExceeded as exc:
            print(f"\n!! Daily token limit reached: {exc}")
            print(f"!! Stopping run early. {len(all_results)}/{len(dataset)} messages scored so far.")
            print("!! Re-run `python -m eval.eval` later (e.g. tomorrow) to continue -- ")
            print("!! it will automatically resume from where this run stopped.")
            break
        except EngineError as exc:
            print(f"  FAILED: {exc}")
            failures.append({"id": entry["id"], "error": str(exc)})
            time.sleep(SECONDS_BETWEEN_CALLS)
            continue

        scored = score_message(entry, result, retrieved_ids)
        scored_by_id[entry["id"]] = scored
        all_results.append(scored)

        time.sleep(SECONDS_BETWEEN_CALLS)

    # ---- Consistency tests: compare paraphrase pairs ----
    consistency_results = []
    for entry in dataset:
        if entry.get("paraphrase_of") and entry["id"] in scored_by_id:
            orig_id = entry["paraphrase_of"]
            if orig_id in scored_by_id:
                orig = scored_by_id[orig_id]["model_output"]
                para = scored_by_id[entry["id"]]["model_output"]
                consistency_results.append({
                    "original_id": orig_id,
                    "paraphrase_id": entry["id"],
                    "priority_stable": orig.get("priority") == para.get("priority"),
                    "routing_stable": orig.get("routing") == para.get("routing"),
                    "intent_jaccard": jaccard(orig.get("intent", []), para.get("intent", [])),
                })

    output = {
        "per_message_results": all_results,
        "failures": failures,
        "consistency_results": consistency_results,
        "total_messages": len(dataset),
        "successful_runs": len(all_results),
        "failed_runs": len(failures),
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print_summary(output)
    return output


def print_summary(output: dict):
    results = output["per_message_results"]
    n = len(results)
    if n == 0:
        print("\nNo successful results to summarize.")
        return

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

    consistency = output["consistency_results"]
    priority_stable_rate = (
        sum(c["priority_stable"] for c in consistency) / len(consistency) if consistency else None
    )
    routing_stable_rate = (
        sum(c["routing_stable"] for c in consistency) / len(consistency) if consistency else None
    )

    print("\n" + "=" * 50)
    print("EVALUATION SUMMARY")
    print("=" * 50)
    print(f"Total messages: {output['total_messages']}")
    print(f"Successful runs: {output['successful_runs']}")
    print(f"Failed runs: {output['failed_runs']}")
    print()
    print("-- Output Quality --")
    print(f"Intent exact-match rate:   {intent_exact_rate:.1%}")
    print(f"Intent Jaccard avg:        {intent_jaccard_avg:.3f}")
    print(f"Routing correctness:       {routing_rate:.1%}")
    print(f"Priority correctness:      {priority_rate:.1%}")
    print(f"Issue type correctness:    {issue_type_rate:.1%}")
    print(f"Output completeness:       {completeness_rate:.1%}")
    print()
    print("-- Retrieval Quality --")
    if retrieval_rate is not None:
        print(f"Correct doc retrieved:     {retrieval_rate:.1%} ({len(retrieval_scored)} messages)")
    else:
        print("No retrieval-flagged messages scored.")
    print()
    print("-- Consistency Tests --")
    if priority_stable_rate is not None:
        print(f"Priority stable across paraphrases: {priority_stable_rate:.1%}")
        print(f"Routing stable across paraphrases:  {routing_stable_rate:.1%}")
    else:
        print("No paraphrase pairs scored.")
    print("=" * 50)
    print(f"\nFull results written to {RESULTS_PATH}")


if __name__ == "__main__":
    run_evaluation()

