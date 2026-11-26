"""Run the evaluation set against the deployed API and write evals/RESULTS.md.

    AWS_PROFILE=rag-demo python evals/run_evals.py --url <api_url>

Documents go through the public API exactly like a visitor's. Step Functions history and Lambda
CloudWatch metrics (for the cost estimate) are read with your AWS credentials.
"""

import argparse
import json
import statistics
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from api_client import Client  # noqa: E402

from evals import cost, scoring  # noqa: E402

DATA = ROOT / "evals" / "data"
FUNCTIONS = (
    "classifier",
    "extractor",
    "validator",
    "resolver",
    "reviewer",
    "finalizer",
    "starter",
    "api",
)


def seconds(document: dict) -> float:
    start, end = (datetime.fromisoformat(document[k]) for k in ("created_at", "updated_at"))
    return (end - start).total_seconds()


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def run_batch(client: Client, records: list[dict]) -> dict[str, dict]:
    """Upload together, wait, then fetch each document with its first-pass results."""
    ids = {r["id"]: client.upload(DATA / "documents" / r["file"]) for r in records}
    client.wait(list(ids.values()), timeout=1800)
    return {
        name: client.request("GET", f"/documents/{doc_id}")["document"]
        for name, doc_id in ids.items()
    }


def transitions(doc_ids: list[str]) -> float:
    """Average billed state transitions per document, from the execution histories."""
    import boto3

    sfn = boto3.client("stepfunctions", region_name="us-east-1")
    arn = next(
        m["stateMachineArn"]
        for m in sfn.list_state_machines()["stateMachines"]
        if m["name"] == "docagent-workflow"
    ).replace(":stateMachine:", ":execution:")
    counts = []
    for doc_id in doc_ids:
        events = []
        for page in sfn.get_paginator("get_execution_history").paginate(
            executionArn=f"{arn}:{doc_id}"
        ):
            events += page["events"]
        entered = sum(e["type"].endswith("StateEntered") for e in events)
        retries = sum(e["type"] == "LambdaFunctionFailed" for e in events)
        counts.append(entered + retries + 1)  # +1: the start transition
    return statistics.mean(counts)


def lambda_seconds(start: datetime) -> dict[str, tuple[float, float]]:
    """(total billed duration in seconds, invocations) per function since `start`."""
    import boto3

    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
    out = {}
    for name in FUNCTIONS:
        totals = []
        for metric in ("Duration", "Invocations"):
            points = cloudwatch.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName=metric,
                Dimensions=[{"Name": "FunctionName", "Value": f"docagent-{name}"}],
                StartTime=start,
                EndTime=datetime.now(UTC) + timedelta(minutes=1),
                Period=3600,
                Statistics=["Sum"],
            )["Datapoints"]
            totals.append(sum(p["Sum"] for p in points))
        out[name] = (totals[0] / 1000, totals[1])
    return out


def pct(value) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def report(result: dict) -> str:
    s, latency, money = result["scores"], result["latency"], result["cost"]
    counts, fixes = s["validation_counts"], s["auto_fix_counts"]
    fixable, unfixable = s["fixable_fixed_correctly"], s["unfixable_sent_to_human"]
    rows = [
        (
            "Classifier",
            "Document type accuracy",
            pct(s["classification_accuracy"]),
            f"{s['documents']} documents",
        ),
        (
            "Extractor",
            "Field accuracy",
            pct(s["field_accuracy"]),
            f"{len(scoring.FIELDS)} fields x {s['financial_documents']} documents",
        ),
        ("Extractor", "Line-item accuracy", pct(s["line_item_accuracy"]), "all 4 values right"),
        ("Extractor", "Category accuracy", pct(s["category_accuracy"]), "7 categories"),
        (
            "Validator",
            "Precision",
            pct(s["validation_precision"]),
            f"{counts['false_positive']} good document(s) flagged",
        ),
        (
            "Validator",
            "Recall",
            pct(s["validation_recall"]),
            f"{counts['false_negative']} bad document(s) missed",
        ),
        (
            "Validator",
            "Exact issue codes",
            pct(s["validation_exact_codes"]),
            "found set equals expected set",
        ),
        (
            "Resolver",
            "Auto-fix rate",
            pct(s["auto_fix_rate"]),
            f"{fixes['fixed']} of {fixes['flagged']} flagged documents saved without a human",
        ),
        (
            "Resolver",
            "Fixable ones fixed correctly",
            f"{fixable[0]}/{fixable[1]}",
            "wrong totals, misspelled vendors",
        ),
        (
            "Resolver",
            "Unfixable ones sent to a human",
            f"{unfixable[0]}/{unfixable[1]}",
            "duplicates, missing fields, odd tax, unknown vendor",
        ),
        (
            "Pipeline",
            "Latency, one document at a time (median)",
            f"{latency['single_p50']:.1f} s",
            f"max {latency['single_max']:.1f} s, "
            f"{latency['single_count']} documents, upload to finished",
        ),
        (
            "Pipeline",
            "Latency, all uploaded at once (p50 / p95)",
            f"{latency['batch_p50']:.0f} s / {latency['batch_p95']:.0f} s",
            "includes waiting on the queue (3 processed at a time)",
        ),
        (
            "Pipeline",
            "Cost per 1,000 documents (Gemini paid tier)",
            f"${money['gemini_paid_total']:.2f}",
            f"models ${money['gemini_paid_models']:.2f} + AWS ${money['aws_total']:.2f}",
        ),
    ]
    table = "\n".join(f"| {' | '.join(row)} |" for row in rows)
    per_field = ", ".join(f"{k} {pct(v)}" for k, v in s["per_field_accuracy"].items())
    mistakes = "\n".join(f"- {m}" for m in s["mistakes"]) or "- none"
    return f"""# Evaluation results

Run on {result["date"]} against the deployed stack, model `{result["model"]}`.
{s["documents"]} synthetic documents ({s["financial_documents"]} financial, 3 not), all for
fictional companies, generated from ground truth by `scripts/generate_dataset.py`.

| Agent | Metric | Result | Notes |
|---|---|---|---|
{table}

Per-field extraction accuracy: {per_field}.

## Every miss

{mistakes}

## Cost per 1,000 documents

Measured averages per document: {money["input_tokens"]:.0f} input and
{money["output_tokens"]:.0f} output tokens, {money["transitions"]:.1f} state transitions,
{money["lambda_gb_seconds"]:.2f} Lambda GB-seconds.

| Option | Models | AWS | Total per 1,000 documents |
|---|---|---|---|
| Gemini free tier (demo/public data only) | $0.00 | ${money["aws_total"]:.2f} | ${money["aws_total"]:.2f} |
| Gemini paid | ${money["gemini_paid_models"]:.2f} | ${money["aws_total"]:.2f} | ${money["gemini_paid_total"]:.2f} |
| Bedrock Nova Lite (estimate, not run) | ${money["bedrock_models"]:.2f} | ${money["aws_total"]:.2f} | ${money["bedrock_total"]:.2f} |

AWS breakdown: {", ".join(f"{k} ${v:.3f}" for k, v in money["aws"].items())}.
Prices and what is excluded: `evals/cost.py`.

## Method

- Scored on each agent's first output: extraction before any Resolver change, issues from the
  first validation pass.
- Two duplicates are uploaded after their originals have finished.
- The set is small and was written by the same author as the pipeline: read it as a regression
  check, not an independent benchmark.
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--latency-samples", type=int, default=5)
    args = parser.parse_args()

    records = [json.loads(p.read_text()) for p in sorted((DATA / "truth").glob("*.json"))]
    started = datetime.now(UTC) - timedelta(minutes=1)
    client = Client(args.url)
    originals = [r for r in records if not r["duplicate_of"]]
    documents = run_batch(client, originals)
    batch_latencies = [seconds(d) for d in documents.values()]
    documents |= run_batch(client, [r for r in records if r["duplicate_of"]])

    single = []
    clean = [r for r in originals if not r["faults"]][: args.latency_samples]
    for record in clean:  # a fresh session each time, so nothing counts as a duplicate
        single.append(seconds(run_batch(Client(args.url), [record])[record["id"]]))

    scores = scoring.score([(r, documents[r["id"]]) for r in records])
    print("waiting 3 minutes for CloudWatch metrics...")
    time.sleep(180)
    processed = len(records) + len(single)
    money = cost.estimate(
        documents=processed,
        input_tokens=statistics.mean(d.get("input_tokens", 0) for d in documents.values()),
        output_tokens=statistics.mean(d.get("output_tokens", 0) for d in documents.values()),
        transitions=transitions([d["doc_id"] for d in documents.values()]),
        functions=lambda_seconds(started),
    )
    result = {
        "date": datetime.now(UTC).date().isoformat(),
        "model": "gemini-3.5-flash-lite",
        "scores": scores,
        "latency": {
            "single_p50": statistics.median(single),
            "single_max": max(single),
            "single_count": len(single),
            "batch_p50": percentile(batch_latencies, 0.5),
            "batch_p95": percentile(batch_latencies, 0.95),
        },
        "cost": money,
    }
    out = ROOT / "evals" / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    (out / f"{stamp}.json").write_text(
        json.dumps(result | {"documents": documents}, indent=2), encoding="utf-8"
    )
    (ROOT / "evals" / "RESULTS.md").write_text(report(result), encoding="utf-8", newline="\n")
    print(report(result))


if __name__ == "__main__":
    main()
