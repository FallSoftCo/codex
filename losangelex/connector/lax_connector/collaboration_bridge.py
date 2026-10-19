"""Protected native collaboration RPC; starts only through explicit administrator CLI.

The kernel peer must be the registered native process, not its connector or shell.
Identity comes from root-protected captured channels and current server/executor
facts. Model arguments contain intent only. All responses/replays remain receipts;
only an original successful begin response can carry a one-shot mutation grant.
"""
import argparse
import hashlib
import json
import os
import socket
import stat
import struct
import urllib.error
import urllib.parse
from pathlib import Path
from uuid import UUID, uuid5

from .host import request
from .journal import saved
from .collaboration_resources import revision, open_root, verify_native_path
from .service_observer import protected, process, observe, expected_owner

FRAME_LIMIT = 1024 * 1024
RPC_FIELDS = {"schema", "threadId", "turnId", "callId", "tool", "port", "arguments", "evidence"}
SOURCE_FIELDS = {"schema", "authorityId", "agentId", "hostId", "deliveryId", "claimId", "generation", "requestId", "nativeThread", "nativeTurn", "roleRevision", "contextId", "nativeGoalId"}
PLAN_ACTIONS = {"propose", "revise", "consent", "revoke", "reconcile", "withdraw"}
PATCH_PORTS = {"patch-preflight", "patch-begin", "patch-settle"}
IMPLEMENTED_PORTS = {"coordination", "edit-plans", *PATCH_PORTS}


class Held(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise Held(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def strict_json(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise Held("Duplicate native frame field")
            obj[key] = value
        return obj
    return json.loads(raw, object_pairs_hook=unique)


def protected_directory(path):
    path = Path(path)
    require(path.is_absolute(), "Absolute protected state path required")
    for parent in (path, *path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "Administrator-owned nonsymlink state ancestry required")
    return path


def canonical_relative(value):
    import unicodedata
    require(isinstance(value, str) and value and len(value.encode()) <= 1024
            and not value.startswith("/") and "\\" not in value and ":" not in value
            and all(part not in ("", ".", "..") for part in value.split("/"))
            and unicodedata.normalize("NFC", value) == value
            and not any(unicodedata.category(c).startswith("C") for c in value),
            "Normalized literal relative path required")
    return value


def local_uri(value):
    parsed = urllib.parse.urlsplit(value)
    require(parsed.scheme == "file" and parsed.netloc in ("", "localhost")
            and not parsed.query and not parsed.fragment, "Registered local file URI required")
    path = Path(urllib.parse.unquote(parsed.path))
    require(path.is_absolute(), "Native file URI must be absolute")
    return path


def read_file(root, relative, root_identity=None):
    """Open every component without following links; preserve absence distinctly."""
    relative = canonical_relative(relative)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = open_root(root)
    if root_identity is not None:
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != tuple(root_identity):
            os.close(fd)
            raise Held("Opened physical root incarnation changed")
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            try:
                nxt = os.open(part, flags | os.O_DIRECTORY, dir_fd=fd)
            except FileNotFoundError:
                return {"relativePath": relative, "sha256": "absent", "size": 0}
            os.close(fd)
            fd = nxt
        try:
            child = os.open(parts[-1], flags, dir_fd=fd)
        except FileNotFoundError:
            return {"relativePath": relative, "sha256": "absent", "size": 0}
        try:
            info = os.fstat(child)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 16 * 1024 * 1024,
                    "Bounded regular patch target required")
            h = hashlib.sha256()
            total = 0
            while chunk := os.read(child, 65536):
                total += len(chunk)
                require(total <= 16 * 1024 * 1024, "Patch target grew beyond bound")
                h.update(chunk)
            after = os.fstat(child)
            require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    and total == info.st_size, "Patch target changed during observation")
            return {"relativePath": relative, "sha256": h.hexdigest(), "size": total}
        finally:
            os.close(child)
    finally:
        os.close(fd)


class Bridge:
    def __init__(self, configuration):
        require(os.geteuid() == 0, "Protected native bridge requires administrator")
        protected_directory(Path(configuration).parent)
        self.config = protected(Path(configuration))
        self.state = protected_directory(self.config["collaborationState"])
        from .collaboration_upgrade import require_settled_upgrades
        require_settled_upgrades(self.state)
        protected_directory(self.state / "channels")
        protected_directory(self.state / "commands")
        self.http = lambda method, route, body=None: request(
            self.config["hollywoodUrl"], self.config["token"], method, route, body)
        if self.config.get("adapterSha256"):
            from .collaboration_install import adapter_digest
            require(self.config["adapterSha256"]==adapter_digest(), "Installed protected adapter source differs from reviewed setup")

    def captured(self, peer, frame):
        require(type(peer[0]) is int and peer[0] > 1, "Kernel peer PID required")
        require(set(frame) == RPC_FIELDS and frame["schema"] == "lax-native-collaboration-rpc/v1",
                "Exact captured native RPC frame required")
        for key in ("threadId", "turnId", "callId", "tool", "port"):
            require(isinstance(frame[key], str) and 1 <= len(frame[key]) <= 256, "Bounded native call identity required")
        if self.config.get("automaticCapture"):
            from .collaboration_capture import AutomaticCapture
            AutomaticCapture(self).ensure(peer, frame)
        actual = process(peer[0])
        require(actual and actual["uid"] == peer[1], "Kernel peer incarnation vanished")
        channels = list((self.state / "channels").glob("*.json"))
        require(len(channels) <= 256, "Protected channel registry exceeds bound")
        found = []
        for path in channels:
            record = protected(path)
            if (record["native"]["pid"] == peer[0] and record["native"].get("start") == actual["start"]
                    and record["sourceBase"]["nativeThread"] == frame["threadId"]
                    and record["sourceBase"]["nativeTurn"] == frame["turnId"]):
                found.append(record)
        require(len(found) == 1, "Peer is not one exact captured native channel")
        record = found[0]
        physical = {}
        for channel_path in channels:
            for root in protected(channel_path).get("resources", []):
                identity = (root["hostId"], root["device"], root["inode"])
                prior = physical.setdefault(identity, root["workspaceId"])
                require(prior == root["workspaceId"], "One physical root has conflicting private-context namespaces")
        require(record["schema"] == "lax-captured-native-channel/v1", "Captured channel schema differs")
        base = record["sourceBase"]
        fields = SOURCE_FIELDS | {"executionScopeId","executorId"} if base["schema"]=="hollywood-native-source/v3" else SOURCE_FIELDS
        require(set(base) == fields and base["schema"] in {"hollywood-native-source/v2","hollywood-native-source/v3"}
                and base["authorityId"] == self.config["authorityId"]
                and base["hostId"] == self.config["hostId"]
                and (base["nativeGoalId"] is None or isinstance(base["nativeGoalId"], str)), "Protected canonical source differs")
        require((frame["threadId"], frame["turnId"]) == (base["nativeThread"], base["nativeTurn"]),
                "Actual native turn/context differs from captured source")
        require(all(actual.get(k) == record["native"].get(k) for k in (
            "pid", "start", "uid", "controlGroup", "executableDevice", "executableInode")),
            "Native peer PID/start/executable/cgroup changed")
        uid, _, _ = expected_owner(base["authorityId"], base["agentId"])
        require(uid == peer[1], "Native peer differs from protected NSS owner")
        value = self.http("GET", "executors/" + str(UUID(record["executorId"])))
        row = value["executor"]
        require(value["deliveryState"] == "running" and value["currentDeliveryGeneration"] == base["generation"]
                and row["launch_phase"] == "attached" and row["state"] == "live"
                and str(row["agent"]) == base["agentId"] and str(row["delivery"]) == base["deliveryId"]
                and row["claim_id"] == base["claimId"] and str(row["host"]) == base["hostId"]
                and row["descriptor_digest"] == record["descriptorDigest"], "Current executor source no longer admits effects")
        descriptor = row["descriptor"]
        require((descriptor["nativePid"], descriptor["nativeStart"]) == (peer[0], actual["start"]),
                "Native socket is not attached executor process")
        from .purpose_observer import observe as purpose_observe
        fact = purpose_observe(self.config, row) or observe(self.config, row)
        require(fact["state"] == "live" and fact["evidence"]["serviceBindingDigest"] == record["serviceBindingDigest"],
                "Independent protected service binding unavailable")
        policy = self.http("GET", "hosts/" + base["hostId"] + "/collaboration-bridge")
        require(policy["bridge"] and policy["bridge"]["state"] == "active"
                and policy["bridge"]["revision"] == record["bridgeRevision"], "Bridge enrollment changed")
        source = {**base, "callId": frame["callId"], "tool": frame["tool"],
                  "argumentsDigest": hashlib.sha256(json.dumps([frame["tool"], frame["arguments"]], sort_keys=True).encode()).hexdigest()}
        return record, source, policy

    def attestation(self, record, body, root, paths):
        require(root is not None, "Actual captured physical environment/root required")
        require(root["hostId"] == self.config["hostId"], "Remote physical target observation is not implemented")
        info = Path(root["root"]).lstat()
        require(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (root["device"], root["inode"]), "Registered root handle changed")
        environment_sha = digest({"hostId": root["hostId"], "environmentId": root["environmentId"]})
        identity_sha = digest({"hostId": root["hostId"], "environmentSha256": environment_sha, "device": info.st_dev, "inode": info.st_ino})
        if body.get("scope") == "delivery":
            require(record.get("scope") == "delivery",
                    "Captured delivery scope required for direct target observation")
            registry = self.http("GET", "collaboration/delivery-targets/" + str(UUID(body["source"]["deliveryId"])))
            require(registry["schema"] == "hollywood-agent-physical-target-registry/v1"
                    and str(registry["deliveryId"]) == body["source"]["deliveryId"]
                    and str(registry["principalId"]) == body["source"]["agentId"],
                    "Direct target registry belongs to another captured execution")
        else:
            registry = self.http("GET", "collaboration/physical-targets/" + str(UUID(body["command"]["workId"])))
            require(registry["workRevision"] == body["command"]["workRevision"], "Current resource work revision changed")
        matches = [row for row in registry["targets"] if str(row["id"]) == root["workspaceId"]]
        require(len(matches) == 1, "Physical root has no current explicit work grant")
        registered = matches[0]
        if body.get("scope") == "delivery":
            require(registered["grant_revision"] == root["agentGrantRevision"]
                    and registered["revision"] == root["registryRevision"]
                    and registered["state"] == "active" and registered["grant_state"] == "active"
                    and registered["can_read"] is True and registered["can_write"] is True
                    and str(registered["execution_host"]) == self.config["hostId"],
                    "Captured agent resource authority/revision changed")
        require(registered["root_path"] == root["root"] and str(registered["host"]) == root["hostId"]
                and registered["environment_sha256"] == environment_sha and registered["root_identity_sha256"] == identity_sha,
                "Server registration differs from independently observed physical root/environment")
        resolved = []
        for relative in sorted(set(paths)):
            relative = canonical_relative(relative)
            verify_native_path(root, relative, record["native"]["pid"])
            read_file(root["root"], relative, (root["device"], root["inode"]))  # Actual no-symlink traversal, including explicit absence.
            resolved.append({"relativePath": relative, "resolvedPath": str(Path(root["root"]) / relative)})
        return {"schema": "hollywood-physical-target/v1", "workspaceId": root["workspaceId"],
                "workspaceRevision": registered["revision"], "grantRevision": registered["grant_revision"],
                "environmentSha256": environment_sha, "rootIdentitySha256": identity_sha,
                "resolution": "beneath-no-symlinks/v1", "actionDigest": digest(body), "paths": resolved}

    def relay(self, record, source, port, command, root=None, paths=()):
        action = command["action"]
        operation = "native-collaboration:" + digest([source["agentId"], source["nativeThread"], source["callId"], port, action])
        route = "collaboration/path-claims" if port == "coordination" else "collaboration/edit-plans"
        body = {"operationId": operation, "bridgeRevision": record["bridgeRevision"], "source": source,
                "executorId": record["executorId"], "descriptorDigest": record["descriptorDigest"],
                "serviceBindingDigest": record["serviceBindingDigest"], "channel": "captured-app-server-rpc/v1",
                "command": command}
        if port in PATCH_PORTS and "planId" not in command and record.get("scope") == "delivery":
            from .delivery_edit import SCHEMA, normalized_envelope
            route = "collaboration/delivery-edits"
            body = normalized_envelope({**body, "schema": SCHEMA, "scope": "delivery"})
        body["target"] = self.attestation(record, body, root, paths)
        if body.get("scope") == "delivery":
            require(len(json.dumps(body).encode()) <= 16000,
                    "Delivery edit envelope exceeds exact request bound")
        fingerprint = digest(body)
        path = self.state / "commands" / (digest(operation) + ".json")
        if path.exists():
            old = protected(path)
            require(old["fingerprint"] == fingerprint, "Original native operation payload changed")
            if old["state"] in ("pending", "unknown"):
                receipt = self.http("GET", "collaboration/commands/" + source["agentId"] + "/" + urllib.parse.quote(operation, safe=""))
                result = receipt.get("acceptedResult") or receipt.get("accepted_result")
                require(result is not None, "Original effect outcome still unknown; do not POST again")
                return {"receipt": result, "admission": None, "replayed": True}
            require(old["state"] == "completed", "Original native operation is held/rejected")
            return {"receipt": old["result"].get("receipt", old["result"]), "admission": None, "replayed": True}
        saved(path, {"state": "pending", "fingerprint": fingerprint, "wire": body})
        try:
            result = self.http("POST", route, body)
        except urllib.error.HTTPError as error:
            if error.code in (400, 403, 409):
                detail=error.read(4096).decode(errors="replace")
                saved(path, {"state": "rejected", "fingerprint": fingerprint, "wire": body,
                    "status": error.code, "rejection":detail,
                    "phase":action,"originalPostConfirmedRejected":True})
                raise Held(
                    f"Canonical {action} request rejected HTTP{error.code}; "
                    f"original operation {operation}. Inspect lax_native_edit_status "
                    "for its protected receipt; no automatic retry."
                ) from None
            raise
        except Exception:
            saved(path, {"state": "unknown", "fingerprint": fingerprint, "wire": body})
            raise
        saved(path, {"state": "completed", "fingerprint": fingerprint, "wire": body, "result": result})
        if action == "begin":
            require(result.get("replayed") is False and result.get("admission", {}).get("mayApply") is True,
                    "Original one-shot mutation grant unavailable")
        return result

    def briefing_sequence(self, record):
        if self.config.get("automaticCapture", {}).get("schema") == "lax-automatic-native-capture/v2":
            from .owner_briefing import sequence
            return sequence(self, record)
        from .delivery_edit import briefing_sequence
        return briefing_sequence(record)

    def plan_pointer(self, record, root):
        return self.state / "commands" / ("plan-" + digest([record["sourceBase"]["agentId"], record["work"]["id"], root["workspaceId"]]) + ".json")

    def resource(self, record, evidence):
        require(isinstance(evidence, dict) and set(evidence) <= {"environmentId", "files", "permitId", "outcome", "originTool"},
                "Typed native patch evidence required")
        require(1 <= len(evidence.get("files", [])) <= 8, "Atomic bounded all-file patch scope required")
        selected = []
        observations = []
        for item in evidence["files"]:
            require(set(item) == {"pathUri", "beforeSha256", "beforeSize", "afterSha256", "afterSize"}, "Exact native patch file evidence required")
            path = local_uri(item["pathUri"])
            roots = [root for root in record["resources"] if root["environmentId"] == evidence["environmentId"]
                     and path.is_relative_to(Path(root["root"]))]
            require(len(roots) == 1, "Native file has no unique authorized physical root mapping")
            root = roots[0]
            info = Path(root["root"]).lstat()
            require(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (root["device"], root["inode"]),
                    "Registered physical root inode changed")
            relative = canonical_relative(path.relative_to(root["root"]).as_posix())
            selected.append(root)
            observations.append(read_file(root["root"], relative, (root["device"], root["inode"])))
        require(all(root == selected[0] for root in selected), "Cross-root atomic mutation requires explicit supported mapping")
        require(len({x["relativePath"] for x in observations}) == len(observations), "Duplicate physical patch target")
        return selected[0], observations

    def patch(self, record, source, frame):
        require(source["tool"] == "apply_patch" and isinstance(frame["arguments"], str), "Real native apply_patch callback required")
        if record.get("scope") == "delivery":
            from .work_delivery import planned_patch
            if not planned_patch(self, record, source, frame):
                from .delivery_edit import patch
                return patch(self, record, source, frame)
        require(record.get("work"), "Captured structured work required for planned patch semantics")
        root, observed = self.resource(record, frame["evidence"])
        # Stable context IDs are not physical edited-resource IDs. Never silently conflate them.
        pointer = protected(self.plan_pointer(record, root))
        plan = self.http("GET", "collaboration/edit-plans/" + str(UUID(pointer["planId"])))
        require(str(plan["plan"]["host"]) == root["hostId"]
                and str(plan["plan"]["workspace_id"]) == root["workspaceId"],
                "Server physical edited-resource namespace differs; never substitute private context identity")
        require(revision(root["root"]) == plan["manifest"]["sourceRevision"], "Actual registered checkout revision differs from consent")
        proposed = {canonical_relative(Path(local_uri(item["pathUri"])).relative_to(root["root"]).as_posix()): item
                    for item in frame["evidence"]["files"]}
        require(set(proposed) == {item["relativePath"] for item in plan["manifest"]["files"]}, "Native patch file set differs from consented manifest")
        for item in plan["manifest"]["files"]:
            require(all(proposed[item["relativePath"]][key] == item[key] for key in ("beforeSha256", "beforeSize", "afterSha256", "afterSize")),
                    "Native verified patch target differs from consented before/after bytes")
        require(str(plan["plan"]["integrator_work"]) == record["work"]["id"], "Current work is not plan integrator")
        work = record["work"]
        phase = frame["port"]
        key = self.state / "commands" / ("permit-" + digest([source["nativeThread"], source["callId"]]) + ".json")
        original = protected(key) if phase != "patch-preflight" else None
        sequence = (work["briefingSequence"] if "briefingSequence" in work else self.briefing_sequence(record)) if original is None else original.get("briefingSequence", work.get("briefingSequence"))
        require(type(sequence) is int and sequence >= 0, "Original planned briefing watermark required")
        common = {"planId": str(plan["plan"]["id"]), "planRevision": plan["plan"]["revision"],
                  "workId": work["id"], "workRevision": work["revision"],
                  "briefingSequence": sequence, "note": "Actual protected native patch phase",
                  "patchSha256": hashlib.sha256(frame["arguments"].encode()).hexdigest(),
                  "sourceRevision": plan["manifest"]["sourceRevision"], "filesObserved": observed}
        if phase == "patch-preflight":
            require(not key.exists(), "Original patch already has a permit/unknown outcome")
            command = {**common, "action": "preflight", "permitId": str(uuid5(UUID(record["executorId"]), source["callId"])),
                       "manifestSha256": plan["manifestSha256"], "consentSetDigest": plan["consentSetDigest"], "leaseSeconds": 15}
            result = self.relay(record, source, phase, command, root, [item["relativePath"] for item in observed])
            saved(key, {"schema": "lax-original-patch-permit/v1", "planId": common["planId"], "permitId": command["permitId"],
                        "permitRevision": 1, "briefingSequence": sequence, "patchSha256": common["patchSha256"], "source": source})
            return result
        original = protected(key)
        require(original["source"] == source and original["patchSha256"] == common["patchSha256"], "Original native patch source changed")
        command = {**common, "action": "begin" if phase == "patch-begin" else "settle", "permitId": original["permitId"],
                   "permitRevision": original["permitRevision"]}
        if phase == "patch-settle":
            command["outcome"] = frame["evidence"]["outcome"]
        result = self.relay(record, source, phase, command, root, [item["relativePath"] for item in observed])
        if phase == "patch-begin":
            admission = result.get("admission")
            require(admission and admission["mayApply"] is True, "Receipt is not mutation authority")
            original["permitRevision"] = admission["permitRevision"]
            saved(key, original)
        if phase == "patch-settle":
            snapshot = self.http("GET", "collaboration/edit-plans/" + common["planId"])
            permits = [row for row in snapshot["permits"] if str(row["id"]) == original["permitId"]]
            result["settlementState"] = permits[0]["state"] if len(permits) == 1 else "held"
        return result

    def handle(self, peer, frame):
        record, source, policy = self.captured(peer, frame)
        port = frame["port"]
        require(port in record["ports"], "Native port is not enrolled")
        if port in PATCH_PORTS:
            require(policy.get("patchPermits") is True and policy.get("physicalTargets") is True, "Canonical mutation permits unavailable")
            if record.get("scope") == "delivery":
                require(self.config.get("automaticCapture", {}).get("schema") == "lax-automatic-native-capture/v2"
                        and policy.get("deliveryEdits") is True
                        and policy.get("deliveryEditSchema") == "canonical-delivery-edits/v1",
                        "Canonical delivery edit protocol unavailable; no legacy fallback")
                from .work_delivery import capability
                capability(record.get("work"), policy)
            result = self.patch(record, source, frame)
        else:
            arguments = frame["arguments"]
            require(isinstance(arguments, dict) and set(arguments) == {"command"}
                    and isinstance(frame["evidence"], dict) and set(frame["evidence"]) == {"environmentId", "cwd"},
                    "Native arguments contain command intent; environment comes from captured StepContext")
            command = arguments["command"]
            if port == "edit-plans":
                require(source["tool"] == "collaborative_edit_plan" and command.get("action") in PLAN_ACTIONS
                        and policy.get("editPlans") is True, "Canonical edit-plan port unavailable")
            else:
                require(port == "coordination" and source["tool"] == "coordination_act", "Unimplemented canonical native port")
            require(policy.get("physicalTargets") is True and policy["bridge"]["protocol"] == "canonical-edit-plans/v2", "Registered physical-target protocol unavailable")
            require(record.get("work") is not None and command["workId"] == record["work"]["id"],
                    "Planned native intent requires captured admitted work; ordinary patches use delivery scope")
            if self.config.get("automaticCapture", {}).get("schema") == "lax-automatic-native-capture/v2":
                from .resource_routing import intent_root
                root = intent_root(self, record, policy, frame["evidence"]["environmentId"])
            else:
                cwd = local_uri(frame["evidence"]["cwd"])
                roots = [root for root in record["resources"] if root["environmentId"] == frame["evidence"]["environmentId"]
                         and cwd.is_relative_to(Path(root["root"]))]
                if not roots:
                    # The protected installed default is an edited resource, never a
                    # replacement for this agent's unchanged private execution cwd.
                    roots = [root for root in record["resources"] if root.get("defaultForIntent")
                             and root["environmentId"] == frame["evidence"]["environmentId"]]
                require(len(roots) == 1, "One explicit physical resource is required for native intent")
                root = roots[0]
            info = Path(root["root"]).lstat()
            require((info.st_dev, info.st_ino) == (root["device"], root["inode"]) and stat.S_ISDIR(info.st_mode), "Physical root changed")
            declared = command.get("manifest", {}).get("sourceRevision") if port == "edit-plans" else command.get("sourceRevision")
            if declared:
                require(revision(root["root"]) == declared, "Model source revision differs from actual registered checkout")
            if port == "coordination" and command["action"] == "acquire":
                relative = canonical_relative(command["relativePath"])
                require(command["kind"] == "file", "Directory claim observation port is not implemented")
                require(read_file(root["root"], relative, (root["device"], root["inode"]))["sha256"] == command["contentSha256"], "Model claim bytes differ from actual physical target")
            if port == "coordination":
                locator = self.state / "commands" / ("claim-" + str(UUID(command["claimId"])) + ".json")
                if command["action"] == "acquire":
                    paths = [command["relativePath"]]
                else:
                    prior = protected(locator)
                    require(prior["workspaceId"] == root["workspaceId"], "Original claim belongs to another physical root")
                    paths = [prior["relativePath"]]
            elif "manifest" in command:
                paths = [item["relativePath"] for item in command["manifest"]["files"]]
            elif command["action"] == "consent":
                paths = [item["relativePath"] for item in command["artifacts"] + command["imports"]]
                for item in command["artifacts"] + command["imports"]:
                    observed = read_file(root["root"], item["relativePath"], (root["device"], root["inode"]))
                    require((observed["sha256"], observed["size"]) == (item["sha256"], item["size"]), "Consent artifact/import differs from observed bytes")
            else:
                snapshot = self.http("GET", "collaboration/edit-plans/" + str(UUID(command["planId"])))
                if command["action"] == "revoke":
                    votes = [vote for vote in snapshot["consents"] if str(vote["work"]) == command["workId"]]
                    paths = [item["relativePath"] for vote in votes for item in vote["artifacts"] + vote["imports"]]
                else:
                    paths = [item["relativePath"] for item in snapshot["manifest"]["files"]]
            result = self.relay(record, source, port, command, root, paths)
            if port == "coordination" and command["action"] == "acquire":
                saved(locator, {"workspaceId": root["workspaceId"], "relativePath": command["relativePath"]})
            if port == "edit-plans":
                saved(self.plan_pointer(record, root), {"planId": str(UUID(command["planId"]))})
        receipt = result.get("receipt", result)
        reply = {"success": True, "result": result, "canonicalReceipt": receipt, "holdReason": None}
        if port not in PATCH_PORTS:
            require(len(json.dumps(reply, ensure_ascii=True, separators=(",", ":")).encode()) <= 8192,
                    "Canonical response exceeds native output bound; effect may already be recorded. Original journal retained; use bounded original receipt inspection, never repeat the POST")
        return reply

    def serve(self, path):
        path = Path(path)
        protected_directory(path.parent)
        require(not path.exists() and not path.is_symlink(), "Never replace another native socket")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            path.chmod(0o666)
            listener.listen(16)
            # systemd readiness follows the real listening socket. Starting the
            # process alone cannot admit a newly installed agent's edit tools.
            notify = os.environ.get("NOTIFY_SOCKET")
            if notify:
                address = "\0" + notify[1:] if notify.startswith("@") else notify
                with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as status:
                    status.connect(address)
                    status.sendall(b"READY=1")
            while True:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(30)
                    try:
                        peer = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                        # Reject unrelated kernel peers before reading any frame bytes.
                        actual = process(peer[0])
                        require(actual and actual["uid"] == peer[1], "Kernel peer incarnation vanished")
                        owner, capture = None, None
                        if self.config.get("automaticCapture"):
                            from .collaboration_capture import AutomaticCapture
                            capture = AutomaticCapture(self)
                            try:
                                capture.peer(peer, authentication_only=True)
                            except Exception:
                                from .owner_briefing import guardian_peer
                                owner = guardian_peer(capture, peer)
                        channels = list((self.state / "channels").glob("*.json"))
                        require(len(channels) <= 256, "Protected channel registry exceeds bound")
                        admitted = False
                        for channel in channels:
                            candidate = protected(channel)
                            native = candidate["native"]
                            if all(actual.get(k) == native.get(k) for k in (
                                    "pid", "start", "uid", "controlGroup", "executableDevice", "executableInode")):
                                uid, _, _ = expected_owner(candidate["sourceBase"]["authorityId"], candidate["sourceBase"]["agentId"])
                                admitted = admitted or uid == peer[1]
                        require(admitted or self.config.get("automaticCapture"), "Peer has no protected captured native process registration")
                        size = struct.unpack("!I", receive(connection, 4))[0]
                        require(0 < size <= (65536 if owner is not None else FRAME_LIMIT), "Native frame bound exceeded")
                        frame = strict_json(receive(connection, size))
                        if owner is not None:
                            if frame.get("schema")=="lax-native-edit-status/v1":
                                from .native_edit_status import carry
                            else:
                                from .owner_briefing import carry
                            response = carry(capture, peer, frame, owner)
                        else:
                            response = self.handle(peer, frame)
                    except Exception as error:
                        response = {"success": False, "result": None, "canonicalReceipt": None, "holdReason": str(error)[:500]}
                    wire = json.dumps(response, separators=(",", ":")).encode()
                    require(len(wire) <= FRAME_LIMIT, "Native response exceeds frame limit")
                    try:
                        connection.sendall(struct.pack("!I", len(wire)) + wire)
                    except OSError:
                        # Durable journal/held permit survives a lost callback. Never repeat its POST.
                        pass


def receive(connection, count):
    data = bytearray()
    while len(data) < count:
        chunk = connection.recv(count - len(data))
        if not chunk:
            raise Held("Captured native channel ended before complete frame")
        data.extend(chunk)
    return data


def register_channel(configuration, specification):
    bridge = Bridge(configuration)
    protected_directory(Path(specification).parent)
    spec = protected(specification)
    base = spec["sourceBase"]
    require(set(base) == SOURCE_FIELDS, "Exact protected captured source required")
    value = bridge.http("GET", "executors/" + str(UUID(spec["executorId"])))
    row = value["executor"]
    require(row["launch_phase"] == "attached" and row["state"] == "live", "Attached live original executor required")
    native = process(row["descriptor"]["nativePid"])
    require(native and native["start"] == row["descriptor"]["nativeStart"], "Native process incarnation differs")
    uid, _, _ = expected_owner(base["authorityId"], base["agentId"])
    require(native["uid"] == uid and str(row["agent"]) == base["agentId"]
            and str(row["delivery"]) == base["deliveryId"] and row["generation"] == base["generation"]
            and row["claim_id"] == base["claimId"] and str(row["host"]) == base["hostId"], "Captured canonical assignment differs")
    fact = observe(bridge.config, row)
    require(fact["state"] == "live", "Fresh independent native observation required")
    record = {**spec, "schema": "lax-captured-native-channel/v1", "native": native,
              "descriptorDigest": row["descriptor_digest"], "serviceBindingDigest": fact["evidence"]["serviceBindingDigest"]}
    path = bridge.state / "channels" / (str(UUID(spec["executorId"])) + ".json")
    require(not path.exists(), "Never replace an original captured native channel")
    saved(path, record)
    return {"registered": True, "executorId": spec["executorId"], "nativeStarted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--socket", type=Path)
    action.add_argument("--register-channel", type=Path)
    args = parser.parse_args()
    if args.register_channel:
        print(json.dumps(register_channel(args.config, args.register_channel)))
    else:
        Bridge(args.config).serve(args.socket)


if __name__ == "__main__":
    main()
