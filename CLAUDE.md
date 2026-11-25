# doc-agents-aws: project brief for Claude Code

Project 2 of the AI portfolio. Project 1 is `../rag-on-aws` (https://github.com/usmanibrahim17/rag-on-aws): reuse its patterns and code (providers, SQS backoff, Terraform layout, bootstrap/OIDC/boundary, CI deploy guard, evals runner, cost script, browser test).

Four-agent document pipeline on AWS: invoices/receipts (PDF or photo) go in; Classifier -> Extractor -> Validator -> Resolver (loop, max 2) -> save, or human review. Orchestrated by Step Functions, one Lambda per agent.

## Working rules

- Ask permission per command, one-line updates. Show every `terraform plan` summary; STOP if anything is destroyed or replaced that was not predicted.
- Never put secrets in code, tfvars, logs, commits or state. Gemini key: SSM `/rag-demo/gemini-api-key` (SecureString, not managed by Terraform, read at runtime).
- Each milestone: tests pass, `terraform fmt` clean, commit + push, report in under 10 lines.
- All demo/eval documents are synthetic and for clearly fictional companies. No real brands.
- Gemini free tier is for synthetic/public data only (see README privacy note).

## Fixed decisions

| Area | Decision |
|-|-|
| AWS | profile `rag-demo`, region `us-east-1`, name prefix `docagent` |
| IaC | Terraform >= 1.10, provider >= 6.x. `infra/bootstrap` (deploy role, boundary), `infra/modules/docagent_stack`, `infra/envs/demo`. Remote state in the existing state bucket, key `docagent/demo.tfstate`, native lockfile |
| Runtime | Python 3.12, boto3 only, no frameworks. Gemini over `urllib` (no Google SDK). Gemini accepts PDF/images inline (base64), so no OCR or PDF libs |
| AI provider | `AI_PROVIDER` = `gemini` (default) or `bedrock` (Terraform `ai_provider`). Bedrock quota is 0 here: never depend on it; implement the interface, test with stubs only. Model IDs are variables |
| Orchestration | Step Functions Standard. Task states per agent Lambda. Validator <-> Resolver loop with a counter, max 2. Unresolved -> `waitForTaskToken` human review |
| Pacing | S3 `uploads/` -> SQS (+DLQ) -> starter Lambda (concurrency capped) -> `StartExecution`. Starter checks running executions and uses `ChangeMessageVisibility` backoff when over the cap. Agent Lambdas raise a `RateLimited` error on Gemini 429; the state machine `Retry` backs off exponentially |
| Data | DynamoDB on-demand: `documents` (status, extracted fields, category, agents run), `audit` (PK doc id, SK timestamp; every agent decision), `vendors` (known vendors), `reviews` (task token, explanation, tried). Duplicate key = hash of normalized vendor + invoice number + total, via GSI |
| Categories | Office supplies, Travel, Utilities, Software, Meals, Professional services, Other |
| API | API Gateway HTTP API + one `api` Lambda: presigned upload, list, detail, audit, review queue, approve/reject (SendTaskSuccess), CSV export, run-sample. Throttled, strict CORS (CloudFront origin only), upload max 5 MB, PDF/PNG/JPEG only, daily processing cap to protect the free tier |
| Site | Static HTML/JS, no build step. CloudFront + private S3 with OAC, CSP/HSTS headers. Sample documents: fictional, one click |
| Security | Least-privilege IAM per Lambda; permissions boundary on all stack roles; S3 blocked public + SSE; deploy role denied boundary/self changes; GitHub OIDC with the immutable subject claim (`gh api repos/<owner>/<repo>/actions/oidc/customization/sub --jq .sub_claim_prefix`); NEW deploy role for this repo on the account's existing OIDC provider |
| CD | GitHub Actions: fmt/validate/ruff/pytest, then plan + apply on main via OIDC; guard blocks any destroy/replace unless commit message has `[allow-destroy]` |
| Isolation | Anonymous session id generated client-side (localStorage), sent as `X-Session-Id` header. Every upload, list, detail, audit, review, approve/reject and export is scoped to that session. Step Functions task tokens stay server-side (`reviews` table), never sent to the browser; approve/reject is by document id after checking the session owns it |
| Retention | S3 lifecycle deletes uploads after 7 days; DynamoDB TTL expires documents/audit/reviews after 7 days. Site shows a clear "demo only, don't upload real invoices" banner |
| Eval data | Synthetic documents are generated programmatically from ground-truth JSON (PDFs rendered; scan-like images rendered with slight rotation/noise), so ground truth is exact by construction |
| Cost | AWS Budget with email alerts (email via secret, never committed) |

## Repo layout

```
app/common/    providers (gemini+bedrock), config, logs, audit, schemas, rules
app/agents/    classifier/ extractor/ validator/ resolver/   (one handler.py each)
app/api/       api Lambda      app/starter/  SQS -> StartExecution
infra/bootstrap  infra/modules/docagent_stack  infra/envs/demo
statemachine/  workflow.asl.json (templated by Terraform)
web/           index.html, app.js, styles.css
evals/         data/ (synthetic docs + ground truth), run_evals.py, RESULTS.md
scripts/       build_lambdas, generate_dataset, cost estimate, browser test
tests/
```

## Milestones (each ends with "done when")

**M1: Skeleton, CI, bootstrap.** Repo layout, ruff/pytest config, CI (fmt/validate/ruff/pytest), `infra/bootstrap` creating the docagent deploy role + boundary on the existing OIDC provider.
Done when: CI green on push; `terraform apply` of bootstrap done (plan shown first); role ARN stored as a GitHub variable.

**M2: Data + storage + providers.** Terraform module: uploads bucket, DynamoDB tables, vendors seed, SQS/DLQ, budget; `common/providers.py` (Gemini multimodal JSON-schema + Bedrock stub), shared audit writer, unit tests.
Done when: `terraform apply` clean via plan review; provider unit tests pass; a one-off script gets valid JSON from Gemini for a sample image.

**M3: Classifier + Extractor + state machine v1.** Both Lambdas, state machine Classifier -> (reject | Extractor -> save), 429 retry/backoff.
Done when: an uploaded sample runs end to end in AWS, status and audit rows exist, a junk file is rejected with a reason.

**M4: Validator + Resolver + loop + human review.** Deterministic rules + LLM anomaly check; Resolver tools (re-extract fields, fuzzy vendor match, recompute totals); loop max 2; `waitForTaskToken` review path with explanation.
Done when: a doc with wrong totals auto-fixes; a doc that cannot be fixed lands in the review queue; approving it resumes the execution.

**M5: Pacing + API.** Upload -> SQS -> starter with concurrency cap and `ChangeMessageVisibility` backoff, API Lambda with all endpoints and CSV, throttling, CORS.
Done when: 20 uploads at once all complete without lost messages; `curl` list/detail/audit/review/CSV work.

**M6: Dataset + evals.** ~30 synthetic docs (fictional companies, varied layouts, ~10 images/scans, 3 non-financial, deliberate faults) with ground-truth JSON; `run_evals.py` measures each agent separately plus latency and cost per 1,000 docs.
Done when: `evals/RESULTS.md` is committed with all metrics.

**M7: Demo site + CD.** CloudFront + OAC site (upload, results table, review queue, audit trail, CSV, one-click samples), strict CORS, Playwright screenshot test, CI deploy job with destroy guard.
Done when: public URL works end to end; screenshots committed; a push to main deploys via Actions.

**M8: README.** Pitch, live link, screenshots, mermaid architecture (as deployed), decisions, eval table, security, cost table, deploy-your-own, problems solved, link to rag-on-aws.
Done when: every number in the README traces to `evals/RESULTS.md` or the cost script.
