"""Cost per 1,000 documents from measured usage and us-east-1 list prices.

Measured: model tokens, Step Functions transitions, Lambda duration and invocations.
Assumed per document (estimates): DynamoDB, S3, SQS and API requests.
Excluded: CloudWatch Logs, CloudFront, data transfer and storage (cents at demo volume), and all
free-tier allowances.

Prices (USD), checked 2026-11:
- Gemini: https://ai.google.dev/gemini-api/docs/pricing
- Bedrock: https://aws.amazon.com/bedrock/pricing/
- Lambda: https://aws.amazon.com/lambda/pricing/
- Step Functions: https://aws.amazon.com/step-functions/pricing/
- DynamoDB: https://aws.amazon.com/dynamodb/pricing/on-demand/
- API Gateway: https://aws.amazon.com/api-gateway/pricing/
"""

GEMINI_PER_M = (0.30, 2.50)  # gemini-3.5-flash-lite input, output (output includes thinking)
NOVA_LITE_PER_M = (0.06, 0.24)
LAMBDA_GB_SECOND = 0.0000166667
LAMBDA_PER_M_REQUESTS = 0.20
SFN_PER_TRANSITION = 0.000025
DDB_PER_M_WRITES, DDB_PER_M_READS = 0.625, 0.125
APIGW_PER_M = 1.00
S3_PER_1K_PUT, S3_PER_1K_GET = 0.005, 0.0004
SQS_PER_M = 0.40

MEMORY_MB = {"starter": 256}  # everything else has 512
PER_DOCUMENT = {"writes": 30, "reads": 25, "api": 6, "s3_put": 1, "s3_get": 3, "sqs": 4}


def estimate(
    documents: int,
    input_tokens: float,
    output_tokens: float,
    transitions: float,
    functions: dict[str, tuple[float, float]],
) -> dict:
    """All costs are per 1,000 documents. `functions`: name -> (seconds, invocations) in total."""
    gb_seconds = sum(s * MEMORY_MB.get(n, 512) / 1024 for n, (s, _) in functions.items())
    invocations = sum(count for _, count in functions.values())
    gb_seconds, invocations = gb_seconds / documents, invocations / documents

    def models(prices):
        return 1000 * (input_tokens * prices[0] + output_tokens * prices[1]) / 1e6

    u = PER_DOCUMENT
    aws = {
        "Step Functions": 1000 * transitions * SFN_PER_TRANSITION,
        "Lambda": 1000
        * (gb_seconds * LAMBDA_GB_SECOND + invocations * LAMBDA_PER_M_REQUESTS / 1e6),
        "DynamoDB": 1000 * (u["writes"] * DDB_PER_M_WRITES + u["reads"] * DDB_PER_M_READS) / 1e6,
        "API Gateway": 1000 * u["api"] * APIGW_PER_M / 1e6,
        "S3 + SQS": u["s3_put"] * S3_PER_1K_PUT
        + u["s3_get"] * S3_PER_1K_GET
        + 1000 * u["sqs"] * SQS_PER_M / 1e6,
    }
    total = sum(aws.values())
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "transitions": transitions,
        "lambda_gb_seconds": gb_seconds,
        "aws": aws,
        "aws_total": total,
        "gemini_paid_models": models(GEMINI_PER_M),
        "gemini_paid_total": models(GEMINI_PER_M) + total,
        "bedrock_models": models(NOVA_LITE_PER_M),
        "bedrock_total": models(NOVA_LITE_PER_M) + total,
    }
