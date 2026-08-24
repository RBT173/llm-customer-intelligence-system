"""
Prompt Engineering Layer.

Defines:
- The output JSON Schema sent to the Claude API via output_config.format
  (guarantees schema-valid output through constrained decoding).
- The system prompt, which encodes task instructions and the intent taxonomy.
- A helper to build the final message list for a given customer message
  and optional retrieved knowledge-base context.
"""

import json
from pathlib import Path

TAXONOMY_PATH = Path(__file__).parent.parent / "config" / "intent_taxonomy.json"

with open(TAXONOMY_PATH) as f:
    TAXONOMY = json.load(f)


def build_output_schema() -> dict:
    """
    JSON Schema for the model's structured response, passed to
    output_config.format. Mirrors the ground_truth shape used in the
    eval dataset (data/customer_messages_dataset.json).
    """
    return {
        "type": "object",
        "properties": {
            "intent": {
                "type": "array",
                "items": {"type": "string", "enum": TAXONOMY["intents"]},
                "description": "One or more detected customer intents.",
            },
            "issue_type": {
                "type": "string",
                "description": "Short label for the specific issue category.",
            },
            "priority": {
                "type": "string",
                "enum": TAXONOMY["priority_levels"],
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key extracted entities (amounts, account types, transaction references, dates).",
            },
            "routing": {
                "type": "string",
                "enum": TAXONOMY["routing_teams"],
            },
            "suggested_action": {
                "type": "string",
                "description": "A concrete next action for the human agent or system.",
            },
            "response": {
                "type": "string",
                "description": "A grounded, customer-facing response. If knowledge base context is provided, it must be used to ground this response.",
            },
            "needs_clarification": {
                "type": "boolean",
                "description": "True if the message is too ambiguous or incomplete to confidently classify.",
            },
            "clarifying_question": {
                "type": "string",
                "description": "If needs_clarification is true, a single question to ask the customer. Empty string otherwise.",
            },
        },
        "required": [
            "intent",
            "issue_type",
            "priority",
            "entities",
            "routing",
            "suggested_action",
            "response",
            "needs_clarification",
            "clarifying_question",
        ],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = f"""You are an internal AI assistant for a bank's customer operations team.
You process a single customer message and produce structured intelligence used by
human agents and downstream routing systems. You are not speaking directly to the
end customer casually — your "response" field will be reviewed or sent by an agent.

## Your task
Given a customer message (and optionally, retrieved internal policy context), produce:
1. Structured understanding: intent(s), issue type, priority, entities.
2. A decision: suggested action and routing recommendation.
3. A grounded response: if policy context is provided, cite it accurately in plain
   language. If no context is provided, give a brief, professional acknowledgment
   without inventing policy details you don't have.

## STRICT VALUE CONSTRAINTS (do not deviate)
The "intent" field must contain ONLY values from this exact list — do not invent new
intent labels, do not rephrase them, use them verbatim:
{", ".join(TAXONOMY['intents'])}

The "routing" field must be EXACTLY ONE of these values, verbatim, no other team
names, no invented departments:
{", ".join(TAXONOMY['routing_teams'])}

The "priority" field must be EXACTLY ONE of: {", ".join(TAXONOMY['priority_levels'])}

## Priority guidance
- Critical: {TAXONOMY['priority_guidance']['Critical']}
- High: {TAXONOMY['priority_guidance']['High']}
- Medium: {TAXONOMY['priority_guidance']['Medium']}
- Low: {TAXONOMY['priority_guidance']['Low']}

## Handling ambiguous or incomplete messages
If the message lacks enough information to confidently determine intent, issue type,
or priority (e.g. "This isn't working.", "Money's missing."), do NOT guess a specific
issue. Instead:
- Set needs_clarification to true
- Provide one specific clarifying_question
- Still provide your best-guess intent/priority/routing based on available signal,
  but keep suggested_action focused on gathering more information first.

## Multi-intent messages
If a message contains more than one distinct request (e.g. an account update AND a
billing dispute), include all relevant intents in the intent array, and reflect the
combined nature of the request in suggested_action and response.

## Grounding rule
Never state a specific policy detail (fee amounts, timelines, eligibility thresholds)
unless it was provided to you in retrieved context. If you don't have grounding for a
policy-specific claim, keep the response general and route to the appropriate team.

## Example
Input: "I was charged twice for the same transaction and I need this resolved
immediately. If not, I will escalate."
Output:
{{
  "intent": ["Billing Issue", "Complaint"],
  "issue_type": "Duplicate Charge",
  "priority": "High",
  "entities": ["duplicate transaction"],
  "routing": "Billing Department",
  "suggested_action": "Escalate and verify transaction logs",
  "response": "Based on our Dispute & Refund Resolution Policy, verified duplicate charges are refunded within 24-48 hours once confirmed against transaction logs. We're opening a case now.",
  "needs_clarification": false,
  "clarifying_question": ""
}}

Respond only with a single valid JSON object matching the required schema — no extra commentary, no markdown code fences, no text before or after the JSON.
"""


def build_messages(customer_message: str, retrieved_context: list[dict] | None = None) -> list[dict]:
    """
    Build the Messages API `messages` list for a single customer message.

    retrieved_context: optional list of {"title": ..., "content": ...} dicts
    from the RAG layer (retrieval.py), already selected as most relevant.
    """
    user_content = f'Customer message:\n"{customer_message}"\n'

    if retrieved_context:
        context_block = "\n\n".join(
            f"[{doc['title']}]\n{doc['content']}" for doc in retrieved_context
        )
        user_content += f"\nRetrieved internal policy context (use this to ground your response):\n{context_block}\n"
    else:
        user_content += "\nNo internal policy context was retrieved for this message.\n"

    return [{"role": "user", "content": user_content}]