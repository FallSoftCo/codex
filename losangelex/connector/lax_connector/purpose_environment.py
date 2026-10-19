"""First-class purpose-agent environment installation; no service/model starts."""
import argparse,hashlib,json,os,pwd,shlex,stat,sys
from pathlib import Path
from uuid import UUID
from . import environment
from .journal import saved

def checked(path):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
        raise PermissionError("Installation environment artifact is not protected")
    return json.loads(path.read_text())

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def install_agent(authority,agent,*,interpreter=None):
    if os.geteuid()!=0:raise PermissionError("Installation administrator required")
    from .purpose_install import directory
    from .purpose_observer import validate
    authority,agent=str(UUID(authority)),str(UUID(agent))
    profile=environment.snapshot(authority)
    if profile["state"]!="configured":
        return {"state":"not-configured","modelsStarted":0,"servicesChanged":False}
    manifest=checked(directory(authority,agent)/"installation.json");validate(manifest)
    facts=profile["facts"]
    if facts.get("github"):
        provider_path=Path("/etc/harness")/authority/"github-provider.json"
        if facts["github"]["providerFile"]!=str(provider_path):
            raise ValueError("GitHub provider route differs from installation")
        provider=checked(provider_path)
        if (provider.get("authorityId")!=authority or provider.get("login")!=facts["github"]["login"]
                or provider.get("credentialCopiesInWorkers") is not False):
            raise ValueError("GitHub provider authority/account differs")
        pwd.getpwnam(provider["linuxAccount"])
    base=Path("/etc/harness")/authority/"agent-environments"
    base.mkdir(mode=0o755,exist_ok=True)
    if base.is_symlink() or base.stat().st_uid!=0 or base.stat().st_mode&0o022:
        raise PermissionError("Installation environment directory differs")
    base.chmod(0o755)
    accepted=base/(agent+".json")
    if accepted.exists():
        value=checked(accepted)
        if (value["authorityId"],value["agentId"],value["uid"],value["profileSha256"])!=(
                authority,agent,manifest["uid"],digest(profile["profileFile"])):
            raise ValueError("Existing environment changed; explicit reconciliation required")
        for name,expected in value["fileHashes"].items():
            if digest(name)!=expected:raise ValueError("Installed environment client changed")
        return {**value,"reconciled":True,"modelsStarted":0,"servicesChanged":False}
    binary_dir=base/agent/"bin";binary_dir.mkdir(mode=0o755,parents=True,exist_ok=True)
    for p in (binary_dir.parent,binary_dir):
        if p.is_symlink() or p.stat().st_uid!=0 or p.stat().st_mode&0o022:
            raise PermissionError("Installed environment binary directory differs")
        p.chmod(0o755)
    python=interpreter or manifest["interpreter"]
    image=Path(python).resolve(strict=True)
    if image.stat().st_uid!=0 or image.stat().st_mode&0o022:
        raise PermissionError("Approved environment interpreter differs")
    clients={}
    if facts.get("github"):
        clients["gh"]=[python,"-I","-B","-m","lax_connector.github_client"]
    if facts.get("sshRoutes"):
        clients["ssh"]=[python,"-I","-B","-m","lax_connector.environment_client","ssh"]
    hashes={}
    for name,command in clients.items():
        path=binary_dir/name
        content="#!/bin/sh\nexec "+" ".join(shlex.quote(x) for x in command)+' "$@"\n'
        if path.exists():raise ValueError("Unreceipted environment executable; inspect original setup")
        with path.open("x") as f:f.write(content);f.flush();os.fsync(f.fileno())
        path.chmod(0o755);hashes[str(path)]=digest(path)
    value={"schema":"lax-purpose-environment/v1","authorityId":authority,"agentId":agent,
        "uid":manifest["uid"],"linuxUser":manifest["linuxUser"],"binDirectory":str(binary_dir),
        "profileFile":profile["profileFile"],"profileSha256":digest(profile["profileFile"]),
        "clientInterpreter":python,"fileHashes":hashes,"credentialCopiesInWorkers":False,
        "modelsStarted":0,"servicesChanged":False}
    saved(accepted,value);accepted.chmod(0o644)
    return value

def activate(authority,agent):
    """Set only this process's child environment; never persist credentials."""
    path=Path("/etc/harness")/str(UUID(authority))/"agent-environments"/(str(UUID(agent))+".json")
    if not path.exists():return {"state":"not-configured"}
    value=checked(path)
    from .environment_identity import current
    identity=current()
    if not identity or (identity["authorityId"],identity["agentId"],os.geteuid())!=(
            value["authorityId"],value["agentId"],value["uid"]):
        raise PermissionError("Installed environment belongs to another execution identity")
    if digest(value["profileFile"])!=value["profileSha256"]:
        raise ValueError("Installation environment profile changed")
    for name,expected in value["fileHashes"].items():
        checked_file=Path(name);info=checked_file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or digest(name)!=expected:
            raise PermissionError("Installation environment client changed")
    directory=value["binDirectory"]
    os.environ["PATH"]=directory+os.pathsep+os.environ.get("PATH","/usr/bin:/bin")
    facts=environment.snapshot(authority)["facts"]
    if facts.get("github"):
        count=int(os.environ.get("GIT_CONFIG_COUNT","0"))
        if not 0<=count<=64:raise ValueError("Git inherited configuration is unbounded")
        entries=[("credential.https://github.com.helper",""),
                 ("credential.https://github.com.helper","!"+shlex.quote(str(Path(directory)/"gh"))+" auth git-credential"),
                 ("url.https://github.com/.insteadOf","git@github.com:"),
                 ("url.https://github.com/.insteadOf","ssh://git@github.com/")]
        for i,(key,item) in enumerate(entries,count):
            os.environ["GIT_CONFIG_KEY_"+str(i)]=key;os.environ["GIT_CONFIG_VALUE_"+str(i)]=item
        os.environ["GIT_CONFIG_COUNT"]=str(count+len(entries))
        os.environ["GIT_TERMINAL_PROMPT"]="0"
    return {"state":"configured","profileFile":value["profileFile"],"credentialCopiesInWorkers":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--authority",required=True);parser.add_argument("--agent",required=True)
    parser.add_argument("--profile",type=Path);parser.add_argument("--provider",type=Path)
    parser.add_argument("--interpreter")
    args=parser.parse_args()
    if os.geteuid()!=0:raise PermissionError("Installation administrator required")
    authority=str(UUID(args.authority))
    if args.profile:environment.install(authority,args.profile)
    if args.provider:
        provider=checked(args.provider)
        if provider.get("authorityId")!=authority or provider.get("credentialCopiesInWorkers") is not False:
            raise ValueError("Approved provider belongs to another installation")
        destination=Path("/etc/harness")/authority/"github-provider.json"
        if destination.exists() and checked(destination)!=provider:
            raise ValueError("Existing provider changed; explicit reconciliation required")
        if not destination.exists():saved(destination,provider);destination.chmod(0o644)
    print(json.dumps(install_agent(authority,args.agent,interpreter=args.interpreter)))

if __name__=="__main__":main()
