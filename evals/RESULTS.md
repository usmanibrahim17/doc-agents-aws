# Evaluation results

## Run history

One row per run, oldest first. "Fixes right" is non-monetary fixes applied, then monetary fixes
(applied or suggested, according to the setting). The last column counts documents saved with no
person involved whose money differs from what was read.

<!-- runs:start -->
| Date | Set | Monetary fixes | Docs | Classification | Fields | Line items | Category | Precision | Recall | Saved without a person | Fixes right | Unfixable to a person | Amounts changed without a person |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-26 | Generated | auto-applied | 33 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 6 of 14 | 3/3 and 3/3 | 8/8 | 3 |
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
| Resolver | Auto-fix rate | 42.9% | 6 of 14 flagged documents saved without a human |
| Resolver | Fixable ones fixed correctly | 6/6 | wrong totals, misspelled vendors |
| Resolver | Unfixable ones sent to a human | 8/8 | duplicates, missing fields, odd tax, unknown vendor |
| Pipeline | Latency, one document at a time (median) | 5.2 s | max 18.8 s, 5 documents, upload to finished |
| Pipeline | Latency, all uploaded at once (p50 / p95) | 73 s / 228 s | includes waiting on the queue (3 processed at a time) |
| Pipeline | Cost per 1,000 documents (Gemini paid tier) | $1.65 | models $1.33 + AWS $0.32 |

Per-field extraction accuracy: vendor 100.0%, invoice_number 100.0%, date 100.0%, currency 100.0%, subtotal 100.0%, tax 100.0%, total 100.0%.

### Every miss

- none

### Cost per 1,000 documents

Measured averages per document: 1971 input and
297 output tokens, 8.8 state transitions,
3.63 Lambda GB-seconds.

| Option | Models | AWS | Total per 1,000 documents |
|---|---|---|---|
| Gemini free tier (demo/public data only) | $0.00 | $0.32 | $0.32 |
| Gemini paid | $1.33 | $0.32 | $1.65 |
| Bedrock Nova Lite (estimate, not run) | $0.19 | $0.32 | $0.51 |

AWS breakdown: Step Functions $0.220, Lambda $0.063, DynamoDB $0.022, API Gateway $0.006, S3 + SQS $0.008.
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
