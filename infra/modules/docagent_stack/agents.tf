# One Lambda and one least-privilege role per agent. All share the same zip.

data "aws_region" "current" {}

locals {
  use_gemini           = var.ai_provider == "gemini"
  gemini_key_param_arn = "arn:aws:ssm:${data.aws_region.current.region}:${local.account_id}:parameter/${trimprefix(var.gemini_api_key_parameter_name, "/")}"

  ai_env = local.use_gemini ? tomap({
    AI_PROVIDER             = "gemini"
    GEMINI_GENERATION_MODEL = var.gemini_generation_model
    GEMINI_API_KEY_PARAM    = var.gemini_api_key_parameter_name
    }) : tomap({
    AI_PROVIDER         = "bedrock"
    GENERATION_MODEL_ID = var.generation_model_id
  })

  # What each agent may do beyond the common set (update its document, append to the audit log).
  agents = {
    classifier = { uses_ai = true, timeout = 150 }
    extractor  = { uses_ai = true, timeout = 150 }
    finalizer  = { uses_ai = false, timeout = 30 }
  }
}

resource "terraform_data" "check_provider_settings" {
  lifecycle {
    precondition {
      condition     = local.use_gemini || var.generation_model_id != ""
      error_message = "generation_model_id is required when ai_provider = \"bedrock\"."
    }
  }
}

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_cloudwatch_log_group" "agent" {
  for_each = local.agents

  name              = "/aws/lambda/${var.name_prefix}-${each.key}"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_iam_role" "agent" {
  for_each = local.agents

  name                 = "${var.name_prefix}-${each.key}"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = var.tags
}

data "aws_iam_policy_document" "agent" {
  for_each = local.agents

  statement {
    sid       = "UpdateDocument"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.documents.arn]
  }

  statement {
    sid       = "AppendAudit"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.audit.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.agent[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = each.value.uses_ai ? [1] : []

    content {
      sid       = "ReadUploads"
      actions   = ["s3:GetObject"]
      resources = ["${aws_s3_bucket.uploads.arn}/uploads/*"]
    }
  }

  dynamic "statement" {
    for_each = each.value.uses_ai && local.use_gemini ? [1] : []

    content {
      sid       = "ReadGeminiKey"
      actions   = ["ssm:GetParameter"]
      resources = [local.gemini_key_param_arn]
    }
  }

  dynamic "statement" {
    for_each = each.value.uses_ai && !local.use_gemini ? [1] : []

    content {
      sid     = "InvokeBedrockModel"
      actions = ["bedrock:InvokeModel"]
      resources = [
        "arn:aws:bedrock:*::foundation-model/*",
        "arn:aws:bedrock:*:${local.account_id}:inference-profile/*",
      ]
    }
  }
}

resource "aws_iam_role_policy" "agent" {
  for_each = local.agents

  name   = "agent"
  role   = aws_iam_role.agent[each.key].id
  policy = data.aws_iam_policy_document.agent[each.key].json
}

resource "aws_lambda_function" "agent" {
  for_each = local.agents

  function_name    = "${var.name_prefix}-${each.key}"
  role             = aws_iam_role.agent[each.key].arn
  runtime          = "python3.12"
  handler          = "app.agents.${each.key}.handler.handler"
  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = each.value.timeout
  memory_size      = 512
  tags             = var.tags

  environment {
    variables = merge(
      {
        DOCUMENTS_TABLE = aws_dynamodb_table.documents.name
        AUDIT_TABLE     = aws_dynamodb_table.audit.name
        UPLOADS_BUCKET  = aws_s3_bucket.uploads.bucket
      },
      each.value.uses_ai ? local.ai_env : tomap({}),
    )
  }

  depends_on = [aws_cloudwatch_log_group.agent, aws_iam_role_policy.agent]
}
