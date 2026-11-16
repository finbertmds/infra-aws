provider "aws" {
  region              = "ap-southeast-2"
  allowed_account_ids = [var.account_id]
}
