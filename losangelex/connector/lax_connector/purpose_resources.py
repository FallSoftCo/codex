"""Register an installed agent's actual workspace through existing resource APIs."""
import os
from pathlib import Path
from uuid import UUID,uuid5
from .collaboration_bridge import digest,require,protected_directory
from .collaboration_capture import administrative_put
from .collaboration_resources import open_root
from .service_observer import protected
from .host import request
from .resource_routing import seed_defaults

def ensure(config):
    channel=config.get("nativeCollaborationChannel")
    if not channel:
        return None
    require(os.geteuid()==0,"Protected installed resource enrollment requires root")
    descriptor=Path(channel)
    protected_directory(descriptor.parent)
    require(protected(descriptor)["schema"]=="lax-native-collaboration-channel/v1",
            "Installed canonical collaboration descriptor required")
    authority,host,agent=(str(UUID(config[k])) for k in ("authorityId","hostId","agentId"))
    controller=protected(Path("/var/lib/harness")/authority/"hosts"/host/"controller.json")
    bridge=protected(Path(controller["nativeCollaborationCaptureConfig"]))
    require((bridge["authorityId"],bridge["hostId"],bridge["hollywoodUrl"])==
            (authority,host,config["hollywoodUrl"]),"Resource installation host differs")
    admin=protected(Path(bridge["automaticCapture"]["administratorConfig"]))
    require((admin["authorityId"],admin["hostId"],admin["hollywoodUrl"])==
            (authority,host,config["hollywoodUrl"]),"Protected resource administrator differs")
    http=lambda method,route,payload=None:request(admin["hollywoodUrl"],admin["token"],method,route,payload)
    state=protected_directory(Path(bridge["collaborationState"]))
    root_path=str(Path(config["workspace"]))
    require(root_path!="/","Filesystem-wide resources are not installation defaults")
    fd=open_root(root_path)
    try:info=os.fstat(fd)
    finally:os.close(fd)
    environment=digest({"hostId":host,"environmentId":"local"})
    identity=str(uuid5(UUID(host),"physical-root:"+digest([environment,info.st_dev,info.st_ino])))
    root={"hostId":host,"environmentId":"local","root":root_path,
          "device":info.st_dev,"inode":info.st_ino,"workspaceId":identity}
    result=administrative_put(state,http,"hosts/"+host+"/physical-workspaces/"+identity,{
        "operationId":"install-root:"+digest(root),"revision":0,"state":"active","rootPath":root_path,
        "environmentSha256":environment,"rootIdentitySha256":digest({"hostId":host,
            "environmentSha256":environment,"device":info.st_dev,"inode":info.st_ino}),
        "registrationSha256":digest(root)})
    revision=result["workspace"]["revision"]
    administrative_put(state,http,"physical-workspaces/"+identity+"/agent-grants/"+agent,{
        "operationId":"install-agent-access:"+digest([agent,identity,revision]),"revision":0,
        "workspaceRevision":revision,"executionHost":host,"state":"active","canRead":True,"canWrite":True})
    defaults=seed_defaults(state,http,authority,host,
        {agent:{"workspaceIds":[identity],"defaultWorkspaceId":identity}},
        {identity:{**root,"registryRevision":revision}})
    return {"schema":"lax-installed-purpose-resource/v1","physicalWorkspaceId":identity,
        "contextWorkspaceId":config["workspaceId"],"hostId":host,"root":root_path,
        "defaultSelected":True,"modelsStarted":0,"servicesStarted":0}
