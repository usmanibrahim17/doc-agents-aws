"""Queue a document for a person. Invoked with waitForTaskToken: the workflow pauses until the
API calls SendTaskSuccess with this token. The token is stored server-side only.
"""

from datetime import UTC, datetime

from app.common import rules, store
from app.common.agent import Runtime


def process(event: dict, runtime: Runtime) -> dict:
    task_token, event = event["task_token"], event["input"]
    document = runtime.get_document(event["doc_id"])
    explanation = rules.explain(
        document.get("issues", []), document.get("tried", []), document.get("suggestions")
    )
    runtime.reviews.put_item(
        Item={
            "doc_id": event["doc_id"],
            "session_id": event["session_id"],
            "task_token": task_token,
            "explanation": explanation,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": store.expires_at(),
        }
    )
    runtime.record(
        event,
        "reviewer",
        "sent to human review",
        updates={"status": "needs_review", "explanation": explanation},
        explanation=explanation,
    )
    return {}


def handler(event, context):
    return process(event, Runtime())
