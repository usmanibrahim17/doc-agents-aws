terraform {
  required_version = ">= 1.10" # S3 native state locking (use_lockfile) needs 1.10+

  # State lives in the bucket created by project 1's bootstrap, under this project's own key.
  # The bucket name contains the account ID, so it is not committed:
  #   terraform init -backend-config=backend.hcl
  backend "s3" {
    key          = "docagent/demo.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.24"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

module "docagent" {
  source = "../../modules/docagent_stack"

  # Created by infra/bootstrap. Every stack role carries it, and the CD deploy role may only
  # create or change stack roles that do.
  permissions_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/docagent-stack-boundary"

  # Built by scripts/build_zip.py; must exist before plan/validate.
  lambda_zip_path          = "${path.root}/../../../dist/app.zip"
  workflow_definition_path = "${path.root}/../../../statemachine/workflow.asl.json"

  # One setting switches provider (Bedrock quota is 0 on this account).
  ai_provider = "gemini"

  # Local development of the site; the CloudFront origin is added by the module.
  cors_allowed_origins = ["http://localhost:8080"]

  monthly_budget_usd  = var.monthly_budget_usd
  budget_alert_emails = var.budget_alert_emails
  vendors_file        = "${path.root}/../../../data/vendors.json"

  # Demo env only: lets `terraform destroy` empty and delete the buckets in one step.
  force_destroy = true

  tags = {
    Project   = "doc-agents-aws"
    ManagedBy = "terraform"
  }
}
