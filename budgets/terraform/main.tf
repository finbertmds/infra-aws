locals {
  notifications = {
    actual_25    = { type = "ACTUAL", threshold = 25 }
    actual_50    = { type = "ACTUAL", threshold = 50 }
    actual_75    = { type = "ACTUAL", threshold = 75 }
    actual_100   = { type = "ACTUAL", threshold = 100 }
    forecast_100 = { type = "FORECASTED", threshold = 100 }
  }
}

resource "aws_budgets_budget" "monthly" {
  account_id   = var.account_id
  name         = "monthly-cost-guardrail"
  budget_type  = "COST"
  limit_amount = "20"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false
    include_refund = false
  }

  dynamic "notification" {
    for_each = local.notifications

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value.type
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
