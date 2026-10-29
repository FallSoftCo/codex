"""Wrong-runtime configuration must fail before state or execution admission."""
import tempfile
import unittest
from pathlib import Path

from lax_connector.connector import Connector
from lax_connector.linux_worker import provision, expected_configuration


class RuntimeModeAdmissionTests(unittest.TestCase):
    def test_purpose_configuration_has_no_single_context_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "not-created"
            for mismatch in ({"runtimeMode": "purpose-contexts"}, {"homes": {}},
                             {"tokens": {}}, {"installedPurposeRuntime": True}):
                for entry in (Connector, provision):
                    with self.subTest(mismatch=mismatch, entry=entry.__name__):
                        with self.assertRaises(ValueError):
                            entry({**mismatch, "state": str(state)})
                        self.assertFalse(state.exists())

    def test_explicit_single_context_preserves_existing_worker_configuration(self):
        spec = {"hollywoodUrl": "http://127.0.0.1:18776", "credential": "fixture",
                "hostId": "host", "binary": "/fixture/binary", "model": "unchanged",
                "effort": "unchanged"}
        original = expected_configuration(spec, "authority", "agent", Path("/fixture/home"))
        explicit = expected_configuration({**spec, "runtimeMode": "single-context"},
                                          "authority", "agent", Path("/fixture/home"))
        self.assertEqual(explicit, {**original, "runtimeMode": "single-context"})
