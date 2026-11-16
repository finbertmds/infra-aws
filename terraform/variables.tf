variable "account_id" {
  description = "ID of the AWS account whose costs the budget monitors."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "The AWS account ID must have exactly 12 digits."
  }
}

variable "budget_alert_email" {
  description = "Email address that receives actual and forecasted cost alerts."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+[.][^@\\s]+$", var.budget_alert_email))
    error_message = "Enter a valid budget alert email address."
  }
}
