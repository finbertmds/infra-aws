import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy.sh"


class DeploymentTests(unittest.TestCase):
    def run_step(
        self, confirmation, account="450114866570", plan="FREE",
        target="450114866570", step="create-group",
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aws = root / "aws"
            aws.write_text("""#!/bin/bash
shift 5
case "$1 $2" in
  'sts get-caller-identity') printf '%s\\n' "$TEST_ACCOUNT" ;;
  'freetier get-account-plan-state') printf '%s\\t%s\\tACTIVE\\t140\\n' "$TEST_ACCOUNT" "$TEST_PLAN" ;;
  'iam create-policy') printf '%s' "$6" > "$WRITE_LOG" ;;
  'iam get-policy') printf '%s' "$4" ;;
  'iam create-group') echo "$*" >> "$WRITE_LOG" ;;
  'iam get-group') echo mfa-required-users ;;
  *) exit 99 ;;
esac
""")
            aws.chmod(0o700)
            log = root / "writes"
            result = subprocess.run(
                ["bash", str(SCRIPT), "default", step, f"account={target}"],
                input=confirmation + "\n",
                env={
                    **os.environ,
                    "PATH": f"{root}:{os.environ['PATH']}",
                    "TEST_ACCOUNT": account,
                    "TEST_PLAN": plan,
                    "WRITE_LOG": str(log),
                },
                text=True, capture_output=True,
            )
            return result, log.read_text().splitlines() if log.exists() else []

    def test_runs_exactly_one_approved_write(self):
        result, writes = self.run_step("create-group")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(writes, ["iam create-group --group-name mfa-required-users"])

    def test_declining_prevents_writes(self):
        result, writes = self.run_step("no")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(writes, [])

    def test_wrong_account_prevents_writes(self):
        result, writes = self.run_step("create-group", account="123456789012")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("123456789012", result.stderr)
        self.assertEqual(writes, [])

    def test_paid_plan_prevents_writes(self):
        result, writes = self.run_step("create-group", plan="PAID")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("PAID", result.stderr)
        self.assertEqual(writes, [])

    def test_create_policy_uses_supplied_account(self):
        account = "123456789012"
        template = SCRIPT.with_name("enforce-mfa-policy.json")
        original = template.read_text()
        result, writes = self.run_step(
            "create-policy", account=account, target=account, step="create-policy",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = json.loads("\n".join(writes))
        resources = [
            statement["Resource"] for statement in policy["Statement"]
            if statement["Resource"] != "*"
        ]
        self.assertIn(f"arn:aws:iam::{account}:user/${{aws:username}}", resources)
        self.assertTrue(all(resource.startswith(f"arn:aws:iam::{account}:") for resource in resources))
        self.assertIn(f"arn:aws:iam::{account}:policy/enforce-mfa-policy", result.stdout)
        self.assertEqual(template.read_text(), original)

    def test_invalid_account_prevents_writes(self):
        result, writes = self.run_step("create-group", target="123")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(writes, [])
