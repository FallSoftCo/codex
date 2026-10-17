"""Verify the configured service launcher against its actual Linux guardian.

A protected unit file alone does not prove which release systemd launched.
This check creates no process, execution admission, or registry record.
"""
import hashlib
from pathlib import Path

from . import service_observer as observer


class RuntimeMismatch(ValueError):
    """The actual guardian does not establish the approved runtime."""


def require_configured_guardian(authority, agent, *, home, service, guardian):
    from .native_release import runtime_spec

    if service.get("NeedDaemonReload") == "yes":
        raise RuntimeMismatch("service-manager-reload-required")
    spec, _, _ = runtime_spec(authority, agent)
    expected = [
        spec["interpreter"], "-m", "lax_connector.connector",
        "--config", str(Path(home) / "connector.json"), "--serve",
    ]
    try:
        with (Path("/proc") / str(guardian["pid"]) / "cmdline").open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise RuntimeMismatch("service-guardian-command-too-large")
        arguments = raw.rstrip(bytes([0])).decode("utf-8").split(chr(0))
        image = Path(spec["interpreter"]).resolve(strict=True).stat()
        if (arguments != expected
                or guardian["executableDevice"] != image.st_dev
                or guardian["executableInode"] != image.st_ino):
            raise RuntimeMismatch("service-runtime-launcher-mismatch")
        if observer.process(guardian["pid"]) != guardian:
            raise RuntimeMismatch("service-guardian-changed")
    except (FileNotFoundError, ProcessLookupError, UnicodeError):
        raise RuntimeMismatch("service-guardian-changed") from None
    return {
        "interpreter": spec["interpreter"],
        "startupArgumentsSha256": hashlib.sha256(raw).hexdigest(),
        "actualGuardianVerified": True,
    }
