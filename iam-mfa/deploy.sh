#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo 'Usage: bash iam-mfa/deploy.sh PROFILE STEP account=ACCOUNT_ID'
  echo 'Steps: preflight, create-policy, create-group, attach-policy, create-test-user, grant-test-read, add-test-user, remove-test-user, detach-policy'
}

if [[ $# == 1 && $1 == --help ]]; then
  usage
  exit 0
fi
if [[ $# != 3 ]] || [[ ! $3 =~ ^account=[0-9]{12}$ ]]; then
  usage >&2
  exit 2
fi

profile=$1
step=$2
account=${3#account=}
region=ap-southeast-2
group=mfa-required-users
test_user=mfa-test-user
policy=enforce-mfa-policy
policy_arn="arn:aws:iam::$account:policy/$policy"
policy_file="$(cd -- "$(dirname -- "$0")" && pwd)/enforce-mfa-policy.json"
test_read='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"iam:ListAccountAliases","Resource":"*"}]}'

aws_call() {
  aws --profile "$profile" --region "$region" --no-cli-pager "$@"
}

preflight() {
  local identity plan plan_account type status credits
  identity=$(aws_call sts get-caller-identity --query Account --output text)
  if [[ $identity != "$account" ]]; then
    echo "Dừng: profile xác thực account $identity, dự kiến $account." >&2
    return 1
  fi

  plan=$(aws_call freetier get-account-plan-state \
    --query '[accountId,accountPlanType,accountPlanStatus,accountPlanRemainingCredits.amount]' \
    --output text)
  read -r plan_account type status credits <<< "$plan"
  if [[ $plan_account != "$account" || $type != FREE || $status != ACTIVE ]] ||
    ! awk -v credits="$credits" 'BEGIN { exit !(credits ~ /^[0-9]+([.][0-9]+)?$/ && credits + 0 > 0) }'; then
    echo "Dừng: không xác minh được Free Plan đang hoạt động và còn credits ($plan)." >&2
    return 1
  fi
  echo "Account $account · Profile $profile · FREE / ACTIVE · Credits $credits"
}

case "$step" in
  preflight) preflight; exit 0 ;;
  create-policy)
    policy_document=$(sed "s/arn:aws:iam::[*]:/arn:aws:iam::$account:/g" "$policy_file")
    write=(iam create-policy --policy-name "$policy" --policy-document "$policy_document")
    verify=(iam get-policy --policy-arn "$policy_arn")
    ;;
  create-group)
    write=(iam create-group --group-name "$group")
    verify=(iam get-group --group-name "$group" --query Group.Arn)
    ;;
  attach-policy)
    write=(iam attach-group-policy --group-name "$group" --policy-arn "$policy_arn")
    verify=(iam list-attached-group-policies --group-name "$group")
    ;;
  create-test-user)
    write=(iam create-user --user-name "$test_user")
    verify=(iam get-user --user-name "$test_user" --query User.Arn)
    ;;
  grant-test-read)
    write=(iam put-user-policy --user-name "$test_user" --policy-name MFAReadProbe --policy-document "$test_read")
    verify=(iam get-user-policy --user-name "$test_user" --policy-name MFAReadProbe)
    ;;
  add-test-user|remove-test-user)
    operation=add-user-to-group
    if [[ $step == remove-* ]]; then operation=remove-user-from-group; fi
    write=(iam "$operation" --group-name "$group" --user-name "$test_user")
    verify=(iam list-groups-for-user --user-name "$test_user" --query 'Groups[].GroupName')
    ;;
  detach-policy)
    write=(iam detach-group-policy --group-name "$group" --policy-arn "$policy_arn")
    verify=(iam list-attached-group-policies --group-name "$group")
    ;;
  *) usage >&2; exit 2 ;;
esac

preflight
if [[ $step == attach-policy ]]; then
  members=$(aws_call iam get-group --group-name "$group" --query 'Users[].UserName' --output text)
  if [[ -n $members ]]; then
    echo "Dừng: nhóm $group đã có thành viên. Kiểm tra tác động trước khi gắn policy." >&2
    exit 1
  fi
  version=$(aws_call iam get-policy --policy-arn "$policy_arn" --query Policy.DefaultVersionId --output text)
  aws_call iam get-policy-version --policy-arn "$policy_arn" --version-id "$version" --query PolicyVersion.Document
fi
printf '%s' 'Lệnh AWS dự kiến:'
printf ' %q' "${write[@]}"
if [[ $step == create-policy ]]; then
  printf '\n%s\n' "$policy_document"
fi
printf '\nNhập %s để duyệt đúng thao tác này: ' "$step" >&2
if ! IFS= read -r approval || [[ $approval != "$step" ]]; then
  echo 'Chưa duyệt thao tác.' >&2
  exit 1
fi

preflight
aws_call "${write[@]}"
if ! aws_call "${verify[@]}" --output json; then
  echo 'AWS đã nhận thao tác ghi, nhưng bước đọc xác minh lỗi. Kiểm tra trạng thái trước khi thử lại.' >&2
  exit 1
fi
