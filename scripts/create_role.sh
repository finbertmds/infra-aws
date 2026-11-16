(
  set -eu
  account_id='123456789012'
  admin_profile='my-aws-admin'
  trusted_principal='arn:aws:iam::123456789012:user/my-deploy-user'

  actual_account=$(aws --profile "$admin_profile" sts get-caller-identity \
    --query Account --output text)
  if [ "$actual_account" != "$account_id" ]; then
    echo "Dừng vì profile quản trị đang trỏ tới tài khoản $actual_account." >&2
    exit 1
  fi

  trust_policy=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "$trusted_principal"},
    "Action": "sts:AssumeRole"
  }]
}
EOF
  )

  create_guardrail_role() {
    role_name="$1"
    policy=$(sed "s/ACCOUNT_ID/$account_id/g" "$2")

    aws --profile "$admin_profile" iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "$trust_policy"

    aws --profile "$admin_profile" iam put-role-policy \
      --role-name "$role_name" \
      --policy-name guardrail-permissions \
      --policy-document "$policy"
  }

  create_guardrail_role guardrail-monitor iam/credit-monitor.json
  create_guardrail_role guardrail-plan iam/plan.json
  create_guardrail_role guardrail-apply iam/apply.json
)