"""Intake pacing: S3 -> SQS -> this Lambda -> StartExecution.

Only `MAX_ACTIVE` documents are processed at once, so a burst of uploads does not hit the free
tier all together. When there is no free slot, the message is released again after a jittered
exponential delay (ChangeMessageVisibility, the pattern from project 1) and reported as a batch
item failure, so it stays on the queue.
"""

import json
import random
from functools import lru_cache
from urllib.parse import unquote_plus

from app.common.agent import Runtime
from app.common.config import env
from app.common.logs import log_json

RETRY_BASE_SECONDS = 15
RETRY_MAX_SECONDS = 120


@lru_cache
def _client(name: str):
    import boto3

    return boto3.client(name)


def retry_delay_seconds(receive_count: int) -> int:
    """~15 s, 30 s, 60 s, then ~120 s. The jitter spreads waiting messages out."""
    base = RETRY_BASE_SECONDS * 2 ** (max(receive_count, 1) - 1)
    return min(RETRY_MAX_SECONDS, round(base * random.uniform(0.8, 1.2)))


def queue_url_from_arn(arn: str) -> str:
    _, _, _, region, account, name = arn.split(":", 5)
    return f"https://sqs.{region}.amazonaws.com/{account}/{name}"


def active_documents(runtime: Runtime, sfn, state_machine_arn: str) -> int:
    """Running executions, not counting those parked waiting for a person."""
    running = 0
    for page in sfn.get_paginator("list_executions").paginate(
        stateMachineArn=state_machine_arn, statusFilter="RUNNING"
    ):
        running += len(page["executions"])
    waiting = runtime.reviews.scan(Select="COUNT")["Count"]
    return max(running - waiting, 0)


def parse_key(key: str) -> tuple[str, str] | None:
    """uploads/<session>/<doc_id>.<ext> -> (session, doc_id)"""
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "uploads":
        return None
    return parts[1], parts[2].rsplit(".", 1)[0]


def start(key: str, runtime: Runtime, sfn, state_machine_arn: str) -> bool:
    """True = message finished (started or not worth keeping), False = no free slot yet."""
    parsed = parse_key(key)
    document = runtime.get_document(parsed[1]) if parsed else None
    if not document or document["session_id"] != parsed[0] or document["s3_key"] != key:
        log_json("upload_ignored", reason="no matching document record")
        return True
    if document["status"] not in ("uploading", "queued"):
        return True  # a redelivered message for a document that already started

    if active_documents(runtime, sfn, state_machine_arn) >= int(env("MAX_ACTIVE", "3")):
        if document["status"] == "uploading":
            runtime.record(document, "intake", "queued", updates={"status": "queued"})
        return False

    event = {k: document[k] for k in ("doc_id", "session_id", "s3_key", "mime_type")}
    # Recorded before starting, so it can never overwrite a status the agents set.
    runtime.record(event, "intake", "processing started", updates={"status": "processing"})
    try:
        sfn.start_execution(
            stateMachineArn=state_machine_arn, name=event["doc_id"], input=json.dumps(event)
        )
    except sfn.exceptions.ExecutionAlreadyExists:
        pass
    return True


def handler(event, context):
    runtime, sfn, sqs = Runtime(), _client("stepfunctions"), _client("sqs")
    arn = env("STATE_MACHINE_ARN")
    failures = []
    for message in event.get("Records", []):
        try:
            body = json.loads(message["body"])
            done = True
            for record in body.get("Records", []):  # s3:TestEvent has no Records
                key = unquote_plus(record["s3"]["object"]["key"])
                done = start(key, runtime, sfn, arn) and done
            if not done:
                receive_count = int(message["attributes"]["ApproximateReceiveCount"])
                delay = retry_delay_seconds(receive_count)
                sqs.change_message_visibility(
                    QueueUrl=queue_url_from_arn(message["eventSourceARN"]),
                    ReceiptHandle=message["receiptHandle"],
                    VisibilityTimeout=delay,
                )
                log_json("waiting_for_slot", receive_count=receive_count, retry_in_seconds=delay)
        except Exception as exc:  # report it; SQS redelivers and eventually dead-letters
            log_json("intake_failed", message_id=message.get("messageId"), error=repr(exc))
            done = False
        if not done:
            failures.append({"itemIdentifier": message["messageId"]})
    return {"batchItemFailures": failures}
