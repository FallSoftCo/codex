"""Finish only pinned release metadata under the existing offline registry locks."""

import base64
import contextlib
import hashlib
import os
from pathlib import Path

from . import native_image_upgrade as image, native_release as release
from . import service_observer as observer
from .service_restart import file_hash, file_identity, settled_definitions


def optional(fd, name):
    try:
        return image._json(fd, name)
    except FileNotFoundError:
        return None


def states(plan, root_fd):
    result = []
    for target in plan["targets"]:
        path = Path(target["path"])
        checksum, _ = file_hash(path, target["uid"])
        hashes = [hashlib.sha256(base64.b64decode(target[k], validate=True)).hexdigest()
                  for k in ("before", "after")]
        if checksum not in hashes:
            raise ValueError("Recorded configuration/unit bytes are uncertain")
        result.append(hashes.index(checksum))
    enrolled = image._json(root_fd, "enrollment.json")
    if enrolled not in (plan["priorEnrollment"], plan["approvedEnrollment"]):
        raise ValueError("Enrollment is neither original nor prepared")
    result.append(int(enrolled == plan["approvedEnrollment"]))
    if result != sorted(result, reverse=True):
        raise ValueError("Recorded metadata stages are not an established prefix")
    return result


def status_locked(fd, operation=None):
    candidates = []
    for name in os.listdir(fd):
        if name.startswith("image-") and name.endswith("-intent.json"):
            value = image._json(fd, name)
            if value.get("schema") == release.SCHEMA:
                candidates.append(value)
    if len(candidates) > 4096:
        raise ValueError("Release history budget exhausted")
    if operation:
        candidates = [v for v in candidates if v["operationId"] == operation]
    else:
        pending = [v for v in candidates if optional(fd, "image-" + v["operationId"] + "-accepted.json") is None]
        index = optional(fd, image.INDEX)
        current = index if index and index.get("schema") == release.SCHEMA else optional(fd, release.CURRENT)
        candidates = pending or ([current] if current else [])
    if not candidates:
        legacy = optional(fd, image.INDEX)
        if legacy and legacy.get("state") != "accepted":
            return {"state": "held", "reason": "Legacy image intent requires original-effect review; no replay",
                    "operationId": legacy.get("operationId"), "intentDigest": observer.digest(legacy)}
    if len(candidates) != 1:
        return {"state": "held" if candidates else "absent",
                "reason": "Explicit original release operation required",
                "operations": [v["operationId"] for v in candidates]}
    intent = candidates[0]
    operation = intent["operationId"]
    intent = image._json(fd, "image-" + operation + "-intent.json")
    accepted = optional(fd, "image-" + operation + "-accepted.json")
    result = {"schema": release.SCHEMA, "operationId": operation,
              "intentDigest": observer.digest(intent), "state": "pending",
              "scope": intent["scope"], "modelsStarted": 0, "servicesStarted": 0,
              "executionReady": False, "restartApprovalRenewalRequired": True,
              "newReleaseRoot": intent["newReleaseRoot"],
              "closureDigest": observer.digest(intent["closure"]),
              "restartReview": {
                  "expectedEnrollment": observer.digest(intent["approvedEnrollment"]),
                  "expectedDefinition": intent["unitDefinitionDigest"],
                  "expectedImageSha256": intent["approvedImageSha256"],
                  "expectedConfigurationSha256": hashlib.sha256(
                      base64.b64decode(intent["targets"][0]["after"])).hexdigest(),
              },
              "expectedPriorEnrollment": observer.digest(intent["priorEnrollment"]),
              "expectedNewEnrollment": observer.digest(intent["approvedEnrollment"]),
              "targets": [{"path": t["path"],
                           "beforeSha256": hashlib.sha256(base64.b64decode(t["before"])).hexdigest(),
                           "afterSha256": hashlib.sha256(base64.b64decode(t["after"])).hexdigest()}
                          for t in intent["targets"]]}
    try:
        for target, observed in zip(intent["targets"], result["targets"]):
            observed["observedSha256"] = file_hash(target["path"], target["uid"])[0]
        result["observedEnrollment"] = observer.digest(image._json(fd, "enrollment.json"))
        stages = states(intent, fd)
        _closure_identity(intent)
        current = optional(fd, image.INDEX)
        pointer = optional(fd, release.CURRENT)
        if accepted is not None and accepted != {**intent, "state": "accepted"}:
            raise ValueError("Original immutable accepted record differs")
        if current not in (intent["priorIndex"], intent, accepted):
            raise ValueError("Original image transition pointer is uncertain")
        if pointer not in (intent["priorRelease"], accepted):
            raise ValueError("Original accepted software pointer is uncertain")
        if (accepted is not None and stages != [1, 1, 1]
                or pointer == accepted and accepted is not None and current != accepted
                or current == intent["priorIndex"] and stages != [0, 0, 0]):
            raise ValueError("Accepted/pointer stages disagree with original metadata prefix")
        complete = stages == [1, 1, 1] and accepted and current == accepted and pointer == accepted
        result.update(state="accepted" if complete else "pending", metadataStages=stages,
                      acceptedRecord=accepted is not None,
                      indexPublished=current == accepted and accepted is not None,
                      softwarePublished=pointer == accepted and accepted is not None)
    except (ValueError, OSError, PermissionError) as error:
        result.update(state="held", reason=str(error)[:240])
    return result


def status(authority, host, agent, operation=None):
    if os.geteuid() != 0:
        raise PermissionError("Verified release administrator required")
    with image.registry_lock(observer.directory(authority, host, agent)) as fd:
        return status_locked(fd, operation)


def _write_target(target):
    path = Path(target["path"])
    parent = image._open_directory(path.parent, target["uid"])
    temporary = ".release-" + os.urandom(16).hex()
    try:
        # The old bytes are independently rechecked immediately before replacement.
        actual = image._read(parent, path.name, target["uid"])
        before, after = [base64.b64decode(target[k], validate=True) for k in ("before", "after")]
        if actual != before:
            raise ValueError("Original target CAS changed before metadata publication")
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         target["mode"], dir_fd=parent)
        os.fchown(handle, target["uid"], path.stat().st_gid)
        os.fchmod(handle, target["mode"])
        with os.fdopen(handle, "wb") as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)


def _closure_identity(plan):
    software = plan["closure"]
    root = Path(software["root"])
    handle = image._open_directory(root)
    try:
        if list(image._identity(os.fstat(handle))) != software["rootIdentity"]:
            raise ValueError("Reviewed release directory changed")
    finally:
        os.close(handle)
    if sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) != sorted(software["identities"]):
        raise ValueError("Reviewed release entry set changed")
    for relative, identity in software["identities"].items():
        if list(image._identity((root / relative).lstat())) != identity:
            raise ValueError("Reviewed release asset identity changed")
    for row in software["entries"]:
        if row["kind"] == "file-link" and file_identity(Path(row["resolved"])) != row["identity"]:
            raise ValueError("Reviewed external interpreter dependency changed")


def finish(root, fd, intent):
    authority, host, agent = intent["scope"]
    uid, home = intent["uid"], Path(intent["home"])
    settled_definitions(root)
    if release.physical(home, uid) != intent["physical"]:
        raise ValueError("Original private physical paths changed")
    if release.closure(intent["newReleaseRoot"]) != intent["closure"]:
        raise ValueError("Reviewed complete software closure changed")
    if (file_hash(intent["oldBinary"], 0)[0] != intent["oldImageSha256"]
            or file_identity(Path(intent["oldInterpreter"]).resolve()) != intent["oldInterpreterIdentity"]
            or list(image._identity(Path(intent["oldReleaseRoot"]).stat())) != intent["oldRootIdentity"]):
        raise ValueError("Original reviewed software paths changed")
    if release.probe(Path(intent["newBinary"]), Path(intent["newInterpreter"]), uid, home,
                     Path(intent["newReleaseRoot"])) != intent["probes"]:
        raise ValueError("Actual service-UID package/interpreter proof changed")
    with contextlib.ExitStack() as stack:
        state_fd = image._open_directory(home / "state", uid)
        stack.callback(os.close, state_fd)
        lock = os.open("connector.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=state_fd)
        stack.callback(os.close, lock)
        image._owned(os.fstat(lock), uid)
        image.fcntl.flock(lock, image.fcntl.LOCK_EX | image.fcntl.LOCK_NB)
        controller_fd = image._open_directory(root.parent.parent)
        stack.callback(os.close, controller_fd)
        controller = image._json(controller_fd, "controller.json")
        config = image.json.loads(base64.b64decode(intent["targets"][0]["before"]))
        if (controller["authorityId"], controller["hostId"], controller["machineIdentity"],
                controller["hollywoodUrl"]) != (authority, host, image.machine_identity(), config["hollywoodUrl"]):
            raise ValueError("Original controller route or physical machine differs")
        if observer.digest(controller) != intent["controllerDigest"]:
            raise ValueError("Reviewed controller configuration changed")
        journals = image._journal_snapshot(state_fd, uid, authority, host, agent)
        if observer.digest(journals) != intent["journalSnapshotDigest"]:
            raise ValueError("Original local execution journals changed")
        def drained():
            fresh_registry = image._open_directory(root)
            try:
                if (os.fstat(fresh_registry).st_dev, os.fstat(fresh_registry).st_ino) != (os.fstat(fd).st_dev, os.fstat(fd).st_ino):
                    raise ValueError("Original service registry was replaced")
            finally:
                os.close(fresh_registry)
            stage = states(intent, fd)
            definition = hashlib.sha256(base64.b64decode(intent["targets"][1][
                "after" if stage[1] else "before"])).hexdigest()
            image._offline(authority, host, agent, uid, home,
                           Path(intent["priorEnrollment"]["binary"]),
                           intent["priorEnrollment"], definition, fd)
            image._canonical(config, controller, host, agent)
            _closure_identity(intent)
            if release.physical(home, uid) != intent["physical"]:
                raise ValueError("Original physical identities changed")
            current_lock = os.stat("connector.lock", dir_fd=state_fd, follow_symlinks=False)
            if (current_lock.st_dev, current_lock.st_ino) != (os.fstat(lock).st_dev, os.fstat(lock).st_ino):
                raise ValueError("Original connector lock was replaced")
            fresh = image._open_directory(home / "state", uid)
            try:
                if (os.fstat(fresh).st_dev, os.fstat(fresh).st_ino) != (os.fstat(state_fd).st_dev, os.fstat(state_fd).st_ino):
                    raise ValueError("Original state directory replaced")
            finally:
                os.close(fresh)
            if image._journal_snapshot(state_fd, uid, authority, host, agent) != journals:
                raise ValueError("Original local journals changed during transition")
            return stage
        for index, target in enumerate(intent["targets"]):
            if not drained()[index]:
                _write_target(target)
        if not drained()[2]:
            image._write(fd, "enrollment.json", intent["approvedEnrollment"], replace=True)
        drained()
        accepted = {**intent, "state": "accepted"}
        name = "image-" + intent["operationId"] + "-accepted.json"
        if optional(fd, name) is None:
            image._write(fd, name, accepted)
        elif image._json(fd, name) != accepted:
            raise ValueError("Original accepted release evidence differs")
        image._write(fd, image.INDEX, accepted, replace=True)
        image._write(fd, release.CURRENT, accepted, replace=True)
        return status_locked(fd, intent["operationId"])


def approve(authority, host, agent, prepared, expected_preparation):
    if os.geteuid() != 0:
        raise PermissionError("Verified release administrator required")
    root = observer.directory(authority, host, agent)
    with image.registry_lock(root) as fd:
        image.require_settled_transition(fd)
        plan = observer.protected(Path(prepared) / "release-plan.json")
        if observer.digest(plan) != expected_preparation or plan["scope"] != [authority, host, agent]:
            raise ValueError("Explicit reviewed preparation digest/scope required")
        if states(plan, fd) != [0, 0, 0]:
            raise ValueError("Original metadata CAS changed; inspect without retry")
        from .service_memory import approved_spec
        if observer.digest(approved_spec(authority, agent)[0]) != plan["originalSpecDigest"]:
            raise ValueError("Original provisioning evidence changed")
        state_fd = image._open_directory(Path(plan["home"]) / "state", plan["uid"])
        controller_fd = image._open_directory(root.parent.parent)
        try:
            journals = image._journal_snapshot(state_fd, plan["uid"], authority, host, agent)
            controller = image._json(controller_fd, "controller.json")
        finally:
            os.close(state_fd)
            os.close(controller_fd)
        prior = optional(fd, image.INDEX)
        operation = observer.digest([expected_preparation, prior])
        intent = {**plan, "state": "intent", "operationId": operation,
                  "priorIndex": prior, "priorRelease": optional(fd, release.CURRENT),
                  "journalSnapshotDigest": observer.digest(journals),
                  "controllerDigest": observer.digest(controller)}
        # Offline evidence precedes intent; full closure/probes are rechecked
        # before any target publication. A changed pin retains the original intent.
        old = intent["priorEnrollment"]
        image._offline(authority, host, agent, plan["uid"], Path(plan["home"]),
                       Path(old["binary"]), old,
                       hashlib.sha256(base64.b64decode(plan["targets"][1]["before"])).hexdigest(), fd)
        config = image.json.loads(base64.b64decode(plan["targets"][0]["before"]))
        image._canonical(config, controller, host, agent)
        image._write(fd, "image-" + operation + "-before.json", old)
        image._write(fd, "image-" + operation + "-intent.json", intent)
        image._write(fd, image.INDEX, intent, replace=True)
        return finish(root, fd, intent)


def reconcile(authority, host, agent, operation, expected_intent):
    if os.geteuid() != 0:
        raise PermissionError("Verified release administrator required")
    if len(operation) != 64 or any(c not in "0123456789abcdef" for c in operation):
        raise ValueError("Original release operation digest required")
    root = observer.directory(authority, host, agent)
    with image.registry_lock(root) as fd:
        current = status_locked(fd, operation)
        if current.get("intentDigest") != expected_intent or current.get("scope") != [authority, host, agent]:
            raise ValueError("Exact original intent digest/scope required")
        if current["state"] == "accepted":
            return current
        if current["state"] != "pending":
            raise ValueError("Original release metadata is uncertain; retained held")
        intent = image._json(fd, "image-" + operation + "-intent.json")
        if intent.get("schema") != release.SCHEMA or intent.get("state") != "intent":
            raise ValueError("Only original release metadata intents can be reconciled")
        for name in os.listdir(fd):
            if name.startswith("image-") and name.endswith("-intent.json") and operation not in name:
                value = image._json(fd, name)
                if optional(fd, name.removesuffix("-intent.json") + "-accepted.json") != {**value, "state": "accepted"}:
                    raise ValueError("Another original image/release transition remains unsettled")
        # An intent may be durable just before its pointer was published.
        if optional(fd, image.INDEX) == intent["priorIndex"]:
            if states(intent, fd) != [0, 0, 0]:
                raise ValueError("Missing transition pointer with changed metadata is uncertain")
            image._write(fd, image.INDEX, intent, replace=True)
        return finish(root, fd, intent)
