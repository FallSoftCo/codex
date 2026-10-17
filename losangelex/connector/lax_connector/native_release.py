"""Reviewed immutable software closure; original provisioning remains historical."""

import base64
import hashlib
import json
import os
import pwd
import re
import subprocess
from pathlib import Path
from uuid import UUID

from . import native_image_upgrade as image, service_observer as observer
from .native_package import preflight_as_owner
from .service_restart import file_hash, file_identity

SCHEMA = "lax-native-release-upgrade/v1"
CURRENT = "native-release-current.json"


def active_spec(spec, authority, host, agent):
    root = observer.directory(authority, host, agent)
    path = root / CURRENT
    if not path.exists():
        return dict(spec)
    value = observer.protected(path)
    accepted = observer.protected(root / ("image-" + value["operationId"] + "-accepted.json"))
    intent = observer.protected(root / ("image-" + value["operationId"] + "-intent.json"))
    if (value != accepted or accepted != {**intent, "state": "accepted"} or value.get("schema") != SCHEMA
            or value.get("state") != "accepted"
            or value["scope"] != [authority, host, agent]
            or value["originalSpecDigest"] != observer.digest(spec)):
        raise ValueError("Accepted software release differs from original provisioning")
    return {**spec, "binary": value["newBinary"], "interpreter": value["newInterpreter"]}


def runtime_spec(authority, agent):
    from .service_memory import approved_spec
    spec, receipt, global_agent = approved_spec(authority, agent)
    return active_spec(spec, authority, spec["hostId"], agent), receipt, global_agent


def closure(root):
    """Hash every protected release entry, including resolved file symlink assets."""
    root = Path(root)
    fd = image._open_directory(root)
    os.close(fd)
    rows, identities, total = [], {}, 0
    for path in sorted(root.rglob("*")):
        if len(rows) >= 20000:
            raise ValueError("Software closure entry budget exhausted")
        info = path.lstat()
        if info.st_uid != 0 or (not path.is_symlink() and info.st_mode & 0o022):
            raise PermissionError("Software closure must be administrator protected")
        relative = path.relative_to(root).as_posix()
        row = {"path": relative, "mode": info.st_mode}
        if path.is_symlink():
            target = path.resolve(strict=True)
            if target.is_dir():
                if not target.is_relative_to(root):
                    raise ValueError("External directory symlink is not an immutable closure")
                h = image._open_directory(target)
                os.close(h)
                row.update(kind="directory-link", target=os.readlink(path), resolved=str(target))
            else:
                checksum, identity = file_hash(target, 0)
                row.update(kind="file-link", target=os.readlink(path), resolved=str(target),
                           sha256=checksum, identity=identity)
                total += identity[2]
        elif path.is_dir():
            row["kind"] = "directory"
        elif path.is_file():
            checksum, identity = file_hash(path, 0)
            row.update(kind="file", sha256=checksum, identity=identity)
            total += info.st_size
        else:
            raise ValueError("Unsupported software closure entry")
        if total > 4 * 1024**3:
            raise ValueError("Software closure byte budget exhausted")
        rows.append(row)
        identities[relative] = list(image._identity(info))
    return {"root": str(root), "rootIdentity": list(image._identity(root.stat())),
            "entries": rows, "identities": identities, "bytes": total}


def probe(binary, interpreter, uid, home, release):
    package = preflight_as_owner(binary, interpreter, uid, home)
    if set(package["assets"]) != {"entrypoint", "codeModeHost", "bubblewrap", "ripgrep"}:
        raise ValueError("Complete native package and helper proof required")
    account = pwd.getpwuid(uid)
    script = ("import json,sys,lax_connector.connector as c;"
              "print(json.dumps({'uid':__import__('os').geteuid(),"
              "'module':c.__file__,'prefix':sys.prefix}))")
    result = subprocess.run(
        ["runuser", "-u", account.pw_name, "--", str(interpreter), "-I", "-B", "-c", script],
        env={"PATH": "/usr/bin:/bin", "HOME": str(home),
             "CODEX_HOME": str(home / "codex-home")},
        stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
    )
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError("Service-UID connector interpreter startup failed")
    value = json.loads(result.stdout)
    if (value["uid"] != uid
            or not Path(value["module"]).resolve().is_relative_to(release)
            or not Path(value["prefix"]).resolve().is_relative_to(release)):
        raise ValueError("Service interpreter loaded a different software closure")
    return {"nativePackage": package, "connector": value,
            "outputSha256": hashlib.sha256(result.stdout + result.stderr).hexdigest(),
            "modelsStarted": 0, "servicesStarted": 0}


def physical(home, uid):
    result = {}
    if Path(pwd.getpwuid(uid).pw_dir) != home:
        raise ValueError("Original NSS home differs")
    for path in (home, home / "work", home / "state", home / "codex-home"):
        fd = image._open_directory(path, uid)
        try:
            info = os.fstat(fd)
            result[str(path)] = [info.st_dev, info.st_ino, info.st_uid]
        finally:
            os.close(fd)
    return result


def prepare(authority, host, agent, request, output):
    if os.geteuid() != 0:
        raise PermissionError("Verified release administrator required")
    authority, host, agent = [str(UUID(v)) for v in (authority, host, agent)]
    scope = [authority, host, agent]
    root = observer.directory(*scope)
    from .service_memory import approved_spec
    from .service_restart import settled_definitions
    from .collaboration_install import protected_tree
    with image.registry_lock(root) as fd:
        image.require_settled_transition(fd)
        settled_definitions(root)
        old = image._json(fd, "enrollment.json")
        spec, _, _ = approved_spec(authority, agent)
        uid, home, _ = observer.expected_owner(authority, agent)
        home = Path(home)
        config_path = home / "connector.json"
        config_bytes = config_path.read_bytes()
        config_hash, _ = file_hash(config_path, uid)
        info = observer.properties(observer.installed_unit(authority, agent))
        unit_path = Path(info["FragmentPath"])
        definition = observer.unit_definition(info)
        before_unit = unit_path.read_bytes()
        if (observer.digest(old) != request["expectedEnrollment"]
                or config_hash != request["expectedConfigurationSha256"]
                or definition != request["expectedDefinition"]
                or hashlib.sha256(config_bytes).hexdigest() != config_hash
                or hashlib.sha256(before_unit).hexdigest() != definition):
            raise ValueError("Original enrollment/configuration/unit CAS changed")
        enrolled_image = Path(old["binary"]).stat()
        if (enrolled_image.st_dev, enrolled_image.st_ino) != (old["binaryDevice"], old["binaryInode"]):
            raise ValueError("Original enrolled native image identity changed")
        config = json.loads(config_bytes)
        old_root, new_root = [Path(request[k]) for k in ("oldReleaseRoot", "newReleaseRoot")]
        old_binary, new_binary = [Path(request[k]) for k in ("oldBinary", "newBinary")]
        old_python, new_python = [Path(request[k]) for k in ("oldInterpreter", "newInterpreter")]
        for path, release in ((old_binary, old_root), (old_python, old_root),
                              (new_binary, new_root), (new_python, new_root)):
            if (not path.is_absolute() or ".." in path.parts or not path.is_relative_to(release)
                    or not re.fullmatch(r"/[A-Za-z0-9_./+-]+", str(path))):
                raise ValueError("Exact old/new paths must belong to their reviewed release and be literal unit paths")
        if old_root == new_root or old_root.is_relative_to(new_root) or new_root.is_relative_to(old_root):
            raise ValueError("Distinct nonnested immutable release paths required")
        h = image._open_directory(old_root)
        os.close(h)
        file_identity(old_binary)
        h = image._open_directory(old_python.parent)
        os.close(h)
        if old_python.lstat().st_uid != 0:
            raise PermissionError("Original interpreter path is not root owned")
        if str(old_binary.resolve(strict=True)) != str(old_binary):
            raise ValueError("Native entrypoints must be exact nonsymlink paths")
        if str(new_binary.resolve(strict=True)) != str(new_binary):
            raise ValueError("New native entrypoint must be an exact nonsymlink path")
        before_exec = f"ExecStart={old_python} -m lax_connector.connector --config {config_path} --serve"
        after_exec = f"ExecStart={new_python} -m lax_connector.connector --config {config_path} --serve"
        if (config["binary"] != str(old_binary)
                or config["agentId"] != agent or config["hostId"] != host
                or config["state"] != str(home / "state")
                or config["workspace"] != str(home / "work")
                or config["codexHome"] != str(home / "codex-home")
                or before_unit.decode().splitlines().count(before_exec) != 1
                or len(re.findall(r"(?m)^ExecStart=", before_unit.decode())) != 1):
            raise ValueError("Reviewed original connector/ExecStart identity differs")
        software = closure(new_root)
        probes = probe(new_binary, new_python, uid, home, new_root)
        if not Path(probes["nativePackage"]["packageRoot"]).is_relative_to(new_root):
            raise ValueError("Native package escaped new release")
        if closure(new_root) != software:
            raise ValueError("Release changed during actual service-UID startup")
        if config_path.read_bytes() != config_bytes or unit_path.read_bytes() != before_unit:
            raise ValueError("Original configuration/unit changed during review")
        new_config = (json.dumps({**config, "binary": str(new_binary)}, indent=2) + "\n").encode()
        new_unit = "\n".join(after_exec if line == before_exec else line
                             for line in before_unit.decode().split("\n")).encode()
        image_info = new_binary.stat()
        upgraded = {**old, "binary": str(new_binary),
                    "binaryDevice": image_info.st_dev, "binaryInode": image_info.st_ino,
                    "unitDefinitionDigest": hashlib.sha256(new_unit).hexdigest()}
        physical_paths = physical(home, uid)
        targets = []
        for path, before, after, owner in (
                (config_path, config_bytes, new_config, uid),
                (unit_path, before_unit, new_unit, 0)):
            targets.append({"path": str(path), "uid": owner,
                            "mode": path.stat().st_mode & 0o777,
                            "before": base64.b64encode(before).decode(),
                            "after": base64.b64encode(after).decode()})
        prepared = {"schema": SCHEMA, "scope": scope, "state": "prepared",
                    "originalSpecDigest": observer.digest(spec), "priorEnrollment": old,
                    "approvedEnrollment": upgraded, "physical": physical_paths,
                    "unit": info["Id"], "home": str(home), "uid": uid,
                    "oldReleaseRoot": str(old_root), "newReleaseRoot": str(new_root),
                    "oldRootIdentity": list(image._identity(old_root.stat())),
                    "oldBinary": str(old_binary), "newBinary": str(new_binary),
                    "oldInterpreter": str(old_python), "newInterpreter": str(new_python),
                    "oldImageSha256": file_hash(old_binary, 0)[0],
                    "oldInterpreterIdentity": file_identity(old_python.resolve()),
                    "closure": software, "probes": probes, "targets": targets,
                    "imageIdentity": list(image._identity(image_info)),
                    "approvedImageSha256": probes["nativePackage"]["assets"]["entrypoint"]["sha256"],
                    "unitDefinitionDigest": upgraded["unitDefinitionDigest"],
                    "modelsStarted": 0, "servicesStarted": 0, "executionReady": False}
        if Path(output).is_relative_to(new_root) or Path(output).is_relative_to(home):
            raise ValueError("Review output cannot modify release or private state")
        target = protected_tree(output, 0o700)
        target_fd = image._open_directory(target)
        try:
            image._write(target_fd, "release-plan.json", prepared)
        finally:
            os.close(target_fd)
        return {"prepared": str(target / "release-plan.json"),
                "preparationDigest": observer.digest(prepared), "scope": scope,
                "closureDigest": observer.digest(software),
                "newConfigurationSha256": hashlib.sha256(new_config).hexdigest(),
                "newDefinitionSha256": hashlib.sha256(new_unit).hexdigest(),
                "probes": probes, "modelsStarted": 0, "servicesStarted": 0}
