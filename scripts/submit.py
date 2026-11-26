"""Developer tool: run one file through the deployed workflow and print what happened.

    python scripts/submit.py path/to/document.pdf [--session dev]

Needs AWS_PROFILE=rag-demo. Reads resource names from `terraform output`.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402

from app.common import store  # noqa: E402

EXTENSIONS = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg"}


def outputs() -> dict:
    raw = subprocess.check_output(
        ["terraform", "output", "-json"], cwd=ROOT / "infra" / "envs" / "demo"
    )
    return {name: item["value"] for name, item in json.loads(raw).items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--session", default="dev")
    args = parser.parse_args()

    out = outputs()
    session = boto3.Session(region_name="us-east-1")
    tables = session.resource("dynamodb")
    documents = tables.Table(out["table_names"]["documents"])
    doc_id = uuid.uuid4().hex
    suffix = args.file.suffix.lower()
    event = {
        "doc_id": doc_id,
        "session_id": args.session,
        "s3_key": f"uploads/{args.session}/{doc_id}{suffix}",
        "mime_type": EXTENSIONS[suffix],
    }
    session.client("s3").put_object(
        Bucket=out["uploads_bucket_name"],
        Key=event["s3_key"],
        Body=args.file.read_bytes(),
        ContentType=event["mime_type"],
    )
    documents.put_item(
        Item=event
        | {
            "filename": args.file.name,
            "status": "queued",
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": store.expires_at(),
        }
    )
    sfn = session.client("stepfunctions")
    arn = sfn.start_execution(
        stateMachineArn=out["state_machine_arn"], name=doc_id, input=json.dumps(event)
    )["executionArn"]

    status = "RUNNING"
    while status == "RUNNING":
        time.sleep(3)
        status = sfn.describe_execution(executionArn=arn)["status"]
        document = documents.get_item(Key={"doc_id": doc_id}, ConsistentRead=True)["Item"]
        if document["status"] == "needs_review":
            break

    print(f"{args.file.name}: execution {status}")
    print(json.dumps(store.from_dynamo(document), indent=2))
    audit = tables.Table(out["table_names"]["audit"]).query(
        KeyConditionExpression=Key("doc_id").eq(doc_id)
    )["Items"]
    for entry in audit:
        print(f"  {entry['timestamp'][11:19]} {entry['agent']}: {entry['decision']}")


if __name__ == "__main__":
    main()
