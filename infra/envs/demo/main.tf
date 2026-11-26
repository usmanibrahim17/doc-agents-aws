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

module "docagent" {
  source = "../../modules/docagent_stack"

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
