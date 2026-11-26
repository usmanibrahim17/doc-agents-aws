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
  agent_defaults = {
    uses_ai        = false
    reads_uploads  = false
    reads_document = false
    reads_vendors  = false
    finds_dups     = false
    review_actions = []
    timeout        = 30
  }
  agent_settings = {
    classifier = { uses_ai = true, reads_uploads = true, timeout = 150 }
    extractor  = { uses_ai = true, reads_uploads = true, timeout = 150 }
    validator  = { uses_ai = true, reads_document = true, reads_vendors = true, finds_dups = true, timeout = 150 }
    resolver   = { uses_ai = true, reads_uploads = true, reads_document = true, reads_vendors = true, timeout = 150 }
    reviewer   = { reads_document = true, review_actions = ["dynamodb:PutItem"] }
    finalizer  = { reads_document = true, review_actions = ["dynamodb:DeleteItem"] }
  }
  agents = { for name, settings in local.agent_settings : name => merge(local.agent_defaults, settings) }
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
    for_each = each.value.reads_document ? [1] : []

    content {
      sid       = "ReadDocument"
      actions   = ["dynamodb:GetItem"]
      resources = [aws_dynamodb_table.documents.arn]
    }
  }

  dynamic "statement" {
    for_each = each.value.finds_dups ? [1] : []

    content {
      sid       = "FindDuplicates"
      actions   = ["dynamodb:Query"]
      resources = ["${aws_dynamodb_table.documents.arn}/index/by-dup-key"]
    }
  }

  dynamic "statement" {
    for_each = each.value.reads_vendors ? [1] : []

    content {
      sid       = "ReadVendors"
      actions   = ["dynamodb:Scan"]
      resources = [aws_dynamodb_table.vendors.arn]
    }
  }

  dynamic "statement" {
    for_each = length(each.value.review_actions) > 0 ? [1] : []

    content {
      sid       = "Reviews"
      actions   = each.value.review_actions
      resources = [aws_dynamodb_table.reviews.arn]
    }
  }

  dynamic "statement" {
    for_each = each.value.reads_uploads ? [1] : []

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
        REVIEWS_TABLE   = aws_dynamodb_table.reviews.name
        VENDORS_TABLE   = aws_dynamodb_table.vendors.name
      },
      each.value.uses_ai ? local.ai_env : tomap({}),
      each.key == "resolver" ? tomap({ AUTO_FIX_MONETARY = tostring(var.auto_fix_monetary_amounts) }) : tomap({}),
    )
  }

  depends_on = [aws_cloudwatch_log_group.agent, aws_iam_role_policy.agent]
}
