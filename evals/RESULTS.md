# Evaluation results

## Run history

One row per run, oldest first. "Fixes right" is non-monetary fixes applied, then monetary fixes
(applied or suggested, according to the setting). The last column counts documents saved with no
person involved whose money differs from what was read.

<!-- runs:start -->
| Date | Set | Monetary fixes | Docs | Classification | Fields | Line items | Category | Precision | Recall | Saved without a person | Fixes right | Unfixable to a person | Amounts changed without a person |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-26 | Generated | auto-applied | 33 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 6 of 14 | 3/3 and 3/3 | 8/8 | 3 |
| 2026-11-26 | Generated | need review | 33 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 3 of 14 | 3/3 and 3/3 | 8/8 | 0 |
<!-- runs:end -->

<!-- documents:start -->
## Latest run: generated documents

Run on 2026-11-26 against the deployed stack, model `gemini-3.5-flash-lite`.
33 synthetic documents (30 financial, 3 not), all for
fictional companies, generated from ground truth by `scripts/generate_dataset.py`.

| Agent | Metric | Result | Notes |
|---|---|---|---|
| Classifier | Document type accuracy | 100.0% | 33 documents |
| Extractor | Field accuracy | 100.0% | 7 fields x 30 documents |
| Extractor | Line-item accuracy | 100.0% | all 4 values right |
| Extractor | Category accuracy | 100.0% | 7 categories |
| Validator | Precision | 100.0% | 0 good document(s) flagged |
| Validator | Recall | 100.0% | 0 bad document(s) missed |
| Validator | Exact issue codes | 100.0% | found set equals expected set |
| Resolver | Saved without a person | 21.4% | 3 of 14 flagged documents |
| Resolver | Non-monetary fixes applied correctly | 3/3 | misspelled vendors |
| Resolver | Monetary fixes correct | 3/3 | wrong totals; monetary fixes need review |
| Resolver | Amounts changed without a person | 0 | documents saved with money different from what was read |
| Resolver | Unfixable ones sent to a human | 8/8 | duplicates, missing fields, odd tax, unknown vendor |
| Pipeline | Latency, one document at a time (median) | 5.3 s | max 6.9 s, 5 documents, upload to finished |
| Pipeline | Latency, all uploaded at once (p50 / p95) | 97 s / 243 s | includes waiting on the queue (3 processed at a time) |
| Pipeline | Cost per 1,000 documents (Gemini paid tier) | $1.61 | models $1.31 + AWS $0.30 |

Per-field extraction accuracy: vendor 100.0%, invoice_number 100.0%, date 100.0%, currency 100.0%, subtotal 100.0%, tax 100.0%, total 100.0%.

### Every miss

- none

### Cost per 1,000 documents

Measured averages per document: 1944 input and
292 output tokens, 8.5 state transitions,
2.83 Lambda GB-seconds.

| Option | Models | AWS | Total per 1,000 documents |
|---|---|---|---|
| Gemini free tier (demo/public data only) | $0.00 | $0.30 | $0.30 |
| Gemini paid | $1.31 | $0.30 | $1.61 |
| Bedrock Nova Lite (estimate, not run) | $0.19 | $0.30 | $0.48 |

AWS breakdown: Step Functions $0.213, Lambda $0.050, DynamoDB $0.022, API Gateway $0.006, S3 + SQS $0.008.
Prices and what is excluded: `evals/cost.py`.

### Method

- Scored on each agent's first output: extraction before any Resolver change, issues from the
  first validation pass.
- Two duplicates are uploaded after their originals have finished.
- The set is small and was written by the same author as the pipeline: read it as a regression
  check, not an independent benchmark.
- The documents are machine-rendered with clear print; the scans add only slight rotation, noise
  and blur. Real photos (creases, shadows, handwriting, unusual layouts) will score lower.
<!-- documents:end -->

<!-- photos:start -->
## Latest run: real photos

Not run yet. See [photos/README.md](photos/README.md).
<!-- photos:end -->
