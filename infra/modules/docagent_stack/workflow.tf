# Standard state machine (needed for waitForTaskToken human review). Every agent decision is in
# the audit table; execution history is available in the Step Functions console.

locals {
  # Shared Retry block. The error names are the Python exception class names (providers.py).
  retry = jsonencode([
    {
      # Free-tier 429s: exponential backoff with jitter, up to about ten minutes in total.
      ErrorEquals     = ["RateLimited"]
      IntervalSeconds = 10
      BackoffRate     = 2
      MaxAttempts     = 8
      MaxDelaySeconds = 120
      JitterStrategy  = "FULL"
    },
    {
      ErrorEquals     = ["TransientError", "Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.SdkClientException", "States.Timeout"]
      IntervalSeconds = 5
      BackoffRate     = 2
      MaxAttempts     = 3
    },
  ])
}

data "aws_iam_policy_document" "workflow_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "workflow" {
  name                 = "${var.name_prefix}-workflow"
  assume_role_policy   = data.aws_iam_policy_document.workflow_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = var.tags
}

data "aws_iam_policy_document" "workflow" {
  statement {
    sid       = "InvokeAgents"
    actions   = ["lambda:InvokeFunction"]
    resources = [for f in aws_lambda_function.agent : f.arn]
  }
}

resource "aws_iam_role_policy" "workflow" {
  name   = "workflow"
  role   = aws_iam_role.workflow.id
  policy = data.aws_iam_policy_document.workflow.json
}

resource "aws_sfn_state_machine" "workflow" {
  name     = "${var.name_prefix}-workflow"
  type     = "STANDARD"
  role_arn = aws_iam_role.workflow.arn
  tags     = var.tags

  definition = templatefile(var.workflow_definition_path, {
    classifier_arn = aws_lambda_function.agent["classifier"].arn
    extractor_arn  = aws_lambda_function.agent["extractor"].arn
    validator_arn  = aws_lambda_function.agent["validator"].arn
    resolver_arn   = aws_lambda_function.agent["resolver"].arn
    reviewer_arn   = aws_lambda_function.agent["reviewer"].arn
    finalizer_arn  = aws_lambda_function.agent["finalizer"].arn
    retry          = local.retry
  })

  depends_on = [aws_iam_role_policy.workflow]
}
