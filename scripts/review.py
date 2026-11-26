"""Developer tool: approve or reject a queued document from the command line.

    python scripts/review.py <doc_id> approve|reject [--set invoice_number=AB-1]

The web API does the same after checking that the session owns the document.
"""

import argparse
import json

import boto3
from submit import outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("doc_id")
    parser.add_argument("decision", choices=["approve", "reject"])
    parser.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
    args = parser.parse_args()

    session = boto3.Session(region_name="us-east-1")
    table = session.resource("dynamodb").Table(outputs()["table_names"]["reviews"])
    review = table.get_item(Key={"doc_id": args.doc_id}, ConsistentRead=True)["Item"]
    decision = {
        "decision": "approved" if args.decision == "approve" else "rejected",
        "fields": dict(pair.split("=", 1) for pair in args.set),
    }
    session.client("stepfunctions").send_task_success(
        taskToken=review["task_token"], output=json.dumps(decision)
    )
    print(f"{args.doc_id}: {decision['decision']}")


if __name__ == "__main__":
    main()
