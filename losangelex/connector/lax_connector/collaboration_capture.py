"""Automatic root-controller capture of an existing canonical native execution.

No model input chooses source identity, a resource, grants or execution. The
installer supplies a protected policy. Administrative credentials are separate
from the enrolled controller credential used for actual native relays.
"""

import fcntl
import hashlib
import json
import os
import pwd
import time
import urllib.error
from pathlib import Path
from uuid import UUID

from .collaboration_bridge import (
    Held,
    SOURCE_FIELDS,
    IMPLEMENTED_PORTS,
    digest,
    protected_directory,
    require,
)
from .collaboration_resources import open_root, verify_native_path
from .host import request
from .journal import saved
from .service_observer import protected, process, observe, expected_owner


def administrative_put(state, http, route, payload):
    """Publish one protected intent; an uncertain PUT is only inspected thereafter."""
    path = (
        Path(state)
        / "administration"
        / (digest([route, payload["operationId"]]) + ".json")
    )
    wire = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    identity = {"method": "PUT", "path": "/hollywood/v3/" + route, "wireDigest": wire}
    if path.exists():
        old = protected(path)
        require(
            old["identity"] == identity and old["payload"] == payload,
            "Original administrative capture intent changed",
        )
        if old["state"] == "accepted":
            return old["result"]
        require(
            old["state"] == "pending", "Original administrative capture was rejected"
        )
    else:
        saved(path, {"state": "pending", "identity": identity, "payload": payload})
        try:
            result = http("PUT", route, payload)
        except urllib.error.HTTPError as error:
            if error.code in (400, 403, 409):
                saved(
                    path,
                    {
                        "state": "rejected",
                        "identity": identity,
                        "payload": payload,
                        "status": error.code,
                    },
                )
                raise Held(
                    "Canonical administrative capture rejected; no automatic revision/retry"
                ) from None
        except Exception:
            pass
        else:
            saved(
                path,
                {
                    "state": "accepted",
                    "identity": identity,
                    "payload": payload,
                    "result": result,
                },
            )
            return result
    original = http("GET", "administration/commands/" + payload["operationId"])
    require(
        all(original.get(k) == v for k, v in identity.items()),
        "Original administrative capture receipt differs",
    )
    result = original["acceptedResult"]
    saved(
        path,
        {
            "state": "accepted",
            "identity": identity,
            "payload": payload,
            "result": result,
        },
    )
    return result


def installed_native_owner(authority, uid):
    """Derive a kernel UID's agent from NSS and protected installation records.

    An installed resource policy is not an agent whitelist. No client frame or
    canonical query chooses the identity or executable used for this first gate.
    """
    authority = str(UUID(authority))
    base = Path("/var/lib/harness") / authority
    account = pwd.getpwuid(uid)
    global_receipt = protected(base / "global-admin-receipt.json")
    if global_receipt["uid"] == uid and Path(global_receipt["home"]) == Path(
        account.pw_dir
    ):
        agent = str(UUID(global_receipt["agentId"]))
    else:
        try:
            parts = Path(account.pw_dir).relative_to(base / "workers").parts
            require(
                len(parts) == 2 and parts[1] == "home",
                "Peer NSS home is not an installed worker",
            )
            agent = str(UUID(parts[0]))
            require(agent == parts[0], "Peer worker identity is not canonical")
        except (ValueError, KeyError):
            raise Held("Peer NSS home is outside this enrolled installation") from None
    expected_uid, home, binary = expected_owner(authority, agent)
    require(
        (expected_uid, str(home)) == (uid, account.pw_dir),
        "Peer NSS identity differs from protected installation owner",
    )
    return agent, binary


class AutomaticCapture:
    def __init__(self, bridge):
        self.bridge = bridge
        self.config, self.state = bridge.config, bridge.state
        self.policy = self.config["automaticCapture"]
        require(
            self.policy["schema"] in {"lax-automatic-native-capture/v1", "lax-automatic-native-capture/v2"},
            "Protected automatic capture policy required",
        )
        require(
            (self.policy["schema"] == "lax-automatic-native-capture/v2" or 1 <= len(self.policy["agents"]) <= 32)
            and 1 <= len(self.policy["resources"]) <= 8,
            "Bounded installed capture policy required",
        )
        path = Path(self.policy["administratorConfig"])
        protected_directory(path.parent)
        admin = protected(path)
        require(
            (admin["authorityId"], admin["hostId"], admin["hollywoodUrl"])
            == (
                self.config["authorityId"],
                self.config["hostId"],
                self.config["hollywoodUrl"],
            ),
            "Administrative capture configuration differs from enrolled host",
        )
        self.admin_http = lambda method, route, payload=None: request(
            admin["hollywoodUrl"], admin["token"], method, route, payload
        )
        protected_directory(self.state / "administration")

    def peer(self, peer):
        """Authenticate kernel identity before consuming any client bytes."""
        actual = process(peer[0])
        require(actual and actual["uid"] == peer[1], "Kernel peer incarnation vanished")
        agent, binary = installed_native_owner(self.config["authorityId"], peer[1])
        image = Path(binary).resolve(strict=True).stat()
        require(
            (actual.get("executableDevice"), actual.get("executableInode"))
            == (image.st_dev, image.st_ino),
            "Peer is not its installed native image; no frame or server query admitted",
        )
        rows, after = [], None
        for _ in range(4):
            route = "hosts/" + self.config["hostId"] + "/executors"
            if after:
                route += "?after=" + str(UUID(after))
            page = self.bridge.http("GET", route)
            rows.extend(
                row
                for row in page["executors"]
                if row["descriptor"].get("nativePid") == peer[0]
                and row["descriptor"].get("nativeStart") == actual["start"]
            )
            after = page["nextAfter"]
            if not after:
                break
        require(
            not after and len(rows) == 1,
            "One bounded canonical native executor required",
        )
        row = rows[0]
        require(
            str(row["agent"]) == agent
            and row["launch_phase"] == "attached"
            and row["state"] == "live"
            and str(row["host"]) == self.config["hostId"],
            "Native executor differs from the protected installed owner",
        )
        uid, _, _ = expected_owner(self.config["authorityId"], str(row["agent"]))
        require(
            uid == peer[1], "Native process differs from protected installation owner"
        )
        fact = observe(self.config, row)
        require(
            fact["state"] == "live",
            "Independent current native service observation required",
        )
        return row, actual, fact

    def ensure(self, peer, frame=None):
        """Capture exact current turn, then grant only its already admitted work."""
        row, native, fact = self.peer(peer)
        lock_path = self.state / "capture.lock"
        fd = os.open(
            lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            snapshot = self.admin_http(
                "GET", "deliveries/" + str(UUID(row["delivery"]))
            )
            # A native tool can arrive before turn/start's receipt is persisted.
            # Wait only on this exact existing delivery; never queue model work.
            for _ in range(3):
                if snapshot["delivery"]["state"] != "claimed":
                    break
                time.sleep(0.05)
                snapshot = self.admin_http(
                    "GET", "deliveries/" + str(UUID(row["delivery"]))
                )
            delivery, event = snapshot["delivery"], snapshot["request"]
            require(
                delivery["state"] == "running"
                and not delivery["cancellation_requested"]
                and (
                    delivery["id"],
                    delivery["agent"],
                    delivery["host"],
                    delivery["generation"],
                    delivery["claim_id"],
                )
                == (
                    row["delivery"],
                    row["agent"],
                    row["host"],
                    row["generation"],
                    row["claim_id"],
                )
                and event["id"] == delivery["event"]
                and event["authority"] == self.config["authorityId"],
                "Original canonical running turn required for capture",
            )
            binding = snapshot["agentContextBinding"]
            require(
                binding["delivery"] == delivery["id"]
                and binding["generation"] == delivery["generation"]
                and binding["principal"] == row["agent"]
                and binding["native_thread"] == delivery["native_thread"]
                and delivery["native_turn"],
                "Exact persistent context/turn binding required",
            )
            role = self.admin_http("GET", "agents/" + str(UUID(row["agent"])) + "/role")
            require(
                role["revision"] == binding["role_revision"],
                "Current role revision changed",
            )
            base = {
                "schema": "hollywood-native-source/v2",
                "authorityId": self.config["authorityId"],
                "agentId": str(row["agent"]),
                "hostId": self.config["hostId"],
                "deliveryId": str(delivery["id"]),
                "generation": delivery["generation"],
                "claimId": delivery["claim_id"],
                "requestId": str(event["id"]),
                "nativeThread": delivery["native_thread"],
                "nativeTurn": delivery["native_turn"],
                "roleRevision": binding["role_revision"],
                "contextId": binding["context_id"],
                "nativeGoalId": (snapshot.get("nativeGoalBinding") or {}).get(
                    "native_goal_id"
                ),
            }
            require(
                set(base) == SOURCE_FIELDS, "Exact canonical captured source required"
            )
            if frame is not None:
                require(
                    (frame["threadId"], frame["turnId"])
                    == (base["nativeThread"], base["nativeTurn"]),
                    "Native frame differs from current canonical turn",
                )
            identity = (
                str(UUID(row["id"]))
                + "-"
                + digest([base["nativeThread"], base["nativeTurn"]])
            )
            path = self.state / "channels" / (identity + ".json")
            policy = self.bridge.http(
                "GET", "hosts/" + base["hostId"] + "/collaboration-bridge"
            )
            require(
                policy.get("bridge")
                and policy["bridge"]["state"] == "active"
                and policy["bridge"]["protocol"] == "canonical-edit-plans/v2",
                "Current protected physical collaboration enrollment required",
            )
            if self.policy["schema"] == "lax-automatic-native-capture/v2":
                from .request_capture import ensure
                return ensure(self, base, snapshot, row, native, fact, policy, path)
            work_id = event.get("data", {}).get("workId")
            require(
                work_id,
                "Canonical editing needs admitted structured work; use authorized Hollywood goal/work tools, never an implicit local fallback",
            )
            work = self.admin_http("GET", "work/" + str(UUID(work_id)))["work"]
            require(
                work["owner"] == row["agent"]
                and work["delivery"] == delivery["id"]
                and work["request_event"] == event["id"]
                and work["state"] == "assigned",
                "Current canonical owned work required for automatic resource grants",
            )
            goal = self.admin_http("GET", "goals/" + str(UUID(work["goal"])))["goal"]
            require(goal["state"] == "active", "Current goal does not admit editing")
            agent_policy = self.policy["agents"][str(row["agent"])]
            resources = []
            registry = self.bridge.http(
                "GET", "collaboration/physical-targets/" + str(UUID(work_id))
            )
            for root in self.policy["resources"]:
                if root["workspaceId"] not in agent_policy["workspaceIds"]:
                    continue
                require(
                    root["hostId"] == base["hostId"]
                    and root["environmentId"] == "local",
                    "Only installed local physical resources are supported",
                )
                handle = open_root(root["root"])
                try:
                    info = os.fstat(handle)
                    require(
                        (info.st_dev, info.st_ino) == (root["device"], root["inode"]),
                        "Installed physical root changed",
                    )
                finally:
                    os.close(handle)
                verify_native_path(root, "", native["pid"])
                prior = [
                    v
                    for v in registry["targets"]
                    if str(v["id"]) == root["workspaceId"]
                ]
                require(len(prior) <= 1, "Ambiguous physical resource grant")
                old = prior[0] if prior else None
                if old:
                    require(
                        old["state"] == "active"
                        and old["grant_state"] == "active"
                        and old["revision"] == root["registryRevision"],
                        "Physical resource or grant was revoked/changed",
                    )
                if old is None or old["work_revision"] != work["revision"]:
                    revision = old["grant_revision"] if old else 0
                    payload = {
                        "operationId": "capture-grant:"
                        + digest(
                            [root["workspaceId"], work_id, work["revision"], revision]
                        ),
                        "revision": revision,
                        "workspaceRevision": root["registryRevision"],
                        "workRevision": work["revision"],
                        "state": "active",
                    }
                    administrative_put(
                        self.state,
                        self.admin_http,
                        "physical-workspaces/"
                        + root["workspaceId"]
                        + "/grants/"
                        + str(UUID(work_id)),
                        payload,
                    )
                resources.append(
                    {k: v for k, v in root.items() if k != "registryRevision"}
                    | {
                        "defaultForIntent": root["workspaceId"]
                        == agent_policy["defaultWorkspaceId"]
                    }
                )
            require(
                resources and sum(v["defaultForIntent"] for v in resources) == 1,
                "One installed default intent resource and explicit grants required",
            )
            fresh = self.bridge.http(
                "GET", "collaboration/physical-targets/" + str(UUID(work_id))
            )
            require(
                fresh["workRevision"] == work["revision"],
                "Resource work revision changed during capture",
            )
            for root in resources:
                matches = [
                    v for v in fresh["targets"] if str(v["id"]) == root["workspaceId"]
                ]
                require(
                    len(matches) == 1,
                    "Fresh original resource grant required after capture",
                )
                target = matches[0]
                environment = digest(
                    {"hostId": root["hostId"], "environmentId": root["environmentId"]}
                )
                require(
                    target["state"] == "active"
                    and target["grant_state"] == "active"
                    and target["work_revision"] == work["revision"]
                    and target["root_path"] == root["root"]
                    and str(target["host"]) == root["hostId"]
                    and target["environment_sha256"] == environment
                    and target["root_identity_sha256"]
                    == digest(
                        {
                            "hostId": root["hostId"],
                            "environmentSha256": environment,
                            "device": root["device"],
                            "inode": root["inode"],
                        }
                    ),
                    "Fresh canonical resource/grant differs from actual captured root",
                )
            record = {
                "schema": "lax-captured-native-channel/v1",
                "sourceBase": base,
                "native": native,
                "executorId": str(row["id"]),
                "descriptorDigest": row["descriptor_digest"],
                "serviceBindingDigest": fact["evidence"]["serviceBindingDigest"],
                "bridgeRevision": policy["bridge"]["revision"],
                "ports": sorted(IMPLEMENTED_PORTS),
                "work": {"id": str(work_id), "revision": work["revision"]},
                "resources": resources,
            }
            if path.exists():
                require(
                    protected(path) == record,
                    "Captured original turn changed; no overwrite",
                )
            else:
                if len(list((self.state / "channels").glob("*.json"))) >= 128:
                    self.archive_closed()
                require(
                    len(list((self.state / "channels").glob("*.json"))) < 256,
                    "Unsettled captured channel bound reached",
                )
                saved(path, record)
            return record
        finally:
            os.close(fd)

    def archive_closed(self):
        """Retain terminal original evidence; never discard unsettled channels."""
        archive = self.state / "channels" / "archive"
        protected_directory(archive)
        for path in sorted((self.state / "channels").glob("*.json"))[:16]:
            record = protected(path)
            old = self.admin_http("GET", "executors/" + str(UUID(record["executorId"])))
            if old["deliveryTerminal"] and old["executor"]["state"] == "stopped":
                target = archive / path.name
                require(not target.exists(), "Original archived channel already exists")
                path.rename(target)
