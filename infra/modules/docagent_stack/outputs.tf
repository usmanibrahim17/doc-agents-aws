output "web_url" {
  value = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "api_url" {
  value = aws_apigatewayv2_api.this.api_endpoint
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.workflow.arn
}

output "uploads_bucket_name" {
  value = aws_s3_bucket.uploads.bucket
}

output "intake_queue_url" {
  value = aws_sqs_queue.intake.url
}

output "table_names" {
  value = {
    documents = aws_dynamodb_table.documents.name
    audit     = aws_dynamodb_table.audit.name
    reviews   = aws_dynamodb_table.reviews.name
    vendors   = aws_dynamodb_table.vendors.name
  }
}
