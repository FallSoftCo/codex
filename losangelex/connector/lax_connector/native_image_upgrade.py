"""Explicit offline native image transition; never change admission or start services.

Placement must remain disabled under administrator coordination through activation.
Local locks serialize maintained writers, not simultaneous privileged policy changes.
An interrupted intent is held for original-effect inspection, never auto-replayed.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import stat
from pathlib import Path
from uuid import UUID

from . import service_observer as observer
from .host import machine_identity, request
from .journal import ExecutionJournals, execution_key, execution_scope
from .native_package import preflight_as_owner

INDEX = "native-image-transition.json"


def _identity(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_uid,
        info.st_gid,
    )


def _owned(info, uid, *, directory=False):
    valid_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_type or info.st_uid != uid or info.st_mode & 0o022:
        raise PermissionError(
            "Image transition path is not protected by its expected owner"
        )


def _open_directory(path, uid=0):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Absolute unchanged installation path required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            if info.st_uid not in {0, uid}:
                raise PermissionError("Installation ancestor has another owner")
            _owned(info, info.st_uid, directory=True)
        _owned(os.fstat(fd), uid, directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(fd, name, uid=0):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        before = os.fstat(handle)
        _owned(before, uid)
        if before.st_size > 16 * 1024 * 1024:
            raise ValueError("Transition evidence exceeds finite read budget")
        with os.fdopen(os.dup(handle), "rb") as stream:
            data = stream.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024 or _identity(before) != _identity(
            os.fstat(handle)
        ):
            raise ValueError("Transition evidence changed while reading")
        return data
    finally:
        os.close(handle)


def _json(fd, name, uid=0):
    return json.loads(_read(fd, name, uid))


def _write(fd, name, value, *, replace=False):
    data = (json.dumps(value, indent=2) + "\n").encode()
    temporary = ".image-transition-" + os.urandom(16).hex()
    handle = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=fd,
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        else:
            # Link publishes a complete immutable record with no-overwrite semantics.
            os.link(
                temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False
            )
        os.fsync(fd)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=fd)
        os.fsync(fd)


@contextlib.contextmanager
def registry_lock(root):
    fd = _open_directory(root)
    handle = None
    try:
        handle = os.open(
            "registry.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=fd
        )
        _owned(os.fstat(handle), 0)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        if handle is not None:
            os.close(handle)
        os.close(fd)


def require_settled_transition(fd, *, check_image=True):
    # The immutable intent can precede the mutable pointer at a crash boundary.
    intents = sorted(
        name
        for name in os.listdir(fd)
        if name.startswith("image-") and name.endswith("-intent.json")
    )
    if len(intents) > 4096:
        raise ValueError("Native transition history inspection budget exhausted")
    has_release = False
    for name in intents:
        intent = _json(fd, name)
        has_release = has_release or intent.get("schema") == "lax-native-release-upgrade/v1"
        try:
            accepted = _json(fd, name.removesuffix("-intent.json") + "-accepted.json")
        except FileNotFoundError:
            raise ValueError(
                "Original native image transition requires explicit reconciliation"
            ) from None
        if (
            intent.get("schema") not in {"lax-native-image-upgrade/v1", "lax-native-release-upgrade/v1"}
            or intent.get("state") != "intent"
            or accepted != {**intent, "state": "accepted"}
        ):
            raise ValueError("Original native image transition evidence changed")
    try:
        current = _json(fd, INDEX)
    except FileNotFoundError:
        if has_release:
            raise ValueError("Original accepted release index is missing; reconcile its metadata")
        return
    if (
        current.get("schema") not in {"lax-native-image-upgrade/v1", "lax-native-release-upgrade/v1"}
        or current.get("state") != "accepted"
    ):
        raise ValueError(
            "Original native image transition requires explicit reconciliation"
        )
    accepted = _json(fd, "image-" + current["operationId"] + "-accepted.json")
    enrolled = _json(fd, "enrollment.json")
    approved = current["approvedEnrollment"]
    # A separately approved definition-only change may follow this image transition.
    if (
        accepted != current
        or set(enrolled) != set(approved)
        or any(
            enrolled[key] != value
            for key, value in approved.items()
            if key != "unitDefinitionDigest"
        )
    ):
        raise ValueError(
            "Accepted native image transition no longer matches enrollment"
        )
    if current.get("schema") == "lax-native-release-upgrade/v1":
        from .native_release import CURRENT
        if _json(fd, CURRENT) != current:
            raise ValueError("Accepted release software publication requires reconciliation")
        from .native_release_transition import _closure_identity
        _closure_identity(current)
    if not check_image:
        return
    parent = _open_directory(Path(approved["binary"]).parent)
    try:
        handle = os.open(
            Path(approved["binary"]).name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent
        )
        try:
            info = os.fstat(handle)
            _owned(info, 0)
            if list(_identity(info)) != current["imageIdentity"]:
                raise ValueError(
                    "Accepted native image changed; explicit transition required"
                )
        finally:
            os.close(handle)
    finally:
        os.close(parent)


def _journal_snapshot(state_fd, uid, authority, host, agent):
    """Inspect all canonical attempts and original indexes without recovery writes."""
    hashes, records = {}, {}
    budget = 0

    def read(fd, name, relative):
        nonlocal budget
        data = _read(fd, name, uid)
        budget += len(data)
        if budget > 64 * 1024 * 1024:
            raise ValueError("Local journal inspection budget exhausted")
        hashes[relative] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    def validate(value):
        scope = execution_scope(value)
        if (scope["authorityId"], scope["hostId"], scope["agentId"]) != (
            authority,
            host,
            agent,
        ):
            raise ValueError("Local execution belongs to another original owner")
        if ExecutionJournals.is_unsettled(value):
            raise ValueError("Original local execution remains unsettled")

    def child(fd, name):
        opened = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            _owned(os.fstat(opened), uid, directory=True)
        except BaseException:
            os.close(opened)
            raise
        return opened

    try:
        executions = child(state_fd, "executions")
    except FileNotFoundError:
        executions = None
    if executions is not None:
        try:
            for delivery in sorted(os.listdir(executions)):
                if delivery == "open":
                    continue
                if str(UUID(delivery)) != delivery:
                    raise ValueError("Unknown original execution directory")
                delivery_fd = child(executions, delivery)
                try:
                    for generation in sorted(os.listdir(delivery_fd)):
                        if (
                            not generation.isdecimal()
                            or str(int(generation)) != generation
                            or int(generation) < 1
                        ):
                            raise ValueError("Unknown original execution generation")
                        generation_fd = child(delivery_fd, generation)
                        try:
                            relative = (
                                "executions/"
                                + delivery
                                + "/"
                                + generation
                                + "/execution.json"
                            )
                            value = read(generation_fd, "execution.json", relative)
                            validate(value)
                            key = execution_key(value)
                            if (key["deliveryId"], str(key["generation"])) != (
                                delivery,
                                generation,
                            ):
                                raise ValueError(
                                    "Execution path differs from its original identity"
                                )
                            records[(delivery, generation)] = value
                            if len(records) > 4096:
                                raise ValueError(
                                    "Local execution inspection budget exhausted"
                                )
                        finally:
                            os.close(generation_fd)
                finally:
                    os.close(delivery_fd)
            try:
                opened = child(executions, "open")
            except FileNotFoundError:
                opened = None
            if opened is not None:
                try:
                    for name in sorted(os.listdir(opened)):
                        delivery, generation = name.rsplit(".", 1)
                        target = os.readlink(name, dir_fd=opened)
                        if (
                            (delivery, generation) not in records
                            or target
                            != "../" + delivery + "/" + generation + "/execution.json"
                        ):
                            raise ValueError(
                                "Dangling or changed original open-execution reference"
                            )
                        hashes["executions/open/" + name] = hashlib.sha256(
                            target.encode()
                        ).hexdigest()
                finally:
                    os.close(opened)
        finally:
            os.close(executions)
    try:
        projection = read(state_fd, "execution.json", "execution.json")
        validate(projection)
    except FileNotFoundError:
        projection = None
    try:
        selection = read(state_fd, "execution-current.json", "execution-current.json")
    except FileNotFoundError:
        selection = None
    if selection is not None:
        selected = records.get((selection["deliveryId"], str(selection["generation"])))
        if (
            not selected
            or execution_key(selected) != selection
            or selected != projection
        ):
            raise ValueError(
                "Original execution projection requires explicit reconciliation"
            )
    return hashes


def _canonical(config, controller, host, agent):
    pending = request(
        controller["hollywoodUrl"],
        config["token"],
        "GET",
        "connector/pending?hostId=" + host,
    )
    if (
        pending["enabled"] is not False
        or pending["busy"] is not None
        or pending["pending"] is not None
    ):
        raise ValueError(
            "Canonical placement must stay disabled with no busy or pending work"
        )
    after, seen = None, set()
    for _ in range(16):
        route = "hosts/" + host + "/executors" + ("?after=" + after if after else "")
        page = request(controller["hollywoodUrl"], controller["token"], "GET", route)
        if any(str(row["agent"]) == agent for row in page["executors"]):
            raise ValueError(
                "Original canonical executor lacks independent stopped evidence"
            )
        after = page["nextAfter"]
        if not after:
            return
        after = str(UUID(after))
        if after in seen:
            raise ValueError("Canonical executor cursor repeated")
        seen.add(after)
    raise ValueError("Bounded canonical executor inspection exhausted")


def _offline(
    authority, host, agent, uid, home, binary, old, expected_definition, root_fd
):
    info = observer.properties(observer.installed_unit(authority, agent))
    if (
        info["ActiveState"] not in {"inactive", "failed"}
        or int(info["MainPID"]) != 0
        or (info["ControlGroup"] and observer.members(info["ControlGroup"]))
    ):
        raise ValueError(
            "Native image transition requires a stopped empty managed service"
        )
    if pwd.getpwnam(info["User"]).pw_uid != uid:
        raise ValueError("Installed service user differs from its original owner")
    definition = observer.unit_definition(info)
    if definition != expected_definition:
        raise ValueError("Protected service definition changed")
    keys = (
        "authorityId",
        "hostId",
        "agentId",
        "uid",
        "home",
        "unit",
        "binary",
        "machineIdentity",
        "killMode",
    )
    expected = (
        authority,
        host,
        agent,
        uid,
        str(home),
        info["Id"],
        str(binary),
        machine_identity(),
        "control-group",
    )
    if tuple(old[k] for k in keys) != expected:
        raise ValueError(
            "Image transition cannot change identity, unit, path, home or host"
        )
    for name in sorted(os.listdir(root_fd)):
        if not name.endswith(".json"):
            continue
        prior = _json(root_fd, name)
        if prior.get("schema") != "lax-service-incarnation/v1":
            continue
        running = observer.process(prior["guardianPid"])
        if running and running["start"] == prior["guardianStart"]:
            raise ValueError("A prior registered guardian still exists")
        if observer.members(prior["controlGroup"]):
            raise ValueError("An original service invocation has remaining descendants")
    return info


def approve_image_upgrade(
    authority,
    host,
    agent,
    expected_enrollment,
    expected_definition,
    expected_image_sha256,
):
    """Approve only an offline, disabled, drained, exact-image local transition.

    Returns no execution readiness. Root separately activates/registers the service
    and re-enables placement after qualification. Never replay an interrupted intent.
    """
    if os.geteuid() != 0:
        raise PermissionError("Verified installation administrator required")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    for value in (expected_enrollment, expected_definition, expected_image_sha256):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError(
                "Explicit original enrollment, definition and image SHA256 required"
            )
    root = observer.directory(authority, host, agent)
    with registry_lock(root) as root_fd, contextlib.ExitStack() as stack:
        require_settled_transition(root_fd, check_image=False)
        try:
            prior_transition = _json(root_fd, INDEX)
        except FileNotFoundError:
            prior_transition = None
        old = _json(root_fd, "enrollment.json")
        if observer.digest(old) != expected_enrollment:
            raise ValueError("Original enrollment changed; inspect without replay")
        uid, home, configured_binary = observer.expected_owner(authority, agent)
        binary = Path(configured_binary)
        if not binary.is_absolute() or str(binary) != old["binary"]:
            raise ValueError(
                "Native image transition preserves the exact installed path"
            )
        state = Path(home) / "state"
        state_fd = _open_directory(state, uid)
        stack.callback(os.close, state_fd)
        lock = os.open("connector.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=state_fd)
        stack.callback(os.close, lock)
        _owned(os.fstat(lock), uid)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        home_fd = _open_directory(home, uid)
        stack.callback(os.close, home_fd)
        config = _json(home_fd, "connector.json", uid)
        if (config["agentId"], config["hostId"], config["state"], config["binary"]) != (
            agent,
            host,
            str(state),
            str(binary),
        ):
            raise ValueError("Installed connector identity or paths changed")
        controller_fd = _open_directory(root.parent.parent)
        stack.callback(os.close, controller_fd)
        controller = _json(controller_fd, "controller.json")
        if (
            controller["authorityId"],
            controller["hostId"],
            controller["machineIdentity"],
            controller["hollywoodUrl"],
        ) != (authority, host, machine_identity(), config["hollywoodUrl"]):
            raise ValueError("Enrolled host controller route or identity changed")
        initial = _offline(
            authority, host, agent, uid, home, binary, old, expected_definition, root_fd
        )
        journals = _journal_snapshot(state_fd, uid, authority, host, agent)
        _canonical(config, controller, host, agent)
        image_parent = _open_directory(binary.parent)
        stack.callback(os.close, image_parent)
        image_fd = os.open(
            binary.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=image_parent
        )
        stack.callback(os.close, image_fd)
        image = os.fstat(image_fd)
        _owned(image, 0)
        if not image.st_mode & 0o111:
            raise ValueError("Approved native image must be executable")
        checksum = hashlib.sha256()
        while chunk := os.read(image_fd, 1024 * 1024):
            checksum.update(chunk)
        if checksum.hexdigest() != expected_image_sha256:
            raise ValueError("Native image differs from its explicitly approved SHA256")
        base = Path("/var/lib/harness") / authority
        global_receipt = observer.protected(base / "global-admin-receipt.json")
        intent_path = (
            base / "global-admin-intent.json"
            if global_receipt["agentId"] == agent
            else base / "workers" / agent / "provision-intent.json"
        )
        from .native_release import active_spec
        spec = active_spec(observer.protected(intent_path)["spec"], authority, host, agent)
        package = preflight_as_owner(binary, spec["interpreter"], uid, home)
        if package["assets"]["entrypoint"]["sha256"] != expected_image_sha256:
            raise ValueError("Service-identity package probe saw another native image")
        package_pins = []
        if set(package["assets"]) != {
            "entrypoint",
            "codeModeHost",
            "bubblewrap",
            "ripgrep",
        }:
            raise ValueError("Complete maintained package proof required")
        package_metadata = Path(package["packageRoot"]) / "codex-package.json"
        metadata_info = package_metadata.lstat()
        metadata_asset = {
            "path": str(package_metadata),
            "device": metadata_info.st_dev,
            "inode": metadata_info.st_ino,
            "size": metadata_info.st_size,
            "sha256": package["metadataSha256"],
        }
        for asset in [*package["assets"].values(), metadata_asset]:
            asset_path = Path(asset["path"])
            parent_fd = _open_directory(asset_path.parent)
            stack.callback(os.close, parent_fd)
            handle = os.open(
                asset_path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            stack.callback(os.close, handle)
            info = os.fstat(handle)
            _owned(info, 0)
            checksum = hashlib.sha256()
            while chunk := os.read(handle, 1024 * 1024):
                checksum.update(chunk)
            if (info.st_dev, info.st_ino, info.st_size, checksum.hexdigest()) != (
                asset["device"],
                asset["inode"],
                asset["size"],
                asset["sha256"],
            ):
                raise ValueError(
                    "Protected package asset differs from service-identity preflight"
                )
            package_pins.append((asset_path, parent_fd, handle, info))
        upgraded = {
            **old,
            "unitDefinitionDigest": expected_definition,
            "binaryDevice": image.st_dev,
            "binaryInode": image.st_ino,
        }
        if (
            prior_transition is not None
            and upgraded == old
            and prior_transition["approvedImageSha256"] == expected_image_sha256
            and prior_transition["imageIdentity"] == list(_identity(image))
        ):
            raise ValueError("Approved image and definition are already enrolled")
        operation = observer.digest(
            [
                expected_enrollment,
                expected_definition,
                expected_image_sha256,
                prior_transition["operationId"] if prior_transition else None,
            ]
        )
        name = "image-" + operation
        if any(
            (root / (name + suffix)).exists()
            for suffix in ("-intent.json", "-accepted.json")
        ):
            raise ValueError("Original image transition exists; inspect without replay")

        def check_package_pins():
            for path, parent, handle, original in package_pins:
                if _identity(original) != _identity(os.fstat(handle)) or _identity(
                    original
                ) != _identity(
                    os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                ):
                    raise ValueError("Protected complete-package asset changed")
                fresh = _open_directory(path.parent)
                try:
                    if (os.fstat(parent).st_dev, os.fstat(parent).st_ino) != (
                        os.fstat(fresh).st_dev,
                        os.fstat(fresh).st_ino,
                    ):
                        raise ValueError("Protected package directory identity changed")
                finally:
                    os.close(fresh)

        def recheck():
            check_package_pins()
            if _identity(image) != _identity(os.fstat(image_fd)) or _identity(
                image
            ) != _identity(
                os.stat(binary.name, dir_fd=image_parent, follow_symlinks=False)
            ):
                raise ValueError("Approved native image identity or path changed")
            fresh_parent = _open_directory(binary.parent)
            fresh_root = _open_directory(root)
            fresh_state = _open_directory(state, uid)
            try:
                for earlier, fresh in (
                    (image_parent, fresh_parent),
                    (root_fd, fresh_root),
                    (state_fd, fresh_state),
                ):
                    if (os.fstat(earlier).st_dev, os.fstat(earlier).st_ino) != (
                        os.fstat(fresh).st_dev,
                        os.fstat(fresh).st_ino,
                    ):
                        raise ValueError("Transition directory identity changed")
            finally:
                for fresh in (fresh_parent, fresh_root, fresh_state):
                    os.close(fresh)
            current_lock = os.stat(
                "connector.lock", dir_fd=state_fd, follow_symlinks=False
            )
            if (current_lock.st_dev, current_lock.st_ino) != (
                os.fstat(lock).st_dev,
                os.fstat(lock).st_ino,
            ):
                raise ValueError("Connector exclusion lock was replaced")
            if (
                _offline(
                    authority,
                    host,
                    agent,
                    uid,
                    home,
                    binary,
                    old,
                    expected_definition,
                    root_fd,
                )
                != initial
            ):
                raise ValueError("Managed service changed during image verification")
            if _journal_snapshot(state_fd, uid, authority, host, agent) != journals:
                raise ValueError(
                    "Original local journals changed during image verification"
                )
            if (
                _json(home_fd, "connector.json", uid) != config
                or _json(controller_fd, "controller.json") != controller
            ):
                raise ValueError(
                    "Installed connector/controller changed during verification"
                )
            if _json(root_fd, "enrollment.json") != old:
                raise ValueError("Enrollment CAS lost; inspect the original transition")
            _canonical(config, controller, host, agent)

        recheck()
        receipt = {
            "schema": "lax-native-image-upgrade/v1",
            "state": "intent",
            "operationId": operation,
            "authorityId": authority,
            "hostId": host,
            "agentId": agent,
            "priorEnrollmentDigest": expected_enrollment,
            "newEnrollmentDigest": observer.digest(upgraded),
            "approvedEnrollment": upgraded,
            "imageIdentity": list(_identity(image)),
            "approvedImageSha256": expected_image_sha256,
            "binaryDevice": image.st_dev,
            "binaryInode": image.st_ino,
            "imageBytes": image.st_size,
            "unitDefinitionDigest": expected_definition,
            "journalSnapshotDigest": observer.digest(journals),
            "nativePackage": package,
            "placementDisabled": True,
            "serviceStopped": True,
            "oldInvocationsDrained": True,
            "localExecutionsSettled": True,
            "modelsStarted": 0,
            "servicesStarted": 0,
            "executionReady": False,
            "admissionChanged": False,
            "boundary": "Administrator must retain disabled placement through separate activation and qualification; no distributed policy lease",
        }
        _write(root_fd, name + "-before.json", old)
        _write(root_fd, name + "-intent.json", receipt)
        _write(root_fd, INDEX, receipt, replace=True)
        # CAS under both maintained-writer locks, with durable uncertainty before mutation.
        recheck()
        _write(root_fd, "enrollment.json", upgraded, replace=True)
        if _identity(image) != _identity(os.fstat(image_fd)) or _identity(
            image
        ) != _identity(
            os.stat(binary.name, dir_fd=image_parent, follow_symlinks=False)
        ):
            raise ValueError(
                "Image changed after enrollment write; original intent remains held"
            )
        check_package_pins()
        accepted = {**receipt, "state": "accepted"}
        _write(root_fd, name + "-accepted.json", accepted)
        _write(root_fd, INDEX, accepted, replace=True)
        return accepted
