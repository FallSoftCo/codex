"""Protected Linux host controller: actual resource samples, no model execution."""

import argparse
import fcntl
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from .journal import saved


def machine_identity():
    return hashlib.sha256(Path("/etc/machine-id").read_bytes().strip()).hexdigest()


def resources():
    cpus = (
        len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else os.cpu_count()
    )
    values = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    available = int(values["MemAvailable"].split()[0]) * 1024
    root = Path("/sys/fs/cgroup")
    groups = {root}
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        hierarchy, controllers, relative = line.split(":", 2)
        if hierarchy == "0" and not controllers:
            current = root / relative.lstrip("/")
            if ".." not in current.parts:
                groups.update(
                    p
                    for p in (current, *current.parents)
                    if p == root or root in p.parents
                )
    for group in groups:
        try:
            quota, period = (group / "cpu.max").read_text().split()
            if quota != "max":
                cpus = min(cpus, max(1, int(quota) // int(period)))
        except (OSError, ValueError, ZeroDivisionError):
            pass
        try:
            limit = (group / "memory.max").read_text().strip()
            used = int((group / "memory.current").read_text())
            if limit != "max":
                available = min(available, max(0, int(limit) - used))
        except (OSError, ValueError):
            pass
    return {"cpuSlots": max(1, cpus or 1), "availableMemoryBytes": available}


def request(url, token, method, path, payload=None):
    command = urllib.request.Request(
        url.rstrip("/") + "/hollywood/v3/" + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(command, timeout=15) as response:
        return json.load(response)


def enroll(spec):
    if os.geteuid() != 0:
        raise PermissionError("Host enrollment writes protected installation state")
    authority, host = str(UUID(spec["authorityId"])), str(UUID(spec["hostId"]))
    identity = machine_identity()
    directory = Path("/var/lib/harness") / authority / "hosts" / host
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / "enrollment-intent.json"
    if path.exists():
        intent = json.loads(path.read_text())
        if (
            intent["authorityId"],
            intent["hostId"],
            intent["machineIdentity"],
            intent["hollywoodUrl"],
        ) != (
            authority,
            host,
            identity,
            spec["hollywoodUrl"],
        ):
            raise ValueError(
                "Host enrollment identity changed; explicit migration required"
            )
    else:
        import secrets

        intent = {
            "authorityId": authority,
            "hostId": host,
            "machineIdentity": identity,
            "hollywoodUrl": spec["hollywoodUrl"],
            "controllerId": str(uuid5(UUID(host), "lax-host-controller")),
            "token": secrets.token_urlsafe(40),
            "policyOperation": "host-policy:" + str(uuid4()),
        }
        saved(path, intent)
    owner = spec["administratorCredential"]
    call = lambda method, route, body=None: request(
        intent["hollywoodUrl"], owner["token"], method, route, body
    )
    call(
        "POST",
        "principals",
        {
            "id": intent["controllerId"],
            "name": "host-controller-" + host[:12],
            "kind": "service",
            "enrollmentCredential": intent["token"],
        },
    )
    policy = call("GET", "hosts/" + host + "/admission")
    if policy["policy"] is None:
        call(
            "PUT",
            "hosts/" + host + "/admission",
            {
                **spec["policy"],
                "operationId": intent["policyOperation"],
                "revision": 0,
                "controllerId": intent["controllerId"],
                "machineIdentity": identity,
            },
        )
        policy = call("GET", "hosts/" + host + "/admission")
    elif (
        str(policy["policy"]["controller"]),
        policy["policy"]["machine_identity"],
    ) != (
        intent["controllerId"],
        identity,
    ):
        raise ValueError(
            "Existing host admission has a different controller; no overwrite"
        )
    config = {
        **{
            k: intent[k]
            for k in (
                "authorityId",
                "hostId",
                "machineIdentity",
                "hollywoodUrl",
                "token",
            )
        },
        "state": str(directory),
        "sampleSeconds": min(5, policy["policy"]["sample_max_age"] / 3),
    }
    config_path = directory / "controller.json"
    saved(config_path, config)
    receipt = {
        "authorityId": authority,
        "hostId": host,
        "controllerId": intent["controllerId"],
        "machineIdentity": identity,
        "configPath": str(config_path),
        "policyRevision": policy["policy"]["revision"],
        "modelExecution": False,
    }
    saved(directory / "enrollment-receipt.json", receipt)
    return receipt


def observe_executors(config):
    """Independent host facts, coalesced and receipted; never a model wake."""
    from .service_observer import observe, digest

    root = Path(config["state"])
    after = None
    observed = 0
    gaps = 0
    while True:
        route = "hosts/" + config["hostId"] + "/executors"
        if after:
            route += "?after=" + after
        page = request(config["hollywoodUrl"], config["token"], "GET", route)
        for row in page["executors"]:
            path = root / ("executor-observation-" + row["id"] + ".json")
            prior = json.loads(path.read_text()) if path.exists() else None
            if prior and prior["state"] == "pending":
                payload = prior["payload"]
            else:
                try:
                    fact = observe(config, row)
                except Exception as error:
                    saved(root / ("executor-sensor-gap-" + row["id"] + ".json"), {
                        "error": type(error).__name__, "detail": str(error)[:500],
                        "executorId": row["id"], "descriptorDigest": row["descriptor_digest"],
                        "selfStopAttested": False,
                    })
                    d = row["descriptor"]
                    fact = {
                        "state": "unknown",
                        "evidence": {
                            "reason": "unverified-host-executor",
                            "error": type(error).__name__,
                            "originalBootId": d["bootId"],
                            "observedBootId": None,
                            "serviceUnit": d["serviceUnit"],
                            "originalServiceInvocation": d["serviceInvocation"],
                            "guardianPid": d["guardianPid"],
                            "guardianStart": d["guardianStart"],
                            "nativePid": d["nativePid"],
                            "nativeStart": d["nativeStart"],
                            "externalEffectsUndone": False,
                        },
                    }
                fingerprint = digest(fact)
                if (
                    prior
                    and prior["state"] == "completed"
                    and prior.get("fingerprint") == fingerprint
                    and not config.get("nativeCollaborationCaptureConfig")
                ):
                    continue
                payload = {
                    "operationId": str(uuid4()),
                    "machineIdentity": config["machineIdentity"],
                    "descriptorDigest": row["descriptor_digest"],
                    **fact,
                }
                saved(
                    path,
                    {
                        "state": "pending",
                        "fingerprint": fingerprint,
                        "payload": payload,
                    },
                )
            try:
                result = request(
                    config["hollywoodUrl"],
                    config["token"],
                    "POST",
                    "hosts/"
                    + config["hostId"]
                    + "/executors/"
                    + row["id"]
                    + "/observation",
                    payload,
                )
            except Exception as error:
                gaps += 1
                original = json.loads(path.read_text())
                rejected = isinstance(error, urllib.error.HTTPError) and error.code in (
                    400,
                    403,
                    409,
                )
                saved(
                    path,
                    {
                        **original,
                        "state": "rejected" if rejected else "pending",
                        "error": type(error).__name__,
                    },
                )
                continue
            original = json.loads(path.read_text())
            saved(path, {**original, "state": "completed", "receipt": result})
            observed += 1
            capture = config.get("nativeCollaborationCaptureConfig")
            native_pid = row["descriptor"].get("nativePid")
            if capture and native_pid and payload["state"] == "live":
                try:
                    from .collaboration_bridge import Bridge
                    from .collaboration_capture import AutomaticCapture
                    from .service_observer import process
                    native = process(native_pid)
                    if native:
                        AutomaticCapture(Bridge(capture)).ensure((native_pid,native["uid"],0))
                except Exception as error:
                    saved(root / ("collaboration-capture-gap-"+row["id"]+".json"), {
                        "executorId":row["id"],"state":"held","reason":type(error).__name__,
                        "modelsStarted":0,"effectReplayed":False,
                    })
        after = page["nextAfter"]
        if not after:
            break
    saved(
        root / "executor-observation-summary.json",
        {"observed": observed, "unconfirmed": gaps},
    )
    return observed


def supervise(config, once=False):
    if machine_identity() != config["machineIdentity"]:
        raise PermissionError("Controller config belongs to another machine")
    root = Path(config["state"])
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock = (root / "controller.lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    path = root / "sample-intent.json"
    while True:
        try:
            prior = json.loads(path.read_text()) if path.exists() else None
            if prior and prior["state"] == "pending":
                payload = prior["payload"]
            else:
                payload = {
                    "operationId": str(uuid4()),
                    "machineIdentity": config["machineIdentity"],
                    **resources(),
                }
                saved(path, {"state": "pending", "payload": payload})
            result = request(
                config["hollywoodUrl"],
                config["token"],
                "POST",
                "hosts/" + config["hostId"] + "/capacity",
                payload,
            )
            saved(path, {"state": "completed", "payload": payload, "receipt": result})
            executor_observations = observe_executors(config)
            from .service_restart import reconcile_services
            service_incarnations = reconcile_services(config)
            executor_gaps = json.loads(
                (root / "executor-observation-summary.json").read_text()
            )["unconfirmed"]
            saved(
                root / "status.json",
                {
                    "state": "observation-gaps" if executor_gaps or service_incarnations["held"] else "healthy",
                    "lastReceipt": result,
                    "executorObservations": executor_observations,
                    "serviceIncarnations": service_incarnations,
                    "executorObservationGaps": executor_gaps,
                    "modelsStarted": 0,
                },
            )
            if once:
                return result
        except Exception as error:
            saved(
                root / "status.json",
                {"state": "held", "error": type(error).__name__, "modelsStarted": 0},
            )
            if once:
                raise
        time.sleep(config.get("sampleSeconds", 5))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--enroll", type=Path)
    actions.add_argument("--serve", type=Path)
    actions.add_argument("--once", type=Path)
    args = parser.parse_args()
    path = args.enroll or args.serve or args.once
    config = json.loads(path.read_text())
    result = enroll(config) if args.enroll else supervise(config, once=bool(args.once))
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
