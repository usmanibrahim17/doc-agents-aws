# S3 upload -> SQS -> starter Lambda -> Step Functions.

resource "aws_s3_bucket_notification" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  queue {
    queue_arn     = aws_sqs_queue.intake.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "uploads/"
  }

  # S3 checks it may send to the queue when saving the notification.
  depends_on = [aws_sqs_queue_policy.intake]
}

resource "aws_cloudwatch_log_group" "starter" {
  name              = "/aws/lambda/${var.name_prefix}-starter"
  retention_in_days = 14
  tags              = var.tags
}

resource "aws_iam_role" "starter" {
  name                 = "${var.name_prefix}-starter"
  assume_role_policy   = data.aws_iam_policy_document.lambda_trust.json
  permissions_boundary = var.permissions_boundary_arn
  tags                 = var.tags
}

data "aws_iam_policy_document" "starter" {
  statement {
    sid       = "ConsumeIntakeQueue"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
    resources = [aws_sqs_queue.intake.arn]
  }

  statement {
    sid       = "Documents"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.documents.arn]
  }

  statement {
    sid       = "AppendAudit"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.audit.arn]
  }

  # Counts documents parked for review, which do not occupy a processing slot.
  statement {
    sid       = "CountReviews"
    actions   = ["dynamodb:Scan"]
    resources = [aws_dynamodb_table.reviews.arn]
  }

  statement {
    sid       = "StartWorkflow"
    actions   = ["states:StartExecution", "states:ListExecutions"]
    resources = [aws_sfn_state_machine.workflow.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.starter.arn}:*"]
  }
}

resource "aws_iam_role_policy" "starter" {
  name   = "starter"
  role   = aws_iam_role.starter.id
  policy = data.aws_iam_policy_document.starter.json
}

resource "aws_lambda_function" "starter" {
  function_name    = "${var.name_prefix}-starter"
  role             = aws_iam_role.starter.arn
  runtime          = "python3.12"
  handler          = "app.starter.handler.handler"
  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  timeout          = 30
  memory_size      = 256
  tags             = var.tags

  environment {
    variables = {
      DOCUMENTS_TABLE   = aws_dynamodb_table.documents.name
      AUDIT_TABLE       = aws_dynamodb_table.audit.name
      REVIEWS_TABLE     = aws_dynamodb_table.reviews.name
      STATE_MACHINE_ARN = aws_sfn_state_machine.workflow.arn
      MAX_ACTIVE        = tostring(var.max_active_documents)
    }
  }

  depends_on = [aws_cloudwatch_log_group.starter, aws_iam_role_policy.starter]
}

resource "aws_lambda_event_source_mapping" "intake" {
  event_source_arn        = aws_sqs_queue.intake.arn
  function_name           = aws_lambda_function.starter.arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2 # the AWS minimum
  }

  depends_on = [aws_iam_role_policy.starter]
}
