output "deploy_role_arn" {
  description = "Role for GitHub Actions to assume (store as the repository variable AWS_DEPLOY_ROLE_ARN)."
  value       = aws_iam_role.deploy.arn
}

output "state_bucket_name" {
  description = "Existing state bucket (repository variable TF_STATE_BUCKET)."
  value       = data.aws_s3_bucket.state.bucket
}

output "stack_boundary_arn" {
  description = "Permissions boundary every <prefix>-* stack role must carry."
  value       = aws_iam_policy.stack_boundary.arn
}
