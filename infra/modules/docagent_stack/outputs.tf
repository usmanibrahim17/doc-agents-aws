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
