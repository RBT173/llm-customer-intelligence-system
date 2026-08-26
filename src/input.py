"""
Input Layer / API Layer.

Exposes POST /process-customer-message per Section 11 (Optional Production
Extensions -> API Layer). Run with:

    uvicorn src.input:app --reload --port 8000

Then:

    curl -X POST http://localhost:8000/process-customer-message \\
      -H "Content-Type: application/json" \\
      -d '{"message": "I was charged twice for the same transaction."}'
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .engine import process_message, EngineError
from .retrieval import retrieve_context
from .logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="LLM-Based Customer Intelligence System",
    description="Processes customer messages into structured, actionable intelligence.",
    version="0.1.0",
)

# Permissive CORS so the standalone frontend (frontend/index.html, opened
# locally or hosted anywhere) can call this API directly from the browser.
# Fine for an internal/demo tool; a real production deployment would
# restrict allow_origins to the actual frontend's domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CustomerMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Raw customer message text.")
    use_retrieval: bool = Field(
        default=True, description="Whether to run the RAG retrieval layer before reasoning."
    )


class CustomerMessageResponse(BaseModel):
    intent: list[str]
    issue_type: str
    priority: str
    entities: list[str]
    routing: str
    suggested_action: str
    response: str
    needs_clarification: bool
    clarifying_question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process-customer-message", response_model=CustomerMessageResponse)
def process_customer_message(req: CustomerMessageRequest):
    logger.info("Received message (len=%d, retrieval=%s)", len(req.message), req.use_retrieval)

    retrieved_context = retrieve_context(req.message) if req.use_retrieval else None

    try:
        result = process_message(req.message, retrieved_context)
    except EngineError as exc:
        logger.error("Engine error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    result.pop("_meta", None)
    return result

