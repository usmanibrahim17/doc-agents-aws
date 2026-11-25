variable "name_prefix" {
  description = "Prefix of the stack's resource names; the deploy role may only manage <prefix>-* resources."
  type        = string
  default     = "docagent"
}

variable "region" {
  description = "AWS region of the stack."
  type        = string
  default     = "us-east-1"
}

variable "state_bucket_name" {
  description = "Existing Terraform state bucket (created by project 1's bootstrap)."
  type        = string
}

variable "github_sub_prefix" {
  description = <<-EOT
    Prefix of the "sub" claim in GitHub's OIDC token for this repository (immutable form with
    numeric owner and repository IDs). Read it with:
      gh api repos/<owner>/<repo>/actions/oidc/customization/sub --jq .sub_claim_prefix
  EOT
  type        = string
  default     = "repo:usmanibrahim17@226472818/doc-agents-aws@1471491033"
}

variable "gemini_key_parameter" {
  description = "SSM parameter holding the Gemini key (shared with project 1; not managed by Terraform)."
  type        = string
  default     = "/rag-demo/gemini-api-key"
}

variable "tags" {
  description = "Tags applied to taggable resources."
  type        = map(string)
  default = {
    Project   = "doc-agents-aws"
    ManagedBy = "terraform"
  }
}
