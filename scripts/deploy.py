#!/usr/bin/env python3
"""Review and deploy the AWS budget from a trusted local terminal."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "terraform"
REGION = "us-east-1"
BUDGET_TYPE = "aws_budgets_budget"
MINIMUM_CREDITS = Decimal("20")


class Blocked(Exception):
    """The deployment gate could not verify a required condition."""


def command(args, profile=None, capture=False):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AWS_", "TF_"))
    }
    env.update(
        AWS_EC2_METADATA_DISABLED="true",
        AWS_IGNORE_CONFIGURED_ENDPOINT_URLS="true",
        TF_IN_AUTOMATION="1",
        CHECKPOINT_DISABLE="1",
    )
    if profile is not None:
        env["AWS_PROFILE"] = profile

    return subprocess.run(
        args, cwd=ROOT, env=env, check=True, text=True, stdout=subprocess.PIPE if capture else None
    ).stdout


def object_response(raw):
    try:
        data = json.loads(raw, parse_float=Decimal, parse_int=Decimal, parse_constant=Decimal)
    except (TypeError, ValueError) as error:
        raise Blocked("Invalid JSON response.") from error
    if not isinstance(data, dict):
        raise Blocked("Expected a JSON object.")
    return data


def verified_credits(raw, account):
    data = object_response(raw)
    if data.get("accountId") != account:
        raise Blocked("The credit response is for a different AWS account.")
    if data.get("accountPlanType") != "FREE" or data.get("accountPlanStatus") != "ACTIVE":
        raise Blocked("AWS did not report an active Free plan.")
    credits = data.get("accountPlanRemainingCredits")
    if not isinstance(credits, dict) or credits.get("unit") != "USD":
        raise Blocked("AWS did not report a remaining USD credit balance.")
    amount = credits.get("amount")
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise Blocked("AWS did not report a valid numeric credit balance.")
    if amount < MINIMUM_CREDITS:
        raise Blocked(f"Remaining Free Tier credits are below USD {MINIMUM_CREDITS}.")
    return amount


def aws(operation, profile):
    return command(
        ["aws", *operation, "--region", REGION, "--output", "json",
         "--no-cli-pager", "--no-cli-auto-prompt", "--cli-connect-timeout", "10",
         "--cli-read-timeout", "20"],
        profile=profile,
        capture=True,
    )


def principal(profile, account):
    identity = object_response(aws(["sts", "get-caller-identity"], profile))
    user_id = identity.get("UserId")
    if identity.get("Account") != account or not isinstance(user_id, str) or not user_id:
        raise Blocked(f"Profile {profile} did not verify against account {account}.")
    # STS appends a session name to the stable role ID for assumed roles.
    return user_id.split(":", 1)[0]


def check_credits(profile, account):
    balance = verified_credits(aws(["freetier", "get-account-plan-state"], profile), account)
    print(f"AWS account {account} has an active Free plan and USD {balance} remaining.", flush=True)


def has_priced_changes(raw):
    plan = object_response(raw)
    if (
        not isinstance(plan.get("format_version"), str)
        or not plan["format_version"].startswith("1.")
        or plan.get("errored") is not False
        or plan.get("complete") is not True
        or plan.get("action_invocations")
        or plan.get("deferred_changes")
    ):
        raise Blocked("The Terraform plan could not be verified as complete.")
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        raise Blocked("The Terraform resource changes could not be verified.")

    changed = False
    for resource in changes:
        if not isinstance(resource, dict):
            raise Blocked("Invalid Terraform resource change.")
        change = resource.get("change")
        if (
            resource.get("mode") != "managed"
            or resource.get("type") != BUDGET_TYPE
            or resource.get("address") != f"{BUDGET_TYPE}.monthly"
            or resource.get("previous_address") is not None
            or not isinstance(change, dict)
            or change.get("importing") is not None
            or change.get("actions") not in (["no-op"], ["create"], ["update"])
        ):
            raise Blocked("Only a create or in-place update of the notification budget is priced.")
        changed |= change["actions"] != ["no-op"]

    if changed and plan.get("applyable") is not True:
        raise Blocked("Terraform marked the saved plan as inapplicable.")
    return changed


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def confirm(digest):
    print(f"Reviewed plan SHA-256 {digest}", flush=True)
    return input(f"Type APPLY {digest[:12]} to approve this plan: ") == f"APPLY {digest[:12]}"


def deploy(account, monitor, planner, writer):
    if not interactive():
        raise Blocked("Run this workflow in an interactive terminal.")
    if not re.fullmatch(r"[0-9]{12}", account) or len({monitor, planner, writer}) != 3:
        raise Blocked("Provide a 12-digit AWS account ID and three distinct profile names.")

    command(["terraform", "fmt", "-check", "-diff"])
    command(["terraform", "validate", "-no-color"])
    monitor_id = principal(monitor, account)
    planner_id = principal(planner, account)
    if monitor_id == planner_id:
        raise Blocked("The monitor and plan profiles use the same AWS principal.")
    check_credits(monitor, account)

    with tempfile.TemporaryDirectory(prefix=".guardrail-plan-", dir=ROOT) as directory:
        plan = Path(directory) / "review.tfplan"
        command(
            ["terraform", "plan", "-input=false", "-no-color", "-lock-timeout=30s",
             f"-var=account_id={account}", f"-out={plan}"],
            profile=planner,
        )
        digest = hashlib.sha256(plan.read_bytes()).hexdigest()
        changed = has_priced_changes(command(["terraform", "show", "-json", str(plan)], capture=True))
        print(f"Review the saved plan for AWS account {account}.", flush=True)
        command(["terraform", "show", "-no-color", str(plan)])
        print("Estimated incremental AWS cost: USD 0/month for budget monitoring and email alerts.", flush=True)
        if not changed:
            print("No budget changes to apply.")
            return

        if hashlib.sha256(plan.read_bytes()).hexdigest() != digest:
            raise Blocked("The saved plan changed during review.")
        if not confirm(digest):
            raise Blocked("Explicit approval was not given.")
        if principal(writer, account) in {monitor_id, planner_id}:
            raise Blocked("The apply profile must use a separate AWS principal.")
        check_credits(monitor, account)
        if hashlib.sha256(plan.read_bytes()).hexdigest() != digest:
            raise Blocked("The saved plan changed after review.")
        command(
            ["terraform", "apply", "-input=false", "-no-color", "-lock-timeout=30s", str(plan)],
            profile=writer,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--monitor-profile", required=True)
    parser.add_argument("--plan-profile", required=True)
    parser.add_argument("--apply-profile", required=True)
    args = parser.parse_args()

    os.umask(0o077)
    try:
        deploy(args.account_id, args.monitor_profile, args.plan_profile, args.apply_profile)
    except (Blocked, subprocess.CalledProcessError, OSError, EOFError, KeyboardInterrupt) as error:
        print(f"Deployment stopped: {error or 'interrupted'}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
