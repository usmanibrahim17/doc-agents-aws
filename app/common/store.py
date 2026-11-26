"""DynamoDB helpers shared by the agents: type conversion, retention and the audit log."""

import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal

RETENTION_SECONDS = 7 * 24 * 3600  # demo data expires after 7 days (DynamoDB TTL)


def expires_at(now: float | None = None) -> int:
    return int(now if now is not None else time.time()) + RETENTION_SECONDS


def to_dynamo(value):
    """DynamoDB rejects floats; convert them (recursively) to Decimal."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value):
    """The reverse, so items can be JSON-encoded."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def write_audit(table, doc_id: str, session_id: str, agent: str, decision: str, **details):
    """Append one agent decision to the audit log. `table` is a boto3 DynamoDB Table."""
    timestamp = datetime.now(UTC).isoformat(timespec="microseconds")
    item = {
        "doc_id": doc_id,
        "sk": f"{timestamp}#{uuid.uuid4().hex[:6]}",  # unique even within one microsecond
        "session_id": session_id,
        "timestamp": timestamp,
        "agent": agent,
        "decision": decision,
        "details": to_dynamo(details),
        "expires_at": expires_at(),
    }
    table.put_item(Item=item)
    return item
