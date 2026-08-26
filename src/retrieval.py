"""
Knowledge Layer (RAG) - retrieval component.

MVP implementation: keyword/tag overlap scoring over the knowledge base.
This is intentionally dependency-light so the core pipeline works without
a vector DB. Swap `retrieve_context` for a FAISS/Chroma-backed version
later (Section 9 recommends FAISS or Chroma) without changing the caller
in input.py or engine.py.
"""

import json
import re
from pathlib import Path

from .logger import get_logger

logger = get_logger(__name__)

KB_PATH = Path(__file__).parent.parent / "knowledge_base" / "knowledge_base.json"

with open(KB_PATH) as f:
    _DOCS = json.load(f)

_STOPWORDS = {
    "the", "a", "an", "is", "was", "were", "and", "or", "to", "of", "in",
    "on", "for", "my", "me", "i", "it", "this", "that", "with", "at",
    "be", "as", "if", "not", "you", "your", "are", "will", "have", "has",
}


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


# Pre-process docs once at import time: lowercase tag phrases (kept whole,
# for substring matching) and pre-tokenized body content.
_DOC_TOKENS = [
    {
        "doc": d,
        "tags": [t.lower() for t in d["tags"]],
        "body_tokens": _tokenize(d["content"]),
    }
    for d in _DOCS
]


def retrieve_context(message: str, top_k: int = 3, min_score: int = 2) -> list[dict] | None:
    """
    Return up to top_k knowledge base docs relevant to the message, as
    [{"id":..., "title":..., "content":...}], or None if nothing scores
    above min_score (i.e. this message likely doesn't need retrieval).

    Scoring: a tag phrase appearing anywhere in the message (as a
    substring, e.g. "overdraft" or "charged twice") counts 3x, since tags
    are curated, precise topic signals. A body-content word overlap counts
    1x. Tags are matched as whole phrases (not split into individual
    words) to avoid generic words like "account" -- which appears in
    several multi-word tags -- causing false-positive matches on
    unrelated messages.
    """
    query_lower = message.lower()
    query_tokens = _tokenize(message)
    if not query_tokens:
        return None

    scored = []
    for entry in _DOC_TOKENS:
        tag_hits = sum(1 for tag in entry["tags"] if tag in query_lower)
        body_overlap = len(query_tokens & entry["body_tokens"])
        score = (tag_hits * 3) + body_overlap
        if score > 0:
            scored.append((score, entry["doc"]))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [doc for score, doc in scored[:top_k] if score >= min_score]

    if not top:
        logger.info("No knowledge base match above threshold for message.")
        return None

    logger.info("Retrieved %d doc(s): %s", len(top), [d["id"] for d in top])
    return [{"id": d["id"], "title": d["title"], "content": d["content"]} for d in top]

