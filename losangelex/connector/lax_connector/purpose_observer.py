"""Observe installed purpose services through the existing non-model host controller."""
import hashlib
import json
import os
import pwd
from pathlib import Path
from uuid import UUID

from . import service_observer as observer
from .host import machine_identity
from .journal import saved
from .purpose_install import directory, protected, checksum, PURPOSES, SCHEMA


def installation(authority,agent):
    path=directory(authority,agent)/"installation.json"
    return protected(path) if path.exists() else None


def validate(value):
    if value["schema"]!=SCHEMA or value["machineIdentity"]!=machine_identity():
        raise ValueError("Purpose installation belongs to another host")
    account=pwd.getpwnam(value["linuxUser"])
    if (account.pw_uid,account.pw_dir)!=(value["uid"],value["home"]):
        raise ValueError("Installed Unix identity changed")
    config=Path(value["config"])
    if config.is_symlink() or config.stat().st_uid!=0 or checksum(config)!=value["configSha256"]:
        raise ValueError("Installed purpose configuration changed")
    image=Path(value["binary"]).stat()
    if (image.st_dev,image.st_ino)!=(value["binaryDevice"],value["binaryInode"]):
        raise ValueError("Installed native image changed")
    slice_file=Path("/etc/systemd/system")/value["slice"]
    if (slice_file.stat().st_uid!=0 or slice_file.is_symlink()
            or checksum(slice_file)!=value["sliceDefinitionSha256"]):
        raise ValueError("Aggregate agent resource budget changed")


def register(value,purpose):
    """Register an actual incarnation; never start a stopped service."""
    if os.geteuid()!=0:raise PermissionError("Root observer required")
    validate(value)
    unit=value["units"][purpose]
    info=observer.properties(unit)
    if info["ActiveState"]!="active" or int(info["MainPID"])<2:
        return {"state":"stopped","purpose":purpose,"servicesStarted":0}
    if observer.unit_definition(info)!=value["unitDefinitionDigests"][unit]:
        raise ValueError("Installed purpose service changed")
    own=observer.process(int(info["MainPID"]))
    if (not own or own["uid"]!=value["uid"] or own["controlGroup"]!=info["ControlGroup"]
            or pwd.getpwnam(info["User"]).pw_uid!=value["uid"]):
        raise ValueError("Actual purpose guardian differs")
    expected=[value["interpreter"],"-m","lax_connector.context_runtime",
              "--config",value["config"],"--purpose",purpose]
    args=Path("/proc",str(own["pid"]),"cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
    interpreter=Path(value["interpreter"]).resolve().stat()
    if (args!=expected or own["executableDevice"]!=interpreter.st_dev
            or own["executableInode"]!=interpreter.st_ino or info.get("NeedDaemonReload")=="yes"):
        raise ValueError("Purpose runtime launcher differs")
    binding={"schema":"lax-service-incarnation/v1","authorityId":value["authorityId"],
        "hostId":value["hostId"],"agentId":value["agentId"],"uid":value["uid"],"home":value["home"],
        "unit":unit,"unitDefinitionDigest":value["unitDefinitionDigests"][unit],
        "binary":value["binary"],"binaryDevice":value["binaryDevice"],"binaryInode":value["binaryInode"],
        "machineIdentity":value["machineIdentity"],"killMode":"control-group","purpose":purpose,
        "bootId":observer.boot_id(),"serviceInvocation":UUID(info["InvocationID"]).hex,
        "controlGroup":info["ControlGroup"],"guardianPid":own["pid"],"guardianStart":own["start"]}
    if observer.process(own["pid"])!=own:
        raise ValueError("Purpose guardian changed during registration")
    root=directory(value["authorityId"],value["agentId"])/"incarnations"
    root.mkdir(mode=0o700,exist_ok=True)
    target=root/(binding["serviceInvocation"]+".json")
    if target.exists():
        if protected(target)!=binding:raise ValueError("Original purpose incarnation changed")
        changed=False
    else:
        saved(target,binding)
        changed=True
    return {"state":"registered","purpose":purpose,"changed":changed,"unit":unit,
            "serviceInvocation":binding["serviceInvocation"],"servicesStarted":0}


def reconcile(config):
    root=Path("/var/lib/harness")/config["authorityId"]/"purpose-agents"
    result={"registered":0,"held":0,"modelsStarted":0,"servicesStarted":0,"results":[]}
    if not root.exists():return result
    paths=sorted(root.glob("*/installation.json"))
    if len(paths)>256:raise ValueError("Bounded installed-agent inspection exceeded")
    for path in paths:
        value=protected(path)
        if value["hostId"]!=config["hostId"]:continue
        for purpose in PURPOSES:
            try:
                row=register(value,purpose)
            except Exception as error:
                row={"state":"held","purpose":purpose,"agentId":value["agentId"],
                     "reason":type(error).__name__,"detail":str(error)[:200]}
            result["results"].append(row)
            result["registered"]+=bool(row.get("changed"))
            result["held"]+=row["state"]=="held"
    return result


def observe(config,row):
    value=installation(config["authorityId"],row["agent"])
    if value is None:return None
    validate(value)
    if row["descriptor"]["serviceUnit"] not in value["units"].values():
        raise ValueError("Executor is not an installed purpose service")
    return observer.observe(config,row,registry=directory(config["authorityId"],row["agent"])/"incarnations")
