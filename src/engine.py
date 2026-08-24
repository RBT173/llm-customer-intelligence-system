"""
LLM Reasoning Layer.

Calls Groq's free cloud API (https://groq.com) -- no local model, no
installation beyond `pip install -r requirements.txt`, and reachable from
a deployed Render app. Free tier: no credit card required, ~30 requests/min.

Uses openai/gpt-oss-120b by default (OpenAI's open-weight model, served on
Groq's hardware). This is Groq's current recommended general-purpose model
as of Aug 2026, after Groq retired its Llama endpoints.

Setup:
  1. Get a free key at https://console.groq.com/keys
  2. Set it as an environment variable: GROQ_API_KEY=gsk_...
  3. Run locally or deploy -- same code path either way.

Groq's JSON mode (response_format={"type": "json_object"}) nudges the
model toward valid JSON but does not guarantee it matches our exact
schema, so this module validates the parsed JSON and retries once with an
explicit correction message if validation fails.
"""

import os
import json
import re
import time
import requests
from jsonschema import validate, ValidationError

from .prompts import SYSTEM_PROMPT, build_output_schema, build_messages
from .logger import get_logger

logger = get_logger(__name__)

GROQ_HOST = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("CIS_MODEL", "openai/gpt-oss-120b")
REQUEST_TIMEOUT = 60
MAX_RATE_LIMIT_RETRIES = 3
TOOL_NAME = "submit_customer_analysis"


class EngineError(Exception):
    pass


def _extract_retry_seconds(response_body: dict, default: float = 5.0) -> float:
    """Groq's 429 error message includes a suggested wait time, either as
    'Please try again in 3.9675s' (seconds only, typical for per-minute
    limits) or 'Please try again in 5m39.984s' (minutes+seconds, typical
    for the daily token limit). Parse both formats."""
    try:
        message = response_body.get("error", {}).get("message", "")
        match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", message)
        if match:
            minutes = float(match.group(1)) if match.group(1) else 0.0
            seconds = float(match.group(2))
            return minutes * 60 + seconds + 0.5  # small safety buffer
    except Exception:
        pass
    return default


def _is_daily_limit(response_body: dict) -> bool:
    """Distinguish a daily token limit (TPD) from a per-minute limit (TPM).
    TPD exhaustion means retrying within the same run is pointless -- the
    caller should stop and resume later, not burn through retry attempts."""
    try:
        message = response_body.get("error", {}).get("message", "")
        return "tokens per day (TPD)" in message
    except Exception:
        return False


class DailyLimitExceeded(EngineError):
    """Raised when Groq's daily token limit is hit. Distinct from a
    transient per-minute rate limit -- retrying won't help until the
    quota resets, so callers (like eval.py) should stop the batch run
    rather than continue burning through retries."""
    pass


def _call_groq(system_prompt: str, user_content: str, schema: dict) -> str:
    """
    Uses tool/function calling (not response_format=json_object) to enforce
    the output schema. Function-calling argument generation is a much
    stronger constraint on enum values than asking for JSON in prose --
    models are specifically trained to conform tool arguments to the given
    parameter schema, which is why this reduces invalid intent/routing
    values compared to plain JSON mode.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise EngineError(
            "GROQ_API_KEY is not set. Get a free key at "
            "https://console.groq.com/keys and set it as an environment variable."
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": TOOL_NAME,
                    "description": "Submit the structured classification, routing decision, and grounded response for this customer message.",
                    "parameters": schema,
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": TOOL_NAME}},
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            resp = requests.post(GROQ_HOST, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            message = resp.json()["choices"][0]["message"]
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                # Model answered in plain text instead of calling the tool --
                # treat as a validation failure the caller can retry.
                raise EngineError(
                    f"Model did not call the required tool. Raw content: {message.get('content', '')[:200]}"
                )
            return tool_calls[0]["function"]["arguments"]
        except requests.exceptions.HTTPError as exc:
            try:
                detail = resp.json()
            except Exception:
                detail = {"error": {"message": resp.text}}

            if resp.status_code == 429:
                if _is_daily_limit(detail):
                    wait = _extract_retry_seconds(detail)
                    raise DailyLimitExceeded(
                        f"Groq daily token limit reached. Try again in ~{wait/60:.1f} minutes "
                        f"or resume tomorrow. Detail: {detail}"
                    )
                if attempt < MAX_RATE_LIMIT_RETRIES:
                    wait = _extract_retry_seconds(detail)
                    logger.warning(
                        "Rate limited (attempt %d/%d), waiting %.1fs before retry...",
                        attempt + 1, MAX_RATE_LIMIT_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue

            raise EngineError(f"Groq request failed ({resp.status_code}): {detail}") from exc
        except requests.exceptions.RequestException as exc:
            raise EngineError(f"Groq request failed: {exc}") from exc

    raise EngineError("Groq request failed: exceeded rate-limit retry attempts.")


def process_message(customer_message: str, retrieved_context: list[dict] | None = None) -> dict:
    """
    Process a single customer message through the LLM reasoning engine.

    Returns a dict matching the schema in prompts.build_output_schema().
    Raises EngineError if the API is unreachable or output remains invalid
    after one retry.
    """
    messages = build_messages(customer_message, retrieved_context)
    user_content = messages[0]["content"]
    schema = build_output_schema()

    start = time.monotonic()
    raw_text = _call_groq(SYSTEM_PROMPT, user_content, schema)

    result, error = _parse_and_validate(raw_text, schema)

    if error:
        logger.warning("First attempt failed validation (%s), retrying once...", error)
        correction_prompt = (
            f"{user_content}\n\n"
            f"Your previous response was invalid: {error}\n"
            f"Call the tool again with corrected arguments matching the schema exactly."
        )
        raw_text = _call_groq(SYSTEM_PROMPT, correction_prompt, schema)
        result, error = _parse_and_validate(raw_text, schema)

        if error:
            logger.error("Retry also failed validation: %s", error)
            raise EngineError(f"Model output failed schema validation after retry: {error}")

    latency_ms = round((time.monotonic() - start) * 1000, 1)

    logger.info(
        "Processed message | model=%s priority=%s routing=%s latency_ms=%s",
        GROQ_MODEL,
        result.get("priority"),
        result.get("routing"),
        latency_ms,
    )

    result["_meta"] = {"model": GROQ_MODEL, "latency_ms": latency_ms}
    return result


def _parse_and_validate(raw_text: str, schema: dict) -> tuple[dict | None, str | None]:
    try:
        result = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, f"Not valid JSON: {exc}"

    try:
        validate(instance=result, schema=schema)
    except ValidationError as exc:
        return None, f"Schema violation: {exc.message}"

    return result, None

