"""Installation contract checks; no OS identities, accounts, services or models."""

import unittest
from unittest.mock import patch
from lax_connector import purpose_install, purpose_upgrade


class PurposeContextPolicyTests(unittest.TestCase):
    def test_only_explicit_policy_changes_are_carried(self):
        self.assertEqual(purpose_install.context_settings({}), {})
        for policy in (None, {"type": "disabled"}, {"type": "canonical"}):
            with self.subTest(policy=policy):
                spec = {"automaticContextRefill": policy, "contextRebuildEnabled": True}
                self.assertEqual(purpose_install.context_settings(spec), spec)

    def test_invalid_policy_is_rejected_before_installation_or_upgrade_effects(self):
        invalid = [
            True,
            "canonical",
            {},
            {"type": "canonical", "contextId": "borrowed"},
            {"type": "reader"},
            {"type": 1},
        ]
        for policy in invalid:
            with self.subTest(policy=policy):
                spec = {"automaticContextRefill": policy}
                with patch.object(purpose_install.os, "geteuid", return_value=0):
                    with patch.object(purpose_install, "machine_identity") as machine:
                        with self.assertRaisesRegex(
                            ValueError, "automatic refill policy"
                        ):
                            purpose_install.install(spec)
                        machine.assert_not_called()
                    upgrade = {**spec, "schema": purpose_upgrade.SCHEMA}
                    with patch.object(purpose_install, "directory") as directory:
                        with self.assertRaisesRegex(
                            ValueError, "automatic refill policy"
                        ):
                            purpose_upgrade.upgrade(upgrade)
                        directory.assert_not_called()

    def test_disabling_refill_does_not_disable_the_existing_rebuild_setting(self):
        original = {
            "contextRebuildEnabled": True,
            "automaticContextRefill": {"type": "canonical"},
        }
        updated = {
            **original,
            **purpose_install.context_settings(
                {"automaticContextRefill": {"type": "disabled"}}
            ),
        }
        self.assertEqual(
            updated,
            {
                "contextRebuildEnabled": True,
                "automaticContextRefill": {"type": "disabled"},
            },
        )


if __name__ == "__main__":
    unittest.main()
