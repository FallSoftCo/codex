"""Install one Hollywood-native LAX agent; no model or semantic orchestration."""
import argparse
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from .host import machine_identity, request
from .journal import saved
from .native_package import preflight_as_owner
from .service_memory import validate

PURPOSES=("reader","writer","responder")
SCHEMA="lax-purpose-installation/v1"


def directory(authority,agent):
    return Path("/var/lib/harness")/str(UUID(authority))/"purpose-agents"/str(UUID(agent))


def checksum(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda:stream.read(1024*1024),b""):h.update(data)
    return h.hexdigest()


def protected(path):
    path=Path(path)
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise PermissionError("Installation record is not administrator protected")
    return json.loads(path.read_text())


def original(path,value):
    if path.exists():
        if protected(path)!=value:raise ValueError("Original installation changed; explicit upgrade required")
    else:saved(path,value)


def file_once(path,text,mode=0o644):
    if path.exists():
        if path.is_symlink() or path.stat().st_uid!=0 or path.read_text()!=text:
            raise ValueError("Existing installed file differs")
    else:
        path.write_text(text)
        path.chmod(mode)


def canonical(spec,config):
    value=request(config["hollywoodUrl"],spec["credential"],"GET","agents/"+config["agentId"]+"/context-system")
    system=value["system"]
    expected={k:config[k] for k in ("agentId","authorityId","hostId","workspaceId")}
    if any(system[k]!=v for k,v in expected.items()):
        raise ValueError("Canonical Hollywood context installation differs")
    by_purpose={b["purpose"]:b for b in value["bindings"]}
    for purpose in PURPOSES:
        b=by_purpose[purpose]
        if (b["contextId"]!=config["contextIds"][purpose] or
                b["credentialDigest"]!=hashlib.sha256(json.dumps(config["tokens"][purpose],sort_keys=True,separators=(",",":")).encode()).hexdigest()):
            raise ValueError("Purpose credentials differ from canonical enrollment")
    return value


def adopt(source,config,uid,gid,record):
    """Explicit stopped QA ownership adoption; bytes and canonical paths stay."""
    source=Path(source)
    if source.is_symlink() or not source.is_dir():raise ValueError("Exact private adoption tree required")
    for path in (Path(config["state"]),Path(config["workspace"]),*(Path(v) for v in config["homes"].values())):
        if not path.is_relative_to(source) or ".." in path.parts:
            raise ValueError("Adoption path escaped its explicit tree")
    entries={}
    paths=[source,*source.rglob("*")]
    if len(paths)>20000:raise ValueError("Bounded adoption file budget exceeded")
    total=0
    for path in paths:
        info=path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("Adoption requires ordinary stopped files/directories")
        row={"uid":info.st_uid,"gid":info.st_gid,"mode":stat.S_IMODE(info.st_mode)}
        if path.is_file():
            total+=info.st_size
            if total>512*1024**2:raise ValueError("Bounded adoption byte budget exceeded")
            row["sha256"]=checksum(path)
        entries[str(path)]=row
    intent=record/"adoption-intent.json"
    if intent.exists():
        prior=protected(intent)
        if prior["source"]!=str(source) or (prior["uid"],prior["gid"])!=(uid,gid) or set(prior["entries"])!=set(entries):
            raise ValueError("Original adoption tree or target differs")
        for name,row in entries.items():
            old=prior["entries"][name]
            if (row.get("sha256")!=old.get("sha256") or row["mode"]!=old["mode"]
                    or (row["uid"],row["gid"]) not in ((old["uid"],old["gid"]),(uid,gid))):
                raise ValueError("Original adoption content or ownership changed")
        entries=prior["entries"]
    else:
        original(intent,{"source":str(source),"entries":entries,"uid":uid,"gid":gid})
    for path in paths:os.chown(path,uid,gid)
    for name,row in entries.items():
        if "sha256" in row and checksum(name)!=row["sha256"]:
            raise ValueError("Adopted original content changed")
    result={"source":str(source),"files":len(entries),"bytes":total,"contentCanariesMatched":True,
            "originalPathsPreserved":True,"nativeHistoriesReplaced":False}
    saved(record/"adoption-receipt.json",result)
    return result


def model_account(path):
    """Compare approved account identity while preserving per-context token refreshes."""
    value=json.loads(Path(path).read_text())
    mode=value.get("auth_mode")
    account=value.get("tokens",{}).get("account_id") if isinstance(value.get("tokens"),dict) else None
    key=value.get("OPENAI_API_KEY")
    if mode=="chatgpt" and isinstance(account,str) and account:
        identity={"mode":mode,"account":account}
    elif isinstance(key,str) and key:
        identity={"mode":mode,"keyDigest":hashlib.sha256(key.encode()).hexdigest()}
    else:
        raise ValueError("Approved native model account identity unavailable")
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()


def install(spec):
    if os.geteuid()!=0:raise PermissionError("Verified root installation required")
    authority,agent,host=[str(UUID(spec[k])) for k in ("authorityId","agentId","hostId")]
    if spec["machineIdentity"]!=machine_identity():raise ValueError("Installation host identity differs")
    record=directory(authority,agent)
    record.mkdir(parents=True,exist_ok=True,mode=0o700)
    if record.is_symlink() or record.stat().st_uid!=0:raise ValueError("Installation root differs")
    record.chmod(0o700)
    digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    original(record/"intent.json",{"digest":digest,"spec":spec})
    if spec.get("environmentProfileFile"):
        from .environment import install as install_environment
        install_environment(authority,spec["environmentProfileFile"])
    accepted=record/"installation.json"
    if accepted.exists():
        value=protected(accepted)
        if value["specDigest"]!=digest:raise ValueError("Accepted installation changed")
        from .purpose_observer import validate as validate_installation
        validate_installation(value)
        canonical(spec,json.loads(Path(value["config"]).read_text()))
        from .purpose_resources import ensure as ensure_resources
        ensure_resources(json.loads(Path(value["config"]).read_text()))
        from .purpose_environment import install_agent
        install_agent(authority,agent)
        return {**public(value),"reconciled":True,"servicesStarted":False}
    slug=authority.replace("-","")[:8]+"-"+agent.replace("-","")[:12]
    user=("hglobal-" if spec.get("global") else "hagent-")+slug
    home=record/"home"
    try:
        account=pwd.getpwnam(user)
        if account.pw_dir!=str(home):raise ValueError("Unix identity belongs to another installation")
    except KeyError:
        subprocess.run(["useradd","--system","--user-group","--create-home","--home-dir",str(home),
                        "--shell","/bin/bash",user],check=True,capture_output=True)
        account=pwd.getpwnam(user)
    # Parent traversal grants no read of another agent's private records.
    parent=record
    while parent!=Path("/var/lib/harness"):
        parent.chmod(0o711)
        parent=parent.parent
    home.chmod(0o700)
    uid,gid=account.pw_uid,account.pw_gid
    if spec.get("sourceConfig"):
        config=json.loads(Path(spec["sourceConfig"]).read_text())
        if checksum(spec["sourceConfig"])!=spec["sourceConfigurationSha256"]:
            raise ValueError("Approved original context configuration changed")
    else:
        config={k:spec[k] for k in ("authorityId","agentId","hostId","workspaceId","contextIds","tokens",
                                  "hollywoodUrl","binary","model","effort")}
        config.update(state=str(home/"state"),workspace=str(home/"work"),
            homes={p:str(home/("native-"+p)) for p in PURPOSES})
    if any(config[k]!=v for k,v in (("authorityId",authority),("agentId",agent),("hostId",host))):
        raise ValueError("Agent identity changed during installation")
    canonical(spec,config)
    config.update(binary=spec["binary"],model=spec["model"],effort=spec["effort"],
        sandbox="danger-full-access",approvalPolicy="never",requireAdministrator=bool(spec.get("global")),
        installedPurposeRuntime=True,installationRecord=str(accepted),pythonRoot=spec["pythonRoot"],
        workerServiceMemoryMaxBytes=spec.get("serviceMemoryMaxBytes",8*1024**3))
    if spec.get("nativeCollaborationChannel"):
        config["nativeCollaborationChannel"]=spec["nativeCollaborationChannel"]
    if spec.get("sourceConfig"):
        adopt(spec["adoptRoot"],config,uid,gid,record)
    for path in (Path(config["state"]),Path(config["workspace"]),*(Path(v) for v in config["homes"].values())):
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chown(path,uid,gid)
    auth_source=Path(spec["approvedModelAuthFile"])
    if not auth_source.is_file():raise ValueError("Approved model authentication unavailable")
    auth_account=model_account(auth_source)
    for path in config["homes"].values():
        auth=Path(path)/"auth.json"
        if auth.exists() and model_account(auth)!=auth_account:
            raise ValueError("Model account differs; explicit account migration required")
        if not auth.exists():shutil.copyfile(auth_source,auth)
        auth.chmod(0o600);os.chown(auth,uid,gid)
    sudo=Path("/etc/sudoers.d")/("lax-agent-"+slug)
    policy=f"{user} ALL=(ALL:ALL) NOPASSWD: ALL\n"
    candidate=record/"sudoers.candidate"
    file_once(candidate,policy,0o440)
    subprocess.run(["visudo","-cf",str(candidate)],check=True,capture_output=True)
    file_once(sudo,policy,0o440)
    verified=subprocess.run(["runuser","-u",user,"--","sudo","-n","/usr/bin/id","-u"],
                            check=True,capture_output=True,text=True).stdout.strip()
    if verified!="0":raise PermissionError("Authorized host administration unavailable")
    package=preflight_as_owner(spec["binary"],spec["interpreter"],uid,home,workspace=config["workspace"])
    runtime=json.loads(subprocess.run(["runuser","-u",user,"--",spec["interpreter"],"-I","-B","-c",
        "import json,sys,lax_connector.context_runtime as c;print(json.dumps({'module':c.__file__,'prefix':sys.prefix}))"],
        check=True,capture_output=True,text=True).stdout)
    if not Path(runtime["module"]).is_relative_to(Path(spec["pythonRoot"])):
        raise ValueError("Installed interpreter loads another connector")
    config_path=home/"agent.json"
    content=json.dumps(config,indent=2)+"\n"
    file_once(config_path,content,0o440)
    os.chown(config_path,0,gid)
    slice_name="lax-agent-"+slug+".slice"
    limit=validate(spec.get("serviceMemoryMaxBytes",8*1024**3))
    slice_text=f"[Unit]\nDescription=LAX aggregate budget {agent}\n[Slice]\nMemoryMax={limit}\nCPUQuota=200%\n"
    file_once(Path("/etc/systemd/system")/slice_name,slice_text)
    units={};definitions={}
    for purpose in PURPOSES:
        unit="lax-agent-"+slug+"-"+purpose+".service"
        text=f"""[Unit]
Description=LAX {agent} {purpose}
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=3
[Service]
Type=simple
User={user}
Slice={slice_name}
WorkingDirectory={config["workspace"]}
ExecStart={spec["interpreter"]} -m lax_connector.context_runtime --config {config_path} --purpose {purpose}
Restart=on-failure
RestartSec=10
UMask=0077
KillMode=control-group
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
"""
        file_once(Path("/etc/systemd/system")/unit,text)
        units[purpose]=unit
        definitions[unit]=hashlib.sha256(text.encode()).hexdigest()
    subprocess.run(["systemctl","daemon-reload"],check=True,capture_output=True)
    image=Path(spec["binary"]).resolve(strict=True).stat()
    value={"schema":SCHEMA,"authorityId":authority,"agentId":agent,"hostId":host,
        "specDigest":digest,"uid":uid,"gid":gid,"linuxUser":user,"home":str(home),
        "config":str(config_path),"configSha256":hashlib.sha256(content.encode()).hexdigest(),
        "units":units,"unitDefinitionDigests":definitions,"slice":slice_name,
        "aggregateMemoryMaxBytes":limit,"sliceDefinitionSha256":hashlib.sha256(slice_text.encode()).hexdigest(),
        "binary":str(Path(spec["binary"]).resolve()),"binaryDevice":image.st_dev,"binaryInode":image.st_ino,
        "interpreter":spec["interpreter"],"pythonRoot":spec["pythonRoot"],"runtime":runtime,
        "approvedModelAccountDigest":auth_account,
        "machineIdentity":machine_identity(),"nativePackage":package,"sudoVerifiedUid":0,
        "servicesStarted":False,"historicalSessionsResumed":False}
    saved(accepted,value)
    from .purpose_resources import ensure as ensure_resources
    resource = ensure_resources(config)
    if resource is not None:
        saved(record/"resource-installation.json",resource)
    from .purpose_environment import install_agent
    install_agent(authority,agent)
    return public(value)


def public(value):
    return {k:value[k] for k in ("schema","authorityId","agentId","hostId","uid","linuxUser","home",
        "config","units","slice","aggregateMemoryMaxBytes","sudoVerifiedUid","servicesStarted")}


def activate(authority,agent):
    record=directory(authority,agent)
    value=protected(record/"installation.json")
    from .purpose_observer import validate as validate_installation
    validate_installation(value)
    intent=record/"activation-intent.json"
    if intent.exists():
        # Read status after an uncertain start or deliberate later stop. No replay.
        return {"activationRepeated":False,"units":{p:subprocess.check_output(
            ["systemctl","show",u,"-p","ActiveState","--value"],text=True).strip()
            for p,u in value["units"].items()}}
    original(intent,{"units":value["units"],"configurationSha256":value["configSha256"]})
    subprocess.run(["systemctl","start",*value["units"].values()],check=True,capture_output=True)
    result={"servicesStarted":True,"units":value["units"],"modelSubmissionByInstaller":False}
    saved(record/"activation-receipt.json",result)
    return result


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument("--spec",type=Path,required=True)
    parser.add_argument("--activate",action="store_true")
    args=parser.parse_args()
    spec=json.loads(args.spec.read_text())
    value=install(spec)
    if args.activate:value["activation"]=activate(spec["authorityId"],spec["agentId"])
    print(json.dumps(value))


if __name__=="__main__":main()
