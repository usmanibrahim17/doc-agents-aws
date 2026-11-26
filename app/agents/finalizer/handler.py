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
    corrected, accepted = [], []
    if approved:
        document = runtime.get_document(event["doc_id"])
        fields = dict(document["fields"])
        suggestions = document.get("suggestions", {})
        submitted = review.get("fields") or {}
        # Approving accepts the suggested corrections; anything the person typed wins over them.
        chosen = {name: s["value"] for name, s in suggestions.items()} | submitted
        allowed = set(schemas.EXTRACTION["properties"]) - {"category"}
        for name, value in chosen.items():
            if name in allowed and fields.get(name) != value:
                fields[name] = value
                corrected.append(name)
        accepted = [n for n, s in suggestions.items() if chosen[n] == s["value"]]
        updates["fields"] = fields
        if submitted.get("category") in schemas.EXTRACTION["properties"]["category"]["enum"]:
            updates["category"] = submitted["category"]
    else:
        updates["reason"] = "Rejected by the reviewer."
    runtime.delete_review(event["doc_id"])
    runtime.record(
        event,
        "human",
        "approved" if approved else "rejected",
        updates=updates,
        corrected_fields=corrected,
        accepted_suggestions=accepted,
    )
    return {"status": updates["status"]}


def handler(event, context):
    return process(event, Runtime())
