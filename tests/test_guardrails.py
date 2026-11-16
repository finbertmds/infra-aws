import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import deploy

ACCOUNT = "123456789012"
FREE = {
    "accountId": ACCOUNT,
    "accountPlanType": "FREE",
    "accountPlanStatus": "ACTIVE",
    "accountPlanRemainingCredits": {"amount": 20, "unit": "USD"},
    "accountPlanExpirationDate": "2099-01-01T00:00:00Z",
}
BUDGET = {
    "address": "aws_budgets_budget.monthly",
    "mode": "managed",
    "type": "aws_budgets_budget",
    "change": {"actions": ["create"]},
}


class CreditTests(unittest.TestCase):
    def test_exact_minimum(self):
        self.assertEqual(deploy.verified_credits(json.dumps(FREE), ACCOUNT), 20)

    def test_unverified_and_ineligible_accounts(self):
        for key, value in [
            ("accountId", "999999999999"),
            ("accountPlanType", "PAID"),
            ("accountPlanStatus", "EXPIRED"),
            ("accountPlanRemainingCredits", None),
            ("accountPlanRemainingCredits", {"amount": 19.999, "unit": "USD"}),
            ("accountPlanRemainingCredits", {"amount": 100, "unit": "EUR"}),
            ("accountPlanRemainingCredits", {"amount": "20", "unit": "USD"}),
            ("accountPlanRemainingCredits", {"amount": True, "unit": "USD"}),
            ("accountPlanRemainingCredits", {"amount": float("inf"), "unit": "USD"}),
        ]:
            with self.subTest(key=key, value=value), self.assertRaises(deploy.Blocked):
                deploy.verified_credits(json.dumps(dict(FREE, **{key: value})), ACCOUNT)
        with self.assertRaises(deploy.Blocked):
            deploy.verified_credits("not json", ACCOUNT)


class WorkflowTests(unittest.TestCase):
    def run_workflow(self, *, approval=True, second_balance=20, changes=None,
                     tamper=False, wrong_apply_account=False, terminal=True,
                     credit_error=False, complete=True):
        calls = []
        plan_path = None

        def command(args, profile=None, capture=False):
            nonlocal plan_path
            calls.append((tuple(map(str, args)), profile))
            if args[:3] == ["aws", "freetier", "get-account-plan-state"]:
                self.assertEqual(profile, "monitor")
                response = copy.deepcopy(FREE)
                count = sum(call[0][:2] == ("aws", "freetier") for call in calls)
                if count == 2 and credit_error:
                    raise subprocess.CalledProcessError(255, args)
                if count == 2:
                    response["accountPlanRemainingCredits"]["amount"] = second_balance
                return json.dumps(response)
            if args[:3] == ["aws", "sts", "get-caller-identity"]:
                account = "999999999999" if profile == "writer" and wrong_apply_account else ACCOUNT
                return json.dumps({"Account": account, "UserId": profile + ":session"})
            if args[:2] == ["terraform", "plan"]:
                self.assertEqual(profile, "reader")
                plan_path = Path(next(arg[5:] for arg in args if arg.startswith("-out=")))
                plan_path.write_bytes(b"reviewed plan")
            if args[:3] == ["terraform", "show", "-json"]:
                return json.dumps({
                    "format_version": "1.2",
                    "complete": complete,
                    "errored": False,
                    "applyable": True,
                    "resource_changes": [BUDGET] if changes is None else changes,
                })
            if args[:2] == ["terraform", "apply"]:
                self.assertEqual(profile, "writer")
                self.assertEqual(Path(args[-1]), plan_path)
                self.assertEqual(plan_path.read_bytes(), b"reviewed plan")
            return ""

        def confirm(digest):
            self.assertIn((("terraform", "show", "-no-color", str(plan_path)), None), calls)
            if tamper:
                plan_path.write_bytes(b"replacement plan")
            return approval

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(deploy, "ROOT", Path(directory)), patch.object(
                deploy, "command", command
            ), patch.object(deploy, "confirm", confirm), patch.object(
                deploy, "interactive", return_value=terminal
            ):
                try:
                    deploy.deploy(ACCOUNT, "monitor", "reader", "writer")
                except (deploy.Blocked, subprocess.CalledProcessError):
                    blocked = True
                else:
                    blocked = False
                if plan_path:
                    self.assertFalse(plan_path.exists())
        return blocked, [args[:2] for args, _ in calls]

    def test_applies_reviewed_plan_after_second_credit_read(self):
        blocked, calls = self.run_workflow()
        self.assertFalse(blocked)
        self.assertEqual(calls[-2:], [("aws", "freetier"), ("terraform", "apply")])
        self.assertEqual(calls.count(("aws", "freetier")), 2)

    def test_declined_approval_never_uses_apply_profile(self):
        blocked, calls = self.run_workflow(approval=False)
        self.assertTrue(blocked)
        self.assertEqual(calls.count(("aws", "sts")), 2)
        self.assertNotIn(("terraform", "apply"), calls)

    def test_rechecks_credit_floor(self):
        blocked, calls = self.run_workflow(second_balance=19)
        self.assertTrue(blocked)
        self.assertEqual(calls.count(("aws", "freetier")), 2)
        self.assertNotIn(("terraform", "apply"), calls)

    def test_unpriced_resource_and_budget_deletion_are_blocked(self):
        for change in [dict(BUDGET, type="aws_instance"), dict(BUDGET, change={"actions": ["delete"]})]:
            with self.subTest(change=change):
                blocked, calls = self.run_workflow(changes=[change])
                self.assertTrue(blocked)
                self.assertNotIn(("terraform", "apply"), calls)

    def test_changed_plan_and_wrong_account_are_blocked(self):
        for options in [{"tamper": True}, {"wrong_apply_account": True}]:
            with self.subTest(options=options):
                blocked, calls = self.run_workflow(**options)
                self.assertTrue(blocked)
                self.assertNotIn(("terraform", "apply"), calls)

    def test_failed_credit_request_blocks_and_discards_plan(self):
        blocked, calls = self.run_workflow(credit_error=True)
        self.assertTrue(blocked)
        self.assertEqual(calls.count(("aws", "freetier")), 2)
        self.assertNotIn(("terraform", "apply"), calls)

    def test_incomplete_plan_blocks_apply(self):
        blocked, calls = self.run_workflow(complete=False)
        self.assertTrue(blocked)
        self.assertNotIn(("terraform", "apply"), calls)

    def test_noop_does_not_use_the_apply_profile(self):
        blocked, calls = self.run_workflow(changes=[])
        self.assertFalse(blocked)
        self.assertEqual(calls.count(("aws", "sts")), 2)
        self.assertNotIn(("terraform", "apply"), calls)

    def test_unattended_run_makes_no_calls(self):
        self.assertEqual(self.run_workflow(terminal=False), (True, []))


if __name__ == "__main__":
    unittest.main()
