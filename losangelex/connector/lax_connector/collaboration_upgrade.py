"""Reviewed offline bridge upgrade; preserve all original evidence and stop state.

No service/reload/model/admission action is performed. All bridge consumers must
be explicitly in scope, disabled, stopped, and independently drained. Unknown
original effects remain held; repeated upgrade intents never reapply changes.
"""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

from . import service_observer as observer
from .collaboration_bridge import digest, protected_directory, require
from .collaboration_capture import administrative_put
from .host import request, machine_identity
from .journal import saved
from .native_image_upgrade import (
    _journal_snapshot,
    _open_directory,
    registry_lock,
    require_settled_transition,
)


def require_settled_upgrades(state):
    intents = list((Path(state) / "upgrades").glob("*-intent.json"))
    require(len(intents) <= 128, "Bounded bridge upgrade history required")
    for path in intents:
        value = observer.protected(path)
        result = path.with_name(
            path.name.removesuffix("-intent.json") + "-accepted.json"
        )
        require(
            result.exists(),
            "Original bridge upgrade is unsettled; explicit original-effect reconciliation required",
        )
        accepted = observer.protected(result)
        require(
            accepted.get("state") == "accepted"
            and all(
                accepted.get(key) == entry
                for key, entry in value.items()
                if key != "state"
            ),
            "Original bridge upgrade evidence changed",
        )


def file_sha(path):
    path = Path(path)
    protected_directory(path.parent)
    info = path.lstat()
    require(
        path.is_file()
        and not path.is_symlink()
        and info.st_uid == 0
        and not info.st_mode & 0o022,
        "Protected existing bridge artifact required",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clients(config, state, seeds):
    values = set(config["automaticCapture"].get("agents", {})) | set(seeds)
    for path in (state / "channels").glob("*.json"):
        values.add(observer.protected(path)["sourceBase"]["agentId"])
    root = (
        Path("/var/lib/harness")
        / config["authorityId"]
        / "hosts"
        / config["hostId"]
        / "services"
    )
    if root.exists():
        protected_directory(root)
        values.update(path.name for path in root.iterdir() if path.is_dir())
    require(len(values) <= 256, "Bounded explicit bridge consumer scope required")
    return {str(UUID(value)) for value in values}


def _drain(config, state, agents, relay):
    from .collaboration_resources import open_root

    host, authority = config["hostId"], config["authorityId"]
    after, seen = None, set()
    for _ in range(16):
        page = relay(
            "GET", "hosts/" + host + "/executors" + ("?after=" + after if after else "")
        )
        require(
            not page["executors"], "Bridge host has a nonstopped canonical executor"
        )
        after = page["nextAfter"]
        if not after:
            break
        after = str(UUID(after))
        require(after not in seen, "Executor inspection cursor repeated")
        seen.add(after)
    else:
        require(False, "Bounded executor inspection exhausted")
    snapshots = {}
    for agent in sorted(agents):
        uid, home, binary = observer.expected_owner(authority, agent)
        unit = observer.properties(observer.installed_unit(authority, agent))
        require(
            unit["ActiveState"] in {"inactive", "failed"}
            and int(unit["MainPID"]) == 0
            and (
                not unit["ControlGroup"] or not observer.members(unit["ControlGroup"])
            ),
            "Every scoped bridge consumer must remain stopped and empty",
        )
        local = json.loads((home / "connector.json").read_text())
        require(
            (
                local["agentId"],
                local["hostId"],
                local["hollywoodUrl"],
                local["binary"],
                local["state"],
            )
            == (agent, host, config["hollywoodUrl"], binary, str(home / "state")),
            "Consumer installed identity or paths changed",
        )
        pending = request(
            config["hollywoodUrl"],
            local["token"],
            "GET",
            "connector/pending?hostId=" + host,
        )
        require(
            pending["enabled"] is False
            and pending["busy"] is None,
            "Every scoped placement must stay disabled with no busy work; queued work is preserved",
        )
        fd = open_root(str(home / "state"))
        try:
            from .native_image_upgrade import _json

            names = os.listdir(fd)
            require(len(names) <= 4096, "Bounded local effect inspection required")
            for name in names:
                if name.startswith("effects-") and name.endswith(".json"):
                    effect = _json(fd, name, uid)
                    require(
                        all(
                            step["state"] in {"confirmed", "rejected"}
                            for step in effect["steps"]
                        ),
                        "Original consumer tool effect remains unconfirmed",
                    )
            snapshots[agent] = {
                "unit": unit,
                "definition": observer.unit_definition(unit),
                "journals": _journal_snapshot(fd, uid, authority, host, agent),
            }
        finally:
            os.close(fd)
    for path in (state / "administration").glob("*.json"):
        require(
            observer.protected(path)["state"] in {"accepted", "rejected"},
            "Original administrative bridge effect remains unknown",
        )
    # No unknown bridge HTTP effect is resolved by timeout or by this upgrade.
    permits = {}
    for path in sorted((state / "commands").glob("*.json")):
        value = observer.protected(path)
        if "wire" not in value:
            continue
        require(
            value["state"] in {"completed", "rejected"},
            "Original bridge command is pending/unknown",
        )
        command = value["wire"].get("command", {})
        if value["state"] == "completed" and command.get("action") in {
            "preflight",
            "begin",
            "settle",
        }:
            permits[command["permitId"]] = (
                value["wire"].get("scope"),
                command.get("planId"),
            )
    for permit, (scope, plan) in permits.items():
        if scope == "delivery":
            result = relay("GET", "collaboration/delivery-edits/" + str(UUID(permit)))
            require(
                result["mayApply"] is False and result["effectiveState"] == "settled",
                "Original direct permit remains held/unsettled",
            )
        else:
            result = relay("GET", "collaboration/edit-plans/" + str(UUID(plan)))
            rows = [row for row in result["permits"] if str(row["id"]) == permit]
            require(
                len(rows) == 1 and rows[0]["state"] == "settled",
                "Original planned permit remains held/unsettled",
            )
    return snapshots


def upgrade(
    directory,
    *,
    expected_revision,
    expected_config_sha256,
    expected_unit_sha256,
    expected_descriptor_sha256,
    controller_unit,
    expected_controller_unit_sha256,
    agents,
):
    from .collaboration_install import adapter_digest, write_original

    require(os.geteuid() == 0, "Verified installation administrator required")
    directory = protected_directory(directory)
    manifest = observer.protected(directory / "setup.json")
    prepared = observer.protected(directory / "bridge.prepared.json")
    descriptor = observer.protected(directory / "channel.prepared.json")
    seeds = observer.protected(directory / "agent-access-seeds.json")
    unit_bytes = (directory / "bridge.prepared.service").read_bytes()
    require(
        (
            digest(prepared),
            digest(descriptor),
            digest(seeds),
            hashlib.sha256(unit_bytes).hexdigest(),
        )
        == (
            manifest["bridgeConfigurationSha256"],
            manifest["descriptorSha256"],
            manifest["agentAccessSeedsSha256"],
            manifest["unitSha256"],
        ),
        "Reviewed candidate artifacts changed",
    )
    require(
        adapter_digest() == manifest["adapterSha256"],
        "Installed candidate adapter differs from reviewed source",
    )
    state = protected_directory(manifest["stateDirectory"])
    require_settled_upgrades(state)
    config_path, unit_path = Path(manifest["configPath"]), Path(manifest["unitPath"])
    descriptor_path = Path(manifest["runtimeDirectory"]) / "channel.json"
    for value in (
        expected_config_sha256,
        expected_unit_sha256,
        expected_descriptor_sha256,
        expected_controller_unit_sha256,
    ):
        require(
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value),
            "Explicit original artifact SHA256 required",
        )
    old_hashes = {
        str(config_path): expected_config_sha256,
        str(unit_path): expected_unit_sha256,
        str(descriptor_path): expected_descriptor_sha256,
    }
    require(
        all(file_sha(Path(path)) == checksum for path, checksum in old_hashes.items()),
        "Original bridge artifact CAS changed",
    )
    require(
        isinstance(controller_unit, str)
        and controller_unit.endswith(".service")
        and all(c.isalnum() or c in "_.-@" for c in controller_unit),
        "Explicit installed controller unit required",
    )
    controller = observer.protected(Path(manifest["controllerConfig"]))
    controller_sha = file_sha(Path(manifest["controllerConfig"]))
    old = observer.protected(config_path)
    old_descriptor = observer.protected(descriptor_path)
    require(
        all(
            old[key] == prepared[key]
            for key in (
                "authorityId",
                "hostId",
                "machineIdentity",
                "hollywoodUrl",
                "token",
                "collaborationState",
            )
        )
        and old["machineIdentity"] == machine_identity()
        and old_descriptor["socket"] == descriptor["socket"],
        "Bridge upgrade cannot move identity, state, credential or socket",
    )

    require(
        all(
            controller[key] == old[key]
            for key in (
                "authorityId",
                "hostId",
                "machineIdentity",
                "hollywoodUrl",
                "token",
            )
        )
        and controller["nativeCollaborationCaptureConfig"] == str(config_path),
        "Original installed controller route differs",
    )

    def root_identity(root):
        return {
            key: root[key]
            for key in (
                "hostId",
                "environmentId",
                "root",
                "device",
                "inode",
                "workspaceId",
            )
        }

    old_roots = {
        root["workspaceId"]: root for root in old["automaticCapture"]["resources"]
    }
    require(
        {key: root_identity(value) for key, value in old_roots.items()}
        == {
            root["workspaceId"]: root_identity(root)
            for root in prepared["automaticCapture"]["resources"]
        },
        "Bridge upgrade preserves original physical resource identities",
    )
    from .collaboration_resources import open_root

    for root in old_roots.values():
        fd = open_root(root["root"])
        try:
            info = os.fstat(fd)
            require(
                (info.st_dev, info.st_ino) == (root["device"], root["inode"]),
                "Original physical root changed",
            )
        finally:
            os.close(fd)
    agents = {str(UUID(value)) for value in agents}
    require(
        agents and _clients(old, state, seeds) <= agents,
        "All affected consumers need explicit upgrade/drain scope",
    )
    admin = observer.protected(Path(manifest["administratorConfig"]))
    require(
        (admin["authorityId"], admin["hostId"], admin["hollywoodUrl"])
        == (old["authorityId"], old["hostId"], old["hollywoodUrl"]),
        "Upgrade administrative scope changed",
    )

    def administrative(method, route, body=None):
        return request(admin["hollywoodUrl"], admin["token"], method, route, body)

    def relay(method, route, body=None):
        return request(old["hollywoodUrl"], old["token"], method, route, body)

    operation = digest(
        [
            expected_revision,
            old_hashes,
            manifest["adapterSha256"],
            manifest["enrollmentSha256"],
            sorted(agents),
            controller_unit,
            expected_controller_unit_sha256,
            controller_sha,
        ]
    )
    upgrades = state / "upgrades"
    upgrades.mkdir(mode=0o700, exist_ok=True)
    protected_directory(upgrades)
    intent_path, result_path = (
        upgrades / (operation + "-intent.json"),
        upgrades / (operation + "-accepted.json"),
    )
    with contextlib.ExitStack() as stack:
        lock = os.open(
            state / "bridge-upgrade.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        stack.callback(os.close, lock)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(
            not intent_path.exists() and not result_path.exists(),
            "Original bridge upgrade exists; inspect without replay",
        )
        require_settled_upgrades(state)
        controller_state = protected_directory(controller["state"])
        controller_lock = os.open(
            controller_state / "controller.lock", os.O_RDWR | os.O_NOFOLLOW
        )
        stack.callback(os.close, controller_lock)
        fcntl.flock(controller_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        controller_info = observer.properties(controller_unit)
        require(
            controller_info["ActiveState"] in {"inactive", "failed"}
            and int(controller_info["MainPID"]) == 0
            and controller_info["User"] in {"", "0", "root"}
            and (
                not controller_info["ControlGroup"]
                or not observer.members(controller_info["ControlGroup"])
            )
            and observer.unit_definition(controller_info)
            == expected_controller_unit_sha256,
            "Original controller must remain stopped with reviewed definition and empty cgroup",
        )
        controller_definition = Path(controller_info["FragmentPath"]).read_text()
        require(
            len(controller_definition) <= 65536
            and " --serve " + manifest["controllerConfig"] in controller_definition,
            "Reviewed controller unit does not serve the original configuration",
        )
        for agent in sorted(agents):
            root_fd = stack.enter_context(
                registry_lock(
                    observer.directory(old["authorityId"], old["hostId"], agent)
                )
            )
            require_settled_transition(root_fd)
            uid, home, _ = observer.expected_owner(old["authorityId"], agent)
            fd = _open_directory(home / "state", uid)
            stack.callback(os.close, fd)
            lock = os.open("connector.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, lock)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        bridge_info = observer.properties(unit_path.name)
        require(
            bridge_info["ActiveState"] in {"inactive", "failed"}
            and int(bridge_info["MainPID"]) == 0
            and (
                not bridge_info["ControlGroup"]
                or not observer.members(bridge_info["ControlGroup"])
            ),
            "Reviewed bridge service must remain stopped and empty",
        )
        require(
            observer.unit_definition(bridge_info) == expected_unit_sha256,
            "Installed bridge definition differs",
        )
        snapshots = _drain(old, state, agents, relay)
        current = administrative(
            "GET", "hosts/" + old["hostId"] + "/collaboration-bridge"
        )
        from .resource_routing import capabilities
        from .placement_control import capabilities as placement_capabilities

        placement_capabilities(capabilities(current))
        policy = current["bridge"]
        require(
            policy
            and policy["state"] == "active"
            and policy["protocol"] == "canonical-edit-plans/v2"
            and policy["revision"] == expected_revision
            and policy["adapter_sha256"] == old["adapterSha256"],
            "Original canonical bridge revision or adapter changed",
        )
        new = json.loads(json.dumps(prepared))
        for root in new["automaticCapture"]["resources"]:
            root["registryRevision"] = old_roots[root["workspaceId"]][
                "registryRevision"
            ]
        archive = upgrades / (operation + "-before")
        archive.mkdir(mode=0o700)
        for name, path in (
            ("bridge.json", config_path),
            ("bridge.service", unit_path),
            ("channel.json", descriptor_path),
            ("setup-receipt.json", state / "setup-receipt.json"),
        ):
            write_original(archive / name, path.read_bytes())
        intent = {
            "schema": "lax-drained-bridge-upgrade/v1",
            "state": "intent",
            "operationId": operation,
            "authorityId": old["authorityId"],
            "hostId": old["hostId"],
            "agents": sorted(agents),
            "originalArtifactHashes": old_hashes,
            "controllerUnit": controller_unit,
            "controllerUnitSha256": expected_controller_unit_sha256,
            "controllerConfigSha256": controller_sha,
            "expectedBridgeRevision": expected_revision,
            "newAdapterSha256": manifest["adapterSha256"],
            "newEnrollmentSha256": manifest["enrollmentSha256"],
            "newConfigurationSha256": digest(new),
            "beforeArchive": str(archive),
            "modelsStarted": 0,
            "servicesStarted": 0,
            "placementsChanged": False,
            "unknownEffectsCleared": False,
        }
        write_original(intent_path, intent)
        require(
            _drain(old, state, agents, relay) == snapshots,
            "Consumer drainage changed during review",
        )
        require(
            observer.properties(controller_unit) == controller_info
            and file_sha(Path(manifest["controllerConfig"])) == controller_sha,
            "Original controller changed before canonical bridge CAS",
        )
        payload = {
            "operationId": "upgrade-bridge:" + operation,
            "revision": expected_revision,
            "controllerId": str(policy["controller"]),
            "state": "active",
            "protocol": "canonical-edit-plans/v2",
            "adapterSha256": manifest["adapterSha256"],
            "enrollmentSha256": manifest["enrollmentSha256"],
        }
        canonical = administrative_put(
            state,
            administrative,
            "hosts/" + old["hostId"] + "/collaboration-bridge",
            payload,
        )
        require(
            _drain(old, state, agents, relay) == snapshots,
            "Drain changed after canonical CAS; intent remains held",
        )
        require(
            observer.properties(unit_path.name) == bridge_info,
            "Bridge service changed after canonical CAS",
        )
        require(
            all(
                file_sha(Path(path)) == checksum
                for path, checksum in old_hashes.items()
            ),
            "Local artifact CAS changed after canonical transition; original intent held",
        )
        require(
            observer.properties(controller_unit) == controller_info
            and file_sha(Path(manifest["controllerConfig"])) == controller_sha,
            "Original controller changed after canonical bridge CAS; intent held",
        )
        # Root orchestrates the matching connector rollout and reload/start separately.
        saved(config_path, new)
        saved(descriptor_path, descriptor)
        descriptor_path.chmod(0o644)
        temporary = unit_path.with_name(unit_path.name + ".reviewed-upgrade")
        write_original(temporary, unit_bytes, 0o644)
        temporary.replace(unit_path)
        directory_fd = os.open(unit_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        for name in ("briefings",):
            (state / name).mkdir(mode=0o700, exist_ok=True)
            protected_directory(state / name)
        # Initial access seeds are immutable reviewed intent, never a runtime whitelist.
        for agent, seed in seeds.items():
            for workspace in seed["workspaceIds"]:
                root = old_roots[workspace]
                grant = {
                    "operationId": "install-agent-access:"
                    + digest([agent, workspace, root["registryRevision"]]),
                    "revision": 0,
                    "workspaceRevision": root["registryRevision"],
                    "executionHost": old["hostId"],
                    "state": "active",
                    "canRead": True,
                    "canWrite": True,
                }
                administrative_put(
                    state,
                    administrative,
                    "physical-workspaces/" + workspace + "/agent-grants/" + agent,
                    grant,
                )
        from .resource_routing import seed_defaults

        routing_defaults = seed_defaults(
            state, administrative, old["authorityId"], old["hostId"], seeds, old_roots
        )
        result = {
            **intent,
            "state": "accepted",
            "canonicalTransition": canonical,
            "configurationSha256": digest(new),
            "activationRequired": True,
            "resourceDefaults": routing_defaults,
            "genuineNativeProof": False,
            "servicesReloaded": False,
        }
        write_original(result_path, result)
        return result
