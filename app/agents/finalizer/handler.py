"""Last step of the workflow: record the outcome (valid, approved, rejected by a person, or
failed).
"""

from app.common import schemas
from app.common.agent import Runtime


def process(event: dict, runtime: Runtime) -> dict:
    if "error" in event:  # reached through a Catch in the state machine
        error = str(event["error"].get("Error", "Unknown"))
        reason = (
            "Nobody reviewed this document in time."
            if error == "States.Timeout"
            else f"Processing failed ({error})."
        )
        runtime.delete_review(event["doc_id"])
        runtime.record(
            event,
            "finalizer",
            "processing failed",
            updates={"status": "failed", "reason": reason},
            error=error,
        )
        return {"status": "failed"}

    review = event.get("review")
    if review is None:
        runtime.record(event, "finalizer", "saved as valid", updates={"status": "valid"})
        return {"status": "valid"}

    approved = review.get("decision") == "approved"
    updates = {"status": "approved" if approved else "rejected", "reviewed": True}
    corrected = []
    if approved and review.get("fields"):
        document = runtime.get_document(event["doc_id"])
        fields = dict(document["fields"])
        allowed = set(schemas.EXTRACTION["properties"]) - {"category"}
        for name, value in review["fields"].items():
            if name in allowed and fields.get(name) != value:
                fields[name] = value
                corrected.append(name)
        updates["fields"] = fields
        if review["fields"].get("category") in schemas.EXTRACTION["properties"]["category"]["enum"]:
            updates["category"] = review["fields"]["category"]
    if not approved:
        updates["reason"] = "Rejected by the reviewer."
    runtime.delete_review(event["doc_id"])
    runtime.record(
        event,
        "human",
        "approved" if approved else "rejected",
        updates=updates,
        corrected_fields=corrected,
    )
    return {"status": updates["status"]}


def handler(event, context):
    return process(event, Runtime())
