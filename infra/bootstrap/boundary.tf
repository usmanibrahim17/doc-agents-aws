# Permissions boundary for the stack's own roles (agent/api/starter Lambda roles and the Step
# Functions role).
#
# A boundary is a ceiling: a role's effective permissions are the INTERSECTION of its own
# policies and the boundary. The deploy role can only create or modify <prefix>-* roles that
# carry this boundary (see deploy_iam.tf), so even a compromised main branch could not mint a
# role with more power than this: no IAM, no admin, no data outside this stack.

data "aws_iam_policy_document" "stack_boundary" {
  statement {
    sid       = "UploadsBucket"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${local.uploads_bucket}/*"]
  }

  statement {
    sid = "StackTables"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = [local.table_arn, "${local.table_arn}/index/*"]
  }

  # Start executions, report human-review decisions, and read execution state.
  statement {
    sid = "Workflow"
    actions = [
      "states:StartExecution",
      "states:DescribeExecution",
      "states:ListExecutions",
      "states:SendTaskSuccess",
      "states:SendTaskFailure",
    ]
    resources = [local.state_machine_arn, local.execution_arn]
  }

  # Step Functions role invokes the agent Lambdas.
  statement {
    sid       = "InvokeAgents"
    actions   = ["lambda:InvokeFunction"]
    resources = [local.lambda_arn]
  }

  # Bedrock models (only used when ai_provider = bedrock).
  statement {
    sid     = "InvokeBedrockModels"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:*:${local.acct}:inference-profile/*",
    ]
  }

  # The Gemini key (only used when ai_provider = gemini).
  statement {
    sid       = "ReadProviderKey"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${local.region}:${local.acct}:parameter${var.gemini_key_parameter}"]
  }

  statement {
    sid = "IntakeQueue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [local.sqs_arn]
  }

  statement {
    sid       = "WriteLambdaLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.lambda_logs}:*"]
  }
}

resource "aws_iam_policy" "stack_boundary" {
  name        = "${local.p}-stack-boundary"
  description = "Permissions boundary for ${local.p}-* roles: the maximum the stack's roles may ever be granted"
  policy      = data.aws_iam_policy_document.stack_boundary.json
  tags        = var.tags
}
