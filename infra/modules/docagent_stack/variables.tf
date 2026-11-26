variable "name_prefix" {
  description = "Prefix of every resource name."
  type        = string
  default     = "docagent"
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD."
  type        = number
  default     = 20
}

variable "budget_alert_emails" {
  description = "Addresses that receive budget alerts. Pass via tfvars (git-ignored) or a CI secret."
  type        = list(string)

  validation {
    condition     = length(var.budget_alert_emails) > 0
    error_message = "At least one budget alert email is required."
  }
}

variable "retention_days" {
  description = "Days after which uploaded files are deleted."
  type        = number
  default     = 7
}

variable "vendors_file" {
  description = "JSON list of known (fictional) vendors to seed: key, name, category."
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Boundary every stack role carries (created by infra/bootstrap)."
  type        = string
}

variable "lambda_zip_path" {
  description = "Zip of app/ built by scripts/build_zip.py."
  type        = string
}

variable "workflow_definition_path" {
  description = "Step Functions definition template."
  type        = string
}

variable "ai_provider" {
  description = "\"gemini\" or \"bedrock\"."
  type        = string
  default     = "gemini"

  validation {
    condition     = contains(["gemini", "bedrock"], var.ai_provider)
    error_message = "ai_provider must be \"gemini\" or \"bedrock\"."
  }
}

variable "gemini_generation_model" {
  description = "Gemini model used by the agents."
  type        = string
  default     = "gemini-3.5-flash-lite"
}

variable "gemini_api_key_parameter_name" {
  description = "SSM SecureString holding the Gemini key. Referenced by name only; never managed by Terraform."
  type        = string
  default     = "/rag-demo/gemini-api-key"
}

variable "generation_model_id" {
  description = "Bedrock model or inference profile ID (only when ai_provider = bedrock)."
  type        = string
  default     = ""
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete non-empty buckets (demo only)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to taggable resources."
  type        = map(string)
  default     = {}
}
