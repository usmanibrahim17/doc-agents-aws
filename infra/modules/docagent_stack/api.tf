# HTTP API for the demo site: one Lambda, throttled, strict CORS, access logs without client IPs.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.name_prefix}-api"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_iam_role" "api" {
  name                 = "${var.name_prefix}-api"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = var.tags
}

data "aws_iam_policy_document" "api" {
  statement {
    sid       = "Documents"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.documents.arn]
  }

  statement {
    sid       = "ListSessionDocuments"
    actions   = ["dynamodb:Query"]
    resources = ["${aws_dynamodb_table.documents.arn}/index/by-session"]
  }

  statement {
    sid       = "ReadAudit"
    actions   = ["dynamodb:Query"]
    resources = [aws_dynamodb_table.audit.arn]
  }

  statement {
    sid       = "CloseReviews"
    actions   = ["dynamodb:GetItem", "dynamodb:DeleteItem"]
    resources = [aws_dynamodb_table.reviews.arn]
  }

  # Signs the browser's upload and download URLs.
  statement {
    sid       = "Uploads"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.uploads.arn}/uploads/*"]
  }

  # Task callbacks have no resource-level permissions: the task token is the capability.
  statement {
    sid       = "ResumeWorkflow"
    actions   = ["states:SendTaskSuccess"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.name_prefix}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.12"
  handler          = "app.api.handler.handler"
  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 20
  memory_size      = 512
  tags             = var.tags

  environment {
    variables = {
      DOCUMENTS_TABLE     = aws_dynamodb_table.documents.name
      AUDIT_TABLE         = aws_dynamodb_table.audit.name
      REVIEWS_TABLE       = aws_dynamodb_table.reviews.name
      UPLOADS_BUCKET      = aws_s3_bucket.uploads.bucket
      DAILY_LIMIT         = tostring(var.daily_upload_limit)
      SESSION_DAILY_LIMIT = tostring(var.session_daily_upload_limit)
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

# The browser uploads straight to S3 with a presigned POST, so the bucket needs the same CORS.
resource "aws_s3_bucket_cors_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  cors_rule {
    allowed_origins = local.cors_origins
    allowed_methods = ["GET", "POST"]
    allowed_headers = ["content-type"]
    max_age_seconds = 3600
  }
}

resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
  tags          = var.tags

  cors_configuration {
    allow_origins = local.cors_origins
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["content-type", "x-session-id"]
    max_age       = 3600
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 20000
}

resource "aws_apigatewayv2_route" "api" {
  for_each = toset([
    "POST /documents",
    "GET /documents",
    "GET /documents/{id}",
    "GET /documents/{id}/audit",
    "GET /reviews",
    "POST /reviews/{id}",
    "GET /export.csv",
  ])

  api_id    = aws_apigatewayv2_api.this.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${var.name_prefix}-api"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags

  # Deliberately no client IP, user agent or session id.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId       = "$context.requestId"
      requestTime     = "$context.requestTime"
      routeKey        = "$context.routeKey"
      status          = "$context.status"
      responseLatency = "$context.responseLatency"
      errorMessage    = "$context.error.message"
    })
  }

  default_route_settings {
    throttling_rate_limit  = var.api_throttle_rate_limit
    throttling_burst_limit = var.api_throttle_burst_limit
  }

  depends_on = [aws_apigatewayv2_route.api]
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
