"""Read-only installed-UID/canonical HTTP integration; no model or service start.

Supply an actual v2 installation whose legitimate resource catalog evolved
after sealing. Run from the candidate SDK, preserving the original seal bytes.
Optional v1 verification checks exact deployed compatibility independently.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess

from lax_connector.purpose_install import protected
from lax_connector.purpose_readiness import require_sealed, seal, verify


def old_check(manifest):
    value = protected(manifest)
    code = (
        "import json,sys;"
        "from pathlib import Path;"
        "from lax_connector.purpose_install import protected;"
        "from lax_connector.purpose_readiness import require_sealed;"
        "print(json.dumps(require_sealed(protected(Path(sys.argv[1])))))"
    )
    return subprocess.run(
        [value["interpreter"], "-I", "-B", "-c", code, str(manifest)],
        text=True, capture_output=True, check=False,
    )


def check(manifest, v1_manifest=None):
    value = protected(manifest)
    path = manifest.parent / "readiness.json"
    original_bytes = path.read_bytes()
    original = protected(path)
    assert original["schema"] == "lax-purpose-readiness/v2"
    previous = old_check(manifest)
    assert previous.returncode != 0 and "not sealed" in previous.stderr
    current = require_sealed(value)
    assert current["resourceAccess"] != original["resourceAccess"]
    assert len(current["resourceAccess"]["resources"]) > len(original["resourceAccess"]["resources"])
    assert seal(value) == current and path.read_bytes() == original_bytes

    wrong_config = copy.deepcopy(value)
    wrong_config["configSha256"] = "0" * 64
    try:
        require_sealed(wrong_config)
    except (PermissionError, ValueError):
        pass
    else:
        raise AssertionError("Live installed configuration validation was bypassed")
    result = {
        "real_current_authorized_catalog_and_uid_pass": True,
        "old_exact_catalog_seal_refusal_observed": True,
        "original_seal_retained_byte_for_byte": True,
        "changed_installed_configuration_refused": True,
        "models_started": 0, "services_started": 0, "permissions_changed": False,
    }
    if v1_manifest is not None:
        old = old_check(v1_manifest)
        assert old.returncode == 0, old.stderr
        expected = protected(v1_manifest.parent / "readiness.json")
        assert json.loads(old.stdout) == expected
        assert verify(protected(v1_manifest)) == expected
        assert require_sealed(protected(v1_manifest)) == expected
        result["deployed_v1_exact_compatibility"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--v1-manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.manifest, args.v1_manifest)))
