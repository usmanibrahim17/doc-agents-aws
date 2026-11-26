"""Last step of the workflow: record the outcome (saved as valid, or failed)."""

from app.common.agent import Runtime


def process(event: dict, runtime: Runtime) -> dict:
    if "error" in event:  # reached through a Catch in the state machine
        error = str(event["error"].get("Error", "Unknown"))
        runtime.record(
            event,
            "finalizer",
            "processing failed",
            updates={"status": "failed", "reason": f"Processing failed ({error})."},
            error=error,
        )
        return {"status": "failed"}

    runtime.record(event, "finalizer", "saved as valid", updates={"status": "valid"})
    return {"status": "valid"}


def handler(event, context):
    return process(event, Runtime())
