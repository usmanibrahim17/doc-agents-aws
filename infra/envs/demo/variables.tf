variable "monthly_budget_usd" {
  type    = number
  default = 20
}

variable "budget_alert_emails" {
  type = list(string)
}
