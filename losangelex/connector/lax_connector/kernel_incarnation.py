"""Fresh systemd/cgroup identities for installed simple purpose guardians.

This reads the manager's root-owned invocation export and the kernel cgroup
attribute, not a cached service status or a model assertion. Service registration
and negative/orphan reconciliation still use the ordinary lifecycle observer.
"""
import configparser
import hashlib
import os
import re
import stat
from pathlib import Path

from . import service_observer as observer


class Unavailable(RuntimeError):
    """No complete live kernel binding; ordinary lifecycle inspection is needed."""


def protected_directory(path):
    for item in (path, *path.parents):
        info = item.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise PermissionError("Kernel identity registry ancestry is not protected")


def invocation(unit):
    if os.geteuid() != 0:
        raise PermissionError("Root kernel observer required")
    if not isinstance(unit, str) or not re.fullmatch(r"lax-[A-Za-z0-9_.@:-]+\.service", unit):
        raise PermissionError("Installed LAX service name required")
    root = Path("/run/systemd/units")
    try:
        protected_directory(root)
    except FileNotFoundError as error:
        raise Unavailable("Systemd invocation export profile unavailable") from error
    path = root / ("invocation:" + unit)
    try:
        info = path.lstat()
        value = os.readlink(path)
    except FileNotFoundError as error:
        raise Unavailable("Current systemd invocation export unavailable") from error
    if not stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise PermissionError("Current systemd invocation export is malformed")
    return value


def guardian(value, binding):
    """Verify the registered live guardian from fresh root/kernel observations."""
    from .purpose_observer import validate
    validate(value)
    purpose = binding.get("purpose")
    if purpose not in value["units"]:
        raise PermissionError("Kernel guardian is not an installed purpose")
    expected = {
        "schema": "lax-service-incarnation/v1",
        "authorityId": value["authorityId"], "hostId": value["hostId"],
        "agentId": value["agentId"], "uid": value["uid"], "home": value["home"],
        "unit": value["units"][purpose], "binary": value["binary"],
        "binaryDevice": value["binaryDevice"], "binaryInode": value["binaryInode"],
        "unitDefinitionDigest": value["unitDefinitionDigests"][value["units"][purpose]],
        "machineIdentity": value["machineIdentity"], "killMode": "mixed",
        "bootId": observer.boot_id(),
    }
    if any(binding.get(key) != item for key, item in expected.items()):
        raise PermissionError("Registered kernel guardian identity differs")
    return _guardian(value, binding, "mixed", [value["interpreter"], "-m",
        "lax_connector.context_runtime", "--config", value["config"], "--purpose", purpose])


def managed_guardian(binding):
    """Verify a legacy connector against protected enrollment and restart approval."""
    from .native_release import runtime_spec
    from .service_restart import validate_approval
    authority, host, agent = (binding[k] for k in ("authorityId", "hostId", "agentId"))
    uid, home, binary = observer.expected_owner(authority, agent)
    spec, receipt, global_agent = runtime_spec(authority, agent)
    baseline = observer.protected(observer.directory(authority, host, agent) / "enrollment.json")
    image = Path(binary).resolve(strict=True).stat()
    unit = receipt["unit"]
    # The original Linux factory receipt omits systemd's default suffix, while
    # enrollment pins the actual manager Id. Normalize ONLY that generated LAX
    # short-name form, without a manager query/alias lookup or receipt rewrite.
    if isinstance(unit, str) and re.fullmatch(r"lax-[A-Za-z0-9_@:-]+", unit):
        unit += ".service"
    expected = {
        "schema": "lax-service-enrollment/v1", "authorityId": authority,
        "hostId": host, "agentId": agent, "uid": uid, "home": str(home),
        "unit": unit, "unitDefinitionDigest": binding["unitDefinitionDigest"],
        "binary": str(Path(binary).resolve()), "binaryDevice": image.st_dev,
        "binaryInode": image.st_ino, "machineIdentity": observer.machine_identity(),
        "killMode": "control-group",
    }
    if baseline != expected or any(binding.get(k) != v for k, v in baseline.items() if k != "schema"):
        raise PermissionError("Registered managed enrollment differs")
    if binding.get("bootId") != observer.boot_id():
        raise Unavailable("Managed guardian belongs to another boot")
    value = {"interpreter": spec["interpreter"]}
    result = _guardian(value, binding, "control-group", [spec["interpreter"], "-m",
        "lax_connector.connector", "--config", str(home / "connector.json"), "--serve"])
    validate_approval(authority, host, agent, baseline, result)
    return result


def _guardian(value, binding, kill_mode, expected_args):
    current = invocation(binding["unit"])
    if current != binding["serviceInvocation"]:
        raise Unavailable("Registered invocation is no longer current")
    unit_path = Path("/etc/systemd/system") / binding["unit"]
    metadata = unit_path.lstat()
    encoded = unit_path.read_bytes()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
            or metadata.st_mode & 0o022
            or hashlib.sha256(encoded).hexdigest() != binding["unitDefinitionDigest"]):
        raise PermissionError("Registered purpose unit changed")
    unit = configparser.ConfigParser(interpolation=None, strict=False)
    unit.read_string(encoded.decode())
    if (unit.get("Service", "Type", fallback="simple") != "simple"
            or unit.get("Service", "PIDFile", fallback="")
            or unit.get("Service", "KillMode", fallback="control-group") != kill_mode):
        raise Unavailable("Kernel guardian path requires the enrolled simple lifecycle")
    group_name = binding["controlGroup"]
    if (not isinstance(group_name, str) or not group_name.startswith("/")
            or ".." in group_name.split("/") or "\x00" in group_name):
        raise PermissionError("Registered control group is malformed")
    group = Path("/sys/fs/cgroup") / group_name.lstrip("/")
    protected_directory(group)
    fd = os.open(group, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        try:
            attribute = os.getxattr(fd, "trusted.invocation_id").decode("ascii")
        except OSError as error:
            raise Unavailable("Trusted cgroup invocation identity unavailable") from error
        if attribute != current:
            raise Unavailable("Kernel and manager invocation identities differ")
        actual = observer.process(binding["guardianPid"])
        image = Path(value["interpreter"]).resolve(strict=True).stat()
        if (actual is None or actual["start"] != binding["guardianStart"]
                or actual["uid"] != binding["uid"]
                or actual["controlGroup"] != group_name
                or (actual["executableDevice"], actual["executableInode"]) !=
                   (image.st_dev, image.st_ino)):
            raise Unavailable("Original purpose guardian is not live")
        root = Path("/proc") / str(actual["pid"])
        args = root.joinpath("cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
        if args != expected_args:
            raise PermissionError("Live guardian launcher differs")
        environment = dict(part.split(b"=", 1) for part in
                           root.joinpath("environ").read_bytes().split(b"\0")
                           if b"=" in part)
        if (environment.get(b"INVOCATION_ID") != current.encode("ascii")
                or environment.get(b"SYSTEMD_EXEC_PID") != str(actual["pid"]).encode("ascii")):
            raise PermissionError("Guardian launch invocation differs")
        if actual["pid"] not in observer.members(group_name):
            raise Unavailable("Original guardian left its registered control group")
        if (invocation(binding["unit"]) != current
                or os.getxattr(fd, "trusted.invocation_id").decode("ascii") != current
                or observer.process(actual["pid"]) != actual):
            raise Unavailable("Guardian incarnation changed during observation")
        return actual
    finally:
        os.close(fd)
