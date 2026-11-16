import json
import unittest
from pathlib import Path

IAM = Path(__file__).resolve().parents[1] / "iam"


class PolicyTests(unittest.TestCase):
    def test_policies_scope_access_and_deny_upgrade_paths(self):
        read = {"budgets:ViewBudget", "budgets:ListTagsForResource"}
        budget = "arn:aws:budgets::ACCOUNT_ID:budget/monthly-cost-guardrail"
        for name, actions, resource in [
            ("credit-monitor", {"freetier:GetAccountPlanState"}, "*"),
            ("plan", read, budget),
            ("apply", read | {"budgets:ModifyBudget"}, budget),
        ]:
            with self.subTest(policy=name):
                policy = json.loads((IAM / f"{name}.json").read_text())
                self.assertEqual(policy["Version"], "2012-10-17")
                statements = policy["Statement"]
                self.assertEqual(len(statements), 2)
                allow, deny = statements
                self.assertNotIn("NotAction", allow)
                self.assertEqual(allow["Effect"], "Allow")
                self.assertEqual(set(allow["Action"]), actions)
                self.assertEqual(allow["Resource"], resource)
                self.assertEqual(deny["Effect"], "Deny")
                self.assertEqual(set(deny["Action"]), {
                    "freetier:UpgradeAccountPlan", "organizations:*", "controltower:*",
                })
                self.assertEqual(deny["Resource"], "*")
                self.assertNotIn("Condition", deny)
