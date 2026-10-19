"""Verify first-start dependencies without launching a model or repairing services."""
import os
import socket
import stat
import struct
import subprocess
from pathlib import Path

from .host import request
from .journal import saved
from .purpose_install import checksum, directory, model_account, protected

SCHEMA = "lax-purpose-readiness/v1"


def verify(value):
    from .purpose_install import canonical
    from .purpose_observer import validate
    from .purpose_environment import checked as checked_environment
    from .environment import snapshot as environment_snapshot
    from .collaboration_bridge import digest, protected_directory
    from .collaboration_resources import open_root

    if os.geteuid() != 0:
        raise PermissionError("Installation administrator required")
    validate(value)
    record = directory(value["authorityId"], value["agentId"])
    spec = protected(record / "intent.json")["spec"]
    config = protected(Path(value["config"]))
    canonical(spec, config)
    files = {value["config"]: value["configSha256"]}
    for unit, expected in value["unitDefinitionDigests"].items():
        path = Path("/etc/systemd/system") / unit
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or checksum(path) != expected:
            raise PermissionError("Installed purpose unit differs")
        files[str(path)] = expected
    # Account identity may remain stable while the provider refreshes its tokens.
    if any(model_account(Path(home) / "auth.json") != value["approvedModelAccountDigest"]
           for home in config["homes"].values()):
        raise PermissionError("Approved purpose model account differs")
    channel = config.get("nativeCollaborationChannel")
    if not channel:
        raise PermissionError("Native collaboration channel is not installed")
    descriptor = protected(Path(channel))
    if descriptor["schema"] != "lax-native-collaboration-channel/v1":
        raise ValueError("Native collaboration descriptor differs")
    files[channel] = checksum(channel)
    sockpath = Path(descriptor["socket"])
    info = sockpath.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
        raise PermissionError("Protected native bridge socket differs")
    protected_directory(sockpath.parent)
    # The socket permits enrolled Unix identities to connect; SO_PEERCRED and
    # protected native capture authenticate them. Its parent must stay protected.
    # A connection with no frame has no command or effect. Check the real local
    # peer rather than treating the existence of a stale socket as health.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
        peer.settimeout(3)
        peer.connect(str(sockpath))
        peer_pid, peer_uid, _ = struct.unpack("3i", peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    bridge_unit = ("lax-collaboration-" + value["authorityId"].replace("-", "")[:8]
                   + "-" + value["hostId"].replace("-", "")[:8] + ".service")
    status = dict(line.split("=", 1) for line in subprocess.check_output(
        ["systemctl", "show", bridge_unit, "-p", "MainPID", "-p", "ActiveState", "-p", "User"],
        text=True).splitlines())
    if peer_uid != 0 or status["ActiveState"] != "active" or int(status["MainPID"]) != peer_pid or status["User"] != "root":
        raise PermissionError("Native bridge peer is not the installed root service")
    host_root = Path("/var/lib/harness") / value["authorityId"] / "hosts" / value["hostId"]
    controller_path = host_root / "controller.json"
    controller = protected(controller_path)
    bridge_path = Path(controller["nativeCollaborationCaptureConfig"])
    bridge = protected(bridge_path)
    if any(bridge[k] != config[k] for k in ("authorityId", "hostId", "hollywoodUrl")):
        raise ValueError("Installed native bridge route differs")
    admin = protected(Path(bridge["automaticCapture"]["administratorConfig"]))
    current = request(config["hollywoodUrl"], admin["token"], "GET",
                      "hosts/" + config["hostId"] + "/collaboration-bridge")["bridge"]
    if not current or current["state"] != "active" or current["protocol"] != "canonical-edit-plans/v2" or current["adapter_sha256"] != bridge["adapterSha256"]:
        raise PermissionError("Canonical native collaboration enrollment differs")
    for path in (controller_path, bridge_path):
        files[str(path)] = checksum(path)
    fd = open_root(config["workspace"])
    try:
        info = os.fstat(fd)
    finally:
        os.close(fd)
    environment = digest({"hostId": config["hostId"], "environmentId": "local"})
    root_identity = digest({"hostId": config["hostId"], "environmentSha256": environment,
                            "device": info.st_dev, "inode": info.st_ino})
    page = request(config["hollywoodUrl"], admin["token"], "GET",
                   "agents/" + config["agentId"] + "/resources?executionHost=" + config["hostId"] + "&limit=8")
    # First setup has its private root. Existing installations with a larger
    # resource catalog follow the same bounded published pagination contract.
    pages = 0
    while True:
        roots = page.get("resources", [])
        matches = [r for r in roots if r.get("workspace", {}).get("root_path") == config["workspace"]]
        if matches:
            root = matches[0]
            break
        cursor = page.get("nextCursor")
        pages += 1
        if not cursor or pages >= 16:
            raise PermissionError("Installed private workspace is not in canonical access")
        page = request(config["hollywoodUrl"], admin["token"], "GET",
                       "agents/" + config["agentId"] + "/resources?executionHost=" + config["hostId"] + "&limit=8&after=" + cursor)
    workspace, grant = root["workspace"], root["grant"]
    if (workspace["root_identity_sha256"] != root_identity or workspace["state"] != "active"
            or grant["state"] != "active" or not grant["can_read"] or not grant["can_write"]
            or grant["principal"] != value["agentId"] or grant["execution_host"] != value["hostId"]):
        raise PermissionError("Current canonical workspace identity/access differs")
    environment = environment_snapshot(value["authorityId"])
    if environment["state"] == "configured":
        env_path = Path("/etc/harness") / value["authorityId"] / "agent-environments" / (value["agentId"] + ".json")
        installed = checked_environment(env_path)
        if (installed["authorityId"], installed["agentId"], installed["uid"], installed["profileSha256"]) != (
                value["authorityId"], value["agentId"], value["uid"], checksum(environment["profileFile"])):
            raise PermissionError("Installed agent environment differs")
        for path, expected in installed["fileHashes"].items():
            info = Path(path).lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or checksum(path) != expected:
                raise PermissionError("Installed agent environment executable differs")
            files[path] = expected
        files[str(env_path)] = checksum(env_path)
        files[environment["profileFile"]] = checksum(environment["profileFile"])
    # Run only local capability checks under the actual service UID. Provider
    # reachability and genuine model execution remain the first-user API proof.
    subprocess.run(["runuser", "-u", value["linuxUser"], "--", value["interpreter"], "-I", "-B", "-c",
        "import os,sys; assert os.geteuid()==int(sys.argv[1]); assert os.access(sys.argv[2],os.R_OK|os.W_OK|os.X_OK)",
        str(value["uid"]), config["workspace"]],check=True,capture_output=True,text=True)
    sudo = subprocess.check_output(["runuser", "-u", value["linuxUser"], "--", "sudo", "-n", "/usr/bin/id", "-u"],text=True).strip()
    if sudo != "0":
        raise PermissionError("Installed administration unavailable")
    return {"schema": SCHEMA, "authorityId": value["authorityId"], "agentId": value["agentId"],
            "hostId": value["hostId"], "configurationSha256": value["configSha256"],
            "dependencyFiles": files, "workspaceIdentitySha256": root_identity,
            "physicalWorkspaceId": workspace["id"], "physicalWorkspaceRevision": workspace["revision"],
            "physicalGrantRevision": grant["revision"],
            "bridgeRevision": current["revision"], "environmentState": environment.get("state", "configured"),
            "sudoVerifiedUid": 0, "modelsStarted": 0, "servicesStarted": 0,
            "meaning": "Local installation and current canonical dependencies verified; genuine model/provider/enterprise delivery remains a separate integration proof."}


def seal(value):
    result = verify(value)
    record = directory(value["authorityId"], value["agentId"])
    path = record / "readiness.json"
    if path.exists() and protected(path) != result:
        raise ValueError("Sealed dependencies changed; explicit setup reconciliation required")
    if not path.exists():
        saved(path, result)
    return result


def require_sealed(value):
    current = verify(value)
    path = directory(value["authorityId"], value["agentId"]) / "readiness.json"
    if not path.exists() or protected(path) != current:
        raise PermissionError("Prepared agent is not sealed against current native dependencies")
    return current

