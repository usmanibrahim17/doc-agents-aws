# Intake pacing: S3 -> SQS -> starter Lambda. The bucket notification and the consumer are added
# with the starter Lambda, so no messages pile up before something can read them.

resource "aws_sqs_queue" "intake_dlq" {
  name                      = "${var.name_prefix}-intake-dlq"
  message_retention_seconds = 14 * 24 * 3600 # 14 days to investigate and redrive
  sqs_managed_sse_enabled   = true
  tags                      = var.tags
}

resource "aws_sqs_queue" "intake" {
  name                       = "${var.name_prefix}-intake"
  visibility_timeout_seconds = 180           # 6x the starter's timeout
  message_retention_seconds  = 4 * 24 * 3600 # 4 days
  sqs_managed_sse_enabled    = true

  # Waiting for a free workflow slot counts as a receive, so this is far higher than project 1's:
  # only a message that keeps failing for a long time reaches the DLQ.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.intake_dlq.arn
    maxReceiveCount     = 20
  })

  tags = var.tags
}

# Only S3, only for the uploads bucket, only from this account, may send messages.
data "aws_iam_policy_document" "intake_queue" {
  statement {
    sid       = "AllowS3SendMessage"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.intake.arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.uploads.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "intake" {
  queue_url = aws_sqs_queue.intake.id
  policy    = data.aws_iam_policy_document.intake_queue.json
}
