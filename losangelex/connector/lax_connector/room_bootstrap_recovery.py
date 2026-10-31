"""Operator reconciliation for a positively proved pre-IPC legacy bootstrap failure.

Never accepts absence alone as proof that an uncertain native creation is safe.
The root-owned receipt binds the original bytes and the failed socket chronology;
we additionally require the original exclusive host profile to be completely empty.
"""
import hashlib,json,stat
from pathlib import Path
from .journal import saved


def proof(path):
    path=Path(path);info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>16384:
        raise PermissionError('Administrator-protected bootstrap reconciliation required')
    return json.loads(path.read_text())


def verify(path,file,prior,binding,fingerprint):
    value=proof(path)
    if (value.get('schema')!='lax-native-bootstrap-not-sent/v1'
            or value.get('binding')!=binding or value.get('requestDigest')!=fingerprint
            or value.get('originalContextSha256')!=hashlib.sha256(file.read_bytes()).hexdigest()
            or prior.get('state')!='creating' or prior.get('nativeThreadId')
            or prior.get('threadStartAttempted') is True
            or value.get('noNativeThreadStartIssued') is not True):
        raise ValueError('Reconciliation does not prove this original bootstrap was unsubmitted')
    failure=value.get('failedAttemptExitUnixSeconds');ready=value.get('socketReadyUnixSeconds')
    if type(failure) not in (int,float) or type(ready) not in (int,float) or not ready>failure:
        raise ValueError('Original socket was not proved absent through failed dispatch')
    return value


SOURCE_KINDS=['cli','vscode','exec','appServer','subAgent','subAgentReview','subAgentCompact','subAgentThreadSpawn','subAgentOther','unknown']


async def reconcile_empty(rpc,path,file,prior,record):
    value=verify(path,file,prior,record['binding'],record['requestDigest'])
    if rpc.manifest.get('ownerAgentId')!=record['binding']['agentId']:
        raise ValueError('Only the original exclusive host owner can recover initial bootstrap')
    for method,params in [('thread/loaded/list',{}),('thread/list',{'limit':1,'archived':False,'sourceKinds':SOURCE_KINDS,'modelProviders':[]}),('thread/list',{'limit':1,'archived':True,'sourceKinds':SOURCE_KINDS,'modelProviders':[]})]:
        result=await rpc.call(method,params)
        if result.get('data')!=[] or result.get('nextCursor'):
            raise RuntimeError('An original native context exists; inspect it without replacement')
    backup=file.with_name('native-initialization-before-recovery-'+value['originalContextSha256']+'.json')
    if not backup.exists():saved(backup,prior)
    record['reconciledOriginalAttempt']=value['originalContextSha256']
    saved(file,record)
