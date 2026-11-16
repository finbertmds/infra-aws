# AWS cost guardrails

This standalone Terraform stack manages one account-wide AWS Budgets cost budget, `monthly-cost-guardrail`. Its USD 20 monthly threshold measures costs before credits and refunds. AWS sends email alerts when actual cost exceeds USD 5, 10, 15, and 20, and when forecasted cost exceeds USD 20. AWS Budgets monitoring and notifications have an estimated incremental charge of USD 0 per month. The stack uses the alert-only budget and has no workload deployment or Render integration. [AWS Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/) · [Terraform budget resource schema](https://registry.terraform.io/providers/hashicorp/aws/6.46.0/docs/resources/budgets_budget)

The deployment script uses the AWS Free Tier `GetAccountPlanState` API in `us-east-1` before planning and again after approval, immediately before applying. Both reads must report the target account, an active Free plan, and a finite numeric balance of at least USD 20. An AWS CLI failure or unverifiable response stops the run. The script uses STS to verify that the three named profiles resolve to distinct principals in the same target account. [Free Tier API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_freetier_GetAccountPlanState.html) · [AWS CLI response schema](https://docs.aws.amazon.com/cli/latest/reference/freetier/get-account-plan-state.html)

## IAM setup

Have the account owner separately approve the intended account, three roles and their trust policies, the exact policy attachments, and the budget and recipient. The attach operations change real AWS permissions. The budget and its email alerts have an estimated direct cost of USD 0. The write permission lets the apply role change or remove the named budget through AWS APIs, and role trust controls who can exercise that permission.

An authorized administrator should provision three dedicated roles in the same commercial AWS account using trusted human authentication, preferably MFA-backed and short lived. Replace `ACCOUNT_ID` in `iam/plan.json` and `iam/apply.json` with the 12-digit account ID. Attach one corresponding policy to each role as its only grant, or also use the same policy as that role's permissions boundary to limit future identity-based grants. Set up local AWS CLI v2 named profiles for those roles.

| Profile used below | Policy | Allow |
| --- | --- | --- |
| `guardrail-monitor` | `iam/credit-monitor.json` | Read the account's Free Tier plan and credit balance |
| `guardrail-plan` | `iam/plan.json` | Read the named budget, its notifications, subscribers and tags |
| `guardrail-apply` | `iam/apply.json` | Read and modify the named budget and its notifications and subscribers |

All three policies explicitly deny Free Tier upgrades and all AWS Organizations and Control Tower actions. STS `GetCallerIdentity` requires no IAM grant. The templates use fine-grained billing permissions. If the account rejects an operation, diagnose the exact missing permission and review any policy change separately. [Free Tier IAM actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_freetier.html) · [Budgets IAM actions](https://docs.aws.amazon.com/service-authorization/latest/reference/list_budgets.html) · [AWS billing permissions migration](https://docs.aws.amazon.com/cost-management/latest/userguide/migrate-granularaccess-whatis.html) · [STS GetCallerIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html)

## Manual deployment

1. Install Python 3.9+, Terraform 1.14+, and AWS CLI v2 with `aws freetier get-account-plan-state`. Complete the separately authorized IAM setup above and verify the roles' trust and grants with the administrator. Use trusted executables and local AWS profiles in the platform's default shared config location.
2. From this directory, copy the alert email template, replace the address, and initialize the provider. `init` uses local state and may download the pinned AWS provider from the Terraform Registry. Retain the generated `terraform/.terraform.lock.hcl` for version control.

   ```sh
   umask 077
   cp terraform/budget.auto.tfvars.example terraform/budget.auto.tfvars
   ${EDITOR:-vi} terraform/budget.auto.tfvars
   terraform -chdir=terraform init -input=false
   ```

3. Once account access is authorized, run the wrapper from an interactive terminal. Replace `123456789012` with the approved target account ID.

   ```sh
   python3 scripts/deploy.py \
     --account-id 123456789012 \
     --monitor-profile guardrail-monitor \
     --plan-profile guardrail-plan \
     --apply-profile guardrail-apply
   ```

4. Review the displayed saved plan and its incremental charge estimate. Check the account, budget amount, alert thresholds and recipient. To authorize AWS changes for that run, type `APPLY <12-character digest>` exactly as displayed. Any other response cancels. The wrapper verifies the apply identity, rechecks credits, verifies the saved plan again, and applies that same file. A no-change plan exits without applying. A failed apply can leave partial changes. Check the result and rerun the wrapper for a fresh review before retrying.
5. After a successful run, verify the budget and email subscriber in AWS Budgets and complete email verification if AWS requests it. Keep the Terraform directory's state and backups private and retain them for future runs.

## Limitations

- The USD 20 budget sends alerts. It cannot cap spend, stop services, close an account, or reserve credits. Billing data and alerts can lag. Forecasts depend on available AWS usage history. Existing AWS costs and future usage are outside the USD 0 incremental estimate. [AWS Budgets best practices](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html)
- The credit check is point-in-time. Credits, plan state and external resources can change between the read and apply. An expired plan or an older account without a verifiable active Free plan blocks this workflow. Free plan balances can run out and AWS can close the account. [AWS Free Tier plans](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)
- IAM cannot require this terminal prompt, bind permission to the plan hash, or make a balance check atomic with a budget write. Anyone who can obtain the apply credentials can potentially call Budgets directly. Root, administrators, other principals and other automatic upgrade paths remain outside these policies. A program controlling a pseudo-terminal or the local machine can bypass a local prompt. Keep the writer profile under human control and out of CI.
- Cost estimation covers this specific alert-only resource. The wrapper rejects unpriced resource changes and budget deletes, imports, moves and replacements. A new workload needs separate permissions, a pricing method and a new review. A budget with the same name that already exists outside this stack requires separate reconciliation before deployment.
- Plans and state can contain sensitive values. The wrapper uses a private temporary plan directory and removes it on normal exit or handled failure. A forced termination can leave files behind. Git ignore rules cover local Terraform artifacts and common secret files. Keep credentials outside the repository and restrict filesystem access. Git ignore rules do not protect already tracked or force-added files. Use an intact local state when deploying again and avoid concurrent operators. [Terraform saved plans](https://developer.hashicorp.com/terraform/cli/commands/plan#out-filename)

## Offline checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
CHECKPOINT_DISABLE=1 terraform -chdir=terraform fmt -check -recursive
CHECKPOINT_DISABLE=1 terraform -chdir=terraform validate
```

The Python suite replaces subprocess calls at the boundary and makes no AWS calls. Terraform validation requires the pinned provider to be installed locally. On a disconnected machine, initialize with `-plugin-dir` pointing at a trusted local provider mirror. Validation checks configuration and provider schemas without planning or applying.
