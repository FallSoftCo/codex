"""Prepare/apply reviewed protected collaboration setup; never start a service.

Preparation observes only named installation roots. Apply performs explicit CAS
registrations and writes the reviewed configuration/unit; the owner separately
orchestrates drained runtime activation and actual native qualification.
"""

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from uuid import UUID, uuid5

from .collaboration_bridge import (
    IMPLEMENTED_PORTS,
    digest,
    protected_directory,
    require,
)
from .collaboration_capture import administrative_put
from .collaboration_resources import open_root
from .host import request, machine_identity
from .journal import saved
from .service_observer import protected, expected_owner


def protected_tree(path, mode):
    path = Path(path)
    require(path.is_absolute(), "Absolute protected installation path required")
    for parent in reversed((path, *path.parents)):
        if not parent.exists():
            desired_mode = mode if parent == path else 0o755
            parent.mkdir(mode=desired_mode)
            parent.chmod(desired_mode)
        protected_directory(parent)
    return path


def write_original(path, value, mode=0o600):
    path = Path(path)
    data = (
        value
        if isinstance(value, bytes)
        else (json.dumps(value, indent=2) + "\n").encode()
    )
    if path.exists():
        require(
            path.lstat().st_uid == 0
            and stat.S_ISREG(path.lstat().st_mode)
            and not path.lstat().st_mode & 0o022
            and path.read_bytes() == data,
            "Original installed artifact differs; explicit drained upgrade required",
        )
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as file:
        os.fchmod(file.fileno(), mode)
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def adapter_digest():
    package = Path(__file__).parent
    return digest(
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(package.glob("*.py"))
        }
    )


def prepare(spec, destination):
    require(
        os.geteuid() == 0,
        "Verified administrator required for installation preparation",
    )
    require(
        spec["schema"] == "lax-collaboration-install/v1",
        "Explicit installation schema required",
    )
    controller_path = Path(spec["controllerConfig"])
    admin_path = Path(spec["administratorConfig"])
    for path in (controller_path, admin_path):
        protected_directory(path.parent)
    controller, admin = protected(controller_path), protected(admin_path)
    authority, host = [str(UUID(controller[k])) for k in ("authorityId", "hostId")]
    require(
        (admin["authorityId"], admin["hostId"], admin["hollywoodUrl"])
        == (authority, host, controller["hollywoodUrl"]),
        "Administrator and enrolled controller differ",
    )
    require(
        controller["token"] != admin["token"],
        "Separate enrolled-controller and administrative credentials required",
    )
    require(
        controller["machineIdentity"] == machine_identity(),
        "Reviewed controller belongs to another machine",
    )
    out = protected_tree(destination, 0o700)
    runtime = Path(
        spec.get(
            "runtimeDirectory",
            str(Path("/etc/harness") / authority / "collaboration" / host),
        )
    )
    state = Path(
        spec.get(
            "stateDirectory", str(Path(controller["state"]) / "native-collaboration")
        )
    )
    socket_directory = Path(
        spec.get(
            "socketDirectory",
            str(
                Path("/run")
                / (
                    "lax-collaboration-"
                    + authority.replace("-", "")[:8]
                    + "-"
                    + host.replace("-", "")[:8]
                )
            ),
        )
    )
    require(
        socket_directory.is_relative_to(Path("/run"))
        and socket_directory != Path("/run"),
        "Socket lifetime directory must be a named /run path",
    )
    require(
        not any(
            path.is_relative_to(socket_directory)
            for path in (state, runtime, admin_path, controller_path)
        ),
        "Persistent state, descriptor and credentials must remain outside the socket lifetime directory",
    )
    for parent in (
        runtime,
        *runtime.parents,
        socket_directory,
        *socket_directory.parents,
    ):
        if parent.exists():
            require(
                parent.lstat().st_mode & 0o001,
                "Native public runtime path has a private ancestor; choose a separate traversable runtime directory",
            )
    resources = []
    named = {}
    seen = set()
    require(
        1 <= len(spec["resources"]) <= 8 and 1 <= len(spec["agents"]) <= 32,
        "Bounded explicit resources and agents required",
    )
    for item in spec["resources"]:
        require(
            item.get("environmentId", "local") == "local",
            "Remote capture is not implemented",
        )
        root = Path(item["root"])
        require(
            str(root) != "/", "Filesystem-wide resource enrollment is not supported"
        )
        fd = open_root(root)
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        identity = (info.st_dev, info.st_ino)
        require(identity not in seen, "One physical root must retain one namespace")
        for previous in resources:
            old = Path(previous["root"])
            require(
                not root.is_relative_to(old) and not old.is_relative_to(root),
                "Nested physical resources require the existing namespace",
            )
        seen.add(identity)
        environment = digest({"hostId": host, "environmentId": "local"})
        resource_id = str(
            uuid5(UUID(host), "physical-root:" + digest([environment, *identity]))
        )
        value = {
            "hostId": host,
            "environmentId": "local",
            "root": str(root),
            "device": info.st_dev,
            "inode": info.st_ino,
            "workspaceId": resource_id,
        }
        require(item["name"] not in named, "Unique resource names required")
        named[item["name"]] = resource_id
        resources.append(value)
    agents = {}
    for agent, policy in spec["agents"].items():
        agent = str(UUID(agent))
        expected_owner(authority, agent)
        names = policy["resources"]
        default = policy["defaultResource"]
        require(
            names and default in names and len(set(names)) == len(names),
            "Explicit unique agent resource/default policy required",
        )
        agents[agent] = {
            "workspaceIds": [named[name] for name in names],
            "defaultWorkspaceId": named[default],
        }
    automatic = {
        "schema": "lax-automatic-native-capture/v2",
        "administratorConfig": str(admin_path),
        "resources": resources,
    }
    bridge = {
        k: controller[k]
        for k in ("authorityId", "hostId", "machineIdentity", "hollywoodUrl", "token")
    }
    bridge.update(collaborationState=str(state), automaticCapture=automatic)
    descriptor = {
        "schema": "lax-native-collaboration-channel/v1",
        "socket": str(socket_directory / "bridge.sock"),
        "ports": sorted(IMPLEMENTED_PORTS | {"owner-briefing/v1"}),
    }
    adapter = adapter_digest()
    bridge["adapterSha256"] = adapter
    unit_name = (
        "lax-collaboration-"
        + authority.replace("-", "")[:8]
        + "-"
        + host.replace("-", "")[:8]
        + ".service"
    )
    interpreter = Path(spec["interpreter"])
    require(
        interpreter.is_absolute() and interpreter.is_file(),
        "Explicit installed interpreter required",
    )
    for path in (runtime, state, socket_directory, interpreter):
        require(
            path.is_absolute()
            and all(c.isalnum() or c in "/_.-" for c in str(path))
            and not any(part in (".", "..") for part in path.parts),
            "Literal service argument paths required",
        )
    config_path = state / "bridge.json"
    unit = (
        "[Unit]\nDescription=Protected LAX native collaboration\nAfter=network-online.target\n"
        "[Service]\nType=simple\nUser=root\nUMask=0077\n"
        "ExecStart="
        + str(interpreter)
        + " -m lax_connector.collaboration_bridge --config "
        + str(config_path)
        + " --socket "
        + descriptor["socket"]
        + "\n"
        "RuntimeDirectory="
        + socket_directory.relative_to("/run").as_posix()
        + "\nRuntimeDirectoryMode=0755\nRuntimeDirectoryPreserve=no\n"
        "Restart=no\nNoNewPrivileges=yes\nMemoryMax=512M\nCPUQuota=50%\nKillMode=control-group\nTimeoutStopSec=30\n"
    )
    result = {
        "schema": "lax-reviewed-collaboration-setup/v1",
        "authorityId": authority,
        "hostId": host,
        "controllerConfig": str(controller_path),
        "administratorConfig": str(admin_path),
        "runtimeDirectory": str(runtime),
        "socketDirectory": str(socket_directory),
        "stateDirectory": str(state),
        "configPath": str(config_path),
        "unitPath": str(
            Path(spec.get("unitDirectory", "/etc/systemd/system")) / unit_name
        ),
        "adapterSha256": adapter,
        "agentAccessSeedsSha256": digest(agents),
        "enrollmentSha256": digest(automatic),
        "descriptorSha256": digest(descriptor),
        "bridgeConfigurationSha256": digest(bridge),
        "unitSha256": hashlib.sha256(unit.encode()).hexdigest(),
        "modelsStarted": 0,
        "servicesStarted": 0,
        "activation": "Owner-controlled drained activation remains required; no per-turn work/plan seeding",
    }
    for name, value in [
        ("bridge.prepared.json", bridge),
        ("channel.prepared.json", descriptor),
        ("setup.json", result),
        ("agent-access-seeds.json", agents),
    ]:
        write_original(out / name, value)
    write_original(out / "bridge.prepared.service", unit.encode())
    return {
        "prepared": True,
        "manifest": str(out / "setup.json"),
        "modelsStarted": 0,
        "servicesStarted": 0,
    }


def apply(directory):
    require(
        os.geteuid() == 0, "Verified administrator required to apply reviewed setup"
    )
    directory = protected_directory(directory)
    manifest = protected(directory / "setup.json")
    bridge = protected(directory / "bridge.prepared.json")
    descriptor = protected(directory / "channel.prepared.json")
    unit = (directory / "bridge.prepared.service").read_bytes()
    seeds = protected(directory / "agent-access-seeds.json")
    require(digest(seeds) == manifest["agentAccessSeedsSha256"], "Reviewed agent access seeds changed")
    require(
        (digest(bridge), digest(descriptor), hashlib.sha256(unit).hexdigest())
        == (
            manifest["bridgeConfigurationSha256"],
            manifest["descriptorSha256"],
            manifest["unitSha256"],
        ),
        "Reviewed setup artifact changed",
    )
    state = protected_tree(manifest["stateDirectory"], 0o700)
    for name in ("channels", "channels/archive", "commands", "administration", "briefings"):
        protected_tree(state / name, 0o700)
    runtime = protected_tree(manifest["runtimeDirectory"], 0o755)
    sockets = protected_tree(manifest["socketDirectory"], 0o755)
    require(
        all(
            p.lstat().st_mode & 0o001
            for p in (runtime, *runtime.parents, sockets, *sockets.parents)
        ),
        "Public descriptor/socket path is not traversable by native owners",
    )
    admin = protected(Path(manifest["administratorConfig"]))
    administrative = lambda method, route, payload=None: request(
        admin["hollywoodUrl"], admin["token"], method, route, payload
    )
    relay = lambda method, route, payload=None: request(
        bridge["hollywoodUrl"], bridge["token"], method, route, payload
    )
    require(
        adapter_digest() == manifest["adapterSha256"],
        "Installed adapter source changed after reviewed preparation",
    )
    require(
        bridge["machineIdentity"] == machine_identity(),
        "Reviewed setup belongs to another machine",
    )
    host = manifest["hostId"]
    policy = relay("GET", "hosts/" + host + "/admission")["policy"]
    resource_policy = administrative("GET", "hosts/" + host + "/collaboration-bridge")
    from .resource_routing import capabilities
    capabilities(resource_policy)
    existing = resource_policy.get("bridge")
    if existing:
        require(
            existing["state"] == "active"
            and existing["protocol"] == "canonical-edit-plans/v2"
            and str(existing["controller"]) == str(policy["controller"])
            and existing["adapter_sha256"] == manifest["adapterSha256"]
            and existing["enrollment_sha256"] == manifest["enrollmentSha256"],
            "Existing bridge differs or was revoked; explicit drained upgrade required",
        )
    else:
        payload = {
            "operationId": "install-bridge:" + manifest["enrollmentSha256"],
            "revision": 0,
            "controllerId": str(policy["controller"]),
            "state": "active",
            "protocol": "canonical-edit-plans/v2",
            "adapterSha256": manifest["adapterSha256"],
            "enrollmentSha256": manifest["enrollmentSha256"],
        }
        administrative_put(
            state, administrative, "hosts/" + host + "/collaboration-bridge", payload
        )
    resources = []
    for root in bridge["automaticCapture"]["resources"]:
        fd = open_root(root["root"])
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        require(
            (info.st_dev, info.st_ino) == (root["device"], root["inode"]),
            "Reviewed resource inode changed before setup",
        )
        environment = digest({"hostId": host, "environmentId": root["environmentId"]})
        payload = {
            "operationId": "install-root:" + digest(root),
            "revision": 0,
            "state": "active",
            "rootPath": root["root"],
            "environmentSha256": environment,
            "rootIdentitySha256": digest(
                {
                    "hostId": host,
                    "environmentSha256": environment,
                    "device": root["device"],
                    "inode": root["inode"],
                }
            ),
            "registrationSha256": digest(root),
        }
        result = administrative_put(
            state,
            administrative,
            "hosts/" + host + "/physical-workspaces/" + root["workspaceId"],
            payload,
        )
        resources.append({**root, "registryRevision": result["workspace"]["revision"]})
    by_workspace = {root["workspaceId"]: root for root in resources}
    for agent, policy in seeds.items():
        for workspace in policy["workspaceIds"]:
            root = by_workspace[workspace]
            payload = {"operationId": "install-agent-access:" + digest([agent, workspace, root["registryRevision"]]),
                       "revision": 0, "workspaceRevision": root["registryRevision"],
                       "executionHost": host, "state": "active", "canRead": True, "canWrite": True}
            administrative_put(state, administrative,
                "physical-workspaces/" + workspace + "/agent-grants/" + str(UUID(agent)), payload)
    from .resource_routing import seed_defaults
    routing_defaults = seed_defaults(state, administrative, manifest["authorityId"], host, seeds, by_workspace)
    bridge["automaticCapture"]["resources"] = resources
    write_original(Path(manifest["configPath"]), bridge)
    write_original(runtime / "channel.json", descriptor, 0o644)
    unit_path = Path(manifest["unitPath"])
    protected_directory(unit_path.parent)
    write_original(unit_path, unit, 0o644)
    controller_path = Path(manifest["controllerConfig"])
    controller = protected(controller_path)
    old = controller.get("nativeCollaborationCaptureConfig")
    require(
        old in (None, manifest["configPath"]),
        "Existing controller collaboration routing differs",
    )
    if old is None:
        write_original(state / "controller.before-collaboration.json", controller)
        saved(
            controller_path,
            {**controller, "nativeCollaborationCaptureConfig": manifest["configPath"]},
        )
    receipt = {
        "schema": "lax-collaboration-setup-receipt/v1",
        "authorityId": manifest["authorityId"],
        "hostId": host,
        "configPath": manifest["configPath"],
        "channelPath": str(runtime / "channel.json"),
        "unitPath": str(unit_path),
        "configurationSha256": digest(bridge),
        "adapterSha256": manifest["adapterSha256"],
        "servicesStarted": 0,
        "modelsStarted": 0,
        "workerConfigurationChanged": False,
        "resourceDefaults": routing_defaults,
        "activation": "Explicit owner-controlled controller reload and bridge start; preserve live contexts and existing unknown effects",
        "genuineNativeProof": False,
    }
    write_original(state / "setup-receipt.json", receipt)
    return receipt


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--prepare", type=Path)
    actions.add_argument("--apply", type=Path)
    actions.add_argument("--upgrade", type=Path)
    parser.add_argument("--expected-bridge-revision", type=int)
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--expected-unit-sha256")
    parser.add_argument("--expected-descriptor-sha256")
    parser.add_argument("--controller-unit")
    parser.add_argument("--expected-controller-unit-sha256")
    parser.add_argument("--scope-agent-id", action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    upgrade_args = [args.expected_bridge_revision, args.expected_config_sha256,
                    args.expected_unit_sha256, args.expected_descriptor_sha256,
                    args.controller_unit, args.expected_controller_unit_sha256]
    if args.upgrade:
        if not all(upgrade_args) or not args.scope_agent_id or args.output:
            parser.error("Upgrade requires original bridge/config/unit/descriptor CAS values and explicit --scope-agent-id; no output")
        from .collaboration_upgrade import upgrade
        print(json.dumps(upgrade(args.upgrade, expected_revision=args.expected_bridge_revision,
              expected_config_sha256=args.expected_config_sha256, expected_unit_sha256=args.expected_unit_sha256,
              expected_descriptor_sha256=args.expected_descriptor_sha256,
              controller_unit=args.controller_unit, expected_controller_unit_sha256=args.expected_controller_unit_sha256, agents=args.scope_agent_id)))
        return
    if any(value is not None for value in upgrade_args) or args.scope_agent_id:
        parser.error("Upgrade CAS/scope options require --upgrade")
    if args.prepare:
        parser.error(
            "--output required for immutable reviewed preparation"
        ) if not args.output else None
        protected_directory(args.prepare.parent)
        result = prepare(protected(args.prepare), args.output)
    else:
        parser.error("--output only applies to preparation") if args.output else None
        result = apply(args.apply)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
