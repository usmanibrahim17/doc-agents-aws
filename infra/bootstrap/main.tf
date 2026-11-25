# Bootstrap: the deploy role and permissions boundary GitHub Actions needs for this project.
#
# Reused from project 1 (rag-on-aws), NOT created here: the Terraform state bucket and the
# GitHub OIDC identity provider (an account can only have one per URL). This project's state goes
# under the key prefix "docagent/" in that bucket.
#
# Like project 1, this stack keeps LOCAL state (git-ignored). It changes rarely; keep a copy of
# the state file outside the repo.

terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.24"
    }
  }
}

provider "aws" {
  region = var.region
}

data "aws_caller_identity" "current" {}

locals {
  account_id       = data.aws_caller_identity.current.account_id
  deploy_role_name = "${var.name_prefix}-github-deploy"
  github_oidc_url  = "token.actions.githubusercontent.com"
}

# Existing state bucket from project 1.
data "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name
}

# Existing GitHub OIDC provider from project 1.
data "aws_iam_openid_connect_provider" "github" {
  url = "https://${local.github_oidc_url}"
}

# Only workflows on the main branch of exactly this repository may assume the role.
# The subject uses GitHub's immutable form with numeric IDs (see var.github_sub_prefix).
data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_url}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_url}:sub"
      values   = ["${var.github_sub_prefix}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = local.deploy_role_name
  description          = "Assumed by GitHub Actions (main branch only) to deploy the ${var.name_prefix} stack"
  assume_role_policy   = data.aws_iam_policy_document.deploy_trust.json
  max_session_duration = 3600
  tags                 = var.tags
}
