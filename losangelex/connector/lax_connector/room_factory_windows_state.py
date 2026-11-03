"""Protected Windows logical-agent state on ONE existing host runtime.

Platform helper only. No service installation/control, thread initialization,
RPC/model call, auth copy or resident-session creation. Common r03 owns binding
this helper to its factory and attaches ConversationalAgent in the parent.
"""
from contextlib import contextmanager
import ctypes,hashlib,json,msvcrt,os,time
from pathlib import Path
from uuid import UUID
from ctypes import wintypes as W
import win32api,win32con,win32process,win32security
from lax_connector.windows_ipc import private_path,create_private_directory,_authenticated_socket

class Held(RuntimeError):pass
def require(ok,reason):
    if not ok:raise Held(reason)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def read(path,expected=None):
    p=Path(path);require(p.is_absolute() and p.resolve()==p,'Protected exact absolute path required')
    private_path(p);require(p.stat().st_size<=1024*1024,'Protected metadata budget exceeded')
    raw=p.read_bytes();require(expected is None or digest(raw)==expected,'Original protected input SHA differs')
    return json.loads(raw)
def once(path,value):
    p=Path(path);private_path(p.parent,directory=True)
    with p.open('xb') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
    private_path(p)
def current_owner():
    token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
    try:
        require(not win32security.GetTokenInformation(token,win32security.TokenElevation),'Limited interactive owner required')
        require(win32security.GetTokenInformation(token,win32security.TokenSessionId)==1,'Session1 required')
        return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0])
    finally:token.Close()
def argv(command):
    shell=ctypes.WinDLL('shell32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    shell.CommandLineToArgvW.argtypes=[W.LPCWSTR,ctypes.POINTER(ctypes.c_int)];shell.CommandLineToArgvW.restype=ctypes.POINTER(W.LPWSTR)
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    size=ctypes.c_int();items=shell.CommandLineToArgvW(command,ctypes.byref(size));require(bool(items),'Process argv unavailable')
    try:return [items[i] for i in range(size.value)]
    finally:kernel.LocalFree(items)
def argv_digest(items):
    require(bool(items),'Host process command missing')
    normalized=[str(Path(items[0])),*items[1:]]
    return digest(canonical(normalized))
def process(pid):
    h=win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION|win32con.SYNCHRONIZE,False,pid)
    try:
        require(win32process.GetExitCodeProcess(h)==259,'Original host process is terminal')
        token=win32security.OpenProcessToken(h,win32con.TOKEN_QUERY)
        try:
            user=win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0])
            require(user==current_owner() and win32security.GetTokenInformation(token,win32security.TokenSessionId)==1
                and not win32security.GetTokenInformation(token,win32security.TokenElevation),'Host process owner/session/elevation differs')
        finally:token.Close()
        k=ctypes.WinDLL('kernel32',use_last_error=True);k.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
        k.QueryFullProcessImageNameW.restype=W.BOOL;size=W.DWORD(32768);image=ctypes.create_unicode_buffer(size.value)
        require(k.QueryFullProcessImageNameW(int(h),0,image,ctypes.byref(size)),'Host process image unavailable')
        return {'pid':pid,'created':str(win32process.GetProcessTimes(h)['CreationTime']),
            'image':str(Path(image.value)),'ownerSidSha256':digest(user.encode()),'sessionId':1}
    finally:h.Close()
def native_peer(manifest):
    connection=_authenticated_socket(Path(manifest['socket']),manifest['binary'])
    try:
        ws=ctypes.WinDLL('Ws2_32',use_last_error=True)
        ws.WSAIoctl.argtypes=[ctypes.c_size_t,W.DWORD,ctypes.c_void_p,W.DWORD,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p,ctypes.c_void_p]
        pid=W.DWORD();returned=W.DWORD()
        require(ws.WSAIoctl(connection.fileno(),0x58000100,None,0,ctypes.byref(pid),ctypes.sizeof(pid),ctypes.byref(returned),None,None)==0,'Native kernel peer unavailable')
        proof=process(pid.value);require(os.path.samefile(proof['image'],manifest['binary']),'Original native image differs')
        return proof
    finally:connection.close()
def inspect_parent(policy_path: Path, *, expected_policy_sha256: str) -> dict:
    owner=current_owner();p=read(policy_path,expected_policy_sha256)
    require(p['schema'] in ('lax-windows-room-parent-policy/v1','lax-windows-room-parent-policy/v2'),'Owner host-account policy required')
    for key in ('authorityId','hostId','parentAgentId'):require(str(UUID(p[key]))==p[key],'Canonical host policy identity required')
    require(p['ownerSidSha256']==digest(owner.encode()),'Original enrolled Windows owner differs')
    root=Path(p['agentRoot']);require(root.is_absolute() and root.resolve()==root,'Exact host-owned agentRoot required');private_path(root,directory=True)
    manifest=read(p['nativeHostManifest'],p['nativeHostManifestSha256'])
    require(manifest['schema']=='lax-native-host/v1' and manifest['platform']=='windows'
        and manifest['runtimeMode']=='room-conversation' and manifest['authorityId']==p['authorityId']
        and manifest['hostId']==p['hostId'] and manifest['ownerAgentId']==p['parentAgentId'],'Original shared host attachment differs')
    require(all(not root.is_relative_to(Path(manifest[k])) for k in ('codexHome','state')) and root!=Path(manifest['workspace']),'Agent homes cannot reuse original profile/state/workspace')
    # OS manager checks/admission belong to the ONE existing host boundary.
    # Per-agent work reads its accepted startup descriptor and kernel facts only.
    accepted=read_parent_acceptance(p,expected_policy_sha256=expected_policy_sha256)
    require(accepted['schema']==('lax-windows-parent-runtime-acceptance/v2' if p['schema']=='lax-windows-room-parent-policy/v2' else 'lax-windows-parent-runtime-acceptance/v1')
        and accepted['state']=='running' and accepted['admissionAllowed'] is True,
        'Parent runtime is not accepting logical sessions; never start or unpause it')
    require(all(accepted[k]==p[k] for k in ('authorityId','hostId','parentAgentId','nativeHostManifestSha256','parentTaskName')),
        'Original parent account/descriptor acceptance differs')
    metadata=read(p['parentRuntimeMetadata']);require(metadata.get('state')=='running','Parent runtime receipt is not running')
    parent=process(metadata['pid'])
    require(parent==accepted['runtimeIdentity'],'Original parent runtime incarnation differs')
    peer=native_peer(manifest)
    require(peer==accepted['nativeIdentity'],'Original shared native incarnation differs')
    identity={k:p[k] for k in ('authorityId','hostId','parentAgentId','ownerSidSha256','agentRoot','nativeHostManifest','nativeHostManifestSha256','parentTaskName')}
    return {'schema':'lax-windows-parent-evidence/v1','identitySha256':digest(canonical(identity)),
        'policySha256':expected_policy_sha256,'authorityId':p['authorityId'],'hostId':p['hostId'],
        'parentAgentId':p['parentAgentId'],'parentRuntime':parent,'sharedNative':peer,
        'nativeHostManifestSha256':p['nativeHostManifestSha256'],'agentRoot':str(root),
        'sharedAppServer':True,'newProcesses':0,'modelCalls':0,'sessionReadiness':'parent-only; no logical session inferred'}
@contextmanager
def _lock(slot,*,create):
    if create:create_private_directory(slot)
    private_path(slot,directory=True);file=slot/'state.lock'
    if create:
        try:
            with file.open('xb') as f:f.write(b'\0')
        except FileExistsError:pass
    private_path(file);require(file.stat().st_size==1,'Original state lock differs')
    with file.open('r+b') as f:
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as e:raise Held('Original agent state operation is busy') from e
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
def _scope(binding,config,evidence):
    require(set(binding)=={'authorityId','hostId','agentId','originRoomId','operationId'},'Exact immutable origin binding required')
    for key in ('authorityId','hostId','agentId','originRoomId'):require(str(UUID(binding[key]))==binding[key],'Canonical agent scope required')
    require(binding['authorityId']==evidence['authorityId'] and binding['hostId']==evidence['hostId']
        and binding['agentId']!=evidence['parentAgentId'],'Distinct local room agent required')
    require(config['runtimeMode']=='room-conversation' and all(config[k]==binding[k] for k in ('authorityId','hostId','agentId')),'Agent config scope differs')
    require(config['rooms']==[{'roomId':binding['originRoomId'],'after':0}],'Only original room from cursor0 allowed')
    require(not any(k in config for k in ('nativeThreadId','homes','tokens','installedPurposeRuntime','conversationParticipationPolicy')),'No old thread/profile or adoption is accepted')
    overrides=config.get('conversationResumeInstructions',{})
    require(isinstance(overrides,dict) and not set(overrides)-{'baseInstructions','developerInstructions'} and all(isinstance(v,str) and v.strip() for v in overrides.values()),'Fresh room resume instructions must use explicit supported fields')
    require(config.get('sandbox')=='danger-full-access' and config.get('approvalPolicy')=='never','Explicit NEW full native policy required')
    require(all(isinstance(config.get(k),str) and config[k].strip() for k in ('token','nativeName','instructions','model','effort')),'Complete NEW initial role/config required')
def prepare_agent(policy_path: Path, config_path: Path, operation_dir: Path, *, expected_policy_sha256: str,
                  expected_config_sha256: str, binding: dict, inspect: bool=False) -> dict:
    evidence=inspect_parent(policy_path,expected_policy_sha256=expected_policy_sha256)
    policy=read(policy_path,expected_policy_sha256);cfg=read(config_path,expected_config_sha256);_scope(binding,cfg,evidence)
    require(cfg['nativeServer']=={'manifest':policy['nativeHostManifest']},'Only original shared native descriptor allowed')
    manifest=read(policy['nativeHostManifest'],policy['nativeHostManifestSha256'])
    require(cfg['codexHome']==manifest['codexHome'] and os.path.samefile(cfg['binary'],manifest['binary']),'Original account/profile/binary required')
    op=Path(operation_dir);require(op.is_absolute() and op.resolve()==op,'Fixed exact operation directory required');private_path(op,directory=True)
    root=Path(policy['agentRoot']);slot=root/binding['agentId']
    # Paths derive from protected host policy and reserved identity, never another
    # Global/room's supplied home or a per-agent CODEX_HOME.
    require(Path(cfg['state'])==slot/'state' and Path(cfg['workspace'])==slot/'home/work','Agent paths must derive from original protected host root')
    if inspect and not slot.exists():return {'state':'blocked','reason':'Original agent preparation absent; not created'}
    record={**binding,'operationDir':str(op),'configSha256':expected_config_sha256,
        'parentIdentitySha256':evidence['identitySha256']}
    with _lock(slot,create=not inspect):
        original=slot/'binding.json'
        if original.exists():require(read(original)==record,'Original origin/operation/config/parent binding is immutable')
        else:
            require(not inspect,'Original preparation receipt missing; not adopted')
            require(set(p.name for p in slot.iterdir())=={'state.lock'},'Populated existing agent root cannot be adopted')
            once(original,record)
        acceptance=op/'windows-state-prepared.json';target=slot/'connector-init.private.json'
        if acceptance.exists():
            old=read(acceptance);require(old['binding']==record and read(target)==cfg,'Original preparation acceptance/config differs')
        else:
            require(not inspect,'Original preparation uncertain; do not rebuild it')
            once(op/'windows-state-intent.json',{'binding':record,'parentEvidence':evidence,'at':time.time()})
            for path in (slot/'home',slot/'home/work',slot/'state'):create_private_directory(path)
            once(target,cfg)
            after=inspect_parent(policy_path,expected_policy_sha256=expected_policy_sha256)
            require(after==evidence,'Parent runtime/native incarnation changed during preparation')
            once(acceptance,{'binding':record,'configPath':str(target),'parentEvidence':after,
                'nativeInitializationDispatched':False,'logicalSessionAttached':False,'at':time.time()})
        # Read-only inspection never rewrites initial defaults or later native
        # permission changes. Core/bootstrap/session ownership remains separate.
        for path in (slot,slot/'home',slot/'home/work',slot/'state'):private_path(path,directory=True)
        return {'schema':'lax-windows-room-state-result/v1',**binding,'state':'prepared',
            'configPath':str(target),'workspace':str(slot/'home/work'),'statePath':str(slot/'state'),
            'parentEvidence':evidence,'preparationReceipt':str(acceptance),
            'nativeInitializationDispatched':False,'logicalSessionAttached':False,
            'servicesCreated':0,'newProcesses':0,'modelCalls':0}

def read_parent_acceptance(policy,*,expected_policy_sha256):
    """V1 retains its exact pin. V2 is explicit owner-incarnation indirection.

    This only READS a separately owner-issued record. Startup evidence never
    becomes acceptance; neither this function nor the parent can issue approval.
    """
    policy_sha256=expected_policy_sha256
    if policy.get('schema')=='lax-windows-room-parent-policy/v1':
        return read(policy['parentAcceptancePath'],policy['parentAcceptanceSha256'])
    require(policy.get('schema')=='lax-windows-room-parent-policy/v2','Explicit parent policy version required')
    require(not any(k in policy for k in ('parentAcceptancePath','parentAcceptanceSha256')),
        'V2 locator cannot ambiguously retain V1 acceptance pins')
    locator=policy.get('parentAcceptanceLocator')
    require(isinstance(locator,dict) and set(locator)=={'path'},'Exact owner acceptance locator required')
    path=Path(locator['path']);private_path(path.parent,directory=True)
    require(path.parent==Path(policy['parentRuntimeMetadata']).parent,'Acceptance must remain in original parent record directory')
    accepted=read(path)
    require(accepted.get('schema')=='lax-windows-parent-runtime-acceptance/v2'
        and accepted.get('policySha256')==policy_sha256,'Owner acceptance is not bound to selected immutable policy')
    operation=accepted.get('ownerAcceptanceOperationId')
    require(isinstance(operation,str) and 1<=len(operation)<=200,'Separate original owner acceptance operation required')
    require(all(accepted.get(k)==policy[k] for k in ('authorityId','hostId','parentAgentId','nativeHostManifestSha256','parentTaskName')),
        'Owner acceptance scope differs from immutable host policy')
    return accepted

