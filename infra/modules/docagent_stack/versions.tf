terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.24"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Browser origins allowed by the API and the uploads bucket.
  cors_origins = concat(["https://${aws_cloudfront_distribution.web.domain_name}"], var.cors_allowed_origins)
}
