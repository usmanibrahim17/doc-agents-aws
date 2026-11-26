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
